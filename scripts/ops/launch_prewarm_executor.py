#!/usr/bin/env python3
"""Realtime launch prewarm executor.

This is the production-path scaffold after the dry-run emitter:
- it watches one whitelisted managed project;
- it evaluates the frozen dynamic strategy;
- on BuyIntent it binds a direct Virtuals buy order and runs simulation;
- in sign-ready mode it signs the prewarmed tx but never prints or persists raw tx;
- in broadcast mode it sends only when both CLI and env allow gates are enabled,
  execution RPC is isolated, active fuse is clear, and risk caps pass.
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
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import (  # noqa: E402
    compact_simulation,
    elapsed_ms,
    load_secret_file,
    read_allowance,
    read_erc20_balance,
    receipt_transfer_deltas,
    suggest_fees,
    wait_receipt,
)
from execution_rpc import apply_execution_rpc_to_config, require_isolated_execution_rpc  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    BURNER_PRIVATE_KEY_ENV,
    DynamicExecutionConfig,
    DynamicAfter1StrategyEvaluator,
    LocalSigner,
    StrategyState,
    TxSimulator,
    VIRTUALS_BUY_SPENDER,
    VirtualsOrderBinder,
    resolve_rule,
)
from live_strategy_dry_run import (  # noqa: E402
    LiveClock,
    append_jsonl,
    compact_sample,
    cst_iso,
    derive_trigger_types,
    find_project,
    fingerprint,
    make_ledger_record,
    poll_interval_for_status,
    utc_iso,
)
from native_launch_replay import build_sample  # noqa: E402
from virtuals_bot import (  # noqa: E402
    DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
    DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
    RPCClient,
    VirtualsBot,
    load_config,
    redact_rpc_url,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime prewarm executor for one Virtuals project.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--mode", choices=["simulate", "sign-ready", "broadcast"], default="simulate")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--min-poll-sec", type=float, default=0.25)
    parser.add_argument("--live-poll-sec", type=float, default=0.25)
    parser.add_argument("--prelaunch-poll-sec", type=float, default=2.0)
    parser.add_argument("--scheduled-poll-sec", type=float, default=20.0)
    parser.add_argument("--heartbeat-log-sec", type=float, default=30.0)
    parser.add_argument("--exit-after-end-sec", type=int, default=0)
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--ignore-active-fuse", action="store_true")
    parser.add_argument("--enable-broadcast", action="store_true", help="Required with VWR_ENABLE_AUTO_BUY_BROADCAST=1.")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--max-buy-v", type=Decimal, default=Decimal("25"))
    parser.add_argument("--max-project-v", type=Decimal, default=Decimal("25"))
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    return parser.parse_args()


def executor_mode(args: argparse.Namespace) -> str:
    return f"prewarm_{args.mode.replace('-', '_')}"


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def broadcast_enabled(args: argparse.Namespace) -> bool:
    return args.mode == "broadcast" and bool(args.enable_broadcast) and env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST")


def ensure_secret_loaded(path: Path) -> None:
    if str(os.environ.get(BURNER_PRIVATE_KEY_ENV) or "").strip():
        return
    load_secret_file(path)


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    raw = str(value).strip()
    if not raw:
        return default
    return Decimal(raw)


def runtime_dynamic_config(row: dict[str, Any] | None) -> DynamicExecutionConfig:
    if not row:
        return DynamicExecutionConfig()
    return DynamicExecutionConfig(
        name=str(row.get("strategy") or DynamicExecutionConfig().name),
        base_buy_v=decimal_value(row.get("base_buy_v"), DynamicExecutionConfig().base_buy_v),
        dip_buy_v=decimal_value(row.get("dip_buy_v"), DynamicExecutionConfig().dip_buy_v),
        dip_from_own_cost_pct=decimal_value(
            row.get("dip_from_own_cost_pct"),
            DynamicExecutionConfig().dip_from_own_cost_pct,
        ),
        flat_pause_pct=decimal_value(row.get("flat_pause_pct"), DynamicExecutionConfig().flat_pause_pct),
        fdv_limit_enabled=False,
        fdv_limit_wan_usd=None,
        pause_after_buy_count=DynamicExecutionConfig().pause_after_buy_count,
        one_buy_per_tax_rate=DynamicExecutionConfig().one_buy_per_tax_rate,
    )


def runtime_effective_args(args: argparse.Namespace, row: dict[str, Any] | None) -> argparse.Namespace:
    if not row:
        return args
    out = copy.copy(args)
    out.max_buy_v = decimal_value(row.get("max_buy_v"), Decimal(str(args.max_buy_v or "0")))
    out.max_project_v = decimal_value(row.get("max_project_v"), Decimal(str(args.max_project_v or "0")))
    return out


def compact_runtime_config(row: dict[str, Any] | None, args: argparse.Namespace) -> dict[str, Any]:
    if not row:
        return {
            "hasOverride": False,
            "version": 0,
            "enabled": True,
            "mode": args.mode,
            "strategy": DynamicExecutionConfig().name,
            "baseBuyV": str(DynamicExecutionConfig().base_buy_v),
            "dipBuyV": str(DynamicExecutionConfig().dip_buy_v),
            "fdvLimitEnabled": False,
            "fdvLimitWanUsd": "",
            "maxBuyV": str(args.max_buy_v),
            "maxProjectV": str(args.max_project_v),
        }
    return {
        "hasOverride": True,
        "version": int(row.get("version") or 0),
        "enabled": bool(int(row.get("enabled") or 0)),
        "mode": str(row.get("mode") or "simulate"),
        "strategy": str(row.get("strategy") or ""),
        "ruleName": str(row.get("rule_name") or ""),
        "baseBuyV": str(row.get("base_buy_v") or ""),
        "dipBuyV": str(row.get("dip_buy_v") or ""),
        "dipFromOwnCostPct": str(row.get("dip_from_own_cost_pct") or ""),
        "flatPausePct": str(row.get("flat_pause_pct") or ""),
        "fdvLimitEnabled": False,
        "fdvLimitWanUsd": "",
        "maxBuyV": str(row.get("max_buy_v") or ""),
        "maxProjectV": str(row.get("max_project_v") or ""),
        "updatedAt": int(row.get("updated_at") or 0),
    }


def normalized_tax_key(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = Decimal(raw)
        if parsed == parsed.to_integral_value():
            return str(int(parsed))
        return format(parsed.normalize(), "f")
    except Exception:
        return raw


def compact_fuse(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "project": row.get("project"),
        "strategy": row.get("strategy"),
        "ruleName": row.get("rule_name"),
        "scope": row.get("scope"),
        "isActive": bool(row.get("is_active")),
        "failureStage": row.get("failure_stage"),
        "failureReason": row.get("failure_reason"),
        "sourceIntentId": row.get("source_intent_id"),
        "updatedAt": row.get("updated_at"),
    }


def failed_simulation_checks(simulation: dict[str, Any]) -> list[str]:
    checks = simulation.get("checks") or {}
    return [name for name, check in checks.items() if not bool((check or {}).get("ok"))]


def simulation_failure_reason(simulation: dict[str, Any]) -> str:
    failed = set(failed_simulation_checks(simulation))
    if "balance" in failed and "allowance" in failed:
        return "wallet_balance_and_allowance_not_ready"
    if "balance" in failed:
        return "wallet_balance_not_ready"
    if "allowance" in failed:
        return "wallet_allowance_not_ready"
    return "simulation_not_green"


def soft_wallet_readiness_reason(reason: str) -> bool:
    return reason in {
        "wallet_balance_and_allowance_not_ready",
        "wallet_balance_not_ready",
        "wallet_allowance_not_ready",
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
    action: str = "would_buy",
    simulation: dict[str, Any] | None = None,
    signed_tx_hash: str | None = None,
    broadcast_tx_hash: str | None = None,
    receipt: dict[str, Any] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    trade_sent: bool = False,
    broadcast_enabled: bool = False,
) -> None:
    bot.storage.upsert_launch_execution_record(
        {
            "intent_id": intent_id,
            "project": project_name,
            "strategy": strategy_name,
            "rule_name": rule_name,
            "mode": mode,
            "status": status,
            "action": action,
            "decision_reason": reason,
            "simulation": simulation,
            "signed_tx_hash": signed_tx_hash,
            "broadcast_tx_hash": broadcast_tx_hash,
            "receipt": receipt,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
            "trade_sent": trade_sent,
            "broadcast_enabled": broadcast_enabled,
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
    details: dict[str, Any],
) -> dict[str, Any]:
    return bot.storage.trigger_launch_execution_fuse(
        project=project_name,
        strategy=strategy_name,
        rule_name=rule_name,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        source_intent_id=intent_id,
        details=details,
    )


def sent_records(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
    return [
        row
        for row in rows
        if str(row.get("strategy") or "") == strategy_name
        and str(row.get("rule_name") or "") == rule_name
        and int(row.get("trade_sent") or 0) == 1
    ]


def sent_project_v(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> Decimal:
    total = Decimal("0")
    for row in sent_records(bot, project_name=project_name, strategy_name=strategy_name, rule_name=rule_name):
        total += decimal_value(row.get("buy_size_v"))
    return total


def tax_rate_already_sent(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    tax_rate: Any,
) -> bool:
    target = normalized_tax_key(tax_rate)
    if not target:
        return False
    for row in sent_records(bot, project_name=project_name, strategy_name=strategy_name, rule_name=rule_name):
        if normalized_tax_key(row.get("tax_rate")) == target:
            return True
    return False


def rebuild_strategy_state_from_sent_rows(rows: list[dict[str, Any]]) -> StrategyState:
    state = StrategyState()
    last_buy: dict[str, Any] | None = None
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("created_at") or 0),
            int(row.get("updated_at") or 0),
            int(row.get("id") or 0),
        ),
    )
    for row in ordered:
        action = str(row.get("action") or "").strip()
        if action not in {"would_buy", "buy"}:
            continue
        tax_key = normalized_tax_key(row.get("tax_rate"))
        buy_size = decimal_value(row.get("buy_size_v"))
        entry = decimal_value(row.get("entry_tax_fdv_wan_usd"))
        if tax_key:
            state.bought_tax_rates.add(tax_key)
        if buy_size > 0 and entry > 0:
            state.total_spent_v += buy_size
            state.weighted_cost_numerator += buy_size * entry
            if tax_key:
                last_buy = {"taxRate": tax_key, "entryTaxFdvWanUsd": str(entry)}
    state.pending_pause_buy = last_buy
    return state


def restore_strategy_state_from_ledger(
    evaluator: DynamicAfter1StrategyEvaluator,
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> StrategyState:
    evaluator.state = rebuild_strategy_state_from_sent_rows(
        sent_records(
            bot,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
        )
    )
    return evaluator.state


def compact_strategy_state(state: StrategyState) -> dict[str, Any]:
    return {
        "boughtTaxRates": sorted(state.bought_tax_rates),
        "pendingPauseBuy": state.pending_pause_buy,
        "totalSpentV": str(state.total_spent_v),
        "ownWeightedCostWanUsd": str(state.own_weighted_cost) if state.own_weighted_cost is not None else None,
    }


def sample_tax_fdv_wan(sample: dict[str, Any]) -> Decimal | None:
    value = decimal_value(sample.get("estimatedFdvWanUsdWithTax"))
    return value if value > 0 else None


def compact_fdv_limit_order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "enabled": bool(int(row.get("enabled") or 0)),
        "status": str(row.get("status") or ""),
        "triggerFdvWanUsd": str(row.get("trigger_fdv_wan_usd") or ""),
        "buyV": str(row.get("buy_v") or ""),
        "attemptCount": int(row.get("attempt_count") or 0),
        "txHash": str(row.get("broadcast_tx_hash") or ""),
        "ledgerIntentId": str(row.get("ledger_intent_id") or ""),
    }


def eligible_fdv_limit_orders(
    rows: list[dict[str, Any]],
    *,
    tax_fdv_wan_usd: Decimal | None,
    project_status: str,
) -> list[dict[str, Any]]:
    if str(project_status or "").lower() != "live":
        return []
    if tax_fdv_wan_usd is None:
        return []
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if not bool(int(row.get("enabled") or 0)):
            continue
        if str(row.get("status") or "") != "pending":
            continue
        trigger = decimal_value(row.get("trigger_fdv_wan_usd"))
        buy_v = decimal_value(row.get("buy_v"))
        if trigger <= 0 or buy_v <= 0:
            continue
        if tax_fdv_wan_usd <= trigger:
            eligible.append(row)
    return sorted(
        eligible,
        key=lambda row: (
            -decimal_value(row.get("trigger_fdv_wan_usd")),
            int(row.get("sort_order") or 0),
            int(row.get("id") or 0),
        ),
    )


def fdv_limit_order_intent(
    *,
    row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
) -> dict[str, Any]:
    entry = sample_tax_fdv_wan(sample) or Decimal("0")
    buy_v = decimal_value(row.get("buy_v"))
    return {
        "project": project_name,
        "index": sample_index,
        "timestamp": int(sample.get("simTimestamp") or 0),
        "tax_rate": str(sample.get("buyTaxRate") or ""),
        "buy_size_v": str(buy_v),
        "entry_tax_fdv_wan_usd": str(entry),
        "entry_spot_fdv_wan_usd": str(sample.get("liveFdvUsd") or ""),
        "own_weighted_cost_before_wan_usd": None,
        "own_weighted_cost_after_wan_usd": str(entry),
        "board_spent_v": str(sample.get("boardSpentV") or ""),
        "board_cost_wan_usd": str(sample.get("boardCostWanUsd") or ""),
        "cost_rows": int(sample.get("costRows") or 0),
        "whale_rows": int(sample.get("whaleRows") or 0),
        "trigger_types": ["fdv_limit_order"],
        "reason": "tax_fdv_limit_order_triggered",
        "fdvLimitOrderId": int(row.get("id") or 0),
        "fdvLimitTriggerWanUsd": str(row.get("trigger_fdv_wan_usd") or ""),
        "speedPriority": True,
    }


def receipt_summary(receipt: dict[str, Any] | None, receipt_deltas: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt and not receipt_deltas:
        return None
    return {
        "status": receipt.get("status") if receipt else None,
        "blockNumber": receipt.get("blockNumber") if receipt else None,
        "gasUsed": receipt.get("gasUsed") if receipt else None,
        "transferDeltas": receipt_deltas,
    }


async def prewarm_intent(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    rule_name: str,
    strategy_name: str,
    sample: dict[str, Any],
    sample_index: int,
    intent: dict[str, Any],
    nonce_override: int | None = None,
    skip_tax_rate_guard: bool = False,
    force_no_wait_receipt: bool = False,
) -> dict[str, Any]:
    mode = executor_mode(args)
    ledger_record = make_ledger_record(
        project_row=project_row,
        project_name=project_name,
        rule_name=rule_name,
        strategy_name=strategy_name,
        action="would_buy",
        reason="signal",
        sample_index=sample_index,
        sample=sample,
        intent=intent,
        pause=None,
    )
    ledger_record["mode"] = mode
    bot.storage.upsert_launch_execution_record(ledger_record)
    intent_id = ledger_record["intent_id"]

    payload: dict[str, Any] = {
        "event": "prewarm_intent",
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
        "intent": intent,
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

    if args.mode == "broadcast":
        if not broadcast_enabled(args):
            payload["event"] = "blocked_by_broadcast_gate"
            payload["reason"] = "missing_cli_or_env_broadcast_gate"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_broadcast_gate",
                reason="missing_cli_or_env_broadcast_gate",
                failure_stage="broadcast_gate",
                failure_reason="broadcast_not_enabled",
            )
            return payload

        buy_size = decimal_value(intent.get("buy_size_v"))
        if args.max_buy_v is not None and Decimal(args.max_buy_v) > 0 and buy_size > Decimal(args.max_buy_v):
            payload["event"] = "blocked_by_single_tx_cap"
            payload["reason"] = "buy_size_exceeds_max_buy_v"
            payload["maxBuyV"] = str(args.max_buy_v)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_single_tx_cap",
                reason="buy_size_exceeds_max_buy_v",
                failure_stage="risk_limit",
                failure_reason="buy_size_exceeds_max_buy_v",
            )
            return payload

        if not skip_tax_rate_guard and tax_rate_already_sent(
            bot,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            tax_rate=sample.get("buyTaxRate"),
        ):
            payload["event"] = "blocked_by_tax_already_sent"
            payload["reason"] = "same_tax_rate_already_broadcast"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_tax_already_sent",
                reason="same_tax_rate_already_broadcast",
                failure_stage="risk_limit",
                failure_reason="same_tax_rate_already_broadcast",
            )
            return payload

        existing_project_v = sent_project_v(
            bot,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
        )
        projected_project_v = existing_project_v + buy_size
        if (
            args.max_project_v is not None
            and Decimal(args.max_project_v) > 0
            and projected_project_v > Decimal(args.max_project_v)
        ):
            payload["event"] = "blocked_by_project_cap"
            payload["reason"] = "project_sent_v_exceeds_max_project_v"
            payload["sentProjectV"] = str(existing_project_v)
            payload["projectedProjectV"] = str(projected_project_v)
            payload["maxProjectV"] = str(args.max_project_v)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_project_cap",
                reason="project_sent_v_exceeds_max_project_v",
                failure_stage="risk_limit",
                failure_reason="project_sent_v_exceeds_max_project_v",
            )
            return payload

    token_addr = str(project_row.get("token_addr") or "").strip()
    pool_addr = str(project_row.get("internal_pool_addr") or "").strip()
    if not token_addr or not pool_addr:
        reason = "missing_token_or_pool"
        payload["event"] = "prewarm_failed"
        payload["reason"] = reason
        should_fuse = args.mode != "simulate"
        payload["fuseTriggered"] = should_fuse
        if should_fuse:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="order_binding",
                failure_reason=reason,
                details={"tokenAddr": token_addr, "poolAddr": pool_addr},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="order_binding_failed",
            reason=reason,
            failure_stage="order_binding" if should_fuse else None,
            failure_reason=reason if should_fuse else None,
        )
        return payload

    timings: dict[str, float] = {}
    try:
        start = time.perf_counter()
        bound = await VirtualsOrderBinder(
            rpc,
            virtual_token_addr=cfg.virtual_token_addr,
            slippage_bps=int(args.slippage_bps),
            deadline_offset_sec=int(args.deadline_offset_sec),
        ).bind_buy(
            chain_id=cfg.chain_id,
            from_addr=args.from_address,
            token_addr=token_addr,
            pool_addr=pool_addr,
            amount_in_v=Decimal(str(intent["buy_size_v"])),
            buy_tax_rate_pct=sample.get("buyTaxRate"),
            now_ts=int(time.time()),
        )
        timings["bindBuyMs"] = elapsed_ms(start)

        start = time.perf_counter()
        simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
        timings["simulateMs"] = elapsed_ms(start)
        simulation_compact = compact_simulation(simulation)
        payload.update(
            {
                "event": "simulation_green" if simulation["green"] else "simulation_failed",
                "quote": asdict(bound.quote),
                "simulation": simulation_compact,
                "timingsMs": timings,
            }
        )
        if not simulation["green"]:
            reason = simulation_failure_reason(simulation)
            failed_checks = failed_simulation_checks(simulation)
            payload["reason"] = reason
            payload["failedChecks"] = failed_checks
            soft_readiness = args.mode == "broadcast" and soft_wallet_readiness_reason(reason)
            should_fuse = args.mode != "simulate" and not soft_readiness
            payload["fuseTriggered"] = should_fuse
            if should_fuse:
                fuse = trigger_fuse(
                    bot,
                    project_name=project_name,
                    strategy_name=strategy_name,
                    rule_name=rule_name,
                    intent_id=intent_id,
                    failure_stage="simulation",
                    failure_reason=reason,
                    details={"simulation": simulation_compact, "failedChecks": failed_checks},
                )
                payload["activeFuse"] = compact_fuse(fuse)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="readiness_not_ready" if args.mode == "simulate" or soft_readiness else "simulation_failed",
                reason=reason,
                simulation=simulation_compact,
                failure_stage=None if args.mode == "simulate" or soft_readiness else "simulation",
                failure_reason=None if args.mode == "simulate" or soft_readiness else reason,
                broadcast_enabled=broadcast_enabled(args),
            )
            return payload

        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="simulation_green",
            reason="simulation_green",
            simulation=simulation_compact,
        )

        if args.mode == "simulate":
            payload["reason"] = "simulate_mode_no_sign"
            return payload

        start = time.perf_counter()
        fees = await suggest_fees(
            rpc,
            max_fee_gwei=args.max_fee_gwei,
            priority_gwei=args.max_priority_fee_gwei,
        )
        timings["feeSuggestMs"] = elapsed_ms(start)
        gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
        gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
        nonce_to_use = int(nonce_override) if nonce_override is not None else int(simulation["checks"]["nonce"]["pendingNonce"])
        tx = replace(
            bound.tx,
            nonce=nonce_to_use,
            gas=gas,
            max_fee_per_gas=str(fees["maxFeePerGas"]),
            max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
        )
        start = time.perf_counter()
        signed = LocalSigner().sign(tx)
        timings["signMs"] = elapsed_ms(start)
        payload.update(
            {
                "event": "signed_ready",
                "signed": True,
                "signedTxHash": signed.tx_hash,
                "signedSummary": {
                    "from": signed.from_addr,
                    "to": signed.to,
                    "chainId": signed.chain_id,
                    "nonce": signed.nonce,
                    "gas": signed.gas,
                    "maxFeePerGas": tx.max_fee_per_gas,
                    "maxPriorityFeePerGas": tx.max_priority_fee_per_gas,
                },
                "timingsMs": timings,
                "reason": "signed_no_raw_tx_persisted",
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="signed_ready",
            reason="signed_no_raw_tx_persisted",
            simulation=simulation_compact,
            signed_tx_hash=signed.tx_hash,
        )
        if args.mode == "sign-ready":
            return payload

        start = time.perf_counter()
        send_start = time.perf_counter()
        sent_hash = await rpc.call("eth_sendRawTransaction", [signed.raw_tx])
        timings["sendRawMs"] = elapsed_ms(send_start)
        timings["triggerToSendAckMs"] = elapsed_ms(start)
        payload.update(
            {
                "event": "broadcast_sent",
                "readOnly": False,
                "broadcasted": True,
                "tradeSent": True,
                "broadcastEnabled": True,
                "txHash": str(sent_hash),
                "timingsMs": timings,
                "reason": "send_raw_transaction_ack",
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
            signed_tx_hash=signed.tx_hash,
            broadcast_tx_hash=str(sent_hash),
            trade_sent=True,
            broadcast_enabled=True,
        )

        skip_receipt_wait = bool(args.no_wait_receipt or force_no_wait_receipt)
        if skip_receipt_wait:
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
                signed_tx_hash=signed.tx_hash,
                broadcast_tx_hash=str(sent_hash),
                trade_sent=True,
                broadcast_enabled=True,
            )
            return payload

        receipt_start = time.perf_counter()
        receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
        timings["waitReceiptMs"] = elapsed_ms(receipt_start)
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=args.from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        balance_start = time.perf_counter()
        virtual_after, token_after, allowance_after = await asyncio.gather(
            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=args.from_address),
            read_erc20_balance(rpc, token=token_addr, owner=args.from_address),
            read_allowance(rpc, token=cfg.virtual_token_addr, owner=args.from_address, spender=VIRTUALS_BUY_SPENDER),
        )
        timings["readAfterMs"] = elapsed_ms(balance_start)
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        receipt_status = str((receipt or {}).get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        payload.update(
            {
                "event": "receipt_success" if receipt_ok else "receipt_failed",
                "receiptSkipped": False,
                "receipt": receipt_payload,
                "balancesAfter": {
                    "virtualWei": str(virtual_after),
                    "targetTokenRaw": str(token_after),
                    "allowanceWei": str(allowance_after),
                },
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
            signed_tx_hash=signed.tx_hash,
            broadcast_tx_hash=str(sent_hash),
            receipt=receipt_payload,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else ("receipt_timeout" if receipt is None else "receipt_failed"),
            trade_sent=True,
            broadcast_enabled=True,
        )
        return payload
    except Exception as exc:
        reason = str(exc)
        payload.update({"event": "prewarm_failed", "reason": reason, "timingsMs": timings})
        should_fuse = args.mode != "simulate"
        payload["fuseTriggered"] = should_fuse
        if should_fuse:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="prewarm",
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
            status="prewarm_failed",
            reason=reason,
            failure_stage="prewarm" if should_fuse else None,
            failure_reason=reason if should_fuse else None,
        )
        return payload


async def reconcile_fdv_limit_order_receipts(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_fdv_limit_orders(
        project_id=int(project_row.get("id") or 0),
        statuses=["broadcast_sent"],
        limit=50,
    )
    token_addr = str(project_row.get("token_addr") or "").strip()
    reconciled: list[dict[str, Any]] = []
    for row in rows:
        tx_hash = str(row.get("broadcast_tx_hash") or "").strip()
        intent_id = str(row.get("ledger_intent_id") or "").strip()
        if not tx_hash or not intent_id:
            continue
        try:
            receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:
            reconciled.append(
                {
                    "order": compact_fdv_limit_order(row),
                    "status": "receipt_lookup_failed",
                    "error": str(exc),
                }
            )
            continue
        if not receipt:
            continue

        receipt_status = str(receipt.get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=args.from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        reason = "receipt_observed" if receipt_ok else "receipt_failed"
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
            rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
            mode=executor_mode(args),
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason=reason,
            receipt=receipt_payload,
            broadcast_tx_hash=tx_hash,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else "receipt_failed",
            trade_sent=True,
            broadcast_enabled=True,
        )
        bot.storage.mark_launch_fdv_limit_order_receipt(
            int(row.get("id") or 0),
            ok=receipt_ok,
            error="" if receipt_ok else "receipt_failed",
        )
        if not receipt_ok:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason="receipt_failed",
                details={"txHash": tx_hash, "receipt": receipt_payload},
            )
            active_fuse = compact_fuse(fuse)
        else:
            active_fuse = None
        reconciled.append(
            {
                "order": compact_fdv_limit_order(row),
                "status": "receipt_success" if receipt_ok else "receipt_failed",
                "receipt": receipt_payload,
                "activeFuse": active_fuse,
            }
        )
    return reconciled


async def reconcile_standard_buy_receipts(
    *,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    from_address: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
    token_addr = str(project_row.get("token_addr") or "").strip()
    reconciled: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("strategy") or "") == DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY:
            continue
        if str(row.get("action") or "") != "would_buy":
            continue
        if int(row.get("trade_sent") or 0) != 1:
            continue
        if str(row.get("status") or "") != "broadcast_sent_no_receipt_wait":
            continue
        if str(row.get("receipt_json") or "").strip():
            continue
        tx_hash = str(row.get("broadcast_tx_hash") or "").strip()
        intent_id = str(row.get("intent_id") or "").strip()
        strategy_name = str(row.get("strategy") or "").strip()
        rule_name = str(row.get("rule_name") or "").strip()
        mode = str(row.get("mode") or "prewarm_broadcast").strip()
        if not tx_hash or not intent_id or not strategy_name or not rule_name:
            continue
        try:
            receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:
            reconciled.append(
                {
                    "intentId": intent_id,
                    "txHash": tx_hash,
                    "status": "receipt_lookup_failed",
                    "error": str(exc),
                }
            )
            continue
        if not receipt:
            continue

        receipt_status = str(receipt.get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason="receipt_observed" if receipt_ok else "receipt_failed",
            simulation=json.loads(row.get("simulation_json") or "null"),
            signed_tx_hash=str(row.get("signed_tx_hash") or "") or None,
            broadcast_tx_hash=tx_hash,
            receipt=receipt_payload,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else "receipt_failed",
            trade_sent=True,
            broadcast_enabled=True,
        )
        active_fuse = None
        if not receipt_ok:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason="receipt_failed",
                details={"txHash": tx_hash, "receipt": receipt_payload},
            )
            active_fuse = compact_fuse(fuse)
        reconciled.append(
            {
                "intentId": intent_id,
                "strategy": strategy_name,
                "rule": rule_name,
                "txHash": tx_hash,
                "status": "receipt_success" if receipt_ok else "receipt_failed",
                "receipt": receipt_payload,
                "activeFuse": active_fuse,
            }
        )
    return reconciled


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.mode == "sign-ready":
        ensure_secret_loaded(Path(args.secret_file))

    rpc_selection = apply_execution_rpc_to_config(cfg)

    if args.mode == "broadcast":
        if args.max_buy_v is not None and Decimal(args.max_buy_v) < 0:
            raise SystemExit("--max-buy-v cannot be negative")
        if args.max_project_v is not None and Decimal(args.max_project_v) < 0:
            raise SystemExit("--max-project-v cannot be negative")
        if not args.enable_broadcast:
            raise SystemExit("broadcast mode requires --enable-broadcast")
        if not env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST"):
            raise SystemExit("broadcast mode requires VWR_ENABLE_AUTO_BUY_BROADCAST=1")
        require_isolated_execution_rpc(
            rpc_selection,
            action="broadcast mode",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )
        ensure_secret_loaded(Path(args.secret_file))

    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/launch-prewarm-executor-{str(args.project).strip().upper()}.jsonl"
    )
    stop_event = asyncio.Event()

    def on_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, on_stop)

    rule = resolve_rule(str(args.rule))
    clock = LiveClock()
    previous_sample: dict[str, Any] | None = None
    previous_fingerprint: tuple[Any, ...] | None = None
    last_logged_heartbeat = 0.0
    sample_count = 0
    counts = {"would_buy": 0, "prewarm": 0, "fdv_limit_order": 0, "pause": 0, "skip": 0}

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        runtime_config_row = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
        runtime_config_version = int(runtime_config_row.get("version") or 0) if runtime_config_row else 0
        evaluator = DynamicAfter1StrategyEvaluator(
            project=project_name,
            rule=rule,
            config=runtime_dynamic_config(runtime_config_row),
        )
        effective_args = runtime_effective_args(args, runtime_config_row)
        restored_state = restore_strategy_state_from_ledger(
            evaluator,
            bot,
            project_name=project_name,
            strategy_name=evaluator.config.name,
            rule_name=rule.name,
        )

        service_meta = {
            "event": "service_start",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "managedProjectId": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "rule": rule.name,
            "strategy": evaluator.config.name,
            "mode": executor_mode(args),
            "readOnly": args.mode != "broadcast",
            "tradeSent": False,
            "broadcastEnabled": broadcast_enabled(args),
            "rpc": redact_rpc_url(cfg.http_rpc_url),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "outputJsonl": str(output_jsonl),
            "maxBuyV": str(effective_args.max_buy_v),
            "maxProjectV": str(effective_args.max_project_v),
            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
            "restoredStrategyState": compact_strategy_state(restored_state),
        }
        append_jsonl(output_jsonl, service_meta)
        print(json.dumps(service_meta, ensure_ascii=False), flush=True)

        async with RPCClient(cfg.http_rpc_url, max_retries=3, timeout_sec=20) as rpc:
            while not stop_event.is_set():
                loop_started = time.monotonic()
                now_ts = int(time.time())
                project_row = find_project(bot, str(args.project))
                sample_count += 1
                try:
                    sample = await build_sample(bot, project_row, clock)
                    sample["triggerTypes"] = derive_trigger_types(previous_sample, sample)
                    current_fingerprint = fingerprint(sample)
                    reconciled_limit_orders = await reconcile_fdv_limit_order_receipts(
                        args=effective_args if "effective_args" in locals() else args,
                        cfg=cfg,
                        bot=bot,
                        rpc=rpc,
                        project_row=project_row,
                        project_name=project_name,
                    )
                    if reconciled_limit_orders:
                        receipt_payload = {
                            "event": "fdv_limit_order_receipts",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                            "strategy": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "orders": reconciled_limit_orders,
                        }
                        append_jsonl(output_jsonl, receipt_payload)
                        print(json.dumps(receipt_payload, ensure_ascii=False), flush=True)
                    reconciled_standard_buys = await reconcile_standard_buy_receipts(
                        cfg=cfg,
                        bot=bot,
                        rpc=rpc,
                        project_row=project_row,
                        project_name=project_name,
                        from_address=args.from_address,
                    )
                    if reconciled_standard_buys:
                        standard_receipt_payload = {
                            "event": "standard_buy_receipts",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "receipts": reconciled_standard_buys,
                        }
                        append_jsonl(output_jsonl, standard_receipt_payload)
                        print(json.dumps(standard_receipt_payload, ensure_ascii=False), flush=True)
                    latest_runtime_config = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
                    latest_runtime_version = int(latest_runtime_config.get("version") or 0) if latest_runtime_config else 0
                    if latest_runtime_version != runtime_config_version:
                        runtime_config_version = latest_runtime_version
                        runtime_config_row = latest_runtime_config
                        evaluator.config = runtime_dynamic_config(runtime_config_row)
                        effective_args = runtime_effective_args(args, runtime_config_row)
                        reload_payload = {
                            "event": "strategy_config_reloaded",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                        }
                        append_jsonl(output_jsonl, reload_payload)
                        print(json.dumps(reload_payload, ensure_ascii=False), flush=True)
                    else:
                        runtime_config_row = latest_runtime_config
                        effective_args = runtime_effective_args(args, runtime_config_row)

                    runtime_block_reason = ""
                    if runtime_config_row and not bool(int(runtime_config_row.get("enabled") or 0)):
                        runtime_block_reason = "runtime_config_disabled"
                    elif (
                        runtime_config_row
                        and args.mode == "broadcast"
                        and str(runtime_config_row.get("mode") or "simulate") != "broadcast"
                    ):
                        runtime_block_reason = "runtime_config_mode_not_broadcast"

                    fdv_limit_order_attempted = False
                    if not runtime_block_reason:
                        open_limit_orders = bot.storage.list_launch_fdv_limit_orders(
                            project_id=int(project_row.get("id") or 0),
                            statuses=["pending"],
                            limit=100,
                        )
                        limit_orders = eligible_fdv_limit_orders(
                            open_limit_orders,
                            tax_fdv_wan_usd=sample_tax_fdv_wan(sample),
                            project_status=str(sample.get("projectStatus") or ""),
                        )
                        next_nonce_override: int | None = None
                        for limit_order in limit_orders:
                            claimed = bot.storage.mark_launch_fdv_limit_order_triggering(int(limit_order.get("id") or 0))
                            if not claimed or str(claimed.get("status") or "") != "triggering":
                                continue
                            fdv_limit_order_attempted = True
                            counts["fdv_limit_order"] = counts.get("fdv_limit_order", 0) + 1
                            fdv_args = copy.copy(effective_args)
                            order_buy_v = decimal_value(claimed.get("buy_v"))
                            if fdv_args.max_buy_v is None or Decimal(fdv_args.max_buy_v) < order_buy_v:
                                fdv_args.max_buy_v = order_buy_v
                            limit_payload = await prewarm_intent(
                                args=fdv_args,
                                cfg=cfg,
                                bot=bot,
                                rpc=rpc,
                                project_row=project_row,
                                project_name=project_name,
                                rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                                strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                                sample=sample,
                                sample_index=sample_count - 1,
                                intent=fdv_limit_order_intent(
                                    row=claimed,
                                    project_name=project_name,
                                    sample=sample,
                                    sample_index=sample_count - 1,
                                ),
                                nonce_override=next_nonce_override,
                                skip_tax_rate_guard=True,
                                force_no_wait_receipt=True,
                            )
                            limit_payload["fdvLimitOrder"] = compact_fdv_limit_order(claimed)
                            if limit_payload.get("tradeSent"):
                                bot.storage.mark_launch_fdv_limit_order_broadcast_sent(
                                    int(claimed.get("id") or 0),
                                    tx_hash=str(limit_payload.get("txHash") or ""),
                                    ledger_intent_id=str(limit_payload.get("ledgerIntentId") or ""),
                                )
                                with contextlib.suppress(Exception):
                                    next_nonce_override = int((limit_payload.get("signedSummary") or {}).get("nonce")) + 1
                            else:
                                reason = str(limit_payload.get("reason") or limit_payload.get("event") or "")
                                if args.mode != "broadcast" or reason in {
                                    "simulate_mode_no_sign",
                                    "signed_no_raw_tx_persisted",
                                    "wallet_balance_and_allowance_not_ready",
                                    "wallet_balance_not_ready",
                                    "wallet_allowance_not_ready",
                                    "missing_cli_or_env_broadcast_gate",
                                    "active_fuse",
                                }:
                                    bot.storage.mark_launch_fdv_limit_order_retryable(
                                        int(claimed.get("id") or 0),
                                        error=reason,
                                    )
                                else:
                                    bot.storage.mark_launch_fdv_limit_order_failed(
                                        int(claimed.get("id") or 0),
                                        error=reason,
                                    )
                            append_jsonl(output_jsonl, limit_payload)
                            print(json.dumps(limit_payload, ensure_ascii=False), flush=True)

                    should_log = False
                    if runtime_block_reason:
                        counts["skip"] = counts.get("skip", 0) + 1
                        payload = {
                            "event": "runtime_config_blocked",
                            "reason": runtime_block_reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": True,
                            "tradeSent": False,
                            "broadcastEnabled": False,
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        should_log = (
                            current_fingerprint != previous_fingerprint
                            or (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec)
                        )
                    elif fdv_limit_order_attempted:
                        counts["skip"] = counts.get("skip", 0) + 1
                        payload = {
                            "event": "standard_buy_skipped_after_fdv_limit_order",
                            "reason": "fdv_limit_order_priority",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        should_log = True
                    else:
                        state_before_decision = copy.deepcopy(evaluator.state) if args.mode == "broadcast" else None
                        decision = evaluator.evaluate(sample, index=sample_count - 1)
                        counts[decision.action] = counts.get(decision.action, 0) + 1

                        payload = {
                            "event": decision.action,
                            "reason": decision.reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        if decision.intent is not None:
                            counts["prewarm"] = counts.get("prewarm", 0) + 1
                            payload = await prewarm_intent(
                                args=effective_args,
                                cfg=cfg,
                                bot=bot,
                                rpc=rpc,
                                project_row=project_row,
                                project_name=project_name,
                                rule_name=rule.name,
                                strategy_name=evaluator.config.name,
                                sample=sample,
                                sample_index=sample_count - 1,
                                intent=asdict(decision.intent),
                            )
                            payload["runtimeStrategyConfig"] = compact_runtime_config(runtime_config_row, effective_args)
                            if args.mode == "broadcast" and not bool(payload.get("tradeSent")) and state_before_decision is not None:
                                evaluator.state = state_before_decision
                            should_log = True
                        elif decision.pause is not None:
                            payload["pause"] = decision.pause
                            should_log = True
                        elif current_fingerprint != previous_fingerprint:
                            payload["event"] = "state_change"
                            should_log = True
                        elif (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec):
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
                        "rule": rule.name,
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
        "rule": str(args.rule),
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
