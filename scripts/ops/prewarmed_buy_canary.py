#!/usr/bin/env python3
"""Prewarm a Virtuals direct-buy transaction and optionally broadcast at trigger.

This script is the reusable version of the hot-path canary:
- prewarm stage: read balances, bind quote, simulate, suggest fees, sign;
- trigger stage: only send the already signed raw transaction;
- default mode does not broadcast;
- no private key or raw transaction is printed or written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
from execution_rpc import require_isolated_execution_rpc, resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    LocalSigner,
    TxSimulator,
    VirtualsOrderBinder,
    VIRTUALS_BUY_SPENDER,
    normalize_hex_address,
)
from virtuals_bot import RPCClient, Storage, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prewarm one Virtuals direct-buy canary.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address", required=True)
    parser.add_argument("--project-label", required=True)
    parser.add_argument("--amount-v", default="0.001")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--trigger-delay-ms", type=int, default=0)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--output-json")
    parser.add_argument("--ledger-intent-id", default="")
    parser.add_argument("--ledger-project", default="")
    parser.add_argument("--ledger-rule", default="manual_canary")
    parser.add_argument("--ledger-strategy", default="prewarmed_buy_canary")
    parser.add_argument("--ignore-active-fuse", action="store_true")
    return parser.parse_args()


def ledger_enabled(args: argparse.Namespace) -> bool:
    return bool(str(args.ledger_intent_id or "").strip())


def ledger_project(args: argparse.Namespace) -> str:
    return str(args.ledger_project or args.project_label).strip()


def ledger_rule(args: argparse.Namespace) -> str:
    return str(args.ledger_rule or "manual_canary").strip()


def ledger_strategy(args: argparse.Namespace) -> str:
    return str(args.ledger_strategy or "prewarmed_buy_canary").strip()


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


def write_output_json(args: argparse.Namespace, output: dict[str, Any]) -> None:
    if not args.output_json:
        return
    path = Path(args.output_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def trigger_fuse(
    storage: Storage | None,
    args: argparse.Namespace,
    *,
    output: dict[str, Any],
    failure_stage: str | None,
    failure_reason: str | None,
) -> None:
    if storage is None or not failure_stage or not failure_reason:
        return
    fuse = storage.trigger_launch_execution_fuse(
        project=ledger_project(args),
        strategy=ledger_strategy(args),
        rule_name=ledger_rule(args),
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        source_intent_id=str(args.ledger_intent_id or "").strip() or None,
        details={
            "projectLabel": output.get("projectLabel"),
            "broadcastRequested": output.get("broadcastRequested"),
            "broadcasted": output.get("broadcasted"),
            "tradeSent": output.get("tradeSent"),
            "txHash": output.get("txHash"),
            "signedTxHash": output.get("signedTxHash"),
            "reason": output.get("reason"),
        },
    )
    output["activeFuse"] = compact_fuse(fuse)


def receipt_summary(receipt: dict[str, Any] | None, receipt_deltas: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt and not receipt_deltas:
        return None
    return {
        "status": receipt.get("status") if receipt else None,
        "blockNumber": receipt.get("blockNumber") if receipt else None,
        "gasUsed": receipt.get("gasUsed") if receipt else None,
        "transferDeltas": receipt_deltas,
    }


def write_ledger_stage(
    storage: Storage | None,
    args: argparse.Namespace,
    *,
    status: str,
    reason: str,
    output: dict[str, Any],
    simulation: dict[str, Any] | None = None,
    signed_tx_hash: str | None = None,
    broadcast_tx_hash: str | None = None,
    receipt: dict[str, Any] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
) -> None:
    if storage is None or not ledger_enabled(args):
        return
    storage.upsert_launch_execution_record(
        {
            "intent_id": str(args.ledger_intent_id).strip(),
            "project": ledger_project(args),
            "strategy": ledger_strategy(args),
            "rule_name": ledger_rule(args),
            "mode": "canary_broadcast" if args.broadcast else "canary_no_broadcast",
            "status": status,
            "action": "canary_buy",
            "decision_reason": reason,
            "buy_size_v": str(args.amount_v),
            "snapshot": {
                "projectLabel": output.get("projectLabel"),
                "owner": output.get("owner"),
                "token": output.get("token"),
                "pool": output.get("pool"),
                "amountV": output.get("amountV"),
                "broadcastRequested": output.get("broadcastRequested"),
                "timingsMs": output.get("prewarmTimingsMs"),
            },
            "intent": {
                "projectLabel": output.get("projectLabel"),
                "amountV": output.get("amountV"),
                "token": output.get("token"),
                "pool": output.get("pool"),
            },
            "simulation": simulation,
            "signed_tx_hash": signed_tx_hash or output.get("signedTxHash"),
            "broadcast_tx_hash": broadcast_tx_hash or output.get("txHash"),
            "receipt": receipt,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
            "trade_sent": bool(output.get("tradeSent")),
            "broadcast_enabled": bool(args.broadcast),
        }
    )
    if failure_stage != "fuse":
        trigger_fuse(
            storage,
            args,
            output=output,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )


async def async_main() -> None:
    args = parse_args()

    cfg = load_config(args.config)
    rpc_selection = resolve_execution_rpc_url(cfg)
    if args.broadcast:
        require_isolated_execution_rpc(
            rpc_selection,
            action="prewarmed buy canary broadcast",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )
    load_secret_file(Path(args.secret_file))
    owner = normalize_hex_address(args.from_address)
    token = normalize_hex_address(args.token_address)
    pool = normalize_hex_address(args.pool_address)
    rpc_url = rpc_selection.rpc_url

    output: dict[str, Any] = {
        "rpc": redact_rpc_url(rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "projectLabel": args.project_label,
        "owner": owner,
        "token": token,
        "pool": pool,
        "amountV": str(args.amount_v),
        "broadcastRequested": bool(args.broadcast),
        "broadcasted": False,
        "tradeSent": False,
        "triggerDelayMs": int(args.trigger_delay_ms),
    }
    prewarm_timings: dict[str, float] = {}
    total_start = time.perf_counter()
    ledger_storage = Storage(cfg.sqlite_path) if (ledger_enabled(args) or args.broadcast) else None

    try:
        if ledger_storage is not None:
            active_fuse = ledger_storage.get_active_launch_execution_fuse(
                project=ledger_project(args),
                strategy=ledger_strategy(args),
                rule_name=ledger_rule(args),
            )
            if active_fuse:
                output["activeFuse"] = compact_fuse(active_fuse)
                if args.broadcast and not args.ignore_active_fuse:
                    write_ledger_stage(
                        ledger_storage,
                        args,
                        status="blocked_by_active_fuse",
                        reason="active_fuse",
                        output=output,
                        failure_stage="fuse",
                        failure_reason="active_fuse",
                    )
                    raise RuntimeError("active launch execution fuse blocks broadcast")

        write_ledger_stage(
            ledger_storage,
            args,
            status="canary_started",
            reason="prewarm_started",
            output=output,
        )

        async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
            section_start = time.perf_counter()
            virtual_before, token_before, allowance_before = await asyncio.gather(
                read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
                read_erc20_balance(rpc, token=token, owner=owner),
                read_allowance(rpc, token=cfg.virtual_token_addr, owner=owner, spender=VIRTUALS_BUY_SPENDER),
            )
            prewarm_timings["readBeforeMs"] = elapsed_ms(section_start)

            section_start = time.perf_counter()
            bound = await VirtualsOrderBinder(
                rpc,
                virtual_token_addr=cfg.virtual_token_addr,
                slippage_bps=args.slippage_bps,
                deadline_offset_sec=args.deadline_offset_sec,
            ).bind_buy(
                chain_id=cfg.chain_id,
                from_addr=owner,
                token_addr=token,
                pool_addr=pool,
                amount_in_v=Decimal(str(args.amount_v)),
                now_ts=int(time.time()),
            )
            prewarm_timings["bindBuyMs"] = elapsed_ms(section_start)

            section_start = time.perf_counter()
            simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
            prewarm_timings["simulateMs"] = elapsed_ms(section_start)
            simulation_compact = compact_simulation(simulation)
            output.update(
                {
                    "quote": asdict(bound.quote),
                    "balancesBefore": {
                        "virtualWei": str(virtual_before),
                        "targetTokenRaw": str(token_before),
                        "allowanceWei": str(allowance_before),
                    },
                    "simulation": simulation_compact,
                }
            )

            if not simulation["green"]:
                output["reason"] = "simulation_not_green"
                write_ledger_stage(
                    ledger_storage,
                    args,
                    status="simulation_failed",
                    reason="simulation_not_green",
                    output=output,
                    simulation=simulation_compact,
                    failure_stage="simulation",
                    failure_reason="simulation_not_green",
                )
            else:
                write_ledger_stage(
                    ledger_storage,
                    args,
                    status="simulation_green",
                    reason="simulation_green",
                    output=output,
                    simulation=simulation_compact,
                )

                gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
                gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
                section_start = time.perf_counter()
                fees = await suggest_fees(
                    rpc,
                    max_fee_gwei=args.max_fee_gwei,
                    priority_gwei=args.max_priority_fee_gwei,
                )
                prewarm_timings["feeSuggestMs"] = elapsed_ms(section_start)
                tx = replace(
                    bound.tx,
                    nonce=int(simulation["checks"]["nonce"]["pendingNonce"]),
                    gas=gas,
                    max_fee_per_gas=str(fees["maxFeePerGas"]),
                    max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
                )
                section_start = time.perf_counter()
                signed = LocalSigner().sign(tx)
                prewarm_timings["signMs"] = elapsed_ms(section_start)
                prewarm_timings["totalPrewarmMs"] = elapsed_ms(total_start)
                output.update(
                    {
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
                    }
                )
                write_ledger_stage(
                    ledger_storage,
                    args,
                    status="signed_ready",
                    reason="signed_no_raw_tx_persisted",
                    output=output,
                    simulation=simulation_compact,
                    signed_tx_hash=signed.tx_hash,
                )

                if args.trigger_delay_ms > 0:
                    await asyncio.sleep(int(args.trigger_delay_ms) / 1000)

                if args.broadcast:
                    trigger_start = time.perf_counter()
                    section_start = time.perf_counter()
                    sent_hash = await rpc.call("eth_sendRawTransaction", [signed.raw_tx])
                    trigger_to_ack_ms = elapsed_ms(trigger_start)
                    send_raw_ms = elapsed_ms(section_start)
                    output.update(
                        {
                            "broadcasted": True,
                            "tradeSent": True,
                            "txHash": str(sent_hash),
                            "sendRawMs": send_raw_ms,
                            "triggerToSendAckMs": trigger_to_ack_ms,
                        }
                    )
                    write_ledger_stage(
                        ledger_storage,
                        args,
                        status="broadcast_sent",
                        reason="send_raw_transaction_ack",
                        output=output,
                        simulation=simulation_compact,
                        signed_tx_hash=signed.tx_hash,
                        broadcast_tx_hash=str(sent_hash),
                    )

                    receipt = None
                    receipt_deltas = None
                    virtual_after = None
                    token_after = None
                    allowance_after = None
                    if not args.no_wait_receipt:
                        section_start = time.perf_counter()
                        receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
                        output["waitReceiptMs"] = elapsed_ms(section_start)
                        receipt_deltas = receipt_transfer_deltas(
                            receipt,
                            owner=owner,
                            virtual_token=cfg.virtual_token_addr,
                            target_token=token,
                        )
                        virtual_after, token_after, allowance_after = await asyncio.gather(
                            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
                            read_erc20_balance(rpc, token=token, owner=owner),
                            read_allowance(
                                rpc,
                                token=cfg.virtual_token_addr,
                                owner=owner,
                                spender=VIRTUALS_BUY_SPENDER,
                            ),
                        )
                    output.update(
                        {
                            "receiptSkipped": bool(args.no_wait_receipt),
                            "receipt": {
                                "status": receipt.get("status") if receipt else None,
                                "blockNumber": receipt.get("blockNumber") if receipt else None,
                                "gasUsed": receipt.get("gasUsed") if receipt else None,
                            }
                            if receipt
                            else None,
                            "receiptTransferDeltas": receipt_deltas,
                            "balancesAfter": {
                                "virtualWei": str(virtual_after),
                                "targetTokenRaw": str(token_after),
                                "allowanceWei": str(allowance_after),
                            }
                            if virtual_after is not None and token_after is not None and allowance_after is not None
                            else None,
                        }
                    )
                    if args.no_wait_receipt:
                        write_ledger_stage(
                            ledger_storage,
                            args,
                            status="broadcast_sent_no_receipt_wait",
                            reason="receipt_wait_skipped",
                            output=output,
                            simulation=simulation_compact,
                            signed_tx_hash=signed.tx_hash,
                            broadcast_tx_hash=str(sent_hash),
                        )
                    else:
                        receipt_status = str((receipt or {}).get("status") or "")
                        write_ledger_stage(
                            ledger_storage,
                            args,
                            status="receipt_success" if receipt_status in {"0x1", "1"} else "receipt_failed",
                            reason="receipt_observed" if receipt else "receipt_timeout",
                            output=output,
                            simulation=simulation_compact,
                            signed_tx_hash=signed.tx_hash,
                            broadcast_tx_hash=str(sent_hash),
                            receipt=receipt_summary(receipt, receipt_deltas),
                            failure_stage=None if receipt_status in {"0x1", "1"} else "receipt",
                            failure_reason=None
                            if receipt_status in {"0x1", "1"}
                            else ("receipt_timeout" if receipt is None else "receipt_failed"),
                        )

        output["prewarmTimingsMs"] = prewarm_timings
        output["totalMs"] = elapsed_ms(total_start)
    except Exception as exc:
        output["reason"] = str(exc)
        output["prewarmTimingsMs"] = prewarm_timings
        output["totalMs"] = elapsed_ms(total_start)
        blocked_by_active_fuse = str(exc) == "active launch execution fuse blocks broadcast"
        if not blocked_by_active_fuse:
            trigger_fuse(
                ledger_storage,
                args,
                output=output,
                failure_stage="canary",
                failure_reason=str(exc),
            )
            write_ledger_stage(
                ledger_storage,
                args,
                status="canary_failed",
                reason="exception",
                output=output,
                simulation=output.get("simulation"),
                failure_stage="canary",
                failure_reason=str(exc),
            )
        write_output_json(args, output)
        raise
    finally:
        if ledger_storage is not None:
            ledger_storage.close()

    write_output_json(args, output)

    print(
        json.dumps(
            {
                "projectLabel": output["projectLabel"],
                "simulationGreen": output.get("simulation", {}).get("green"),
                "broadcasted": output["broadcasted"],
                "tradeSent": output["tradeSent"],
                "rpcSharedWithMain": output.get("rpcSharedWithMain"),
                "executionRpcSource": output.get("executionRpcSource"),
                "txHash": output.get("txHash"),
                "signedTxHash": output.get("signedTxHash"),
                "triggerToSendAckMs": output.get("triggerToSendAckMs"),
                "sendRawMs": output.get("sendRawMs"),
                "receiptStatus": output.get("receipt", {}).get("status") if output.get("receipt") else None,
                "prewarmTimingsMs": output.get("prewarmTimingsMs"),
                "reason": output.get("reason"),
                "outputJson": args.output_json,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
