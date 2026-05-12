#!/usr/bin/env python3
"""Backtest a launch sell trigger from existing SR/ISC event-level samples.

Read-only boundaries:
- reads local replay reports, sample JSONL, and parsed buy-event JSONL files;
- writes local JSON/Markdown reports only;
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
class SellTriggerConfig:
    name: str = "tax30_large_buy_5ku_profit50"
    max_tax_rate: Decimal = Decimal("30")
    min_large_buy_usd: Decimal = Decimal("5000")
    min_profit_pct: Decimal = Decimal("50")


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
            if spent is not None:
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


def find_sample_index_at_or_after(samples: list[dict[str, Any]], ts: int, start_index: int) -> int | None:
    index = max(0, int(start_index))
    while index < len(samples):
        if int(samples[index].get("simTimestamp") or 0) >= ts:
            return index
        index += 1
    return None


def find_sell_trigger(
    *,
    samples: list[dict[str, Any]],
    buy_events: list[dict[str, Any]],
    buy_result: dict[str, Any],
    config: SellTriggerConfig,
) -> dict[str, Any] | None:
    buys = list(buy_result.get("buys") or [])
    spent_v = parse_decimal(buy_result.get("totalSpentV")) or Decimal("0")
    if not buys or spent_v <= 0:
        return None

    event_index = 0
    sample_index = 0
    candidate_count = 0
    best_candidate: dict[str, Any] | None = None
    largest_tax30_buy: dict[str, Any] | None = None
    first_any_size_profit50: dict[str, Any] | None = None
    first_tax30_index = next(
        (
            index
            for index, row in enumerate(samples)
            if (parse_decimal(row.get("buyTaxRate")) is not None and parse_decimal(row.get("buyTaxRate")) <= config.max_tax_rate)
        ),
        None,
    )
    sample_index = int(first_tax30_index or 0)

    while event_index < len(buy_events):
        event = buy_events[event_index]
        event_index += 1
        event_ts = int(event.get("timestamp") or 0)
        if first_tax30_index is not None and event_ts < int(samples[first_tax30_index].get("simTimestamp") or 0):
            continue

        event_spent = parse_decimal(event.get("spentV_est")) or Decimal("0")
        virtual_price_usd = parse_decimal(event.get("virtualPriceUSD")) or Decimal("0")
        event_spent_usd = event_spent * virtual_price_usd

        matched_index = find_sample_index_at_or_after(samples, event_ts, sample_index)
        if matched_index is None:
            continue
        sample_index = matched_index
        sample = samples[matched_index]
        tax_rate = parse_decimal(sample.get("buyTaxRate"))
        if tax_rate is None or tax_rate > config.max_tax_rate:
            continue

        spot_fdv = spot_fdv_wan(sample)
        if spot_fdv is None or spot_fdv <= 0:
            continue

        candidate_count += 1
        current_value = value_at_spot(buys, spot_fdv)
        current_pnl_pct = pnl_pct(current_value, spent_v)
        candidate = {
            "index": matched_index,
            "timestamp": int(sample.get("simTimestamp") or event_ts),
            "timestampCst": cst_text(sample.get("simTimestamp") or event_ts),
            "taxRate": fmt_decimal(tax_rate, 6),
            "eventTxHash": event.get("txHash"),
            "eventBuyer": event.get("buyer"),
            "eventSpentV": fmt_decimal(event_spent, 6),
            "eventSpentActualV": fmt_decimal(parse_decimal(event.get("spentV_actual")), 6),
            "eventSpentUsd": fmt_decimal(event_spent_usd, 6),
            "eventVirtualPriceUsd": fmt_decimal(virtual_price_usd, 8),
            "spotFdvWanUsd": fmt_decimal(spot_fdv, 6),
            "taxFdvWanUsd": fmt_decimal(parse_decimal(sample.get("estimatedFdvWanUsdWithTax")), 6),
            "valueV": fmt_decimal(current_value, 6),
            "pnlV": fmt_decimal(current_value - spent_v, 6),
            "pnlPct": fmt_decimal(current_pnl_pct, 4),
            "triggerTypes": sample.get("triggerTypes") or [],
        }
        if largest_tax30_buy is None or event_spent_usd > (parse_decimal(largest_tax30_buy.get("eventSpentUsd")) or Decimal("0")):
            largest_tax30_buy = candidate
        if first_any_size_profit50 is None and current_pnl_pct >= config.min_profit_pct:
            first_any_size_profit50 = candidate
        if event_spent_usd < config.min_large_buy_usd:
            continue

        if best_candidate is None or current_pnl_pct > (parse_decimal(best_candidate.get("pnlPct")) or Decimal("-999999")):
            best_candidate = candidate
        if current_pnl_pct >= config.min_profit_pct:
            candidate["reason"] = "tax<=30_and_large_buy>=5k_and_profit>=50"
            candidate["largeBuyCandidateCountBeforeSell"] = candidate_count
            return candidate

    if best_candidate is not None:
        return {
            "noTrigger": True,
            "reason": "no_candidate_reached_profit_threshold",
            "largeBuyCandidateCount": candidate_count,
            "bestCandidate": best_candidate,
            "largestTax30Buy": largest_tax30_buy,
            "firstAnySizeProfit50": first_any_size_profit50,
        }
    return {
        "noTrigger": True,
        "reason": "no_tax30_large_buy_candidate",
        "largeBuyCandidateCount": 0,
        "bestCandidate": None,
        "largestTax30Buy": largest_tax30_buy,
        "firstAnySizeProfit50": first_any_size_profit50,
    }


def evaluate_project(
    *,
    report_path: Path,
    rule_name: str,
    buy_config: DynamicBuyConfig,
    sell_config: SellTriggerConfig,
) -> dict[str, Any]:
    source_report = load_json(report_path)
    samples_path = Path(str(source_report.get("samplesPath") or ""))
    events_path = Path(str(source_report.get("jsonlPath") or ""))
    samples = load_samples(samples_path)
    buy_events = load_buy_events(events_path)
    rule = next(item for item in rules() if item.name == rule_name)
    buy_result = evaluate_dynamic(samples, rule, buy_config)
    sell = find_sell_trigger(samples=samples, buy_events=buy_events, buy_result=buy_result, config=sell_config)

    spent_v = parse_decimal(buy_result.get("totalSpentV")) or Decimal("0")
    end_value = parse_decimal(buy_result.get("finalValueV")) or Decimal("0")
    sell_value = parse_decimal((sell or {}).get("valueV")) if sell and not sell.get("noTrigger") else None
    if sell_value is None:
        realized_value = end_value
        realized_mode = "hold_to_tax_end"
    else:
        realized_value = sell_value
        realized_mode = "sell_trigger"
    realized_pnl = realized_value - spent_v
    realized_pnl_pct = pnl_pct(realized_value, spent_v)
    end_pnl_pct = parse_decimal(buy_result.get("finalPnlPct")) or Decimal("0")

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
        "sell": sell,
        "realizedMode": realized_mode,
        "realizedValueV": fmt_decimal(realized_value, 6),
        "realizedPnlV": fmt_decimal(realized_pnl, 6),
        "realizedPnlPct": fmt_decimal(realized_pnl_pct, 4),
        "taxEndValueV": buy_result.get("finalValueV"),
        "taxEndPnlV": buy_result.get("finalPnlV"),
        "taxEndPnlPct": buy_result.get("finalPnlPct"),
        "deltaVsTaxEndPnlPct": fmt_decimal(realized_pnl_pct - end_pnl_pct, 4),
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Tax<=30 Large-Buy Sell Trigger Backtest",
        "",
        "本报告只读取本地 SR/ISC event-level replay 产物，未重新抓链、未写生产库、未发送交易。",
        "",
        "## 策略口径",
        "",
        "- 买入：沿用当前动态买入策略 `dynamic_25v_dip20_after1_flat10_no_cap`。",
        "- 卖出：当税率 `<=30%` 后，出现单笔 parsed buy `spentV_est * virtualPriceUSD >= 5,000 USD`，并且按当前 spot FDV 计算我方持仓收益率 `>=50%`，立即全仓卖出。",
        "- 收益计算：买入成本使用入场时 `含税估算 FDV`；卖出/持有估值使用当前或 tax-end 的 `spot FDV`，与既有 end-only 回测口径一致。",
        "",
        "## 结果概览",
        "",
        table_line(["项目", "买入规则", "买入", "投入V", "卖出触发", "卖出/持有收益", "Tax-end收益", "差异"]),
        table_line(["---", "---", "---:", "---:", "---", "---:", "---:", "---:"]),
    ]
    for item in report["projects"]:
        sell = item.get("sell") or {}
        if sell.get("noTrigger"):
            sell_text = f"未触发（{sell.get('reason')}）"
        else:
            sell_text = f"tax {sell.get('taxRate')} / {sell.get('timestampCst')} / ${sell.get('eventSpentUsd')}"
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
        lines.append(f"- 样本：`{item.get('sampleCount')}`；parsed buy events：`{item.get('parsedBuyEventCount')}`。")
        lines.append(f"- 买入规则：`{item.get('buyRule')}`；买入 `{item.get('buyCount')}` 次，投入 `{item.get('totalSpentV')} V`。")
        lines.append(f"- 我方加权成本 FDV：`{item.get('ownWeightedCostWanUsd')}` 万 USD。")
        sell = item.get("sell") or {}
        if sell.get("noTrigger"):
            lines.append(f"- 卖出：未触发，原因 `{sell.get('reason')}`。")
            largest = sell.get("largestTax30Buy")
            if largest:
                lines.append(
                    f"- tax<=30 后最大买入：约 `${largest.get('eventSpentUsd')}`（`{largest.get('eventSpentV')} V`），"
                    f"收益 `{largest.get('pnlPct')}%`，时间 `{largest.get('timestampCst')}`。"
                )
            best = sell.get("bestCandidate")
            if best:
                lines.append(
                    f"- 最接近候选：tax `{best.get('taxRate')}`，单笔 `{best.get('eventSpentV')} V`，"
                    f"约 `${best.get('eventSpentUsd')}`，收益 `{best.get('pnlPct')}%`，时间 `{best.get('timestampCst')}`。"
                )
            any_profit = sell.get("firstAnySizeProfit50")
            if any_profit:
                lines.append(
                    f"- 敏感性：如果不要求 5KU，只要求 tax<=30 后有买入且收益>=50%，"
                    f"首次会在 `{any_profit.get('timestampCst')}` 触发，单笔约 `${any_profit.get('eventSpentUsd')}`，"
                    f"收益 `{any_profit.get('pnlPct')}%`。"
                )
        else:
            lines.append(
                f"- 卖出触发：tax `{sell.get('taxRate')}`，时间 `{sell.get('timestampCst')}`，"
                f"单笔买入约 `${sell.get('eventSpentUsd')}`（`{sell.get('eventSpentV')} V`），收益 `{sell.get('pnlPct')}%`。"
            )
            lines.append(f"- 触发 tx：`{sell.get('eventTxHash')}`；buyer：`{sell.get('eventBuyer')}`。")
            lines.append(f"- 触发时 spot FDV：`{sell.get('spotFdvWanUsd')}` 万 USD；含税 FDV：`{sell.get('taxFdvWanUsd')}` 万 USD。")
        lines.append(f"- 策略结果：`{item.get('realizedPnlV')} V / {item.get('realizedPnlPct')}%`。")
        lines.append(f"- 持有到 tax-end：`{item.get('taxEndPnlV')} V / {item.get('taxEndPnlPct')}%`。")
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
    sell_config = SellTriggerConfig(
        max_tax_rate=Decimal(str(args.sell_max_tax)),
        min_large_buy_usd=Decimal(str(args.large_buy_usd)),
        min_profit_pct=Decimal(str(args.profit_pct)),
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
        "scope": "SR and ISC sell-trigger backtest from existing event-level samples",
        "strategyDefinition": {
            "buyStrategy": buy_config.name,
            "sellWhen": [
                f"buyTaxRate <= {fmt_decimal(sell_config.max_tax_rate)}",
                f"single parsed buy spentV_est * virtualPriceUSD >= {fmt_decimal(sell_config.min_large_buy_usd)} USD",
                f"current spot-FDV mark-to-market PnL >= {fmt_decimal(sell_config.min_profit_pct)}%",
            ],
            "settlement": "sell trigger spot FDV, otherwise tax-end spot FDV",
        },
        "projects": projects,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest tax<=30 large-buy sell trigger for SR and ISC.")
    parser.add_argument("--sr-report", default="data/backtests/sr-event-level-replay-20260510T073102Z.json")
    parser.add_argument("--isc-report", default="data/backtests/isc-event-level-replay-20260510.json")
    parser.add_argument("--sr-rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--isc-rule", default="gate_5k_tax89_fdv_one_per_tax")
    parser.add_argument("--sell-max-tax", default="30")
    parser.add_argument("--large-buy-usd", default="5000")
    parser.add_argument("--profit-pct", default="50")
    parser.add_argument("--output-json", default="data/backtests/sell-trigger-tax30-large5ku-profit50-20260511.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-sell-trigger-tax30-large5ku-profit50-2026-05-11.md")
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
