#!/usr/bin/env python3
"""Recalculate SR-only strategy candidates from an existing matrix report.

This is intentionally result-level only:
- reads the existing strategy-test matrix JSON;
- filters/re-summarizes SR rows under the latest hard gates;
- does not replay chain data, rebuild samples, touch DBs, or send trades.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


PRIMARY_DATASET = "sr_chainstack_highres_strategy"
EVENT_MODEL = {
    "requiredForNextFullReplay": ["pool_state_change", "tax_tick", "heartbeat"],
    "poolStateChangeTypes": ["buy", "sell", "unknown_pool_event"],
    "taxTickMeaning": "tax changes are first-class trigger points even when token price is unchanged",
}
SETTLEMENT_MODEL = {
    "mode": "end_tax_1_only",
    "deprecatedSnapshots": ["1m", "3m", "5m", "10m"],
}
CRITICAL_FLAGS = {
    "no_fdv_cost_guard",
    "no_board_spent_guard",
    "low_sample_first_buy",
    "high_slippage",
    "high_latency",
    "tax_signal_risk",
}


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt(value: Any, places: int = 4) -> str:
    parsed = dec(value)
    if parsed is None:
        return "-"
    normalized = parsed.quantize(Decimal(1).scaleb(-places))
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def is_sr_dataset(name: Any) -> bool:
    return str(name or "").lower().startswith("sr_")


def observed_buys(item: dict[str, Any]) -> list[dict[str, Any]]:
    buys = item.get("buys")
    if isinstance(buys, list) and buys:
        return [row for row in buys if isinstance(row, dict)]
    first = item.get("firstBuy")
    return [first] if isinstance(first, dict) else []


def latest_gate_rejections(item: dict[str, Any]) -> list[str]:
    rejections: list[str] = []
    rule = item.get("rule") if isinstance(item.get("rule"), dict) else {}
    spent_threshold = dec(rule.get("spentThresholdV"))
    max_tax = dec(rule.get("maxTaxRate"))
    fdv_discount = dec(rule.get("fdvDiscount"))
    risk_flags = set(item.get("riskFlags") or [])

    if item.get("scenarioName") != "actual":
        rejections.append("not_actual_scenario")
    if item.get("suite") != "dry_run_candidates":
        rejections.append("not_dry_run_candidate_suite")
    if int(item.get("buyCount") or 0) <= 0:
        rejections.append("no_buy")
    if dec(item.get("finalPnlPct")) is None or dec(item.get("finalPnlPct")) <= 0:
        rejections.append("non_positive_final_pnl")
    if spent_threshold is None or spent_threshold < Decimal("50000"):
        rejections.append("missing_or_low_board_spent_guard")
    if max_tax is None or max_tax <= 0 or max_tax > Decimal("95"):
        rejections.append("missing_or_loose_tax_guard")
    if fdv_discount is None:
        rejections.append("missing_fdv_cost_guard")
    if risk_flags & CRITICAL_FLAGS:
        rejections.append("critical_risk_flags:" + ",".join(sorted(risk_flags & CRITICAL_FLAGS)))

    buys = observed_buys(item)
    if not buys:
        rejections.append("missing_buy_rows")
        return rejections

    for idx, buy in enumerate(buys, start=1):
        tax = dec(buy.get("tax_rate"))
        board = dec(buy.get("board_spent_v"))
        cost_rows = int(buy.get("cost_rows") or 0)
        whale_rows = int(buy.get("whale_rows") or 0)
        tax_fdv = dec(buy.get("entry_tax_fdv_wan_usd") or buy.get("signal_tax_fdv_wan_usd"))
        board_cost = dec(buy.get("board_cost_wan_usd"))

        if whale_rows < 20:
            rejections.append(f"buy{idx}_whale_rows_lt_20")
        if cost_rows < 5:
            rejections.append(f"buy{idx}_cost_rows_lt_5")
        if board is None or board < Decimal("50000"):
            rejections.append(f"buy{idx}_board_spent_lt_50000")
        if tax is None or tax <= 0 or tax > Decimal("95"):
            rejections.append(f"buy{idx}_tax_not_lte_95")
        if fdv_discount is not None:
            if tax_fdv is None or board_cost is None or board_cost <= 0:
                rejections.append(f"buy{idx}_missing_fdv_or_board_cost")
            elif tax_fdv > board_cost * fdv_discount:
                rejections.append(f"buy{idx}_fdv_above_board_cost")
    return rejections


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    first = item.get("firstBuy") if isinstance(item.get("firstBuy"), dict) else {}
    return {
        "dataset": item.get("dataset"),
        "suite": item.get("suite"),
        "ruleName": item.get("ruleName"),
        "scenarioName": item.get("scenarioName"),
        "buyCount": int(item.get("buyCount") or 0),
        "totalSpentV": item.get("totalSpentV"),
        "finalPnlV": item.get("finalPnlV"),
        "finalPnlPct": item.get("finalPnlPct"),
        "firstBuy": {
            "timestamp": first.get("entry_timestamp") or first.get("trigger_timestamp"),
            "taxRate": first.get("tax_rate"),
            "boardSpentV": first.get("board_spent_v"),
            "taxFdvWanUsd": first.get("entry_tax_fdv_wan_usd") or first.get("signal_tax_fdv_wan_usd"),
            "boardCostWanUsd": first.get("board_cost_wan_usd"),
            "costRows": first.get("cost_rows"),
            "whaleRows": first.get("whale_rows"),
            "costPosition": first.get("cost_position"),
            "vCostPosition": first.get("v_cost_position"),
        },
        "riskFlags": item.get("riskFlags") or [],
    }


def entry_cluster_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    first = item.get("firstBuy") if isinstance(item.get("firstBuy"), dict) else {}
    return (
        str(first.get("timestamp") or ""),
        str(first.get("taxRate") or ""),
        str(first.get("boardSpentV") or ""),
        str(first.get("taxFdvWanUsd") or ""),
    )


def build_report(matrix: dict[str, Any]) -> dict[str, Any]:
    results = [row for row in matrix.get("results") or [] if isinstance(row, dict) and is_sr_dataset(row.get("dataset"))]
    actual = [row for row in results if row.get("scenarioName") == "actual"]
    primary_actual = [row for row in actual if row.get("dataset") == PRIMARY_DATASET]
    validation_actual = [row for row in actual if row.get("dataset") != PRIMARY_DATASET]

    candidate_rows: list[dict[str, Any]] = []
    rejected_actual_rows: list[dict[str, Any]] = []
    for row in actual:
        rejections = latest_gate_rejections(row)
        if not rejections:
            candidate_rows.append(row)
        elif int(row.get("buyCount") or 0) > 0:
            payload = compact_item(row)
            payload["rejections"] = rejections
            rejected_actual_rows.append(payload)

    by_rule: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in candidate_rows:
        dataset = str(row.get("dataset") or "")
        by_rule[str(row.get("ruleName") or "")][dataset] = compact_item(row)

    primary_candidates = [compact_item(row) for row in candidate_rows if row.get("dataset") == PRIMARY_DATASET]
    primary_clusters: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in primary_candidates:
        key = entry_cluster_key(item)
        cluster = primary_clusters.setdefault(
            key,
            {
                "rules": [],
                "buyCount": item.get("buyCount"),
                "totalSpentV": item.get("totalSpentV"),
                "finalPnlV": item.get("finalPnlV"),
                "finalPnlPct": item.get("finalPnlPct"),
                "firstBuy": item.get("firstBuy"),
            },
        )
        cluster["rules"].append(item.get("ruleName"))

    controls = []
    for row in primary_actual:
        rule_name = str(row.get("ruleName") or "")
        if int(row.get("buyCount") or 0) <= 0:
            continue
        if row.get("suite") == "control" or rule_name.startswith("only_") or "no_fdv" in rule_name or "tax_only" in rule_name:
            payload = compact_item(row)
            payload["rejections"] = latest_gate_rejections(row)
            controls.append(payload)

    dataset_stats = matrix.get("datasetStats") if isinstance(matrix.get("datasetStats"), dict) else {}
    sr_dataset_stats = {name: stats for name, stats in dataset_stats.items() if is_sr_dataset(name)}

    return {
        "ok": True,
        "scope": "SR only result-level recalculation",
        "sourceMatrix": "data/backtests/strategy-test-matrix-20260507.json",
        "notRecomputed": [
            "chain replay",
            "sample extraction",
            "sell event timeline",
            "unknown pool event timeline",
            "tax_tick timeline",
            "heartbeat timeline",
            "token price path",
            "whale board aggregation",
            "ISC/TDS rows",
            "strategy-lab UI derived metrics",
            "synthetic scenario generation",
        ],
        "eventModel": EVENT_MODEL,
        "settlementModel": SETTLEMENT_MODEL,
        "currentExecutionLimits": [
            "The source matrix stores buy entries and final sample PnL; it does not reconstruct sell/tax_tick/unknown event trigger points.",
            "This run treats finalPnlPct/finalPnlV from the matrix as the end performance proxy.",
            "A full precision SR replay still requires rebuilding the event timeline from pool_state_change + tax_tick + heartbeat.",
        ],
        "latestGates": {
            "primaryDataset": PRIMARY_DATASET,
            "validationDatasets": sorted({row.get("dataset") for row in validation_actual}),
            "actualScenarioOnlyForCandidates": True,
            "minWhaleRows": 20,
            "minCostRows": 5,
            "minBoardSpentV": "50000",
            "maxTaxRate": "95",
            "requireBoardSpentGuard": True,
            "requireTaxGuard": True,
            "requireFdvCostGuard": True,
            "requirePositiveFinalPnl": True,
        },
        "counts": {
            "sourceResultCount": len(matrix.get("results") or []),
            "srResultRows": len(results),
            "srActualRows": len(actual),
            "primaryActualRows": len(primary_actual),
            "validationActualRows": len(validation_actual),
            "candidateRows": len(candidate_rows),
            "uniqueCandidateRules": len(by_rule),
            "primaryEntryClusters": len(primary_clusters),
        },
        "datasetStats": sr_dataset_stats,
        "candidateGroups": [
            {
                "ruleName": rule,
                "primary": datasets.get(PRIMARY_DATASET),
                "validation": {name: item for name, item in datasets.items() if name != PRIMARY_DATASET},
            }
            for rule, datasets in sorted(by_rule.items())
        ],
        "primaryCandidates": primary_candidates,
        "validationCandidates": [compact_item(row) for row in candidate_rows if row.get("dataset") != PRIMARY_DATASET],
        "primaryEntryClusters": sorted(
            primary_clusters.values(),
            key=lambda item: dec((item.get("firstBuy") or {}).get("timestamp")) or Decimal("0"),
        ),
        "primaryControlsNotCandidates": sorted(controls, key=lambda item: str(item.get("ruleName"))),
        "rejectedActualTriggeredSample": sorted(
            rejected_actual_rows,
            key=lambda item: (len(item.get("rejections") or []), -(dec(item.get("finalPnlPct")) or Decimal("0"))),
        )[:80],
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    lines.append("# SR 最新门槛结果级重筛")
    lines.append("")
    lines.append("本报告只读取既有 `strategy-test-matrix-20260507.json` 中的 SR result rows，未重新抓链、未重放 tx、未重建样本、未包含 ISC/TDS。")
    lines.append("")
    lines.append("> 本轮是结果级重筛，不是完整事件级 replay。源矩阵没有重建 sell、unknown pool event、tax_tick 和 heartbeat 时间线。")
    lines.append("")
    lines.append("## 口径")
    gates = report["latestGates"]
    lines.append(f"- 主样本：`{gates['primaryDataset']}`。")
    lines.append(f"- 交叉验证样本：`{', '.join(gates['validationDatasets']) or '-'}`。")
    lines.append("- 候选只看 `actual` 场景；压力/合成/价格路径场景不进入候选排序。")
    lines.append("- 硬门槛：榜单人数 `>=20`、成本样本 `>=5`、榜单累计投入 `>=50,000 V`、税率 `0-95%`、规则本身必须包含榜单 V 门槛、税率门槛和 FDV 成本保护。")
    lines.append("- 完整事件模型应为 `pool_state_change + tax_tick + heartbeat`，其中 `pool_state_change` 覆盖 buy、sell、unknown pool event。")
    lines.append("- 收益只看 tax 降到 `1%` 的 end 表现；`1m / 3m / 5m / 10m` 不再作为默认指标。")
    lines.append("- 本结果级重筛使用矩阵里的 `finalPnlPct / finalPnlV` 作为 end 表现代理；仍然只是 realtime dry-run 候选，不是自动买入开关。")
    lines.append("")
    lines.append("## 当前执行限制")
    for item in report["currentExecutionLimits"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 不重新计算的数据")
    for item in report["notRecomputed"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 数据规模")
    counts = report["counts"]
    lines.append(table_line(["source results", "SR rows", "SR actual rows", "primary actual", "validation actual", "candidate rows", "unique rules", "primary entry clusters"]))
    lines.append(table_line(["---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]))
    lines.append(table_line([counts["sourceResultCount"], counts["srResultRows"], counts["srActualRows"], counts["primaryActualRows"], counts["validationActualRows"], counts["candidateRows"], counts["uniqueCandidateRules"], counts["primaryEntryClusters"]]))
    lines.append("")
    lines.append("## 主样本实际入场簇")
    lines.append(table_line(["入场簇", "覆盖规则", "买入次数", "投入", "end收益", "首买"]))
    lines.append(table_line(["---", "---", "---:", "---:", "---:", "---"]))
    for index, item in enumerate(report["primaryEntryClusters"], start=1):
        lines.append(
            table_line(
                [
                    index,
                    ", ".join(item.get("rules") or []),
                    item.get("buyCount"),
                    item.get("totalSpentV"),
                    f"{fmt(item.get('finalPnlPct'))}%",
                    first_buy_text({"firstBuy": item.get("firstBuy")}),
                ]
            )
        )
    lines.append("")
    lines.append("## 候选规则")
    lines.append(table_line(["Rule", "主样本买入", "主样本end收益", "主样本首买", "验证样本买入", "验证样本end收益", "验证样本首买"]))
    lines.append(table_line(["---", "---:", "---:", "---", "---:", "---:", "---"]))
    for group in report["candidateGroups"]:
        primary = group.get("primary") or {}
        validation_items = list((group.get("validation") or {}).values())
        validation = validation_items[0] if validation_items else {}
        lines.append(
            table_line(
                [
                    group["ruleName"],
                    primary.get("buyCount", "-"),
                    f"{fmt(primary.get('finalPnlPct'))}%",
                    first_buy_text(primary),
                    validation.get("buyCount", "-"),
                    f"{fmt(validation.get('finalPnlPct'))}%" if validation else "-",
                    first_buy_text(validation) if validation else "-",
                ]
            )
        )
    if not report["candidateGroups"]:
        lines.append("- None.")
    lines.append("")
    lines.append("## 关键解释")
    lines.append("- 旧口径的 `14` 个候选不应理解为 14 个独立策略；它主要是 7 条规则乘以 2 个 SR 采样数据集。")
    lines.append("- 高频 SR 主样本显示 `50k tax<=93/94/95 fdv` 的首买更早，历史收益更高；但它仍是单个历史项目结果，只能进入 would-buy 观察。")
    lines.append("- 144-sample 验证样本由于采样更粗，所有候选首买都延后到 `tax=90 / boardSpentV≈164k`，只能说明低频采样会错过早期触发点，不能当作独立 Alpha 证据。")
    lines.append("- 真正下一版 SR replay 必须补入 sell、unknown pool event 和 tax_tick；否则触发时间仍可能系统性延后。")
    lines.append("")
    lines.append("## 主样本对照项，不作为候选")
    lines.append(table_line(["Rule", "Buys", "End PnL", "First buy", "Reject reason"]))
    lines.append(table_line(["---", "---:", "---:", "---", "---"]))
    for item in report["primaryControlsNotCandidates"][:30]:
        lines.append(table_line([item.get("ruleName"), item.get("buyCount"), f"{fmt(item.get('finalPnlPct'))}%", first_buy_text(item), ", ".join(item.get("rejections") or [])]))
    if not report["primaryControlsNotCandidates"]:
        lines.append("- None.")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def first_buy_text(item: dict[str, Any]) -> str:
    first = item.get("firstBuy") if isinstance(item.get("firstBuy"), dict) else {}
    if not first:
        return "-"
    return (
        f"tax {first.get('taxRate')}, "
        f"board {fmt(first.get('boardSpentV'), 0)}V, "
        f"FDV {fmt(first.get('taxFdvWanUsd'), 2)}万, "
        f"cost {fmt(first.get('boardCostWanUsd'), 2)}万, "
        f"costPos {first.get('costPosition')}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SR-only result-level recalculation from strategy matrix JSON.")
    parser.add_argument("--input-json", default="data/backtests/strategy-test-matrix-20260507.json")
    parser.add_argument("--output-json", default="data/backtests/sr-only-latest-gates-20260510.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-sr-only-latest-gates-2026-05-10.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matrix = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    report = build_report(matrix)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(json.dumps({"outputJson": args.output_json, "outputMd": args.output_md, "counts": report["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
