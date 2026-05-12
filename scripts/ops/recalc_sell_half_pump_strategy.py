#!/usr/bin/env python3
"""Backtest a tax<=30 spot-FDV pump sell-half rule from existing replay samples.

Read-only boundaries:
- reads local SR/ISC event-level replay reports and sample JSONL files;
- writes local JSON/Markdown backtest reports only;
- does not touch production DBs and does not sign or broadcast transactions.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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
from recalc_dynamic_buy_strategy import DynamicBuyConfig, evaluate_dynamic, load_samples  # noqa: E402
from sr_event_level_replay import rules  # noqa: E402


@dataclass(frozen=True)
class SellHalfPumpConfig:
    name: str = "tax30_spot_above_board_cost_adjacent_pump10_sell_half"
    max_tax_rate: Decimal = Decimal("30")
    min_spot_jump_pct: Decimal = Decimal("10")
    sell_fraction: Decimal = Decimal("0.5")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cst_text(ts: Any) -> str:
    value = int(ts or 0)
    if value <= 0:
        return "-"
    return datetime.fromtimestamp(value, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def value_at_spot(buys: list[dict[str, Any]], spot_fdv: Decimal) -> Decimal:
    value = Decimal("0")
    for buy in buys:
        size_v = parse_decimal(buy.get("buySizeV")) or Decimal("0")
        entry_fdv = parse_decimal(buy.get("entryTaxFdvWanUsd"))
        if size_v > 0 and entry_fdv is not None and entry_fdv > 0:
            value += size_v * spot_fdv / entry_fdv
    return value


def pnl_pct(value_v: Decimal, spent_v: Decimal) -> Decimal:
    if spent_v <= 0:
        return Decimal("0")
    return (value_v - spent_v) / spent_v * Decimal("100")


def adjacent_jump_pct(previous: Decimal, current: Decimal) -> Decimal | None:
    if previous <= 0:
        return None
    return (current - previous) / previous * Decimal("100")


def find_first_sell_half_trigger(
    *,
    samples: list[dict[str, Any]],
    buy_result: dict[str, Any],
    config: SellHalfPumpConfig,
) -> dict[str, Any]:
    buys = list(buy_result.get("buys") or [])
    spent_v = parse_decimal(buy_result.get("totalSpentV")) or Decimal("0")
    if not buys or spent_v <= 0:
        return {"noTrigger": True, "reason": "no_buy_position"}

    top_candidates: list[dict[str, Any]] = []
    trigger_candidates: list[dict[str, Any]] = []
    for index in range(1, len(samples)):
        previous_row = samples[index - 1]
        current_row = samples[index]
        tax_rate = parse_decimal(current_row.get("buyTaxRate"))
        if tax_rate is None or tax_rate > config.max_tax_rate:
            continue

        previous_spot = spot_fdv_wan(previous_row)
        current_spot = spot_fdv_wan(current_row)
        board_cost = parse_decimal(current_row.get("boardCostWanUsd"))
        if previous_spot is None or current_spot is None or board_cost is None:
            continue
        if previous_spot <= 0 or current_spot <= 0 or board_cost <= 0:
            continue
        if current_spot <= board_cost:
            continue

        jump_pct = adjacent_jump_pct(previous_spot, current_spot)
        if jump_pct is None:
            continue

        current_value = value_at_spot(buys, current_spot)
        candidate = {
            "index": index,
            "previousIndex": index - 1,
            "timestamp": int(current_row.get("simTimestamp") or 0),
            "timestampCst": cst_text(current_row.get("simTimestamp")),
            "previousTimestamp": int(previous_row.get("simTimestamp") or 0),
            "previousTimestampCst": cst_text(previous_row.get("simTimestamp")),
            "taxRate": fmt_decimal(tax_rate, 6),
            "previousTaxRate": fmt_decimal(parse_decimal(previous_row.get("buyTaxRate")), 6),
            "spotFdvWanUsd": fmt_decimal(current_spot, 6),
            "previousSpotFdvWanUsd": fmt_decimal(previous_spot, 6),
            "spotJumpPct": fmt_decimal(jump_pct, 4),
            "boardCostWanUsd": fmt_decimal(board_cost, 6),
            "spotAboveBoardCostPct": fmt_decimal((current_spot - board_cost) / board_cost * Decimal("100"), 4),
            "taxFdvWanUsd": fmt_decimal(parse_decimal(current_row.get("estimatedFdvWanUsdWithTax")), 6),
            "previousTaxFdvWanUsd": fmt_decimal(parse_decimal(previous_row.get("estimatedFdvWanUsdWithTax")), 6),
            "positionValueV": fmt_decimal(current_value, 6),
            "positionPnlV": fmt_decimal(current_value - spent_v, 6),
            "positionPnlPct": fmt_decimal(pnl_pct(current_value, spent_v), 4),
            "triggerTypes": current_row.get("triggerTypes") or [],
        }
        top_candidates.append(candidate)
        if jump_pct > config.min_spot_jump_pct:
            trigger_candidates.append(candidate)

    top_candidates.sort(key=lambda item: parse_decimal(item.get("spotJumpPct")) or Decimal("-999999"), reverse=True)
    top_candidates_copy = [dict(item) for item in top_candidates[:10]]
    if trigger_candidates:
        trigger = dict(trigger_candidates[0])
        trigger["noTrigger"] = False
        trigger["topSpotAboveBoardJumps"] = top_candidates_copy
        return trigger
    return {
        "noTrigger": True,
        "reason": "no_tax30_spot_above_board_cost_adjacent_pump_gt_threshold",
        "topSpotAboveBoardJumps": top_candidates_copy,
    }


def evaluate_project(
    *,
    report_path: Path,
    rule_name: str,
    buy_config: DynamicBuyConfig,
    sell_config: SellHalfPumpConfig,
) -> dict[str, Any]:
    source_report = load_json(report_path)
    samples_path = Path(str(source_report.get("samplesPath") or ""))
    samples = load_samples(samples_path)
    rule = next(item for item in rules() if item.name == rule_name)
    buy_result = evaluate_dynamic(samples, rule, buy_config)
    sell = find_first_sell_half_trigger(samples=samples, buy_result=buy_result, config=sell_config)

    spent_v = parse_decimal(buy_result.get("totalSpentV")) or Decimal("0")
    tax_end_value = parse_decimal(buy_result.get("finalValueV")) or Decimal("0")
    tax_end_pnl_pct = parse_decimal(buy_result.get("finalPnlPct")) or Decimal("0")
    sell_fraction = sell_config.sell_fraction

    if sell.get("noTrigger"):
        realized_value = tax_end_value
        realized_mode = "hold_to_tax_end_no_sell_half_trigger"
        sell_summary: dict[str, Any] = sell
    else:
        trigger_value = parse_decimal(sell.get("positionValueV")) or Decimal("0")
        realized_sell_value = trigger_value * sell_fraction
        remaining_tax_end_value = tax_end_value * (Decimal("1") - sell_fraction)
        realized_value = realized_sell_value + remaining_tax_end_value
        realized_mode = "sell_half_then_hold_remaining_to_tax_end"
        sell_summary = {
            **sell,
            "noTrigger": False,
            "sellFraction": fmt_decimal(sell_fraction, 6),
            "realizedSellValueV": fmt_decimal(realized_sell_value, 6),
            "remainingTaxEndValueV": fmt_decimal(remaining_tax_end_value, 6),
        }

    realized_pnl = realized_value - spent_v
    realized_pnl_pct = pnl_pct(realized_value, spent_v)
    return {
        "project": source_report.get("project"),
        "virtualsId": source_report.get("virtualsId"),
        "sourceReport": str(report_path),
        "samplesPath": str(samples_path),
        "sampleCount": len(samples),
        "buyRule": rule_name,
        "buyStrategy": buy_config.name,
        "sellStrategy": sell_config.name,
        "buyCount": buy_result.get("buyCount"),
        "pauseCount": buy_result.get("pauseCount"),
        "totalSpentV": buy_result.get("totalSpentV"),
        "ownWeightedCostWanUsd": buy_result.get("ownWeightedCostWanUsd"),
        "buyPath": [
            {
                "timestampCst": cst_text(buy.get("timestamp")),
                "taxRate": buy.get("taxRate"),
                "buySizeV": buy.get("buySizeV"),
                "entryTaxFdvWanUsd": buy.get("entryTaxFdvWanUsd"),
                "entrySpotFdvWanUsd": buy.get("entrySpotFdvWanUsd"),
            }
            for buy in (buy_result.get("buys") or [])
        ],
        "sell": sell_summary,
        "realizedMode": realized_mode,
        "realizedValueV": fmt_decimal(realized_value, 6),
        "realizedPnlV": fmt_decimal(realized_pnl, 6),
        "realizedPnlPct": fmt_decimal(realized_pnl_pct, 4),
        "taxEndValueV": buy_result.get("finalValueV"),
        "taxEndPnlV": buy_result.get("finalPnlV"),
        "taxEndPnlPct": buy_result.get("finalPnlPct"),
        "deltaVsTaxEndPnlPct": fmt_decimal(realized_pnl_pct - tax_end_pnl_pct, 4),
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Tax<=30 Spot-FDV Pump Sell-Half Backtest",
        "",
        "本报告只读取本地 SR/ISC event-level replay 产物，未重新抓链、未写生产库、未发送交易。",
        "",
        "## 策略口径",
        "",
        "- 买入：沿用当前动态买入策略 `dynamic_25v_dip20_after1_flat10_no_cap`。",
        "- 卖出：税率 `<=30%` 后，如果 `spot FDV > 大户榜单成本`，并且当前样本的 `spot FDV` 相比上一样本上涨 `>10%`，视为大单拉升，卖出当前持仓的一半。",
        "- 关键点：`>10%` 不是拿当前 spot FDV 和榜单成本比，而是相邻两个样本的 spot FDV 比。",
        "- 收益计算：买入成本使用入场时 `含税估算 FDV`；卖出一半按触发样本的 `spot FDV` 估值；剩余一半持有到 tax-end；暂未计入卖出滑点、gas、成交税。",
        "",
        "## 结果概览",
        "",
        table_line(["项目", "买入规则", "买入", "投入V", "卖半触发", "卖半后结果", "Tax-end纯持有", "差异"]),
        table_line(["---", "---", "---:", "---:", "---", "---:", "---:", "---:"]),
    ]
    for item in report["projects"]:
        sell = item.get("sell") or {}
        if sell.get("noTrigger"):
            sell_text = f"未触发（{sell.get('reason')}）"
        else:
            sell_text = (
                f"tax {sell.get('taxRate')} / {sell.get('timestampCst')} / "
                f"spot +{sell.get('spotJumpPct')}%"
            )
        lines.append(
            table_line(
                [
                    item.get("project"),
                    item.get("buyRule"),
                    item.get("buyCount"),
                    item.get("totalSpentV"),
                    sell_text,
                    f"{item.get('realizedPnlV')}V / {item.get('realizedPnlPct')}%",
                    f"{item.get('taxEndPnlV')}V / {item.get('taxEndPnlPct')}%",
                    f"{item.get('deltaVsTaxEndPnlPct')} pct",
                ]
            )
        )
    lines.append("")

    for item in report["projects"]:
        lines.append(f"## {item.get('project')}")
        lines.append("")
        lines.append(f"- Virtuals ID：`{item.get('virtualsId')}`。")
        lines.append(f"- 样本：`{item.get('sampleCount')}`。")
        lines.append(f"- 买入规则：`{item.get('buyRule')}`；买入 `{item.get('buyCount')}` 次，投入 `{item.get('totalSpentV')} V`。")
        lines.append(f"- 我方加权成本 FDV：`{item.get('ownWeightedCostWanUsd')}` 万 USD。")
        sell = item.get("sell") or {}
        if sell.get("noTrigger"):
            lines.append(f"- 卖半：未触发，原因 `{sell.get('reason')}`。")
            top_jumps = sell.get("topSpotAboveBoardJumps") or []
            if top_jumps:
                best = top_jumps[0]
                lines.append(
                    f"- 最大相邻涨幅：tax `{best.get('taxRate')}`，时间 `{best.get('timestampCst')}`，"
                    f"spot FDV `{best.get('previousSpotFdvWanUsd')}` -> `{best.get('spotFdvWanUsd')}` 万，"
                    f"涨幅 `{best.get('spotJumpPct')}%`，低于本次 `>10%` 阈值。"
                )
                lines.append("")
                lines.append("最大相邻涨幅样本：")
                lines.append("")
                lines.append(table_line(["时间(CST)", "税率", "上一spotFDV", "当前spotFDV", "涨幅", "榜单成本"]))
                lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:"]))
                for jump in top_jumps[:5]:
                    lines.append(
                        table_line(
                            [
                                jump.get("timestampCst"),
                                jump.get("taxRate"),
                                jump.get("previousSpotFdvWanUsd"),
                                jump.get("spotFdvWanUsd"),
                                f"{jump.get('spotJumpPct')}%",
                                jump.get("boardCostWanUsd"),
                            ]
                        )
                    )
        else:
            lines.append(
                f"- 卖半触发：tax `{sell.get('taxRate')}`，时间 `{sell.get('timestampCst')}`，"
                f"上一刻 spot FDV `{sell.get('previousSpotFdvWanUsd')}` 万，当前 `{sell.get('spotFdvWanUsd')}` 万，"
                f"跳涨 `{sell.get('spotJumpPct')}%`。"
            )
            lines.append(
                f"- 与榜单成本：榜单成本 `{sell.get('boardCostWanUsd')}` 万，"
                f"spot 高出 `{sell.get('spotAboveBoardCostPct')}%`。"
            )
            lines.append(
                f"- 触发时持仓：估值 `{sell.get('positionValueV')} V`，"
                f"浮盈 `{sell.get('positionPnlV')} V / {sell.get('positionPnlPct')}%`。"
            )
            lines.append(
                f"- 卖出一半落袋 `{sell.get('realizedSellValueV')} V`；"
                f"剩余一半 tax-end 估值 `{sell.get('remainingTaxEndValueV')} V`。"
            )
        lines.append(f"- 策略结果：`{item.get('realizedPnlV')} V / {item.get('realizedPnlPct')}%`。")
        lines.append(f"- 纯持有到 tax-end：`{item.get('taxEndPnlV')} V / {item.get('taxEndPnlPct')}%`。")
        lines.append("")
        lines.append("买入路径：")
        lines.append("")
        lines.append(table_line(["时间(CST)", "税率", "买入V", "含税FDV", "spotFDV"]))
        lines.append(table_line(["---", "---:", "---:", "---:", "---:"]))
        for buy in item.get("buyPath") or []:
            lines.append(
                table_line(
                    [
                        buy.get("timestampCst"),
                        buy.get("taxRate"),
                        buy.get("buySizeV"),
                        buy.get("entryTaxFdvWanUsd"),
                        buy.get("entrySpotFdvWanUsd"),
                    ]
                )
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    buy_config = DynamicBuyConfig(pause_after_buy_count=1)
    sell_config = SellHalfPumpConfig(
        max_tax_rate=Decimal(str(args.sell_max_tax)),
        min_spot_jump_pct=Decimal(str(args.spot_jump_pct)),
        sell_fraction=Decimal(str(args.sell_fraction)),
    )
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
        "scope": "SR and ISC sell-half pump backtest from existing event-level samples",
        "strategyDefinition": {
            "buyStrategy": buy_config.name,
            "sellStrategy": sell_config.name,
            "sellWhen": [
                f"buyTaxRate <= {fmt_decimal(sell_config.max_tax_rate)}",
                "spotFdvWanUsd > boardCostWanUsd",
                f"adjacent spotFdvWanUsd jump > {fmt_decimal(sell_config.min_spot_jump_pct)}%",
            ],
            "sellFraction": fmt_decimal(sell_config.sell_fraction, 6),
            "settlement": "sell half at trigger spot FDV, hold remaining half to tax-end spot FDV",
            "feesModeled": False,
        },
        "projects": projects,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest tax<=30 adjacent spot-FDV pump sell-half rule for SR and ISC.")
    parser.add_argument("--sr-report", default="data/backtests/sr-event-level-replay-20260510T073102Z.json")
    parser.add_argument("--isc-report", default="data/backtests/isc-event-level-replay-20260510.json")
    parser.add_argument("--sr-rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--isc-rule", default="gate_5k_tax89_fdv_one_per_tax")
    parser.add_argument("--sell-max-tax", default="30")
    parser.add_argument("--spot-jump-pct", default="10")
    parser.add_argument("--sell-fraction", default="0.5")
    parser.add_argument("--output-json", default="data/backtests/sell-half-tax30-spot-pump10-20260511.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-sell-half-tax30-spot-pump10-2026-05-11.md")
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
                        "buyRule": item.get("buyRule"),
                        "realizedMode": item.get("realizedMode"),
                        "realizedPnlPct": item.get("realizedPnlPct"),
                        "taxEndPnlPct": item.get("taxEndPnlPct"),
                        "deltaVsTaxEndPnlPct": item.get("deltaVsTaxEndPnlPct"),
                        "sell": item.get("sell"),
                    }
                    for item in report.get("projects") or []
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
