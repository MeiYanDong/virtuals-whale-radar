#!/usr/bin/env python3
"""Local runtime-control launch simulator.

This tool verifies the UI -> DB -> executor-config loop without broadcasting:
- reads launch runtime config rows saved by the admin frontend;
- replays a deterministic 98/99-minute launch window at an accelerated speed;
- evaluates the production dynamic buy strategy;
- applies paper max-buy/max-project caps so tiny UI values remain bounded.

It intentionally does not sign, broadcast, or write launch_execution_ledger.
"""

from __future__ import annotations

import argparse
import copy
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

from launch_execution_pipeline import DynamicAfter1StrategyEvaluator, resolve_rule  # noqa: E402
from launch_prewarm_executor import (  # noqa: E402
    compact_runtime_config,
    compact_strategy_state,
    decimal_value,
    eligible_fdv_limit_orders,
    fdv_limit_order_intent,
    runtime_dynamic_config,
    runtime_effective_args,
    sample_tax_fdv_wan,
)
from live_strategy_dry_run import append_jsonl, cst_iso, utc_iso  # noqa: E402
from virtuals_bot import Storage, load_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a paper launch window using frontend-saved runtime config.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name or id.")
    parser.add_argument("--rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--speed", type=Decimal, default=Decimal("20"), help="Virtual launch speed, e.g. 10 or 20.")
    parser.add_argument("--tick-sec", type=Decimal, default=Decimal("60"), help="Virtual seconds per tax tick.")
    parser.add_argument("--no-sleep", action="store_true", help="Run all ticks immediately but preserve simulated timestamps.")
    parser.add_argument("--max-ticks", type=int, default=0, help="Limit ticks for smoke tests; 0 means full window.")
    parser.add_argument("--mode", default="paper-broadcast", help="Displayed mode for default config summaries.")
    parser.add_argument("--max-buy-v", type=Decimal, default=Decimal("0.2"))
    parser.add_argument("--max-project-v", type=Decimal, default=Decimal("0.6"))
    parser.add_argument(
        "--skip-fdv-limit-orders",
        action="store_true",
        help="Do not evaluate independent tax-FDV limit orders during the replay.",
    )
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--summary-json", default="")
    return parser.parse_args()


def find_project(storage: Storage, raw_project: str) -> dict[str, Any]:
    value = str(raw_project or "").strip()
    if not value:
        raise ValueError("project is required")
    if value.isdigit():
        row = storage.get_managed_project(int(value))
        if row:
            return row
    target = value.lower()
    for row in storage.list_managed_projects():
        if str(row.get("name") or "").strip().lower() == target:
            return row
        if str(row.get("signalhub_project_id") or "").strip().lower() == target:
            return row
    raise ValueError(f"managed project not found: {raw_project}")


def fmt_decimal(value: Decimal, places: int = 6) -> str:
    quant = Decimal(1).scaleb(-places)
    text = format(value.quantize(quant).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fdv_for_tax(tax: int) -> Decimal:
    scripted = {
        99: Decimal("150"),
        98: Decimal("145"),
        97: Decimal("140"),
        96: Decimal("135"),
        95: Decimal("100"),
        94: Decimal("96"),
        93: Decimal("70"),
        92: Decimal("105"),
        91: Decimal("108"),
        90: Decimal("55"),
        89: Decimal("80"),
        88: Decimal("78"),
        87: Decimal("65"),
    }
    if tax in scripted:
        return scripted[tax]
    if tax >= 60:
        return Decimal("72") + Decimal(90 - tax) * Decimal("0.35")
    if tax >= 30:
        return Decimal("82") + Decimal(60 - tax) * Decimal("0.25")
    return Decimal("90") + Decimal(30 - tax) * Decimal("0.15")


def build_fixture_samples(*, start_ts: int, max_ticks: int = 0) -> list[dict[str, Any]]:
    taxes = list(range(99, 0, -1))
    if max_ticks > 0:
        taxes = taxes[:max_ticks]
    samples: list[dict[str, Any]] = []
    for index, tax in enumerate(taxes):
        fdv = fdv_for_tax(tax)
        live_fdv_usd = fdv * Decimal("10000")
        samples.append(
            {
                "index": index,
                "projectStatus": "live",
                "simTimestamp": int(start_ts + index * 60),
                "blockTimestamp": int(start_ts + index * 60),
                "buyTaxRate": str(tax),
                "estimatedFdvWanUsdWithTax": fmt_decimal(fdv),
                "liveFdvUsd": fmt_decimal(live_fdv_usd),
                "boardCostWanUsd": "120",
                "boardSpentV": fmt_decimal(Decimal("6000") + Decimal(index) * Decimal("750"), 3),
                "costRows": 20,
                "whaleRows": 20,
                "costPosition": "1/20",
                "vCostPosition": "0/6000",
                "triggerTypes": ["fixture_tax_tick"],
            }
        )
    return samples


def runtime_row_version(row: dict[str, Any] | None) -> int:
    return int(row.get("version") or 0) if row else 0


def runtime_block_reason(row: dict[str, Any] | None) -> str:
    if not row:
        return "runtime_config_missing"
    if not bool(int(row.get("enabled") or 0)):
        return "runtime_config_disabled"
    if str(row.get("mode") or "simulate").strip().lower() != "broadcast":
        return "runtime_config_mode_not_broadcast"
    return ""


def paper_risk_block(
    *,
    intent: dict[str, Any],
    effective_args: argparse.Namespace,
    paper_sent_project_v: Decimal,
) -> tuple[str, dict[str, Any]]:
    buy_size = decimal_value(intent.get("buy_size_v"))
    max_buy_v = Decimal(str(effective_args.max_buy_v or "0"))
    max_project_v = Decimal(str(effective_args.max_project_v or "0"))
    if max_buy_v > 0 and buy_size > max_buy_v:
        return "buy_size_exceeds_max_buy_v", {
            "buySizeV": fmt_decimal(buy_size),
            "maxBuyV": fmt_decimal(max_buy_v),
        }
    projected = paper_sent_project_v + buy_size
    if max_project_v > 0 and projected > max_project_v:
        return "project_sent_v_exceeds_max_project_v", {
            "buySizeV": fmt_decimal(buy_size),
            "sentProjectV": fmt_decimal(paper_sent_project_v),
            "projectedProjectV": fmt_decimal(projected),
            "maxProjectV": fmt_decimal(max_project_v),
        }
    return "", {}


def main() -> None:
    args = parse_args()
    if args.speed <= 0:
        raise ValueError("--speed must be positive")
    cfg = load_config(args.config)
    storage = Storage(cfg.sqlite_path)
    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/runtime-control-launch-sim-{str(args.project).strip().upper()}-{int(time.time())}.jsonl"
    )
    summary_json = Path(args.summary_json) if args.summary_json else None
    samples = build_fixture_samples(start_ts=int(time.time()), max_ticks=int(args.max_ticks or 0))
    project_row = find_project(storage, str(args.project))
    project_name = str(project_row.get("name") or args.project).strip()
    rule = resolve_rule(str(args.rule))
    runtime_config_row = storage.get_launch_strategy_runtime_config_by_project(project_name)
    runtime_config_version = runtime_row_version(runtime_config_row)
    evaluator = DynamicAfter1StrategyEvaluator(
        project=project_name,
        rule=rule,
        config=runtime_dynamic_config(runtime_config_row),
    )
    effective_args = runtime_effective_args(args, runtime_config_row)
    paper_sent_project_v = Decimal("0")
    paper_triggered_fdv_limit_order_ids: set[int] = set()
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    service_start = {
        "event": "service_start",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "managedProjectId": project_row.get("id"),
        "rule": rule.name,
        "speed": str(args.speed),
        "tickSec": str(args.tick_sec),
        "sampleCount": len(samples),
        "paperOnly": True,
        "tradeSent": False,
        "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
    }
    append_jsonl(output_jsonl, service_start)
    print(json.dumps(service_start, ensure_ascii=False), flush=True)

    try:
        for sample_index, sample in enumerate(samples):
            latest_runtime_config = storage.get_launch_strategy_runtime_config_by_project(project_name)
            latest_version = runtime_row_version(latest_runtime_config)
            if latest_version != runtime_config_version:
                runtime_config_version = latest_version
                runtime_config_row = latest_runtime_config
                evaluator.config = runtime_dynamic_config(runtime_config_row)
                effective_args = runtime_effective_args(args, runtime_config_row)
                payload = {
                    "event": "strategy_config_reloaded",
                    "at": utc_iso(),
                    "atCst": cst_iso(),
                    "project": project_name,
                    "sampleIndex": sample_index,
                    "taxRate": sample.get("buyTaxRate"),
                    "tradeSent": False,
                    "paperOnly": True,
                    "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                }
                append_jsonl(output_jsonl, payload)
                print(json.dumps(payload, ensure_ascii=False), flush=True)

            runtime_config_row = latest_runtime_config
            effective_args = runtime_effective_args(args, runtime_config_row)
            block_reason = runtime_block_reason(runtime_config_row)
            if block_reason:
                payload = {
                    "event": "runtime_config_blocked",
                    "reason": block_reason,
                    "at": utc_iso(),
                    "atCst": cst_iso(),
                    "project": project_name,
                    "sampleIndex": sample_index,
                    "taxRate": sample.get("buyTaxRate"),
                    "paperOnly": True,
                    "tradeSent": False,
                    "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                }
            else:
                if not args.skip_fdv_limit_orders:
                    open_limit_orders = storage.list_launch_fdv_limit_orders(
                        project_id=int(project_row.get("id") or 0),
                        statuses=["pending"],
                        limit=100,
                    )
                    limit_orders = eligible_fdv_limit_orders(
                        [
                            row
                            for row in open_limit_orders
                            if int(row.get("id") or 0) not in paper_triggered_fdv_limit_order_ids
                        ],
                        tax_fdv_wan_usd=sample_tax_fdv_wan(sample),
                        project_status=str(sample.get("projectStatus") or ""),
                    )
                    for limit_order in limit_orders:
                        intent = fdv_limit_order_intent(
                            row=limit_order,
                            project_name=project_name,
                            sample=sample,
                            sample_index=sample_index,
                        )
                        fdv_args = copy.copy(effective_args)
                        order_buy_v = decimal_value(limit_order.get("buy_v"))
                        if fdv_args.max_buy_v is None or Decimal(str(fdv_args.max_buy_v)) < order_buy_v:
                            fdv_args.max_buy_v = order_buy_v
                        risk_reason, risk_details = paper_risk_block(
                            intent=intent,
                            effective_args=fdv_args,
                            paper_sent_project_v=paper_sent_project_v,
                        )
                        if risk_reason:
                            limit_payload = {
                                "event": "paper_fdv_limit_order_blocked_by_risk_cap",
                                "reason": risk_reason,
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "sampleIndex": sample_index,
                                "taxRate": sample.get("buyTaxRate"),
                                "paperOnly": True,
                                "tradeSent": False,
                                "risk": risk_details,
                                "intent": intent,
                                "fdvLimitOrder": {
                                    "id": int(limit_order.get("id") or 0),
                                    "enabled": bool(int(limit_order.get("enabled") or 0)),
                                    "status": str(limit_order.get("status") or ""),
                                    "triggerFdvWanUsd": str(limit_order.get("trigger_fdv_wan_usd") or ""),
                                    "buyV": str(limit_order.get("buy_v") or ""),
                                },
                                "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, fdv_args),
                            }
                        else:
                            buy_size = decimal_value(intent.get("buy_size_v"))
                            paper_sent_project_v += buy_size
                            paper_triggered_fdv_limit_order_ids.add(int(limit_order.get("id") or 0))
                            limit_payload = {
                                "event": "paper_fdv_limit_order_intent",
                                "reason": "tax_fdv_limit_order_triggered",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "sampleIndex": sample_index,
                                "taxRate": sample.get("buyTaxRate"),
                                "paperOnly": True,
                                "tradeSent": False,
                                "paperSentProjectV": fmt_decimal(paper_sent_project_v),
                                "intent": intent,
                                "fdvLimitOrder": {
                                    "id": int(limit_order.get("id") or 0),
                                    "enabled": bool(int(limit_order.get("enabled") or 0)),
                                    "status": str(limit_order.get("status") or ""),
                                    "triggerFdvWanUsd": str(limit_order.get("trigger_fdv_wan_usd") or ""),
                                    "buyV": str(limit_order.get("buy_v") or ""),
                                },
                                "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, fdv_args),
                            }
                        counts[limit_payload["event"]] = counts.get(limit_payload["event"], 0) + 1
                        events.append(limit_payload)
                        append_jsonl(output_jsonl, limit_payload)
                        print(json.dumps(limit_payload, ensure_ascii=False), flush=True)

                state_before = copy.deepcopy(evaluator.state)
                decision = evaluator.evaluate(sample, index=sample_index)
                if decision.intent:
                    intent = asdict(decision.intent)
                    risk_reason, risk_details = paper_risk_block(
                        intent=intent,
                        effective_args=effective_args,
                        paper_sent_project_v=paper_sent_project_v,
                    )
                    if risk_reason:
                        evaluator.state = state_before
                        payload = {
                            "event": "paper_blocked_by_risk_cap",
                            "reason": risk_reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "sampleIndex": sample_index,
                            "taxRate": sample.get("buyTaxRate"),
                            "paperOnly": True,
                            "tradeSent": False,
                            "risk": risk_details,
                            "intent": intent,
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "strategyState": compact_strategy_state(evaluator.state),
                        }
                    else:
                        buy_size = decimal_value(intent.get("buy_size_v"))
                        paper_sent_project_v += buy_size
                        payload = {
                            "event": "paper_buy_intent",
                            "reason": decision.reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "sampleIndex": sample_index,
                            "taxRate": sample.get("buyTaxRate"),
                            "paperOnly": True,
                            "tradeSent": False,
                            "paperSentProjectV": fmt_decimal(paper_sent_project_v),
                            "intent": intent,
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "strategyState": compact_strategy_state(evaluator.state),
                        }
                elif decision.pause:
                    payload = {
                        "event": "paper_pause",
                        "reason": decision.reason,
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": project_name,
                        "sampleIndex": sample_index,
                        "taxRate": sample.get("buyTaxRate"),
                        "paperOnly": True,
                        "tradeSent": False,
                        "pause": decision.pause,
                        "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                        "strategyState": compact_strategy_state(evaluator.state),
                    }
                else:
                    payload = {
                        "event": "paper_skip",
                        "reason": decision.reason,
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": project_name,
                        "sampleIndex": sample_index,
                        "taxRate": sample.get("buyTaxRate"),
                        "paperOnly": True,
                        "tradeSent": False,
                        "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                    }

            counts[payload["event"]] = counts.get(payload["event"], 0) + 1
            events.append(payload)
            append_jsonl(output_jsonl, payload)
            if payload["event"] != "paper_skip":
                print(json.dumps(payload, ensure_ascii=False), flush=True)
            if not args.no_sleep and sample_index < len(samples) - 1:
                time.sleep(float(args.tick_sec / args.speed))
    finally:
        storage.close()

    buy_events = [event for event in events if event.get("event") == "paper_buy_intent"]
    fdv_limit_events = [event for event in events if event.get("event") == "paper_fdv_limit_order_intent"]
    blocked_events = [event for event in events if event.get("event") == "paper_blocked_by_risk_cap"]
    fdv_limit_blocked_events = [
        event for event in events if event.get("event") == "paper_fdv_limit_order_blocked_by_risk_cap"
    ]
    summary = {
        "ok": True,
        "project": project_name,
        "speed": str(args.speed),
        "sampleCount": len(samples),
        "outputJsonl": str(output_jsonl),
        "counts": counts,
        "paperSentProjectV": fmt_decimal(paper_sent_project_v),
        "buyIntentCount": len(buy_events),
        "fdvLimitOrderIntentCount": len(fdv_limit_events),
        "riskBlockedCount": len(blocked_events),
        "fdvLimitOrderRiskBlockedCount": len(fdv_limit_blocked_events),
        "buySizes": [event.get("intent", {}).get("buy_size_v") for event in buy_events],
        "buyTaxes": [event.get("taxRate") for event in buy_events],
        "fdvLimitOrderIds": [event.get("fdvLimitOrder", {}).get("id") for event in fdv_limit_events],
        "fdvLimitOrderBuySizes": [event.get("intent", {}).get("buy_size_v") for event in fdv_limit_events],
        "fdvLimitOrderTaxes": [event.get("taxRate") for event in fdv_limit_events],
        "riskBlockedTaxes": [event.get("taxRate") for event in blocked_events[:10]],
    }
    if summary_json:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
