#!/usr/bin/env python3
"""Backtest the dual independent sell strategy from SR/ISC event-level samples.

Read-only boundaries:
- reads local replay reports, sample JSONL, and parsed buy-event JSONL files;
- writes local JSON/Markdown backtest reports only;
- does not touch production DBs and does not sign or broadcast transactions.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from backtest_launch_strategy import fmt_decimal, parse_decimal, spot_fdv_wan  # noqa: E402
from launch_sell_strategy import (  # noqa: E402
    DualSellConfig,
    DualSellInput,
    DualSellState,
    apply_successful_sell,
    evaluate_dual_sell,
)
from recalc_dynamic_buy_strategy import DynamicBuyConfig, evaluate_dynamic, load_samples  # noqa: E402
from sr_event_level_replay import rules  # noqa: E402


RAW_POSITION_SCALE = 10**18


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_buy_events(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            spent = parse_decimal(row.get("spentV_est"))
            if spent is None:
                continue
            rows.append(row)
    rows.sort(
        key=lambda item: (
            int(item.get("timestamp") or 0),
            int(item.get("blockNumber") or 0),
            str(item.get("txHash") or ""),
        )
    )
    return rows


def cst_text(ts: Any) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "-"
    return datetime.fromtimestamp(value, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def pnl_pct(value_v: Decimal, spent_v: Decimal) -> Decimal:
    if spent_v <= 0:
        return Decimal("0")
    return (value_v - spent_v) / spent_v * Decimal("100")


def buy_units(buy: dict[str, Any]) -> Decimal:
    size_v = parse_decimal(buy.get("buySizeV")) or Decimal("0")
    entry = parse_decimal(buy.get("entryTaxFdvWanUsd"))
    if size_v <= 0 or entry is None or entry <= 0:
        return Decimal("0")
    return size_v / entry


def find_largest_buy_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not events:
        return None
    return max(events, key=lambda item: parse_decimal(item.get("spentV_est")) or Decimal("0"))


def current_balance_raw(*, remaining_units: Decimal, total_units: Decimal) -> int:
    if total_units <= 0 or remaining_units <= 0:
        return 0
    value = Decimal(RAW_POSITION_SCALE) * remaining_units / total_units
    return int(value)


def evaluate_project(*, report_path: Path, rule_name: str, buy_config: DynamicBuyConfig, sell_config: DualSellConfig) -> dict[str, Any]:
    source_report = load_json(report_path)
    samples_path = Path(str(source_report.get("samplesPath") or ""))
    events_path = Path(str(source_report.get("jsonlPath") or ""))
    samples = load_samples(samples_path)
    buy_events = load_buy_events(events_path)
    rule = next(item for item in rules() if item.name == rule_name)
    buy_result = evaluate_dynamic(samples, rule, buy_config)
    buys = list(buy_result.get("buys") or [])
    total_spent_v = parse_decimal(buy_result.get("totalSpentV")) or Decimal("0")
    total_units = sum((buy_units(buy) for buy in buys), Decimal("0"))

    state = DualSellState(total_position_raw=RAW_POSITION_SCALE)
    remaining_units = total_units
    realized_value_v = Decimal("0")
    sell_events: list[dict[str, Any]] = []
    event_index = 0

    for index, sample in enumerate(samples):
        sample_ts = int(sample.get("simTimestamp") or 0)
        interval_events: list[dict[str, Any]] = []
        while event_index < len(buy_events) and int(buy_events[event_index].get("timestamp") or 0) <= sample_ts:
            interval_events.append(buy_events[event_index])
            event_index += 1

        spot = spot_fdv_wan(sample)
        tax_rate = parse_decimal(sample.get("buyTaxRate"))
        if spot is None or spot <= 0 or total_units <= 0 or total_spent_v <= 0:
            continue

        full_position_value_v = total_units * spot
        current_roi = pnl_pct(full_position_value_v, total_spent_v)
        largest_event = find_largest_buy_event(interval_events)
        latest_buy_v = parse_decimal(largest_event.get("spentV_est")) if largest_event else None
        latest_buy_tx = str(largest_event.get("txHash") or "") if largest_event else None
        if latest_buy_tx == "":
            latest_buy_tx = None

        balance_raw = current_balance_raw(remaining_units=remaining_units, total_units=total_units)
        decision = evaluate_dual_sell(
            state=state,
            signal=DualSellInput(
                timestamp=sample_ts,
                tax_rate=tax_rate,
                current_roi_pct=current_roi,
                current_balance_raw=balance_raw,
                latest_buy_v=latest_buy_v,
                latest_buy_tx_hash=latest_buy_tx,
            ),
            config=sell_config,
        )
        if not decision.should_sell:
            continue

        units_to_sell = Decimal(decision.amount_raw) * total_units / Decimal(RAW_POSITION_SCALE)
        if units_to_sell > remaining_units:
            units_to_sell = remaining_units
        sell_value_v = units_to_sell * spot
        realized_value_v += sell_value_v
        remaining_units -= units_to_sell
        apply_successful_sell(state=state, decision=decision, timestamp=sample_ts, config=sell_config)

        sell_events.append(
            {
                "index": index,
                "timestamp": sample_ts,
                "timestampCst": cst_text(sample_ts),
                "taxRate": fmt_decimal(tax_rate, 6),
                "myRoiPct": fmt_decimal(current_roi, 4),
                "latestBuyV": fmt_decimal(latest_buy_v, 6),
                "spotFdvWanUsd": fmt_decimal(spot, 6),
                "sellPctOfOriginal": fmt_decimal(decision.total_sell_pct, 6),
                "roiSellPct": fmt_decimal(decision.roi_delta_pct, 6),
                "largeBuySellPct": fmt_decimal(decision.large_buy_delta_pct, 6),
                "sellValueV": fmt_decimal(sell_value_v, 6),
                "remainingPositionPct": fmt_decimal(Decimal(balance_raw - decision.amount_raw) / Decimal(RAW_POSITION_SCALE) * Decimal("100"), 4),
                "triggerReasons": list(decision.trigger_reasons),
                "largeBuyTxHash": decision.large_buy_tx_hash,
            }
        )

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_remaining_value_v = remaining_units * final_spot if final_spot is not None else Decimal("0")
    final_value_v = realized_value_v + final_remaining_value_v
    final_pnl_v = final_value_v - total_spent_v
    final_pnl_pct = pnl_pct(final_value_v, total_spent_v)
    hold_final_value_v = parse_decimal(buy_result.get("finalValueV")) or Decimal("0")
    hold_final_pnl_pct = parse_decimal(buy_result.get("finalPnlPct")) or Decimal("0")
    return {
        "project": source_report.get("project"),
        "virtualsId": source_report.get("virtualsId"),
        "sourceReport": str(report_path),
        "samplesPath": str(samples_path),
        "eventsPath": str(events_path),
        "sampleCount": len(samples),
        "parsedBuyEventCount": len(buy_events),
        "buyRule": rule_name,
        "buyStrategy": buy_config.name,
        "sellStrategy": sell_config.name,
        "buyCount": buy_result.get("buyCount"),
        "totalSpentV": buy_result.get("totalSpentV"),
        "ownWeightedCostWanUsd": buy_result.get("ownWeightedCostWanUsd"),
        "sellCount": len(sell_events),
        "sellEvents": sell_events,
        "realizedSellValueV": fmt_decimal(realized_value_v, 6),
        "remainingValueV": fmt_decimal(final_remaining_value_v, 6),
        "finalValueV": fmt_decimal(final_value_v, 6),
        "finalPnlV": fmt_decimal(final_pnl_v, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "holdFinalValueV": fmt_decimal(hold_final_value_v, 6),
        "holdFinalPnlV": buy_result.get("finalPnlV"),
        "holdFinalPnlPct": buy_result.get("finalPnlPct"),
        "deltaVsHoldPnlPct": fmt_decimal(final_pnl_pct - hold_final_pnl_pct, 4),
        "finalState": {
            "roiSoldPct": fmt_decimal(state.roi_sold_pct, 6),
            "largeBuySoldPct": fmt_decimal(state.large_buy_sold_pct, 6),
            "totalSoldPct": fmt_decimal(state.roi_sold_pct + state.large_buy_sold_pct, 6),
            "cooldownUntil": state.cooldown_until,
        },
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Dual Independent Sell Strategy Backtest",
        "",
        "本报告只读取本地 SR/ISC event-level replay 产物，未重新抓链、未写生产库、未发送交易。",
        "",
        "## 策略口径",
        "",
        "- 当前采用：先按该双策略作为本地自动卖出候选口径，后续若接生产必须继续走 Phase 053 执行门禁。",
        "- 进入卖出观察：税率 `<=30%`。",
        "- 收益率策略：我的收益率 `>=30%` 卖总仓位 `30%`；`>=50%` 卖总仓位 `50%`。",
        "- 大额买入策略：单笔买入 `>=5,000 VIRTUAL` 卖总仓位 `30%`；`>=8,000 VIRTUAL` 卖总仓位 `50%`。",
        "- 两条策略独立记账；同一刻同时触发时合并为一笔卖出。",
        "- 执行保护：卖出比例基于原始累计收到 token 数量；如果真实余额低于目标卖出数量，只按实际卖出比例更新策略状态。",
        "- 回测估值口径：买入成本使用入场时含税 FDV；卖出和剩余持仓使用当时或 tax-end spot FDV；暂未计入卖出滑点、gas、成交税。",
        "",
        "## 结果概览",
        "",
        table_line(["项目", "买入", "投入V", "卖出次数", "最终收益", "纯持有收益", "差异", "最终已卖"]),
        table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]),
    ]
    for item in report["projects"]:
        state = item.get("finalState") or {}
        lines.append(
            table_line(
                [
                    item.get("project"),
                    item.get("buyCount"),
                    item.get("totalSpentV"),
                    item.get("sellCount"),
                    f"{item.get('finalPnlV')}V / {item.get('finalPnlPct')}%",
                    f"{item.get('holdFinalPnlV')}V / {item.get('holdFinalPnlPct')}%",
                    f"{item.get('deltaVsHoldPnlPct')} pct",
                    state.get("totalSoldPct"),
                ]
            )
        )
    lines.append("")

    for item in report["projects"]:
        lines.append(f"## {item.get('project')}")
        lines.append("")
        lines.append(f"- Virtuals ID：`{item.get('virtualsId')}`。")
        lines.append(f"- 买入 `{item.get('buyCount')}` 次，投入 `{item.get('totalSpentV')} V`。")
        lines.append(f"- 卖出 `{item.get('sellCount')}` 次；最终收益 `{item.get('finalPnlV')} V / {item.get('finalPnlPct')}%`。")
        lines.append(f"- 纯持有到 tax-end：`{item.get('holdFinalPnlV')} V / {item.get('holdFinalPnlPct')}%`。")
        state = item.get("finalState") or {}
        lines.append(
            f"- 最终卖出额度：收益率策略 `{state.get('roiSoldPct')}%`，"
            f"大额买入策略 `{state.get('largeBuySoldPct')}%`，合计 `{state.get('totalSoldPct')}%`。"
        )
        lines.append("")
        if item.get("sellEvents"):
            lines.append(table_line(["时间(CST)", "税率", "收益率", "大额买入", "本次卖出", "收益率卖", "大额买入卖", "触发原因"]))
            lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---"]))
            for event in item.get("sellEvents") or []:
                lines.append(
                    table_line(
                        [
                            event.get("timestampCst"),
                            event.get("taxRate"),
                            f"{event.get('myRoiPct')}%",
                            f"{event.get('latestBuyV') or '-'} V",
                            f"{event.get('sellPctOfOriginal')}%",
                            f"{event.get('roiSellPct')}%",
                            f"{event.get('largeBuySellPct')}%",
                            " + ".join(event.get("triggerReasons") or []),
                        ]
                    )
                )
        else:
            lines.append("未触发卖出。")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    buy_config = DynamicBuyConfig(pause_after_buy_count=1)
    sell_config = DualSellConfig()
    projects = [
        evaluate_project(
            report_path=Path(args.sr_report),
            rule_name=args.sr_rule,
            buy_config=buy_config,
            sell_config=sell_config,
        ),
        evaluate_project(
            report_path=Path(args.isc_report),
            rule_name=args.isc_rule,
            buy_config=buy_config,
            sell_config=sell_config,
        ),
    ]
    return {
        "ok": True,
        "readOnly": True,
        "productionDbTouched": False,
        "tradeSent": False,
        "scope": "SR and ISC dual independent sell-strategy backtest from existing event-level samples",
        "strategyDefinition": {
            "name": sell_config.name,
            "sellWindow": "buyTaxRate <= 30",
            "roiTrack": ["my ROI >= 30% => sell 30% original position", "my ROI >= 50% => sell 50% original position"],
            "largeBuyTrack": [
                "single parsed buy spentV_est >= 5000 VIRTUAL => sell 30% original position",
                "single parsed buy spentV_est >= 8000 VIRTUAL => sell 50% original position",
            ],
            "mergeRule": "independent tracks; simultaneous deltas are merged into one sell order",
            "cooldownSec": sell_config.cooldown_sec,
        },
        "projects": projects,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest dual independent sell strategy for SR and ISC.")
    parser.add_argument("--sr-report", default="data/backtests/sr-event-level-replay-20260510T073102Z.json")
    parser.add_argument("--isc-report", default="data/backtests/isc-event-level-replay-20260510.json")
    parser.add_argument("--sr-rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--isc-rule", default="gate_5k_tax89_fdv_one_per_tax")
    parser.add_argument("--output-json", default="data/backtests/dual-sell-strategy-20260511.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-dual-sell-strategy-2026-05-11.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(args)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(
        json.dumps(
            {
                "outputJson": args.output_json,
                "outputMd": args.output_md,
                "projects": [
                    {
                        "project": item.get("project"),
                        "sellCount": item.get("sellCount"),
                        "finalPnlPct": item.get("finalPnlPct"),
                        "holdFinalPnlPct": item.get("holdFinalPnlPct"),
                        "deltaVsHoldPnlPct": item.get("deltaVsHoldPnlPct"),
                        "finalState": item.get("finalState"),
                    }
                    for item in report.get("projects") or []
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
