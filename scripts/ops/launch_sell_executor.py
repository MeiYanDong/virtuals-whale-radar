#!/usr/bin/env python3
"""Realtime dual-track launch sell executor.

This is the production counterpart to launch_sell_strategy.py:
- simulate mode is read-only;
- broadcast mode requires both CLI and env gates;
- broadcast mode requires an isolated execution RPC;
- target-token approval is exact to the current sell amount and only runs when
  both CLI and env auto-approve gates are enabled;
- raw transactions and private keys are never printed or persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import os
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from approve_erc20_spender import (  # noqa: E402
    encode_approve,
    read_allowance as read_token_allowance,
    wait_allowance_at_least,
)
from backtest_launch_strategy import fmt_decimal, parse_decimal, spot_fdv_wan  # noqa: E402
from buy_virtual_canary import (  # noqa: E402
    elapsed_ms,
    load_secret_file,
    read_erc20_balance,
    suggest_fees,
    wait_receipt,
)
from execution_rpc import (  # noqa: E402
    apply_execution_rpc_to_config,
    env_flag_enabled,
    require_isolated_execution_rpc,
)
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    VIRTUALS_BUY_SPENDER,
    hex_quantity,
    normalize_hex_address,
)
from launch_prewarm_executor import compact_fuse  # noqa: E402
from launch_sell_strategy import (  # noqa: E402
    DualSellConfig,
    DualSellInput,
    DualSellState,
    apply_successful_sell,
    evaluate_dual_sell,
)
from live_strategy_dry_run import (  # noqa: E402
    LiveClock,
    append_jsonl,
    cst_iso,
    compact_sample,
    derive_trigger_types,
    find_project,
    poll_interval_for_status,
    stable_json,
    utc_iso,
)
from native_launch_replay import build_sample  # noqa: E402
from sell_virtuals_token import (  # noqa: E402
    bind_sell,
    receipt_sell_deltas,
    simulate_sell,
)
from virtuals_bot import RPCClient, VirtualsBot, load_config, redact_rpc_url  # noqa: E402


SELL_BROADCAST_ENV = "VWR_ENABLE_AUTO_SELL_BROADCAST"
SELL_APPROVE_ENV = "VWR_ENABLE_AUTO_SELL_APPROVE"
WEI_PER_VIRTUAL = Decimal(10) ** 18


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime dual-track launch sell executor.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--rule", default="dual_roi_large_buy_sell")
    parser.add_argument("--mode", choices=["simulate", "broadcast"], default="simulate")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--min-poll-sec", type=float, default=0.25)
    parser.add_argument("--live-poll-sec", type=float, default=0.25)
    parser.add_argument("--prelaunch-poll-sec", type=float, default=2.0)
    parser.add_argument("--scheduled-poll-sec", type=float, default=20.0)
    parser.add_argument("--heartbeat-log-sec", type=float, default=30.0)
    parser.add_argument("--catch-up-events-sec", type=int, default=120)
    parser.add_argument("--exit-after-end-sec", type=int, default=300)
    parser.add_argument("--slippage-bps", type=int, default=500)
    parser.add_argument("--deadline-offset-sec", type=int, default=90)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    parser.add_argument("--enable-broadcast", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--ignore-active-fuse", action="store_true")
    return parser.parse_args()


def executor_mode(args: argparse.Namespace) -> str:
    return f"autosell_{args.mode}"


def broadcast_enabled(args: argparse.Namespace) -> bool:
    return args.mode == "broadcast" and bool(args.enable_broadcast) and env_flag_enabled(SELL_BROADCAST_ENV)


def auto_approve_enabled(args: argparse.Namespace) -> bool:
    return broadcast_enabled(args) and bool(args.auto_approve) and env_flag_enabled(SELL_APPROVE_ENV)


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def transfer_deltas_from_receipt_json(raw: Any) -> dict[str, Any]:
    receipt = json_dict(raw)
    transfer = receipt.get("transferDeltas")
    return transfer if isinstance(transfer, dict) else {}


def wei_to_virtual(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0")) / WEI_PER_VIRTUAL
    except Exception:
        return Decimal("0")


def make_sell_intent_id(
    *,
    project_name: str,
    signalhub_project_id: Any,
    strategy_name: str,
    rule_name: str,
    sample: dict[str, Any],
    decision: dict[str, Any],
    owner: str,
) -> str:
    payload = {
        "project": project_name,
        "signalhubProjectId": signalhub_project_id,
        "strategy": strategy_name,
        "rule": rule_name,
        "action": "sell",
        "owner": normalize_hex_address(owner),
        "simTimestamp": sample.get("simTimestamp"),
        "taxRate": sample.get("buyTaxRate"),
        "amountRaw": decision.get("amountRaw"),
        "largeBuyTxHash": decision.get("largeBuyTxHash"),
        "totalSellPct": decision.get("totalSellPct"),
        "roiDeltaPct": decision.get("roiDeltaPct"),
        "largeBuyDeltaPct": decision.get("largeBuyDeltaPct"),
    }
    import hashlib

    digest = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()[:24]
    return f"lsell_{digest}"


def make_sell_ledger_record(
    *,
    project_row: dict[str, Any],
    project_name: str,
    strategy_name: str,
    rule_name: str,
    mode: str,
    sample_index: int,
    sample: dict[str, Any],
    decision: dict[str, Any],
    position: dict[str, Any],
    owner: str,
    status: str = "intent_recorded",
    reason: str = "sell_signal",
) -> dict[str, Any]:
    intent_id = make_sell_intent_id(
        project_name=project_name,
        signalhub_project_id=project_row.get("signalhub_project_id"),
        strategy_name=strategy_name,
        rule_name=rule_name,
        sample=sample,
        decision=decision,
        owner=owner,
    )
    return {
        "intent_id": intent_id,
        "project": project_name,
        "managed_project_id": project_row.get("id"),
        "signalhub_project_id": project_row.get("signalhub_project_id"),
        "strategy": strategy_name,
        "rule_name": rule_name,
        "mode": mode,
        "status": status,
        "action": "sell",
        "decision_reason": reason,
        "sample_index": sample_index,
        "snapshot_ts": sample.get("simTimestamp"),
        "tax_rate": sample.get("buyTaxRate"),
        "entry_tax_fdv_wan_usd": sample.get("estimatedFdvWanUsdWithTax") or spot_fdv_wan(sample),
        "board_spent_v": sample.get("boardSpentV"),
        "board_cost_wan_usd": sample.get("boardCostWanUsd"),
        "trigger_types": sample.get("triggerTypes") or [],
        "snapshot": compact_sample(sample),
        "intent": {
            "type": "sell",
            "owner": normalize_hex_address(owner),
            "decision": decision,
            "position": position,
        },
        "trade_sent": False,
        "broadcast_enabled": False,
    }


def update_ledger_stage(
    bot: VirtualsBot,
    *,
    intent_id: str,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    mode: str,
    status: str,
    reason: str,
    simulation: dict[str, Any] | None = None,
    signed_tx_hash: str | None = None,
    broadcast_tx_hash: str | None = None,
    receipt: dict[str, Any] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    trade_sent: bool = False,
    broadcast_enabled_value: bool = False,
) -> dict[str, Any]:
    return bot.storage.upsert_launch_execution_record(
        {
            "intent_id": intent_id,
            "project": project_name,
            "strategy": strategy_name,
            "rule_name": rule_name,
            "mode": mode,
            "status": status,
            "action": "sell",
            "decision_reason": reason,
            "simulation": simulation,
            "signed_tx_hash": signed_tx_hash,
            "broadcast_tx_hash": broadcast_tx_hash,
            "receipt": receipt,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
            "trade_sent": trade_sent,
            "broadcast_enabled": broadcast_enabled_value,
        }
    )


def trigger_fuse(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    intent_id: str,
    failure_stage: str,
    failure_reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return bot.storage.trigger_launch_execution_fuse(
        project=project_name,
        strategy=strategy_name,
        rule_name=rule_name,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        source_intent_id=intent_id,
        details=details or {},
    )


def build_position_from_records(
    *,
    rows: list[dict[str, Any]],
    current_balance_raw: int,
) -> dict[str, Any]:
    buy_token_raw = 0
    buy_units = Decimal("0")
    spent_v = Decimal("0")
    roi_sold_raw = Decimal("0")
    large_sold_raw = Decimal("0")
    sold_raw_total = 0
    processed_large_buy_txs: set[str] = set()
    cooldown_until = 0

    for row in reversed(rows):
        action = str(row.get("action") or "")
        trade_sent = int(row.get("trade_sent") or 0) == 1
        status = str(row.get("status") or "")
        intent = json_dict(row.get("intent_json"))
        receipt_deltas = transfer_deltas_from_receipt_json(row.get("receipt_json"))

        if trade_sent and action in {"would_buy", "buy"} and status.startswith("receipt_success"):
            buy_token_raw += int(str(receipt_deltas.get("targetReceivedRaw") or "0"))
            virtual_spent = wei_to_virtual(receipt_deltas.get("virtualSpentWei"))
            if virtual_spent <= 0:
                virtual_spent = decimal_or_none(row.get("buy_size_v")) or Decimal("0")
            spent_v += virtual_spent
            entry = decimal_or_none(row.get("entry_tax_fdv_wan_usd"))
            if virtual_spent > 0 and entry is not None and entry > 0:
                buy_units += virtual_spent / entry
            continue

        if trade_sent and action == "sell" and status.startswith("receipt_success"):
            receipt_sold_raw = int(str(receipt_deltas.get("soldTokenSpentRaw") or "0"))
            intent_body = json_dict(intent.get("decision"))
            total_pct = decimal_or_none(intent_body.get("totalSellPct")) or Decimal("0")
            roi_pct = decimal_or_none(intent_body.get("roiDeltaPct")) or Decimal("0")
            large_pct = decimal_or_none(intent_body.get("largeBuyDeltaPct")) or Decimal("0")
            if receipt_sold_raw > 0 and total_pct > 0:
                roi_sold_raw += Decimal(receipt_sold_raw) * roi_pct / total_pct
                large_sold_raw += Decimal(receipt_sold_raw) * large_pct / total_pct
                sold_raw_total += receipt_sold_raw
            tx_hash = str(intent_body.get("largeBuyTxHash") or "").strip()
            if tx_hash:
                processed_large_buy_txs.add(tx_hash.lower())
            updated_at = int(row.get("updated_at") or 0)
            if updated_at > 0:
                cooldown_until = max(cooldown_until, updated_at + int(DualSellConfig().cooldown_sec))

    total_position_raw = max(buy_token_raw, int(current_balance_raw) + int(sold_raw_total))
    if total_position_raw > 0:
        roi_sold_pct = Decimal(roi_sold_raw) * Decimal("100") / Decimal(total_position_raw)
        large_sold_pct = Decimal(large_sold_raw) * Decimal("100") / Decimal(total_position_raw)
    else:
        roi_sold_pct = Decimal("0")
        large_sold_pct = Decimal("0")

    return {
        "totalPositionRaw": int(total_position_raw),
        "currentBalanceRaw": int(current_balance_raw),
        "autoBuyTokenRaw": int(buy_token_raw),
        "soldTokenRaw": int(sold_raw_total),
        "totalSpentV": spent_v,
        "buyUnits": buy_units,
        "roiSoldPct": roi_sold_pct,
        "largeBuySoldPct": large_sold_pct,
        "cooldownUntil": cooldown_until,
        "processedLargeBuyTxs": processed_large_buy_txs,
    }


def dual_state_from_position(position: dict[str, Any]) -> DualSellState:
    return DualSellState(
        total_position_raw=int(position.get("totalPositionRaw") or 0),
        roi_sold_pct=Decimal(str(position.get("roiSoldPct") or "0")),
        large_buy_sold_pct=Decimal(str(position.get("largeBuySoldPct") or "0")),
        cooldown_until=int(position.get("cooldownUntil") or 0),
        processed_large_buy_txs=set(position.get("processedLargeBuyTxs") or set()),
    )


def current_roi_pct(position: dict[str, Any], sample: dict[str, Any]) -> Decimal | None:
    spot = spot_fdv_wan(sample)
    spent_v = Decimal(str(position.get("totalSpentV") or "0"))
    buy_units = Decimal(str(position.get("buyUnits") or "0"))
    if spot is None or spot <= 0 or spent_v <= 0 or buy_units <= 0:
        return None
    full_position_value_v = buy_units * spot
    return (full_position_value_v - spent_v) / spent_v * Decimal("100")


def compact_position(position: dict[str, Any]) -> dict[str, Any]:
    return {
        "totalPositionRaw": str(position.get("totalPositionRaw") or 0),
        "currentBalanceRaw": str(position.get("currentBalanceRaw") or 0),
        "autoBuyTokenRaw": str(position.get("autoBuyTokenRaw") or 0),
        "soldTokenRaw": str(position.get("soldTokenRaw") or 0),
        "totalSpentV": fmt_decimal(Decimal(str(position.get("totalSpentV") or "0")), 6),
        "buyUnits": fmt_decimal(Decimal(str(position.get("buyUnits") or "0")), 18),
        "roiSoldPct": fmt_decimal(Decimal(str(position.get("roiSoldPct") or "0")), 6),
        "largeBuySoldPct": fmt_decimal(Decimal(str(position.get("largeBuySoldPct") or "0")), 6),
        "cooldownUntil": int(position.get("cooldownUntil") or 0),
    }


def latest_unseen_buy_event(
    bot: VirtualsBot,
    *,
    project_name: str,
    since_ts: int,
    processed_txs: set[str],
) -> dict[str, Any] | None:
    rows = bot.storage.conn.execute(
        """
        SELECT tx_hash, block_timestamp, block_number, buyer, spent_v_est
        FROM events
        WHERE project = ? AND block_timestamp >= ?
        ORDER BY block_timestamp ASC, block_number ASC, id ASC
        LIMIT 500
        """,
        (project_name, int(since_ts)),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        tx_hash = str(item.get("tx_hash") or "").lower()
        if not tx_hash or tx_hash in processed_txs:
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: decimal_or_none(item.get("spent_v_est")) or Decimal("0"))


def receipt_summary(receipt: dict[str, Any] | None, receipt_deltas: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt and not receipt_deltas:
        return None
    return {
        "status": receipt.get("status") if receipt else None,
        "blockNumber": receipt.get("blockNumber") if receipt else None,
        "gasUsed": receipt.get("gasUsed") if receipt else None,
        "transferDeltas": receipt_deltas,
    }


async def approve_exact_amount(
    *,
    rpc: RPCClient,
    account: Any,
    to_checksum_address: Any,
    cfg: Any,
    owner: str,
    token: str,
    spender: str,
    amount_raw: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    before = await read_token_allowance(rpc, token=token, owner=owner, spender=spender)
    if before >= amount_raw:
        return {
            "needed": False,
            "broadcasted": False,
            "allowanceBeforeRaw": str(before),
            "allowanceAfterRaw": str(before),
            "allowanceConfirmed": True,
            "reason": "allowance_already_sufficient",
        }
    data = encode_approve(spender, amount_raw)
    call_payload = {"from": owner, "to": token, "value": "0x0", "data": data}
    await rpc.call("eth_call", [call_payload, "latest"])
    gas_estimate = int(await rpc.call("eth_estimateGas", [call_payload]), 16)
    gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
    nonce = int(await rpc.call("eth_getTransactionCount", [owner, "pending"]), 16)
    fees = await suggest_fees(
        rpc,
        max_fee_gwei=args.max_fee_gwei,
        priority_gwei=args.max_priority_fee_gwei,
    )
    tx = {
        "type": 2,
        "chainId": int(cfg.chain_id),
        "nonce": nonce,
        "to": to_checksum_address(token),
        "value": 0,
        "data": data,
        "gas": gas,
        "maxFeePerGas": fees["maxFeePerGas"],
        "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"],
    }
    signed = account.sign_transaction(tx)
    raw_bytes = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    raw_tx = "0x" + bytes(raw_bytes).hex()
    tx_hash = "0x" + bytes(getattr(signed, "hash")).hex()
    sent_hash = await rpc.call("eth_sendRawTransaction", [raw_tx])
    receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
    receipt_status = str((receipt or {}).get("status") or "")
    allowance_confirm = await wait_allowance_at_least(
        rpc,
        token=token,
        owner=owner,
        spender=spender,
        amount_raw=amount_raw,
        timeout_sec=10,
        interval_sec=Decimal("0.5"),
    )
    ok = receipt_status in {"0x1", "1"} and bool(allowance_confirm["ok"])
    return {
        "needed": True,
        "broadcasted": True,
        "txHash": str(sent_hash),
        "signedTxHash": tx_hash,
        "receipt": {
            "status": receipt.get("status") if receipt else None,
            "blockNumber": receipt.get("blockNumber") if receipt else None,
            "gasUsed": receipt.get("gasUsed") if receipt else None,
        }
        if receipt
        else None,
        "allowanceBeforeRaw": str(before),
        "allowanceAfterRaw": allowance_confirm["allowanceRaw"],
        "allowanceConfirmed": bool(allowance_confirm["ok"]),
        "ok": ok,
        "reason": "approval_confirmed" if ok else "approval_failed_or_not_confirmed",
    }


async def execute_sell_decision(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    account: Any,
    to_checksum_address: Any,
    project_row: dict[str, Any],
    project_name: str,
    strategy_name: str,
    rule_name: str,
    sample: dict[str, Any],
    sample_index: int,
    decision: Any,
    position: dict[str, Any],
    owner: str,
    token: str,
    pool: str,
) -> dict[str, Any]:
    mode = executor_mode(args)
    decision_payload = decision.as_dict()
    position_payload = compact_position(position)
    ledger_record = make_sell_ledger_record(
        project_row=project_row,
        project_name=project_name,
        strategy_name=strategy_name,
        rule_name=rule_name,
        mode=mode,
        sample_index=sample_index,
        sample=sample,
        decision=decision_payload,
        position=position_payload,
        owner=owner,
    )
    bot.storage.upsert_launch_execution_record(ledger_record)
    intent_id = str(ledger_record["intent_id"])
    timings: dict[str, float] = {}
    total_start = time.perf_counter()
    payload: dict[str, Any] = {
        "event": "sell_intent",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "rule": rule_name,
        "strategy": strategy_name,
        "mode": mode,
        "ledgerIntentId": intent_id,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "autoApproveEnabled": auto_approve_enabled(args),
        "decision": decision_payload,
        "position": position_payload,
        "sample": compact_sample(sample),
    }

    active_fuse = bot.storage.get_active_launch_execution_fuse(
        project=project_name,
        strategy=strategy_name,
        rule_name=rule_name,
    )
    if active_fuse and not args.ignore_active_fuse:
        payload["event"] = "blocked_by_active_fuse"
        payload["activeFuse"] = compact_fuse(active_fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="blocked_by_active_fuse",
            reason="active_fuse",
            failure_stage="fuse",
            failure_reason="active_fuse",
        )
        return payload

    try:
        section_start = time.perf_counter()
        tx, quote = await bind_sell(
            rpc,
            chain_id=cfg.chain_id,
            from_addr=owner,
            token_addr=token,
            pool_addr=pool,
            virtual_token_addr=cfg.virtual_token_addr,
            amount_raw=int(decision.amount_raw),
            slippage_bps=int(args.slippage_bps),
            deadline_offset_sec=int(args.deadline_offset_sec),
            now_ts=int(time.time()),
        )
        timings["bindSellMs"] = elapsed_ms(section_start)
        section_start = time.perf_counter()
        simulation = await simulate_sell(
            rpc,
            tx=tx,
            token_addr=token,
            owner=owner,
            spender=VIRTUALS_BUY_SPENDER,
            amount_raw=int(decision.amount_raw),
        )
        timings["simulateMs"] = elapsed_ms(section_start)
        approval_payload: dict[str, Any] | None = None
        if not bool(simulation.get("green")):
            allowance_ok = bool(((simulation.get("checks") or {}).get("allowance") or {}).get("ok"))
            if not allowance_ok and auto_approve_enabled(args):
                section_start = time.perf_counter()
                approval_payload = await approve_exact_amount(
                    rpc=rpc,
                    account=account,
                    to_checksum_address=to_checksum_address,
                    cfg=cfg,
                    owner=owner,
                    token=token,
                    spender=VIRTUALS_BUY_SPENDER,
                    amount_raw=int(decision.amount_raw),
                    args=args,
                )
                timings["approveMs"] = elapsed_ms(section_start)
                if not bool(approval_payload.get("ok", approval_payload.get("allowanceConfirmed"))):
                    raise RuntimeError("target token approval failed or was not confirmed")
                tx, quote = await bind_sell(
                    rpc,
                    chain_id=cfg.chain_id,
                    from_addr=owner,
                    token_addr=token,
                    pool_addr=pool,
                    virtual_token_addr=cfg.virtual_token_addr,
                    amount_raw=int(decision.amount_raw),
                    slippage_bps=int(args.slippage_bps),
                    deadline_offset_sec=int(args.deadline_offset_sec),
                    now_ts=int(time.time()),
                )
                section_start = time.perf_counter()
                simulation = await simulate_sell(
                    rpc,
                    tx=tx,
                    token_addr=token,
                    owner=owner,
                    spender=VIRTUALS_BUY_SPENDER,
                    amount_raw=int(decision.amount_raw),
                )
                timings["simulateAfterApproveMs"] = elapsed_ms(section_start)
        simulation_compact = {
            "green": bool(simulation.get("green")),
            "checks": simulation.get("checks"),
            "approval": approval_payload,
            "quote": asdict(quote),
        }
        if not bool(simulation.get("green")):
            reason = "simulation_not_green"
            payload.update(
                {
                    "event": "simulation_failed",
                    "reason": reason,
                    "simulation": simulation_compact,
                    "timingsMs": timings,
                }
            )
            should_fuse = args.mode == "broadcast"
            if should_fuse:
                fuse = trigger_fuse(
                    bot,
                    project_name=project_name,
                    strategy_name=strategy_name,
                    rule_name=rule_name,
                    intent_id=intent_id,
                    failure_stage="simulation",
                    failure_reason=reason,
                    details={"simulation": simulation_compact},
                )
                payload["activeFuse"] = compact_fuse(fuse)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="simulation_failed",
                reason=reason,
                simulation=simulation_compact,
                failure_stage="simulation" if should_fuse else None,
                failure_reason=reason if should_fuse else None,
                broadcast_enabled_value=broadcast_enabled(args),
            )
            return payload
        if args.mode != "broadcast":
            payload.update(
                {
                    "event": "simulation_green",
                    "reason": "read_only_simulate",
                    "simulation": simulation_compact,
                    "timingsMs": timings,
                }
            )
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="simulation_green",
                reason="read_only_simulate",
                simulation=simulation_compact,
            )
            return payload
        if not broadcast_enabled(args):
            payload.update({"event": "blocked_by_broadcast_gate", "reason": "missing_cli_or_env_broadcast_gate"})
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_broadcast_gate",
                reason="missing_cli_or_env_broadcast_gate",
                simulation=simulation_compact,
                failure_stage="broadcast_gate",
                failure_reason="broadcast_not_enabled",
            )
            return payload

        gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
        gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
        section_start = time.perf_counter()
        fees = await suggest_fees(
            rpc,
            max_fee_gwei=args.max_fee_gwei,
            priority_gwei=args.max_priority_fee_gwei,
        )
        timings["feeSuggestMs"] = elapsed_ms(section_start)
        tx_payload = {
            "type": 2,
            "chainId": int(tx.chain_id),
            "nonce": int(simulation["checks"]["nonce"]["pendingNonce"]),
            "to": to_checksum_address(normalize_hex_address(tx.to)),
            "value": int(tx.value_wei),
            "data": tx.data,
            "gas": gas,
            "maxFeePerGas": fees["maxFeePerGas"],
            "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"],
        }
        section_start = time.perf_counter()
        signed = account.sign_transaction(tx_payload)
        raw_bytes = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        raw_tx = "0x" + bytes(raw_bytes).hex()
        signed_hash = "0x" + bytes(getattr(signed, "hash")).hex()
        timings["signMs"] = elapsed_ms(section_start)
        section_start = time.perf_counter()
        sent_hash = await rpc.call("eth_sendRawTransaction", [raw_tx])
        timings["sendRawMs"] = elapsed_ms(section_start)
        timings["totalToSendAckMs"] = elapsed_ms(total_start)
        payload.update(
            {
                "event": "sell_broadcast_sent",
                "reason": "send_raw_transaction_ack",
                "readOnly": False,
                "tradeSent": True,
                "broadcastEnabled": True,
                "txHash": str(sent_hash),
                "timingsMs": timings,
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="broadcast_sent",
            reason="send_raw_transaction_ack",
            simulation=simulation_compact,
            signed_tx_hash=signed_hash,
            broadcast_tx_hash=str(sent_hash),
            trade_sent=True,
            broadcast_enabled_value=True,
        )
        if args.no_wait_receipt:
            payload["receiptSkipped"] = True
            payload["reason"] = "receipt_wait_skipped"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="broadcast_sent_no_receipt_wait",
                reason="receipt_wait_skipped",
                simulation=simulation_compact,
                signed_tx_hash=signed_hash,
                broadcast_tx_hash=str(sent_hash),
                trade_sent=True,
                broadcast_enabled_value=True,
            )
            return payload

        section_start = time.perf_counter()
        receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
        timings["waitReceiptMs"] = elapsed_ms(section_start)
        receipt_deltas = receipt_sell_deltas(
            receipt,
            owner=owner,
            virtual_token=cfg.virtual_token_addr,
            sold_token=token,
        )
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        receipt_status = str((receipt or {}).get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        payload.update(
            {
                "event": "sell_receipt_success" if receipt_ok else "sell_receipt_failed",
                "receiptSkipped": False,
                "receipt": receipt_payload,
                "timingsMs": timings,
                "reason": "receipt_observed" if receipt is not None else "receipt_timeout",
            }
        )
        if not receipt_ok:
            reason = "receipt_timeout" if receipt is None else "receipt_failed"
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason=reason,
                details={"txHash": str(sent_hash), "receipt": receipt_payload},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason="receipt_observed" if receipt is not None else "receipt_timeout",
            simulation=simulation_compact,
            signed_tx_hash=signed_hash,
            broadcast_tx_hash=str(sent_hash),
            receipt=receipt_payload,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else ("receipt_timeout" if receipt is None else "receipt_failed"),
            trade_sent=True,
            broadcast_enabled_value=True,
        )
        if receipt_ok:
            state = dual_state_from_position(position)
            apply_successful_sell(
                state=state,
                decision=decision,
                timestamp=int(sample.get("simTimestamp") or time.time()),
                config=DualSellConfig(),
            )
        return payload
    except Exception as exc:
        reason = str(exc)
        payload.update({"event": "sell_failed", "reason": reason, "timingsMs": timings})
        if args.mode == "broadcast":
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="sell",
                failure_reason=reason,
                details={"event": payload.get("event"), "timingsMs": timings},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="sell_failed",
            reason=reason,
            failure_stage="sell" if args.mode == "broadcast" else None,
            failure_reason=reason if args.mode == "broadcast" else None,
            broadcast_enabled_value=broadcast_enabled(args),
        )
        return payload


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    owner = normalize_hex_address(args.from_address)
    rpc_selection = apply_execution_rpc_to_config(cfg)
    if args.mode == "broadcast":
        if not args.enable_broadcast:
            raise SystemExit("broadcast mode requires --enable-broadcast")
        if not env_flag_enabled(SELL_BROADCAST_ENV):
            raise SystemExit(f"broadcast mode requires {SELL_BROADCAST_ENV}=1")
        if args.auto_approve and not env_flag_enabled(SELL_APPROVE_ENV):
            raise SystemExit(f"--auto-approve requires {SELL_APPROVE_ENV}=1")
        require_isolated_execution_rpc(
            rpc_selection,
            action="auto sell broadcast",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )
        load_secret_file(Path(args.secret_file))

    account = None
    to_checksum_address = None
    if args.mode == "broadcast":
        try:
            from eth_account import Account
            from eth_utils import to_checksum_address as eth_to_checksum_address
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("eth-account and eth-utils are required") from exc
        account = Account.from_key(os.environ[BURNER_PRIVATE_KEY_ENV])
        if normalize_hex_address(account.address) != owner:
            raise ValueError("secret file private key does not match --from-address")
        to_checksum_address = eth_to_checksum_address

    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output_jsonl = Path(args.output_jsonl or f"data/execution/launch-autosell-{str(args.project).strip().upper()}.jsonl")
    stop_event = asyncio.Event()

    def on_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, on_stop)

    sell_config = DualSellConfig(name=str(args.rule))
    clock = LiveClock()
    previous_sample: dict[str, Any] | None = None
    previous_fingerprint: tuple[Any, ...] | None = None
    last_logged_heartbeat = 0.0
    sample_count = 0
    counts = {"sell": 0, "hold": 0, "skip": 0, "simulation": 0}
    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        token = normalize_hex_address(str(project_row.get("token_addr") or ""))
        pool = normalize_hex_address(str(project_row.get("internal_pool_addr") or ""))

        service_meta = {
            "event": "service_start",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "managedProjectId": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "rule": sell_config.name,
            "strategy": sell_config.name,
            "mode": executor_mode(args),
            "readOnly": args.mode != "broadcast",
            "tradeSent": False,
            "broadcastEnabled": broadcast_enabled(args),
            "autoApproveEnabled": auto_approve_enabled(args),
            "rpc": redact_rpc_url(cfg.http_rpc_url),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "owner": owner,
            "token": token,
            "pool": pool,
            "outputJsonl": str(output_jsonl),
        }
        append_jsonl(output_jsonl, service_meta)
        print(json.dumps(service_meta, ensure_ascii=False), flush=True)

        async with RPCClient(cfg.http_rpc_url, max_retries=3, timeout_sec=20) as rpc:
            while not stop_event.is_set():
                loop_started = time.monotonic()
                now_ts = int(time.time())
                project_row = find_project(bot, str(args.project))
                project_name = str(project_row.get("name") or project_name).strip()
                token = normalize_hex_address(str(project_row.get("token_addr") or token))
                pool = normalize_hex_address(str(project_row.get("internal_pool_addr") or pool))
                sample_count += 1
                try:
                    sample = await build_sample(bot, project_row, clock)
                    sample["triggerTypes"] = derive_trigger_types(previous_sample, sample)
                    current_fingerprint = (
                        sample.get("projectStatus"),
                        sample.get("events"),
                        sample.get("buyTaxRate"),
                        sample.get("liveFdvUsd"),
                        sample.get("estimatedFdvWanUsdWithTax"),
                    )
                    current_balance_raw = 0
                    if token and token != "0x0000000000000000000000000000000000000000":
                        current_balance_raw = await read_erc20_balance(rpc, token=token, owner=owner)
                    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
                    position = build_position_from_records(rows=rows, current_balance_raw=current_balance_raw)
                    state = dual_state_from_position(position)
                    event_since_ts = max(
                        0,
                        int(sample.get("simTimestamp") or now_ts) - max(0, int(args.catch_up_events_sec)),
                    )
                    latest_buy = latest_unseen_buy_event(
                        bot,
                        project_name=project_name,
                        since_ts=event_since_ts,
                        processed_txs=state.processed_large_buy_txs,
                    )
                    roi_pct = current_roi_pct(position, sample)
                    latest_buy_v = decimal_or_none(latest_buy.get("spent_v_est")) if latest_buy else None
                    latest_buy_tx = str(latest_buy.get("tx_hash") or "").lower() if latest_buy else None
                    decision = evaluate_dual_sell(
                        state=state,
                        signal=DualSellInput(
                            timestamp=int(sample.get("simTimestamp") or now_ts),
                            tax_rate=decimal_or_none(sample.get("buyTaxRate")),
                            current_roi_pct=roi_pct,
                            current_balance_raw=current_balance_raw,
                            latest_buy_v=latest_buy_v,
                            latest_buy_tx_hash=latest_buy_tx or None,
                        ),
                        config=sell_config,
                    )
                    payload: dict[str, Any] = {
                        "event": decision.action,
                        "reason": decision.reason,
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": project_name,
                        "rule": sell_config.name,
                        "strategy": sell_config.name,
                        "mode": executor_mode(args),
                        "sampleIndex": sample_count - 1,
                        "readOnly": args.mode != "broadcast",
                        "tradeSent": False,
                        "broadcastEnabled": broadcast_enabled(args),
                        "autoApproveEnabled": auto_approve_enabled(args),
                        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                        "executionRpcSource": rpc_selection.source,
                        "sample": compact_sample(sample),
                        "position": compact_position(position),
                        "currentRoiPct": fmt_decimal(roi_pct, 4) if roi_pct is not None else None,
                        "latestBuy": {
                            "txHash": latest_buy_tx,
                            "spentV": fmt_decimal(latest_buy_v, 6) if latest_buy_v is not None else None,
                            "blockTimestamp": latest_buy.get("block_timestamp") if latest_buy else None,
                        }
                        if latest_buy
                        else None,
                        "decision": decision.as_dict(),
                    }
                    should_log = False
                    if decision.should_sell:
                        counts["sell"] = counts.get("sell", 0) + 1
                        payload = await execute_sell_decision(
                            args=args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            account=account,
                            to_checksum_address=to_checksum_address,
                            project_row=project_row,
                            project_name=project_name,
                            strategy_name=sell_config.name,
                            rule_name=sell_config.name,
                            sample=sample,
                            sample_index=sample_count - 1,
                            decision=decision,
                            position=position,
                            owner=owner,
                            token=token,
                            pool=pool,
                        )
                        should_log = True
                    elif current_fingerprint != previous_fingerprint:
                        counts["hold"] = counts.get("hold", 0) + 1
                        payload["event"] = "state_change"
                        should_log = True
                    elif (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec):
                        counts["hold"] = counts.get("hold", 0) + 1
                        payload["event"] = "heartbeat"
                        should_log = True

                    if should_log:
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                        if payload["event"] == "heartbeat":
                            last_logged_heartbeat = time.monotonic()

                    previous_sample = dict(sample)
                    previous_fingerprint = current_fingerprint

                    projected_status = str(sample.get("projectStatus") or "")
                    end_at = int(project_row.get("resolved_end_at") or 0)
                    if args.once:
                        break
                    if args.max_samples and sample_count >= int(args.max_samples):
                        break
                    if (
                        args.exit_after_end_sec > 0
                        and projected_status == "ended"
                        and end_at > 0
                        and now_ts >= end_at + int(args.exit_after_end_sec)
                    ):
                        break
                    sleep_for = poll_interval_for_status(args, projected_status)
                except Exception as exc:
                    payload = {
                        "event": "error",
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": str(args.project),
                        "rule": sell_config.name,
                        "mode": executor_mode(args),
                        "readOnly": args.mode != "broadcast",
                        "tradeSent": False,
                        "broadcastEnabled": broadcast_enabled(args),
                        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                        "executionRpcSource": rpc_selection.source,
                        "error": str(exc),
                    }
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    sleep_for = max(1.0, float(args.prelaunch_poll_sec))

                elapsed = time.monotonic() - loop_started
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, sleep_for - elapsed))

    summary = {
        "event": "service_stop",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": str(args.project),
        "rule": sell_config.name,
        "mode": executor_mode(args),
        "sampleCount": sample_count,
        "decisionCounts": counts,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "outputJsonl": str(output_jsonl),
    }
    append_jsonl(output_jsonl, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
