#!/usr/bin/env python3
"""Production launch GO/NO-GO gate.

This script is intentionally read-only: it does not sign, approve, broadcast,
or mutate runtime config. It combines the checks that should be true before a
live launch is treated as armed:

- project identity matches the operator-selected project;
- core and launch systemd services are active;
- buy/sell runtime configs are enabled in broadcast mode;
- no active execution fuse exists;
- launch_readiness_check is green for the real buy sizes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_execution_pipeline import DEFAULT_DEADLINE_OFFSET_SEC  # noqa: E402
from launch_readiness_check import build_readiness_report  # noqa: E402
from live_strategy_dry_run import cst_iso, find_project, utc_iso  # noqa: E402
from virtuals_bot import VirtualsBot, load_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only production launch preflight gate.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True, help="Burner wallet address.")
    parser.add_argument("--expected-project-id", type=int, help="Expected managed_projects.id from the admin URL.")
    parser.add_argument("--expected-project", help="Expected project symbol/name from the admin selector.")
    parser.add_argument("--amount-v", action="append", help="Buy size to check. Defaults to runtime base/dip.")
    parser.add_argument("--slippage-bps", type=int, default=9999)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--health-url", default="http://127.0.0.1:8080/health")
    parser.add_argument("--skip-systemd", action="store_true")
    parser.add_argument("--skip-sell", action="store_true", help="Do not require autosell runtime config/service.")
    parser.add_argument("--output-json")
    return parser.parse_args()


def decimal_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        normalized = Decimal(raw).normalize()
    except Exception:
        return raw
    return format(normalized, "f")


def systemd_is_active(service: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["systemctl", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return {"service": service, "active": False, "status": "systemctl_missing"}
    except Exception as exc:
        return {"service": service, "active": False, "status": "check_failed", "error": str(exc)}
    status = (completed.stdout or completed.stderr or "").strip()
    return {"service": service, "active": completed.returncode == 0 and status == "active", "status": status}


def fetch_health(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body)
        return {"ok": bool(parsed.get("ok")), "url": url, "payload": parsed}
    except urllib.error.URLError as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "url": url, "error": str(exc)}


def compact_runtime_config(row: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    if not row:
        return {"present": False, "kind": kind}
    if kind == "buy":
        return {
            "present": True,
            "kind": kind,
            "enabled": bool(int(row.get("enabled") or 0)),
            "mode": str(row.get("mode") or ""),
            "version": int(row.get("version") or 0),
            "baseBuyV": decimal_text(row.get("base_buy_v")),
            "dipBuyV": decimal_text(row.get("dip_buy_v")),
            "maxBuyV": decimal_text(row.get("max_buy_v")),
            "maxProjectV": decimal_text(row.get("max_project_v")),
            "updatedAt": int(row.get("updated_at") or 0),
        }
    return {
        "present": True,
        "kind": kind,
        "enabled": bool(int(row.get("enabled") or 0)),
        "mode": str(row.get("mode") or ""),
        "version": int(row.get("version") or 0),
        "maxTaxRate": decimal_text(row.get("max_tax_rate")),
        "cooldownSec": int(row.get("cooldown_sec") or 0),
        "catchUpEventsSec": int(row.get("catch_up_events_sec") or 0),
        "updatedAt": int(row.get("updated_at") or 0),
    }


def runtime_amounts(args: argparse.Namespace, buy_config: dict[str, Any] | None) -> list[str]:
    if args.amount_v:
        return [str(value) for value in args.amount_v]
    if buy_config:
        values = [decimal_text(buy_config.get("base_buy_v")), decimal_text(buy_config.get("dip_buy_v"))]
        unique = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        if unique:
            return unique
    return ["25", "50"]


async def collect_runtime_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False
    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or "").strip()
        project_id = int(project_row.get("id") or 0)
        buy_config = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
        sell_config = bot.storage.get_launch_sell_runtime_config_by_project(project_name)
        fdv_orders = bot.storage.list_launch_fdv_limit_orders(project_id=project_id, limit=500)
        active_fuses = bot.storage.list_launch_execution_fuses(project_name, active_only=True, limit=20)
        return {
            "project": {
                "id": project_id,
                "name": project_name,
                "signalhubProjectId": project_row.get("signalhub_project_id"),
                "storedStatus": project_row.get("status"),
                "derivedStatus": bot.derive_managed_project_status(project_row),
                "tokenAddr": str(project_row.get("token_addr") or ""),
                "poolAddr": str(project_row.get("internal_pool_addr") or ""),
                "startAt": int(project_row.get("start_at") or 0),
                "resolvedEndAt": int(project_row.get("resolved_end_at") or 0),
                "collectEnabled": bool(project_row.get("collect_enabled")),
                "watched": bool(project_row.get("is_watched")),
            },
            "buyConfig": compact_runtime_config(buy_config, "buy"),
            "sellConfig": compact_runtime_config(sell_config, "sell"),
            "fdvLimitOrders": {
                "total": len(fdv_orders),
                "enabled": len([row for row in fdv_orders if int(row.get("enabled") or 0)]),
                "pendingEnabled": len(
                    [
                        row
                        for row in fdv_orders
                        if int(row.get("enabled") or 0) and str(row.get("status") or "") == "pending"
                    ]
                ),
            },
            "activeFuses": active_fuses,
            "readinessAmounts": runtime_amounts(args, buy_config),
        }


def evaluate_gate(args: argparse.Namespace, snapshot: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    project = snapshot.get("project") or {}
    blockers: list[str] = []
    warnings: list[str] = []

    if args.expected_project_id is not None and int(project.get("id") or 0) != int(args.expected_project_id):
        blockers.append("project_id_mismatch")
    if args.expected_project and str(project.get("name") or "").strip().lower() != args.expected_project.strip().lower():
        blockers.append("project_name_mismatch")

    health = fetch_health(args.health_url)
    if not health.get("ok"):
        blockers.append("health_not_ok")
    else:
        payload = health.get("payload") or {}
        if int(payload.get("queueSize") or 0) >= 100:
            blockers.append("health_queue_backlog")
        if int(payload.get("pendingTx") or 0) != 0:
            blockers.append("health_pending_tx")
        stats = payload.get("stats") or {}
        if int(stats.get("rpc_errors") or 0) > 0:
            warnings.append("health_rpc_errors_nonzero")
        if int(stats.get("dead_letters") or 0) > 0:
            blockers.append("health_dead_letters")

    systemd: list[dict[str, Any]] = []
    if not args.skip_systemd:
        project_name = str(project.get("name") or args.project)
        required_services = [
            "vwr-signalhub.service",
            "vwr@writer.service",
            "vwr@realtime.service",
            "vwr@backfill.service",
            f"vwr-launch-autobuy@{project_name}.service",
        ]
        if not args.skip_sell:
            required_services.append(f"vwr-launch-autosell@{project_name}.service")
        recorder_services = [
            f"vwr-launch-dryrun@{project_name}.service",
            f"vwr-launch-prewarm@{project_name}.service",
        ]
        for service in required_services:
            row = systemd_is_active(service)
            systemd.append({**row, "required": True})
            if not row.get("active"):
                blockers.append(f"service_inactive:{service}")
        for service in recorder_services:
            row = systemd_is_active(service)
            systemd.append({**row, "required": False})
            if not row.get("active"):
                warnings.append(f"recorder_inactive:{service}")

    buy_config = snapshot.get("buyConfig") or {}
    if not buy_config.get("present"):
        blockers.append("buy_runtime_config_missing")
    elif not buy_config.get("enabled") or buy_config.get("mode") != "broadcast":
        blockers.append("buy_runtime_not_broadcast")

    sell_config = snapshot.get("sellConfig") or {}
    if not args.skip_sell:
        if not sell_config.get("present"):
            blockers.append("sell_runtime_config_missing")
        elif not sell_config.get("enabled") or sell_config.get("mode") != "broadcast":
            blockers.append("sell_runtime_not_broadcast")

    if snapshot.get("activeFuses"):
        blockers.append("active_fuse")

    if not readiness.get("ready"):
        blockers.append("readiness_not_ready")
        blockers.extend([f"readiness:{reason}" for reason in readiness.get("reasons") or []])

    return {
        "checkedAt": utc_iso(),
        "checkedAtCst": cst_iso(),
        "project": project,
        "go": not blockers,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "health": health,
        "systemd": systemd,
        "runtime": {
            "buy": buy_config,
            "sell": sell_config,
            "fdvLimitOrders": snapshot.get("fdvLimitOrders"),
            "activeFuseCount": len(snapshot.get("activeFuses") or []),
        },
        "readiness": readiness,
        "readOnly": True,
        "tradeSent": False,
        "broadcastEnabled": False,
    }


def write_output(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "go": report.get("go"),
                "project": (report.get("project") or {}).get("name"),
                "projectId": (report.get("project") or {}).get("id"),
                "status": (report.get("project") or {}).get("derivedStatus"),
                "blockers": report.get("blockers") or [],
                "warnings": report.get("warnings") or [],
                "buy": (report.get("runtime") or {}).get("buy"),
                "sell": (report.get("runtime") or {}).get("sell"),
                "readinessAmounts": [
                    row.get("amountV") for row in ((report.get("readiness") or {}).get("buySizeChecks") or [])
                ],
                "outputJson": args.output_json,
            },
            ensure_ascii=False,
        )
    )


async def async_main() -> int:
    args = parse_args()
    snapshot = await collect_runtime_snapshot(args)
    amounts = snapshot.get("readinessAmounts") or runtime_amounts(args, None)
    readiness_args = argparse.Namespace(
        config=args.config,
        project=args.project,
        from_address=args.from_address,
        amount_v=amounts,
        slippage_bps=args.slippage_bps,
        deadline_offset_sec=args.deadline_offset_sec,
        output_json=None,
    )
    readiness = await build_readiness_report(readiness_args)
    report = evaluate_gate(args, snapshot, readiness)
    write_output(args, report)
    return 0 if report.get("go") else 2


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
