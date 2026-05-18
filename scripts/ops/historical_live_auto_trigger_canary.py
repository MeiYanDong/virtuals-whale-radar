#!/usr/bin/env python3
"""Historical-sample driven live auto-trigger canary.

This canary is stricter than the fixture full-window canary:
- decision data comes from a real historical launch sample stream;
- runtime buy/sell configs are changed during the stream and hot-reloaded;
- actual execution uses the current tradable internal-market project;
- the buy and sell are real on-chain broadcasts, guarded by the normal gates.

It validates automatic triggering and runtime config propagation. It does not
try to reproduce historical fill price because the broadcast happens against
the current chain state.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import load_secret_file, read_allowance, read_erc20_balance  # noqa: E402
from execution_rpc import apply_execution_rpc_to_config, require_isolated_execution_rpc  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    DynamicAfter1StrategyEvaluator,
    VIRTUALS_BUY_SPENDER,
    normalize_hex_address,
    resolve_rule,
)
from launch_prewarm_executor import (  # noqa: E402
    compact_runtime_config,
    runtime_dynamic_config,
    runtime_effective_args as buy_runtime_effective_args,
    prewarm_intent,
)
from launch_sell_executor import (  # noqa: E402
    build_position_from_records,
    compact_runtime_sell_config,
    current_roi_pct,
    execute_sell_decision,
    multi_state_from_position,
    runtime_custom_sell_config,
    runtime_effective_args as sell_runtime_effective_args,
)
from launch_sell_strategy import (  # noqa: E402
    MultiSellInput,
    evaluate_custom_sell,
)
from live_strategy_dry_run import append_jsonl, cst_iso, find_project, utc_iso  # noqa: E402
from virtuals_bot import RPCClient, VirtualsBot, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a historical live auto-trigger canary.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--samples-jsonl", required=True)
    parser.add_argument("--decision-label", default="SR")
    parser.add_argument("--execution-project", required=True)
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--initial-buy-v", type=Decimal, default=Decimal("0.005"))
    parser.add_argument("--updated-buy-v", type=Decimal, default=Decimal("0.01"))
    parser.add_argument("--max-project-v", type=Decimal, default=Decimal("0.01"))
    parser.add_argument("--buy-update-index", type=int, default=30)
    parser.add_argument("--sell-update-index", type=int, default=700)
    parser.add_argument("--sell-roi-pct", type=Decimal, default=Decimal("0"))
    parser.add_argument(
        "--sell-trigger-mode",
        choices=["roi", "price_zero"],
        default="roi",
        help="Sell trigger for the canary. price_zero verifies the sell path after max tax without requiring positive ROI.",
    )
    parser.add_argument("--sell-max-tax-rate", type=Decimal, default=Decimal("30"))
    parser.add_argument("--sell-pct", type=Decimal, default=Decimal("100"))
    parser.add_argument("--sleep-sec", type=Decimal, default=Decimal("0"))
    parser.add_argument("--no-sleep", action="store_true")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--sell-slippage-bps", type=int, default=500)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--post-balance-timeout-sec", type=int, default=20)
    parser.add_argument("--post-balance-interval-sec", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--ignore-active-fuse", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    return parser.parse_args()


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            if isinstance(item, dict):
                rows.append(item)
    if not rows:
        raise ValueError(f"no samples found: {path}")
    return rows


def decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def make_buy_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        config=args.config,
        project=args.execution_project,
        from_address=normalize_hex_address(args.from_address),
        secret_file=args.secret_file,
        rule="gate_5k_tax95_fdv_one_per_tax",
        mode="broadcast",
        output_jsonl="",
        once=False,
        max_samples=0,
        min_poll_sec=0.25,
        live_poll_sec=0.25,
        prelaunch_poll_sec=2.0,
        scheduled_poll_sec=20.0,
        heartbeat_log_sec=30.0,
        exit_after_end_sec=0,
        slippage_bps=int(args.slippage_bps),
        deadline_offset_sec=DEFAULT_DEADLINE_OFFSET_SEC,
        gas_buffer_bps=2000,
        max_fee_gwei=None,
        max_priority_fee_gwei=None,
        ignore_active_fuse=bool(args.ignore_active_fuse),
        enable_broadcast=True,
        allow_shared_rpc_broadcast=bool(args.allow_shared_rpc_broadcast),
        max_buy_v=args.updated_buy_v,
        max_project_v=args.max_project_v,
        receipt_timeout_sec=int(args.receipt_timeout_sec),
        no_wait_receipt=False,
    )


def make_sell_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        config=args.config,
        project=args.execution_project,
        from_address=normalize_hex_address(args.from_address),
        secret_file=args.secret_file,
        rule="custom_multi_sell",
        mode="broadcast",
        output_jsonl="",
        once=False,
        max_samples=0,
        min_poll_sec=0.25,
        live_poll_sec=0.25,
        prelaunch_poll_sec=2.0,
        scheduled_poll_sec=20.0,
        heartbeat_log_sec=30.0,
        catch_up_events_sec=120,
        exit_after_end_sec=300,
        slippage_bps=int(args.sell_slippage_bps),
        deadline_offset_sec=DEFAULT_DEADLINE_OFFSET_SEC,
        gas_buffer_bps=2000,
        max_fee_gwei=None,
        max_priority_fee_gwei=None,
        receipt_timeout_sec=int(args.receipt_timeout_sec),
        no_wait_receipt=False,
        enable_broadcast=True,
        allow_shared_rpc_broadcast=bool(args.allow_shared_rpc_broadcast),
        auto_approve=True,
        ignore_active_fuse=bool(args.ignore_active_fuse),
    )


def buy_payload_for(
    *,
    strategy: str,
    rule_name: str,
    enabled: bool,
    mode: str,
    buy_v: Decimal,
    max_project_v: Decimal,
    reason: str,
) -> dict[str, Any]:
    return {
        "strategy": strategy,
        "ruleName": rule_name,
        "enabled": bool(enabled),
        "mode": mode,
        "baseBuyV": decimal_text(buy_v),
        "dipBuyV": decimal_text(buy_v),
        "dipFromOwnCostPct": "20",
        "flatPausePct": "10",
        "maxBuyV": decimal_text(buy_v),
        "maxProjectV": decimal_text(max_project_v),
        "updatedReason": reason,
    }


def sell_payload_for(
    *,
    strategy: str,
    enabled: bool,
    mode: str,
    max_tax_rate: Decimal,
    roi_pct: Decimal,
    sell_pct: Decimal,
    trigger_mode: str,
    reason: str,
) -> dict[str, Any]:
    if trigger_mode == "price_zero":
        conditions = [
            {
                "id": "price",
                "type": "price",
                "priceThreshold": "0",
                "priceUnit": "usd",
            }
        ]
        label = "历史样本 canary 价格触发退出"
    else:
        conditions = [
            {"id": "roi", "type": "roi", "roiPct": decimal_text(roi_pct)},
        ]
        label = "历史样本 canary 收益退出"
    return {
        "strategy": strategy,
        "ruleName": strategy,
        "enabled": bool(enabled),
        "mode": mode,
        "maxTaxRate": decimal_text(max_tax_rate),
        "roiLowPct": "30",
        "roiHighPct": "50",
        "largeBuyLowV": "5000",
        "largeBuyHighV": "8000",
        "sellLowPct": "30",
        "sellHighPct": "50",
        "cooldownSec": 0,
        "catchUpEventsSec": 120,
        "customRules": [
            {
                "id": "historical_canary_roi_exit",
                "type": "condition_group",
                "operator": "and",
                "enabled": True,
                "sellPct": decimal_text(sell_pct),
                "label": label,
                "conditions": conditions,
            }
        ],
        "updatedReason": reason,
    }


def row_to_buy_payload(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "strategy": row.get("strategy"),
        "ruleName": row.get("rule_name"),
        "enabled": bool(int(row.get("enabled") or 0)),
        "mode": row.get("mode"),
        "baseBuyV": row.get("base_buy_v"),
        "dipBuyV": row.get("dip_buy_v"),
        "dipFromOwnCostPct": row.get("dip_from_own_cost_pct"),
        "flatPausePct": row.get("flat_pause_pct"),
        "maxBuyV": row.get("max_buy_v"),
        "maxProjectV": row.get("max_project_v"),
        "updatedReason": reason,
    }


def row_to_sell_payload(row: dict[str, Any], *, reason: str) -> dict[str, Any]:
    custom_rules = []
    try:
        parsed = json.loads(str(row.get("custom_rules_json") or "[]"))
        if isinstance(parsed, list):
            custom_rules = parsed
    except Exception:
        custom_rules = []
    return {
        "strategy": row.get("strategy"),
        "ruleName": row.get("rule_name"),
        "enabled": bool(int(row.get("enabled") or 0)),
        "mode": row.get("mode"),
        "maxTaxRate": row.get("max_tax_rate"),
        "roiLowPct": row.get("roi_low_pct"),
        "roiHighPct": row.get("roi_high_pct"),
        "largeBuyLowV": row.get("large_buy_low_v"),
        "largeBuyHighV": row.get("large_buy_high_v"),
        "sellLowPct": row.get("sell_low_pct"),
        "sellHighPct": row.get("sell_high_pct"),
        "cooldownSec": int(row.get("cooldown_sec") or 0),
        "catchUpEventsSec": int(row.get("catch_up_events_sec") or 120),
        "customRules": custom_rules,
        "updatedReason": reason,
    }


def compact_event(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "event",
        "reason",
        "project",
        "decisionSource",
        "sampleIndex",
        "taxRate",
        "runtimeVersion",
        "tradeSent",
        "broadcastEnabled",
        "autoApproveEnabled",
        "txHash",
        "ledgerIntentId",
        "receipt",
        "timingsMs",
        "runtimeStrategyConfig",
        "runtimeSellConfig",
    ]
    return {key: payload.get(key) for key in keys if key in payload}


def current_run_records(rows: list[dict[str, Any]], *, buy_strategy: str, sell_strategy: str) -> list[dict[str, Any]]:
    allowed = {str(buy_strategy).strip(), str(sell_strategy).strip()}
    return [row for row in rows if str(row.get("strategy") or "").strip() in allowed]


async def wait_balance_condition(
    rpc: RPCClient,
    *,
    token: str,
    owner: str,
    timeout_sec: int,
    interval_sec: Decimal,
    want_zero: bool,
) -> tuple[int, list[str]]:
    deadline = time.time() + max(0, int(timeout_sec))
    reads: list[str] = []
    last = 0
    while True:
        last = await read_erc20_balance(rpc, token=token, owner=owner)
        reads.append(str(last))
        if (want_zero and last == 0) or ((not want_zero) and last > 0):
            return last, reads
        if time.time() >= deadline:
            return last, reads
        await asyncio.sleep(float(interval_sec))


async def async_main() -> None:
    args = parse_args()
    if args.sell_max_tax_rate > Decimal("30"):
        raise SystemExit("--sell-max-tax-rate cannot exceed production sell window 30 for this canary")
    if not env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST"):
        raise SystemExit("requires VWR_ENABLE_AUTO_BUY_BROADCAST=1")
    if not env_flag_enabled("VWR_ENABLE_AUTO_SELL_BROADCAST"):
        raise SystemExit("requires VWR_ENABLE_AUTO_SELL_BROADCAST=1")
    if not env_flag_enabled("VWR_ENABLE_AUTO_SELL_APPROVE"):
        raise SystemExit("requires VWR_ENABLE_AUTO_SELL_APPROVE=1")
    if args.initial_buy_v <= 0 or args.updated_buy_v <= 0 or args.max_project_v <= 0:
        raise SystemExit("buy amounts and max project amount must be positive")
    if args.updated_buy_v > args.max_project_v:
        raise SystemExit("--updated-buy-v cannot exceed --max-project-v")

    cfg = load_config(args.config)
    rpc_selection = apply_execution_rpc_to_config(cfg)
    require_isolated_execution_rpc(
        rpc_selection,
        action="historical live auto-trigger canary",
        allow_shared=bool(args.allow_shared_rpc_broadcast),
    )

    owner = normalize_hex_address(args.from_address)
    load_secret_file(Path(args.secret_file))
    try:
        from eth_account import Account
        from eth_utils import to_checksum_address
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("eth-account and eth-utils are required") from exc
    account = Account.from_key(os.environ[BURNER_PRIVATE_KEY_ENV])
    if normalize_hex_address(account.address) != owner:
        raise ValueError("secret file private key does not match --from-address")

    samples_path = Path(args.samples_jsonl)
    samples = load_samples(samples_path)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/historical-live-auto-trigger-canary-{args.execution_project}-{args.decision_label}-{run_id}.jsonl"
    )
    summary_json = Path(args.summary_json) if args.summary_json else output_jsonl.with_suffix(".summary.json")
    buy_strategy_name = f"historical_canary_buy_{run_id.replace('-', '_')}"
    sell_strategy_name = f"historical_canary_sell_{run_id.replace('-', '_')}"
    buy_args = make_buy_args(args)
    sell_args = make_sell_args(args)
    rule = resolve_rule(str(buy_args.rule))

    counts: dict[str, int] = {}
    buy_payloads: list[dict[str, Any]] = []
    sell_payloads: list[dict[str, Any]] = []
    config_events: list[dict[str, Any]] = []
    buy_sent = False
    sell_done = False
    last_buy_sample_index: int | None = None
    buy_intent_sample_index: int | None = None
    sell_intent_sample_index: int | None = None
    restored_configs = False

    def count(event: str) -> None:
        counts[event] = counts.get(event, 0) + 1

    start_payload = {
        "event": "service_start",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "executionProject": str(args.execution_project),
        "decisionSource": str(args.decision_label),
        "samplesJsonl": str(samples_path),
        "sampleCount": len(samples),
        "autoTrigger": True,
        "paperOnly": False,
        "mode": "broadcast",
        "rpc": redact_rpc_url(cfg.http_rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "buyStrategy": buy_strategy_name,
        "sellStrategy": sell_strategy_name,
        "initialBuyV": decimal_text(args.initial_buy_v),
        "updatedBuyV": decimal_text(args.updated_buy_v),
        "maxProjectV": decimal_text(args.max_project_v),
        "sellMaxTaxRate": decimal_text(args.sell_max_tax_rate),
        "sellRoiPct": decimal_text(args.sell_roi_pct),
        "sellTriggerMode": args.sell_trigger_mode,
        "sellPct": decimal_text(args.sell_pct),
    }
    append_jsonl(output_jsonl, start_payload)
    print(json.dumps(start_payload, ensure_ascii=False), flush=True)

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.execution_project))
        project_name = str(project_row.get("name") or args.execution_project).strip()
        token = normalize_hex_address(str(project_row.get("token_addr") or ""))
        pool = normalize_hex_address(str(project_row.get("internal_pool_addr") or ""))
        if not token or not pool:
            raise ValueError(f"execution project missing token/pool: {project_name}")

        previous_buy_config = copy.deepcopy(bot.storage.get_launch_strategy_runtime_config_by_project(project_name))
        previous_sell_config = copy.deepcopy(bot.storage.get_launch_sell_runtime_config_by_project(project_name))

        initial_buy_row = bot.storage.upsert_launch_strategy_runtime_config(
            project_row=project_row,
            payload=buy_payload_for(
                strategy=buy_strategy_name,
                rule_name=rule.name,
                enabled=True,
                mode="broadcast",
                buy_v=args.initial_buy_v,
                max_project_v=args.max_project_v,
                reason="historical canary initial buy config",
            ),
        )
        initial_sell_row = bot.storage.upsert_launch_sell_runtime_config(
            project_row=project_row,
            payload=sell_payload_for(
                strategy=sell_strategy_name,
                enabled=False,
                mode="simulate",
                max_tax_rate=args.sell_max_tax_rate,
                roi_pct=args.sell_roi_pct,
                sell_pct=args.sell_pct,
                trigger_mode=args.sell_trigger_mode,
                reason="historical canary initial sell disabled config",
            ),
        )
        initial_config_payload = {
            "event": "runtime_configs_seeded",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "decisionSource": args.decision_label,
            "runtimeStrategyConfig": compact_runtime_config(initial_buy_row, buy_args),
            "runtimeSellConfig": compact_runtime_sell_config(
                initial_sell_row,
                sell_args,
                runtime_custom_sell_config(initial_sell_row, default_name=sell_strategy_name),
            ),
            "tradeSent": False,
            "broadcastEnabled": False,
        }
        append_jsonl(output_jsonl, initial_config_payload)
        print(json.dumps(compact_event(initial_config_payload), ensure_ascii=False), flush=True)
        config_events.append(initial_config_payload)
        count("runtime_configs_seeded")

        runtime_buy_row = initial_buy_row
        runtime_buy_version = int(runtime_buy_row.get("version") or 0)
        evaluator = DynamicAfter1StrategyEvaluator(
            project=project_name,
            rule=rule,
            config=runtime_dynamic_config(runtime_buy_row),
        )
        effective_buy_args = buy_runtime_effective_args(buy_args, runtime_buy_row)

        runtime_sell_row = initial_sell_row
        runtime_sell_version = int(runtime_sell_row.get("version") or 0)
        sell_config = runtime_custom_sell_config(runtime_sell_row, default_name=sell_strategy_name)
        effective_sell_args = sell_runtime_effective_args(sell_args, runtime_sell_row)

        try:
            async with RPCClient(cfg.http_rpc_url, max_retries=3, timeout_sec=20) as rpc:
                for index, raw_sample in enumerate(samples):
                    sample = dict(raw_sample)
                    sample["projectStatus"] = "live"
                    trigger_types = list(sample.get("triggerTypes") or [])
                    if "historical_replay" not in trigger_types:
                        trigger_types.append("historical_replay")
                    sample["triggerTypes"] = trigger_types
                    sample["decisionSource"] = args.decision_label
                    count("samples")

                    if index == int(args.buy_update_index):
                        row = bot.storage.upsert_launch_strategy_runtime_config(
                            project_row=project_row,
                            payload=buy_payload_for(
                                strategy=buy_strategy_name,
                                rule_name=rule.name,
                                enabled=True,
                                mode="broadcast",
                                buy_v=args.updated_buy_v,
                                max_project_v=args.max_project_v,
                                reason="historical canary admin buy amount update",
                            ),
                        )
                        payload = {
                            "event": "admin_buy_config_update_applied",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "decisionSource": args.decision_label,
                            "sampleIndex": index,
                            "taxRate": sample.get("buyTaxRate"),
                            "runtimeStrategyConfig": compact_runtime_config(row, buy_args),
                            "tradeSent": False,
                            "broadcastEnabled": False,
                        }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        config_events.append(payload)
                        count("admin_buy_config_update_applied")

                    if index == int(args.sell_update_index):
                        row = bot.storage.upsert_launch_sell_runtime_config(
                            project_row=project_row,
                            payload=sell_payload_for(
                                strategy=sell_strategy_name,
                                enabled=True,
                                mode="broadcast",
                                max_tax_rate=args.sell_max_tax_rate,
                                roi_pct=args.sell_roi_pct,
                                sell_pct=args.sell_pct,
                                trigger_mode=args.sell_trigger_mode,
                                reason="historical canary admin sell config update",
                            ),
                        )
                        payload = {
                            "event": "admin_sell_config_update_applied",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "decisionSource": args.decision_label,
                            "sampleIndex": index,
                            "taxRate": sample.get("buyTaxRate"),
                            "runtimeSellConfig": compact_runtime_sell_config(
                                row,
                                sell_args,
                                runtime_custom_sell_config(row, default_name=sell_strategy_name),
                            ),
                            "tradeSent": False,
                            "broadcastEnabled": False,
                        }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        config_events.append(payload)
                        count("admin_sell_config_update_applied")

                    latest_buy_row = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
                    latest_buy_version = int(latest_buy_row.get("version") or 0) if latest_buy_row else 0
                    if latest_buy_version != runtime_buy_version:
                        runtime_buy_version = latest_buy_version
                        runtime_buy_row = latest_buy_row
                        evaluator.config = runtime_dynamic_config(runtime_buy_row)
                        effective_buy_args = buy_runtime_effective_args(buy_args, runtime_buy_row)
                        payload = {
                            "event": "strategy_config_reloaded",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "decisionSource": args.decision_label,
                            "sampleIndex": index,
                            "taxRate": sample.get("buyTaxRate"),
                            "runtimeVersion": runtime_buy_version,
                            "runtimeStrategyConfig": compact_runtime_config(runtime_buy_row, effective_buy_args),
                            "tradeSent": False,
                            "broadcastEnabled": False,
                        }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        config_events.append(payload)
                        count("strategy_config_reloaded")
                    else:
                        runtime_buy_row = latest_buy_row
                        effective_buy_args = buy_runtime_effective_args(buy_args, runtime_buy_row)

                    latest_sell_row = bot.storage.get_launch_sell_runtime_config_by_project(project_name)
                    latest_sell_version = int(latest_sell_row.get("version") or 0) if latest_sell_row else 0
                    if latest_sell_version != runtime_sell_version:
                        runtime_sell_version = latest_sell_version
                        runtime_sell_row = latest_sell_row
                        sell_config = runtime_custom_sell_config(runtime_sell_row, default_name=sell_strategy_name)
                        effective_sell_args = sell_runtime_effective_args(sell_args, runtime_sell_row)
                        payload = {
                            "event": "sell_config_reloaded",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "decisionSource": args.decision_label,
                            "sampleIndex": index,
                            "taxRate": sample.get("buyTaxRate"),
                            "runtimeVersion": runtime_sell_version,
                            "runtimeSellConfig": compact_runtime_sell_config(runtime_sell_row, effective_sell_args, sell_config),
                            "tradeSent": False,
                            "broadcastEnabled": False,
                        }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        config_events.append(payload)
                        count("sell_config_reloaded")
                    else:
                        runtime_sell_row = latest_sell_row
                        effective_sell_args = sell_runtime_effective_args(sell_args, runtime_sell_row)

                    if not buy_sent:
                        runtime_block_reason = ""
                        if runtime_buy_row and not bool(int(runtime_buy_row.get("enabled") or 0)):
                            runtime_block_reason = "runtime_config_disabled"
                        elif runtime_buy_row and str(runtime_buy_row.get("mode") or "simulate") != "broadcast":
                            runtime_block_reason = "runtime_config_mode_not_broadcast"
                        if not runtime_block_reason:
                            decision = evaluator.evaluate(sample, index=index)
                            if decision.intent is not None:
                                buy_intent_sample_index = index
                                intent = asdict(decision.intent)
                                payload = await prewarm_intent(
                                    args=effective_buy_args,
                                    cfg=cfg,
                                    bot=bot,
                                    rpc=rpc,
                                    project_row=project_row,
                                    project_name=project_name,
                                    rule_name=rule.name,
                                    strategy_name=buy_strategy_name,
                                    sample=sample,
                                    sample_index=index,
                                    intent=intent,
                                )
                                payload["autoTriggerSource"] = "historical_sample_stream"
                                payload["decisionSource"] = args.decision_label
                                payload["taxRate"] = sample.get("buyTaxRate")
                                payload["runtimeStrategyConfig"] = compact_runtime_config(runtime_buy_row, effective_buy_args)
                                append_jsonl(output_jsonl, payload)
                                print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                                buy_payloads.append(payload)
                                count(str(payload.get("event") or "buy_unknown"))
                                if payload.get("event") == "receipt_success" and payload.get("tradeSent"):
                                    buy_sent = True
                                    last_buy_sample_index = index
                                    balance, reads = await wait_balance_condition(
                                        rpc,
                                        token=token,
                                        owner=owner,
                                        timeout_sec=int(args.post_balance_timeout_sec),
                                        interval_sec=Decimal(str(args.post_balance_interval_sec)),
                                        want_zero=False,
                                    )
                                    balance_payload = {
                                        "event": "post_buy_balance_visible" if balance > 0 else "post_buy_balance_not_visible",
                                        "at": utc_iso(),
                                        "atCst": cst_iso(),
                                        "project": project_name,
                                        "decisionSource": args.decision_label,
                                        "sampleIndex": index,
                                        "taxRate": sample.get("buyTaxRate"),
                                        "tokenBalanceRaw": str(balance),
                                        "reads": reads,
                                        "tradeSent": False,
                                        "broadcastEnabled": False,
                                    }
                                    append_jsonl(output_jsonl, balance_payload)
                                    print(json.dumps(compact_event(balance_payload), ensure_ascii=False), flush=True)
                                    count(balance_payload["event"])
                                elif payload.get("event") not in {"prewarm_intent", "simulation_green", "signed_ready"}:
                                    break

                    if (
                        buy_sent
                        and not sell_done
                        and last_buy_sample_index is not None
                        and index > last_buy_sample_index
                        and runtime_sell_row
                        and bool(int(runtime_sell_row.get("enabled") or 0))
                        and str(runtime_sell_row.get("mode") or "simulate") == "broadcast"
                    ):
                        current_balance_raw = await read_erc20_balance(rpc, token=token, owner=owner)
                        rows = current_run_records(
                            bot.storage.list_launch_execution_records(project_name, limit=800),
                            buy_strategy=buy_strategy_name,
                            sell_strategy=sell_strategy_name,
                        )
                        position = build_position_from_records(rows=rows, current_balance_raw=current_balance_raw)
                        roi_pct = current_roi_pct(position, sample)
                        sell_decision = evaluate_custom_sell(
                            state=multi_state_from_position(position),
                            signal=MultiSellInput(
                                timestamp=int(sample.get("simTimestamp") or time.time()),
                                tax_rate=Decimal(str(sample.get("buyTaxRate") or "0")),
                                current_roi_pct=roi_pct,
                                token_price_usd=Decimal(str(sample.get("tokenPriceUsd")))
                                if sample.get("tokenPriceUsd") is not None
                                else None,
                                token_price_v=Decimal(str(sample.get("tokenPriceV")))
                                if sample.get("tokenPriceV") is not None
                                else None,
                                recent_large_buys=(),
                            ),
                            config=sell_config,
                        )
                        if sell_decision.should_sell:
                            sell_intent_sample_index = index
                            payload = await execute_sell_decision(
                                args=effective_sell_args,
                                cfg=cfg,
                                bot=bot,
                                rpc=rpc,
                                account=account,
                                to_checksum_address=to_checksum_address,
                                project_row=project_row,
                                project_name=project_name,
                                strategy_name=sell_strategy_name,
                                rule_name=sell_config.name,
                                sample=sample,
                                sample_index=index,
                                decision=sell_decision,
                                position=position,
                                sell_config=sell_config,
                                owner=owner,
                                token=token,
                                pool=pool,
                            )
                            payload["autoTriggerSource"] = "historical_sample_stream"
                            payload["decisionSource"] = args.decision_label
                            payload["taxRate"] = sample.get("buyTaxRate")
                            payload["currentRoiPct"] = str(roi_pct) if roi_pct is not None else None
                            payload["runtimeSellConfig"] = compact_runtime_sell_config(runtime_sell_row, effective_sell_args, sell_config)
                            append_jsonl(output_jsonl, payload)
                            print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                            sell_payloads.append(payload)
                            count(str(payload.get("event") or "sell_unknown"))
                            if payload.get("event") == "sell_receipt_success" and payload.get("tradeSent"):
                                sell_done = True
                                balance, reads = await wait_balance_condition(
                                    rpc,
                                    token=token,
                                    owner=owner,
                                    timeout_sec=int(args.post_balance_timeout_sec),
                                    interval_sec=Decimal(str(args.post_balance_interval_sec)),
                                    want_zero=True,
                                )
                                balance_payload = {
                                    "event": "post_sell_balance_zero" if balance == 0 else "post_sell_balance_not_zero",
                                    "at": utc_iso(),
                                    "atCst": cst_iso(),
                                    "project": project_name,
                                    "decisionSource": args.decision_label,
                                    "sampleIndex": index,
                                    "taxRate": sample.get("buyTaxRate"),
                                    "tokenBalanceRaw": str(balance),
                                    "reads": reads,
                                    "tradeSent": False,
                                    "broadcastEnabled": False,
                                }
                                append_jsonl(output_jsonl, balance_payload)
                                print(json.dumps(compact_event(balance_payload), ensure_ascii=False), flush=True)
                                count(balance_payload["event"])
                            else:
                                break

                    if not args.no_sleep and args.sleep_sec > 0 and index < len(samples) - 1:
                        await asyncio.sleep(float(args.sleep_sec))

                final_token_balance = await read_erc20_balance(rpc, token=token, owner=owner)
                final_virtual_allowance = await read_allowance(
                    rpc,
                    token=cfg.virtual_token_addr,
                    owner=owner,
                    spender=VIRTUALS_BUY_SPENDER,
                )
                final_token_allowance = await read_allowance(
                    rpc,
                    token=token,
                    owner=owner,
                    spender=VIRTUALS_BUY_SPENDER,
                )
                active_fuses = bot.storage.list_launch_execution_fuses(project_name, active_only=True, limit=20)
        finally:
            if previous_buy_config:
                bot.storage.upsert_launch_strategy_runtime_config(
                    project_row=project_row,
                    payload=row_to_buy_payload(previous_buy_config, reason="restore after historical canary"),
                )
            else:
                bot.storage.upsert_launch_strategy_runtime_config(
                    project_row=project_row,
                    payload=buy_payload_for(
                        strategy="dynamic_25v_dip20_after1_flat10_no_cap",
                        rule_name=rule.name,
                        enabled=False,
                        mode="simulate",
                        buy_v=Decimal("25"),
                        max_project_v=Decimal("150"),
                        reason="restore disabled default after historical canary",
                    ),
                )
            if previous_sell_config:
                bot.storage.upsert_launch_sell_runtime_config(
                    project_row=project_row,
                    payload=row_to_sell_payload(previous_sell_config, reason="restore after historical canary"),
                )
            else:
                bot.storage.upsert_launch_sell_runtime_config(
                    project_row=project_row,
                    payload=sell_payload_for(
                        strategy="custom_multi_sell",
                        enabled=False,
                        mode="simulate",
                        max_tax_rate=Decimal("30"),
                        roi_pct=Decimal("30"),
                        sell_pct=Decimal("30"),
                        trigger_mode="roi",
                        reason="restore disabled default after historical canary",
                    ),
                )
            restored_configs = True

    buy_last = buy_payloads[-1] if buy_payloads else {}
    sell_last = sell_payloads[-1] if sell_payloads else {}
    summary = {
        "ok": bool(
            buy_payloads
            and sell_payloads
            and buy_last.get("event") == "receipt_success"
            and sell_last.get("event") == "sell_receipt_success"
            and counts.get("strategy_config_reloaded", 0) >= 1
            and counts.get("sell_config_reloaded", 0) >= 1
            and str(final_token_balance) == "0"
        ),
        "executionProject": str(args.execution_project),
        "decisionSource": str(args.decision_label),
        "samplesJsonl": str(samples_path),
        "sampleCount": len(samples),
        "autoTrigger": True,
        "paperOnly": False,
        "counts": counts,
        "configEvents": [compact_event(item) for item in config_events],
        "buyStrategy": buy_strategy_name,
        "sellStrategy": sell_strategy_name,
        "buyTx": buy_last.get("txHash"),
        "buyReceiptStatus": (buy_last.get("receipt") or {}).get("status") if buy_last else None,
        "buyIntentSampleIndex": buy_intent_sample_index,
        "sellTx": sell_last.get("txHash"),
        "sellReceiptStatus": (sell_last.get("receipt") or {}).get("status") if sell_last else None,
        "sellIntentSampleIndex": sell_intent_sample_index,
        "targetBalanceRawAfter": str(final_token_balance),
        "targetTokenAllowanceRawAfter": str(final_token_allowance),
        "tdsBalanceRawAfter": str(final_token_balance),
        "virtualAllowanceWeiAfter": str(final_virtual_allowance),
        "executionTokenAllowanceRawAfter": str(final_token_allowance),
        "activeFuseCount": len(active_fuses),
        "activeFuses": active_fuses,
        "restoredRuntimeConfigs": restored_configs,
        "outputJsonl": str(output_jsonl),
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_jsonl(output_jsonl, {"event": "service_stop", "summary": summary, "at": utc_iso(), "atCst": cst_iso()})
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
