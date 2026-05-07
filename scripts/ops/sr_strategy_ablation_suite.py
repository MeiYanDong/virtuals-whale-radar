#!/usr/bin/env python3
"""Controlled ablation tests for SR launch strategy conditions.

This is a read-only analysis tool. It answers questions like:

- what happens at 70k / 80k / 90k board-spent thresholds;
- what happens if board-spent is not limited and only tax is used;
- what happens when one trigger variable is removed;
- what happens across spent x tax grids.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from backtest_launch_strategy import fmt_decimal, load_samples, parse_decimal, spot_fdv_wan


@dataclass(frozen=True)
class Rule:
    name: str
    spent_threshold_v: Decimal | None = None
    max_tax_rate: Decimal | None = None
    fdv_discount: Decimal | None = None
    min_rows: int = 0
    cooldown_sec: int = 60
    burst_limit: int = 2
    burst_window_sec: int = 120
    burst_cooldown_sec: int = 600
    buy_size_v: Decimal = Decimal("50")
    max_project_spend_v: Decimal = Decimal("300")


@dataclass(frozen=True)
class Buy:
    index: int
    sim_timestamp: int
    tax_rate: str | None
    board_spent_v: str | None
    tax_fdv_wan_usd: str | None
    spot_fdv_wan_usd: str | None
    board_cost_wan_usd: str | None
    cost_rows: int
    whale_rows: int
    cost_position: str
    v_cost_position: str


def d(value: str | int | float) -> Decimal:
    parsed = parse_decimal(value)
    if parsed is None:
        raise ValueError(f"invalid decimal: {value}")
    return parsed


def serialize_rule(rule: Rule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "spentThresholdV": fmt_decimal(rule.spent_threshold_v) if rule.spent_threshold_v is not None else None,
        "maxTaxRate": fmt_decimal(rule.max_tax_rate) if rule.max_tax_rate is not None else None,
        "fdvDiscount": fmt_decimal(rule.fdv_discount) if rule.fdv_discount is not None else None,
        "minRows": rule.min_rows,
        "cooldownSec": rule.cooldown_sec,
        "burstLimit": rule.burst_limit,
        "burstWindowSec": rule.burst_window_sec,
        "burstCooldownSec": rule.burst_cooldown_sec,
        "buySizeV": fmt_decimal(rule.buy_size_v),
        "maxProjectSpendV": fmt_decimal(rule.max_project_spend_v),
    }


def should_buy(row: dict[str, Any], rule: Rule) -> tuple[bool, str]:
    if row.get("projectStatus") not in {None, "live"}:
        return False, "not_live"

    tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
    if tax_fdv is None or tax_fdv <= 0:
        return False, "missing_tax_fdv"

    board_spent = parse_decimal(row.get("boardSpentV")) or Decimal("0")
    if rule.spent_threshold_v is not None and board_spent < rule.spent_threshold_v:
        return False, "spent_threshold"

    tax_rate = parse_decimal(row.get("buyTaxRate"))
    if rule.max_tax_rate is not None and (tax_rate is None or tax_rate > rule.max_tax_rate):
        return False, "tax_threshold"

    cost_rows = int(row.get("costRows") or 0)
    whale_rows = int(row.get("whaleRows") or 0)
    if rule.min_rows > 0 and (cost_rows < rule.min_rows or whale_rows < rule.min_rows):
        return False, "min_rows"

    if rule.fdv_discount is not None:
        board_cost = parse_decimal(row.get("boardCostWanUsd"))
        if board_cost is None or board_cost <= 0:
            return False, "missing_board_cost"
        if tax_fdv > board_cost * rule.fdv_discount:
            return False, "fdv_not_below_cost"

    return True, "signal"


def evaluate(samples: list[dict[str, Any]], rule: Rule) -> dict[str, Any]:
    buys: list[Buy] = []
    total_spent = Decimal("0")
    next_allowed_ts = -1
    buy_timestamps: list[int] = []
    skip_reasons: dict[str, int] = {}

    for index, row in enumerate(samples):
        ts = int(row.get("simTimestamp") or 0)
        ok, reason = should_buy(row, rule)
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        if ts < next_allowed_ts:
            skip_reasons["cooldown"] = skip_reasons.get("cooldown", 0) + 1
            continue
        if total_spent + rule.buy_size_v > rule.max_project_spend_v:
            skip_reasons["max_project_spend"] = skip_reasons.get("max_project_spend", 0) + 1
            continue

        tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        if tax_fdv is None or tax_fdv <= 0:
            continue

        board_spent = parse_decimal(row.get("boardSpentV"))
        board_cost = parse_decimal(row.get("boardCostWanUsd"))
        spot_fdv = spot_fdv_wan(row)
        buys.append(
            Buy(
                index=index,
                sim_timestamp=ts,
                tax_rate=fmt_decimal(parse_decimal(row.get("buyTaxRate"))),
                board_spent_v=fmt_decimal(board_spent, 3) if board_spent is not None else None,
                tax_fdv_wan_usd=fmt_decimal(tax_fdv, 6),
                spot_fdv_wan_usd=fmt_decimal(spot_fdv, 6) if spot_fdv is not None else None,
                board_cost_wan_usd=fmt_decimal(board_cost, 6) if board_cost is not None else None,
                cost_rows=int(row.get("costRows") or 0),
                whale_rows=int(row.get("whaleRows") or 0),
                cost_position=str(row.get("costPosition") or "-"),
                v_cost_position=str(row.get("vCostPosition") or "-"),
            )
        )
        buy_timestamps.append(ts)
        total_spent += rule.buy_size_v

        recent = [item for item in buy_timestamps if ts - item <= rule.burst_window_sec]
        if rule.burst_limit > 0 and len(recent) >= rule.burst_limit:
            next_allowed_ts = ts + rule.burst_cooldown_sec
        else:
            next_allowed_ts = ts + rule.cooldown_sec

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_value = Decimal("0")
    returns: list[Decimal] = []
    for buy in buys:
        entry = parse_decimal(buy.tax_fdv_wan_usd)
        if entry is None or entry <= 0 or final_spot is None:
            continue
        value = rule.buy_size_v * final_spot / entry
        final_value += value
        returns.append(value / rule.buy_size_v - Decimal("1"))

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent else Decimal("0")
    avg_return_pct = Decimal(str(statistics.mean(float(item * 100) for item in returns))) if returns else Decimal("0")

    return {
        "rule": serialize_rule(rule),
        "buyCount": len(buys),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "avgBuyReturnPct": fmt_decimal(avg_return_pct, 4),
        "firstBuy": asdict(buys[0]) if buys else None,
        "buys": [asdict(item) for item in buys],
        "skipReasons": skip_reasons,
    }


def rule(
    name: str,
    *,
    spent: int | None = None,
    tax: int | None = None,
    fdv_discount: str | None = None,
    min_rows: int = 0,
    max_spend: int = 300,
    cooldown: int = 60,
) -> Rule:
    return Rule(
        name=name,
        spent_threshold_v=d(spent) if spent is not None else None,
        max_tax_rate=d(tax) if tax is not None else None,
        fdv_discount=d(fdv_discount) if fdv_discount is not None else None,
        min_rows=min_rows,
        max_project_spend_v=d(max_spend),
        cooldown_sec=cooldown,
    )


def build_suites() -> dict[str, list[Rule]]:
    spent_values = [50000, 60000, 70000, 80000, 90000, 100000, 110000, 120000]
    tax_values = [95, 94, 93, 92, 91, 90]
    suites: dict[str, list[Rule]] = {}

    suites["spent_gradient_fixed_tax92_fdv"] = [
        rule(f"spent={spent}|tax<=92|fdv", spent=spent, tax=92, fdv_discount="1", min_rows=10)
        for spent in spent_values
    ]
    suites["spent_gradient_fixed_tax95_fdv"] = [
        rule(f"spent={spent}|tax<=95|fdv", spent=spent, tax=95, fdv_discount="1", min_rows=10)
        for spent in spent_values
    ]
    suites["tax_gradient_no_spent_tax_only"] = [
        rule(f"tax<={tax}|tax_only", tax=tax)
        for tax in tax_values
    ]
    suites["tax_gradient_no_spent_with_fdv"] = [
        rule(f"tax<={tax}|fdv", tax=tax, fdv_discount="1", min_rows=10)
        for tax in tax_values
    ]
    suites["tax_gradient_fixed_100k_with_fdv"] = [
        rule(f"spent=100000|tax<={tax}|fdv", spent=100000, tax=tax, fdv_discount="1", min_rows=10)
        for tax in tax_values
    ]
    suites["ablation_cancel_variables"] = [
        rule("all_vars_baseline", spent=100000, tax=92, fdv_discount="1", min_rows=10),
        rule("cancel_spent_keep_tax92_fdv", tax=92, fdv_discount="1", min_rows=10),
        rule("cancel_tax_keep_100k_fdv", spent=100000, fdv_discount="1", min_rows=10),
        rule("cancel_fdv_keep_100k_tax92", spent=100000, tax=92),
        rule("only_tax92", tax=92),
        rule("only_tax95", tax=95),
        rule("only_spent100k", spent=100000),
        rule("only_fdv", fdv_discount="1", min_rows=10),
        rule("spent100k_plus_tax92", spent=100000, tax=92),
        rule("spent100k_plus_fdv", spent=100000, fdv_discount="1", min_rows=10),
        rule("tax92_plus_fdv", tax=92, fdv_discount="1", min_rows=10),
    ]
    suites["spent_x_tax_with_fdv"] = [
        rule(f"spent={spent}|tax<={tax}|fdv", spent=spent, tax=tax, fdv_discount="1", min_rows=10)
        for spent in spent_values
        for tax in tax_values
    ]
    suites["spent_x_tax_no_fdv"] = [
        rule(f"spent={spent}|tax<={tax}|no_fdv", spent=spent, tax=tax)
        for spent in spent_values
        for tax in tax_values
    ]
    return suites


def dataset_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [int(row.get("simTimestamp") or 0) for row in samples]
    return {
        "sampleCount": len(samples),
        "firstTimestamp": timestamps[0] if timestamps else None,
        "lastTimestamp": timestamps[-1] if timestamps else None,
        "durationSec": timestamps[-1] - timestamps[0] if len(timestamps) >= 2 else 0,
    }


def table_line(cells: list[Any]) -> str:
    escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
    return "| " + " | ".join(escaped) + " |"


def by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["rule"]["name"]: item for item in rows}


def append_focus_table(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    lines.append(table_line(["规则", "买入次数", "投入 V", "收益 V", "收益率", "首次买入"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---"]))
    for item in rows:
        first = item.get("firstBuy") or {}
        first_text = "-"
        if first:
            first_text = (
                f"tax {first.get('tax_rate')}, "
                f"board {first.get('board_spent_v')}, "
                f"taxFDV {first.get('tax_fdv_wan_usd')}, "
                f"cost {first.get('board_cost_wan_usd')}"
            )
        lines.append(
            table_line(
                [
                    item["rule"]["name"],
                    item["buyCount"],
                    item["totalSpentV"],
                    item["finalPnlV"],
                    f"{item['finalPnlPct']}%",
                    first_text,
                ]
            )
        )
    lines.append("")


def write_markdown(report: dict[str, Any], output: Path) -> None:
    lines: list[str] = []
    lines.append("# SR 策略控制变量与消融测试")
    lines.append("")
    lines.append("本报告只读 SR 高采样 replay，不写生产数据库，不发交易。")
    lines.append("")
    lines.append("## 测试口径")
    lines.append("")
    lines.append("- `fdv` 表示要求 `含税估算 FDV <= 榜单加权成本 FDV`。")
    lines.append("- `tax_only` 表示取消大户榜单 V 门槛，也取消 FDV/榜单成本条件，只按税率触发。")
    lines.append("- 所有规则默认每次模拟买入 `50V`，普通冷却 `60s`，`120s` 内连续 `2` 次后冷却 `600s`，项目最多 `300V`。")
    lines.append("")
    lines.append("## 样本")
    for key, value in report["datasetStats"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    suites = report["suites"]
    spent_tax95 = by_name(suites["spent_gradient_fixed_tax95_fdv"])
    append_focus_table(
        lines,
        "重点 1：70k / 80k / 90k，固定 tax<=95 + fdv",
        [
            spent_tax95["spent=70000|tax<=95|fdv"],
            spent_tax95["spent=80000|tax<=95|fdv"],
            spent_tax95["spent=90000|tax<=95|fdv"],
            spent_tax95["spent=100000|tax<=95|fdv"],
        ],
    )

    tax_only = suites["tax_gradient_no_spent_tax_only"]
    append_focus_table(lines, "重点 2：不限制大户榜单 V，只看税率 95-90", tax_only)

    tax_fdv = suites["tax_gradient_no_spent_with_fdv"]
    append_focus_table(lines, "重点 3：不限制大户榜单 V，但保留 fdv 成本条件，税率 95-90", tax_fdv)

    append_focus_table(lines, "重点 4：取消变量消融", suites["ablation_cancel_variables"])

    for suite_name, rows in report["suites"].items():
        lines.append(f"## {suite_name}")
        lines.append(table_line(["规则", "买入次数", "投入 V", "收益 V", "收益率", "首次买入"]))
        lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---"]))
        for item in rows:
            first = item.get("firstBuy") or {}
            first_text = "-"
            if first:
                first_text = (
                    f"tax {first.get('tax_rate')}, "
                    f"board {first.get('board_spent_v')}, "
                    f"taxFDV {first.get('tax_fdv_wan_usd')}, "
                    f"cost {first.get('board_cost_wan_usd')}"
                )
            lines.append(
                table_line(
                    [
                        item["rule"]["name"],
                        item["buyCount"],
                        item["totalSpentV"],
                        item["finalPnlV"],
                        f"{item['finalPnlPct']}%",
                        first_text,
                    ]
                )
            )
        lines.append("")

    lines.append("## 直接结论")
    lines.append("")
    lines.append("- `70k / 80k / 90k` 必须作为独立梯度点看，不应只用 `50k / 100k` 代表。")
    lines.append("- `只看税率` 是完全不同策略：它取消了大户榜单确认，也取消了 FDV 低于榜单成本的安全垫，容易更早进入，但风险含义不同。")
    lines.append("- 真正可比较的口径应分成：单变量、取消变量、固定变量梯度、多变量组合。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SR strategy controlled ablation tests.")
    parser.add_argument("--samples", required=True)
    parser.add_argument("--output-json", default="data/backtests/sr-strategy-ablation-suite-20260507.json")
    parser.add_argument("--output-md", default="docs/sr-strategy-ablation-suite-2026-05-07.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = load_samples(Path(args.samples))
    suites: dict[str, list[dict[str, Any]]] = {}
    for suite_name, rules in build_suites().items():
        suites[suite_name] = [evaluate(samples, item) for item in rules]

    report = {
        "samples": args.samples,
        "datasetStats": dataset_stats(samples),
        "assumptions": {
            "readOnly": True,
            "entryCost": "estimatedFdvWanUsdWithTax at trigger sample",
            "markToMarket": "final liveFdvUsd / 10000",
            "tradeSize": "50 VIRTUAL",
            "productionDbTouched": False,
        },
        "suites": suites,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(
        json.dumps(
            {
                "outputJson": args.output_json,
                "outputMd": args.output_md,
                "suiteCount": len(suites),
                "caseCount": sum(len(items) for items in suites.values()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
