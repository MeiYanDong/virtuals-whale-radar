#!/usr/bin/env python3
"""Recalculate dynamic launch-buy strategy from existing event-level samples.

Read-only boundaries:
- reads existing local replay JSON + sample JSONL files;
- writes local JSON/Markdown backtest reports;
- does not touch production DBs and does not send trades.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from backtest_launch_strategy import fmt_decimal, parse_decimal, spot_fdv_wan
from sr_event_level_replay import StrategyRule, rules, should_buy


@dataclass(frozen=True)
class DynamicBuyConfig:
    name: str = "dynamic_25v_dip20_after1_flat10_no_cap"
    base_buy_v: Decimal = Decimal("25")
    dip_buy_v: Decimal = Decimal("50")
    dip_from_own_cost_pct: Decimal = Decimal("20")
    flat_pause_pct: Decimal = Decimal("10")
    pause_after_buy_count: int = 1
    one_buy_per_tax_rate: bool = True


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def decimal_ratio_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous <= 0:
        return None
    return abs(current - previous) / previous * Decimal("100")


def tax_number(value: Any) -> Decimal | None:
    parsed = parse_decimal(value)
    return parsed if parsed is not None else None


def is_next_tax_period(previous_tax: Any, current_tax: Any) -> bool:
    previous = tax_number(previous_tax)
    current = tax_number(current_tax)
    if previous is None or current is None:
        return False
    return previous - current == Decimal("1")


def compact_buy(
    *,
    index: int,
    row: dict[str, Any],
    entry: Decimal,
    size_v: Decimal,
    own_cost_before: Decimal | None,
    own_cost_after: Decimal,
    reason: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "timestamp": int(row.get("simTimestamp") or 0),
        "taxRate": str(row.get("buyTaxRate")),
        "buySizeV": fmt_decimal(size_v, 6),
        "entryTaxFdvWanUsd": fmt_decimal(entry, 6),
        "entrySpotFdvWanUsd": fmt_decimal(spot_fdv_wan(row), 6),
        "ownWeightedCostBeforeWanUsd": fmt_decimal(own_cost_before, 6) if own_cost_before is not None else None,
        "ownWeightedCostAfterWanUsd": fmt_decimal(own_cost_after, 6),
        "sizeReason": reason,
        "boardSpentV": fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal(0), 3),
        "boardCostWanUsd": fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
        "costRows": int(row.get("costRows") or 0),
        "whaleRows": int(row.get("whaleRows") or 0),
        "costPosition": str(row.get("costPosition") or "-"),
        "vCostPosition": str(row.get("vCostPosition") or "-"),
        "triggerTypes": row.get("triggerTypes") or [],
    }


def evaluate_dynamic(samples: list[dict[str, Any]], rule: StrategyRule, config: DynamicBuyConfig) -> dict[str, Any]:
    buys: list[dict[str, Any]] = []
    paused_rows: list[dict[str, Any]] = []
    skipped_tax_rates: set[str] = set()
    bought_tax_rates: set[str] = set()
    skip_reasons: Counter[str] = Counter()

    active_tax_key: str | None = None
    active_tax_had_buy = False
    consecutive_buys: list[dict[str, Any]] = []

    total_spent = Decimal("0")
    weighted_cost_numerator = Decimal("0")

    for index, row in enumerate(samples):
        tax_key = str(row.get("buyTaxRate"))
        if tax_key != active_tax_key:
            if active_tax_key is not None and not active_tax_had_buy:
                consecutive_buys = []
            active_tax_key = tax_key
            active_tax_had_buy = False

        ok, reason = should_buy(row, rule)
        if not ok:
            skip_reasons[reason] += 1
            continue
        if config.one_buy_per_tax_rate and tax_key in bought_tax_rates:
            skip_reasons["same_tax_period"] += 1
            continue
        if tax_key in skipped_tax_rates:
            skip_reasons["flat_pause_tax_period"] += 1
            continue

        entry = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        if entry is None or entry <= 0:
            skip_reasons["missing_entry_fdv"] += 1
            continue

        if (
            len(consecutive_buys) >= config.pause_after_buy_count
            and is_next_tax_period(consecutive_buys[-1].get("taxRate"), tax_key)
        ):
            previous_entry = parse_decimal(consecutive_buys[-1].get("entryTaxFdvWanUsd"))
            change_pct = decimal_ratio_change(entry, previous_entry) if previous_entry is not None else None
            if change_pct is not None and change_pct <= config.flat_pause_pct:
                skipped_tax_rates.add(tax_key)
                skip_reasons["flat_pause_tax_period"] += 1
                paused_rows.append(
                    {
                        "index": index,
                        "timestamp": int(row.get("simTimestamp") or 0),
                        "taxRate": tax_key,
                        "taxFdvWanUsd": fmt_decimal(entry, 6),
                        "previousBuyTaxFdvWanUsd": fmt_decimal(previous_entry, 6),
                        "fdvChangePct": fmt_decimal(change_pct, 4),
                        "boardSpentV": fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal(0), 3),
                        "boardCostWanUsd": fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
                        "triggerTypes": row.get("triggerTypes") or [],
                    }
                )
                consecutive_buys = []
                active_tax_had_buy = False
                continue

        own_cost_before = weighted_cost_numerator / total_spent if total_spent > 0 else None
        if own_cost_before is not None and entry <= own_cost_before * (Decimal("1") - config.dip_from_own_cost_pct / Decimal("100")):
            buy_size = config.dip_buy_v
            size_reason = "dip20_double"
        else:
            buy_size = config.base_buy_v
            size_reason = "base25"

        total_spent += buy_size
        weighted_cost_numerator += buy_size * entry
        own_cost_after = weighted_cost_numerator / total_spent
        buy = compact_buy(
            index=index,
            row=row,
            entry=entry,
            size_v=buy_size,
            own_cost_before=own_cost_before,
            own_cost_after=own_cost_after,
            reason=size_reason,
        )
        buys.append(buy)
        bought_tax_rates.add(tax_key)
        active_tax_had_buy = True

        if consecutive_buys and not is_next_tax_period(consecutive_buys[-1].get("taxRate"), tax_key):
            consecutive_buys = []
        consecutive_buys.append(buy)

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_value = Decimal("0")
    for buy in buys:
        entry = parse_decimal(buy.get("entryTaxFdvWanUsd"))
        size_v = parse_decimal(buy.get("buySizeV")) or Decimal("0")
        if entry is not None and entry > 0 and final_spot is not None:
            final_value += size_v * final_spot / entry

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent > 0 else Decimal("0")
    double_buys = sum(1 for buy in buys if buy.get("sizeReason") == "dip20_double")
    return {
        "ruleName": f"{rule.name}__{config.name}",
        "sourceRuleName": rule.name,
        "dynamicConfig": {
            "baseBuyV": fmt_decimal(config.base_buy_v),
            "dipBuyV": fmt_decimal(config.dip_buy_v),
            "dipFromOwnCostPct": fmt_decimal(config.dip_from_own_cost_pct),
            "flatPausePct": fmt_decimal(config.flat_pause_pct),
            "pauseAfterBuyCount": config.pause_after_buy_count,
            "oneBuyPerTaxRate": config.one_buy_per_tax_rate,
            "maxProjectSpendV": None,
        },
        "rule": {
            "spentThresholdV": fmt_decimal(rule.spent_threshold_v),
            "maxTaxRate": fmt_decimal(rule.max_tax_rate),
            "fdvDiscount": fmt_decimal(rule.fdv_discount),
            "minCostRows": rule.min_cost_rows,
            "minWhaleRows": rule.min_whale_rows,
        },
        "buyCount": len(buys),
        "doubleBuyCount": double_buys,
        "pauseCount": len(paused_rows),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "ownWeightedCostWanUsd": fmt_decimal(weighted_cost_numerator / total_spent, 6) if total_spent > 0 else None,
        "finalSpotFdvWanUsd": fmt_decimal(final_spot, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "firstBuy": buys[0] if buys else None,
        "lastBuy": buys[-1] if buys else None,
        "buys": buys,
        "pausedRows": paused_rows,
        "skipReasons": dict(skip_reasons),
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def first_buy_text(item: dict[str, Any]) -> str:
    first = item.get("firstBuy") if isinstance(item.get("firstBuy"), dict) else {}
    if not first:
        return "-"
    return (
        f"tax {first.get('taxRate')}, "
        f"{first.get('buySizeV')}V, "
        f"FDV {first.get('entryTaxFdvWanUsd')}万, "
        f"board {first.get('boardSpentV')}V, "
        f"cost {first.get('boardCostWanUsd')}万"
    )


def buy_path_text(item: dict[str, Any], limit: int = 12) -> str:
    buys = item.get("buys") or []
    if not buys:
        return "-"
    parts = [
        f"{buy.get('taxRate')}%:{buy.get('buySizeV')}V@{buy.get('entryTaxFdvWanUsd')}"
        for buy in buys[:limit]
    ]
    if len(buys) > limit:
        parts.append(f"... +{len(buys) - limit}")
    return " / ".join(parts)


def build_project_result(report_path: Path, config: DynamicBuyConfig) -> dict[str, Any]:
    source_report = load_json(report_path)
    samples_path = Path(str(source_report.get("samplesPath") or ""))
    samples = load_samples(samples_path)
    project_results = [evaluate_dynamic(samples, rule, config) for rule in rules()]
    project_results.sort(key=lambda item: Decimal(str(item.get("finalPnlPct") or "0")), reverse=True)
    return {
        "project": source_report.get("project"),
        "virtualsId": source_report.get("virtualsId"),
        "sourceReport": str(report_path),
        "samplesPath": str(samples_path),
        "sampleCount": len(samples),
        "sourceCounts": source_report.get("counts") or {},
        "finalSample": source_report.get("finalSample"),
        "results": project_results,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    pause_after_buy_count = max(1, int(args.pause_after_buy_count))
    name = "dynamic_25v_dip20_double_flat10_no_cap"
    if pause_after_buy_count == 1:
        name = "dynamic_25v_dip20_after1_flat10_no_cap"
    elif pause_after_buy_count != 2:
        name = f"dynamic_25v_dip20_after{pause_after_buy_count}_flat10_no_cap"
    config = DynamicBuyConfig(name=name, pause_after_buy_count=pause_after_buy_count)
    report_paths = [Path(item.split("=", 1)[1] if "=" in item else item) for item in args.report]
    if not report_paths:
        report_paths = [Path(args.sr_report), Path(args.isc_report)]
    projects = [build_project_result(path, config) for path in report_paths]
    return {
        "ok": True,
        "readOnly": True,
        "productionDbTouched": False,
        "tradeSent": False,
        "scope": "Dynamic buy strategy recalculation from existing event-level samples",
        "strategyRevision": config.name,
        "strategyDefinition": {
            "hardGates": [
                "project live",
                "boardSpentV >= 5,000",
                "buyTaxRate <= rule threshold",
                "costRows >= 5",
                "whaleRows >= 20",
                "estimatedFdvWanUsdWithTax <= boardCostWanUsd",
                "one buy per tax-rate period",
            ],
            "buySizing": [
                "base buy = 25 VIRTUAL",
                "if current tax FDV <= own weighted entry FDV * 0.8, buy = 50 VIRTUAL",
            ],
            "pauseRule": [
                f"after {config.pause_after_buy_count} consecutive tax-rate minute(s) with buys",
                "if the next tax-rate minute's tax FDV changes <= 10% from the previous buy FDV, skip that whole tax-rate minute",
                "the following tax-rate minute resets the streak and can buy again if gates pass",
            ],
            "maxProjectSpendV": None,
            "settlement": "tax-end final spot FDV only",
            "futureLeakageGuard": "uses only current and previous sample/buy state while iterating chronological samples",
        },
        "projects": projects,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# Dynamic 25V/50V Strategy Recalculation")
    lines.append("")
    lines.append("本报告只读取既有事件级 sample JSONL 或 launch archive，未重新抓链、未写生产库、未发送交易。")
    lines.append("")
    lines.append("## 策略口径")
    lines.append("- 硬条件沿用上一版：榜单累计投入 `>=5,000 V`、榜单人数 `>=20`、成本样本 `>=5`、含税估算 FDV `<=` 榜单成本位、每个税率档位最多买一次。")
    lines.append("- 单笔基础买入：`25 VIRTUAL`。")
    lines.append("- 如果当前含税估算 FDV 比我方历史加权买入 FDV 低 `20%` 以上，本次买入 `50 VIRTUAL`。")
    pause_after_buy_count = int((report.get("projects") or [{}])[0].get("results", [{}])[0].get("dynamicConfig", {}).get("pauseAfterBuyCount") or 2)
    if pause_after_buy_count == 1:
        lines.append("- 某税率分钟买入后，如果下一税率分钟的含税估算 FDV 相比上一笔买入变化 `<=10%`，跳过该税率分钟；再下一个税率分钟重新计算。")
    else:
        lines.append("- 连续两个税率分钟买入后，如果下一个税率分钟的含税估算 FDV 相比上一笔买入变化 `<=10%`，跳过该税率分钟；再下一个税率分钟重新计算。")
    lines.append("- 本轮不限制项目最大买入上限，只作为回测压力测试，不等于生产自动买入开关。")
    lines.append("")

    for project in report["projects"]:
        lines.append(f"## {project.get('project')} / Virtuals ID {project.get('virtualsId')}")
        lines.append("")
        counts = project.get("sourceCounts") or {}
        lines.append(f"- 样本：`{project.get('sampleCount')}`；源样本：`{project.get('samplesPath')}`。")
        lines.append(f"- pool events：`{counts.get('poolEventCount')}`；buy/sell/unknown：`{(counts.get('poolEventTypes') or {}).get('buy', 0)}` / `{(counts.get('poolEventTypes') or {}).get('sell', 0)}` / `{(counts.get('poolEventTypes') or {}).get('unknown_pool_event', 0)}`。")
        lines.append("")
        lines.append(table_line(["Rule", "买入", "50V次数", "暂停", "投入V", "加权成本FDV", "end收益", "End PnL V", "首买"]))
        lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---"]))
        for item in project["results"]:
            lines.append(
                table_line(
                    [
                        item.get("sourceRuleName"),
                        item.get("buyCount"),
                        item.get("doubleBuyCount"),
                        item.get("pauseCount"),
                        item.get("totalSpentV"),
                        item.get("ownWeightedCostWanUsd"),
                        f"{item.get('finalPnlPct')}%",
                        item.get("finalPnlV"),
                        first_buy_text(item),
                    ]
                )
            )
        lines.append("")
        tax95 = next((item for item in project["results"] if item.get("sourceRuleName") == "gate_5k_tax95_fdv_one_per_tax"), None)
        best = project["results"][0] if project.get("results") else None
        for title, item in [("tax<=95 主规则路径", tax95), ("当前 ROI 最优路径", best)]:
            if not item:
                continue
            lines.append(f"### {title}")
            lines.append("")
            lines.append(f"- Rule：`{item.get('sourceRuleName')}`。")
            lines.append(f"- 买入次数/投入：`{item.get('buyCount')}` / `{item.get('totalSpentV')} V`。")
            lines.append(f"- 50V 加倍次数：`{item.get('doubleBuyCount')}`；暂停次数：`{item.get('pauseCount')}`。")
            lines.append(f"- 加权成本 FDV：`{item.get('ownWeightedCostWanUsd')}` 万 USD；end PnL：`{item.get('finalPnlV')} V` / `{item.get('finalPnlPct')}%`。")
            lines.append(f"- 买入路径：{buy_path_text(item)}")
            if item.get("pausedRows"):
                lines.append("- 暂停点：")
                for pause in (item.get("pausedRows") or [])[:8]:
                    lines.append(
                        f"  - tax {pause.get('taxRate')}，FDV {pause.get('taxFdvWanUsd')} 万，"
                        f"相对上一买入变化 {pause.get('fdvChangePct')}%，board {pause.get('boardSpentV')} V"
                    )
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recalculate dynamic buy strategy from existing samples.")
    parser.add_argument(
        "--report",
        action="append",
        default=[],
        help="Project summary/archive JSON. Repeatable. Optional PROJECT=path form is accepted.",
    )
    parser.add_argument("--sr-report", default="data/backtests/sr-event-level-replay-20260510T073102Z.json")
    parser.add_argument("--isc-report", default="data/backtests/isc-event-level-replay-20260510.json")
    parser.add_argument("--output-json", default="data/backtests/dynamic-buy-recalc-after1-flat10-20260510.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-dynamic-buy-recalc-after1-flat10-2026-05-10.md")
    parser.add_argument("--pause-after-buy-count", type=int, default=1)
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
                        "project": project.get("project"),
                        "bestRule": (project.get("results") or [{}])[0].get("sourceRuleName"),
                        "bestPnlPct": (project.get("results") or [{}])[0].get("finalPnlPct"),
                    }
                    for project in report["projects"]
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
