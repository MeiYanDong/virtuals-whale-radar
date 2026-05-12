#!/usr/bin/env python3
"""Read-only launch execution readiness check.

This script does not sign or broadcast. It validates the project row, active
fuses, execution RPC routing, wallet gas balance, and Virtuals direct-buy
simulation for the configured buy sizes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import compact_simulation, elapsed_ms  # noqa: E402
from execution_rpc import resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    TxSimulator,
    VirtualsOrderBinder,
    decimal_v_to_wei,
    normalize_hex_address,
)
from live_strategy_dry_run import cst_iso, find_project, utc_iso  # noqa: E402
from virtuals_bot import RPCClient, VirtualsBot, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only launch execution readiness check.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--amount-v", action="append", help="Buy size to simulate. Can be repeated.")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--output-json")
    return parser.parse_args()


def failed_checks(simulation: dict[str, Any]) -> list[str]:
    checks = simulation.get("checks") or {}
    return [name for name, check in checks.items() if not bool((check or {}).get("ok"))]


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_selection = resolve_execution_rpc_url(cfg)
    rpc_url = rpc_selection.rpc_url
    from_addr = normalize_hex_address(args.from_address)
    amount_values = [Decimal(str(v)) for v in (args.amount_v or ["25", "50"])]

    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output: dict[str, Any] = {
        "checkedAt": utc_iso(),
        "checkedAtCst": cst_iso(),
        "projectArg": str(args.project),
        "from": from_addr,
        "rpc": redact_rpc_url(rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "readOnly": True,
        "tradeSent": False,
        "broadcastEnabled": False,
    }

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        project_status = bot.derive_managed_project_status(project_row)
        token_addr = str(project_row.get("token_addr") or "").strip()
        pool_addr = str(project_row.get("internal_pool_addr") or "").strip()
        active_fuses = bot.storage.list_launch_execution_fuses(project_name, active_only=True, limit=20)
        output["project"] = {
            "id": project_row.get("id"),
            "name": project_name,
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "storedStatus": project_row.get("status"),
            "derivedStatus": project_status,
            "collectEnabled": bool(project_row.get("collect_enabled")),
            "tokenAddr": token_addr,
            "poolAddr": pool_addr,
            "startAt": project_row.get("start_at"),
            "resolvedEndAt": project_row.get("resolved_end_at"),
            "complete": bool(token_addr and pool_addr and project_row.get("start_at") and project_row.get("resolved_end_at")),
        }
        output["activeFuses"] = [
            {
                "project": row.get("project"),
                "strategy": row.get("strategy"),
                "ruleName": row.get("rule_name"),
                "failureStage": row.get("failure_stage"),
                "failureReason": row.get("failure_reason"),
                "updatedAt": row.get("updated_at"),
            }
            for row in active_fuses
        ]

        if not token_addr or not pool_addr:
            output["ready"] = False
            output["reason"] = "missing_token_or_pool"
        else:
            async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
                gas_balance_hex = await rpc.call("eth_getBalance", [from_addr, "latest"])
                gas_balance_wei = int(str(gas_balance_hex), 16)
                output["wallet"] = {
                    "baseEthBalanceWei": str(gas_balance_wei),
                    "hasGasForApproval": gas_balance_wei > 0,
                    "approvalCanBeSentWithoutVirtualBalance": gas_balance_wei > 0,
                    "note": "ERC20 approve does not require current VIRTUAL balance, but it does require Base ETH gas.",
                }
                checks: list[dict[str, Any]] = []
                for amount_v in amount_values:
                    row: dict[str, Any] = {"amountV": str(amount_v), "amountWei": str(decimal_v_to_wei(amount_v))}
                    try:
                        start = time.perf_counter()
                        bound = await VirtualsOrderBinder(
                            rpc,
                            virtual_token_addr=cfg.virtual_token_addr,
                            slippage_bps=int(args.slippage_bps),
                            deadline_offset_sec=int(args.deadline_offset_sec),
                        ).bind_buy(
                            chain_id=cfg.chain_id,
                            from_addr=from_addr,
                            token_addr=token_addr,
                            pool_addr=pool_addr,
                            amount_in_v=amount_v,
                            now_ts=int(time.time()),
                        )
                        row["bindBuyMs"] = elapsed_ms(start)
                        row["quote"] = asdict(bound.quote)
                        start = time.perf_counter()
                        simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
                        row["simulateMs"] = elapsed_ms(start)
                        row["simulation"] = compact_simulation(simulation)
                        row["green"] = bool(simulation["green"])
                        row["failedChecks"] = failed_checks(simulation)
                    except Exception as exc:
                        row["green"] = False
                        row["failedChecks"] = ["readiness_exception"]
                        row["error"] = str(exc)
                    checks.append(row)
                output["buySizeChecks"] = checks
                output["ready"] = (
                    output["project"]["complete"]
                    and bool(project_row.get("collect_enabled"))
                    and not rpc_selection.rpc_shared_with_main
                    and not active_fuses
                    and all(bool(row.get("green")) for row in checks)
                )
                if not output["ready"]:
                    reasons = []
                    if not output["project"]["complete"]:
                        reasons.append("project_incomplete")
                    if not bool(project_row.get("collect_enabled")):
                        reasons.append("collect_disabled")
                    if rpc_selection.rpc_shared_with_main:
                        reasons.append("execution_rpc_missing_or_shared")
                    if active_fuses:
                        reasons.append("active_fuse")
                    for row in checks:
                        for failed in row.get("failedChecks") or []:
                            reasons.append(f"{row.get('amountV')}V:{failed}")
                    output["reasons"] = reasons

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ready": output.get("ready"),
                "project": (output.get("project") or {}).get("name"),
                "derivedStatus": (output.get("project") or {}).get("derivedStatus"),
                "rpcSharedWithMain": output.get("rpcSharedWithMain"),
                "activeFuseCount": len(output.get("activeFuses") or []),
                "buySizeChecks": [
                    {
                        "amountV": row.get("amountV"),
                        "green": row.get("green"),
                        "failedChecks": row.get("failedChecks"),
                    }
                    for row in output.get("buySizeChecks", [])
                ],
                "reasons": output.get("reasons", []),
                "outputJson": args.output_json,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
