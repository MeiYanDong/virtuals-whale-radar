#!/usr/bin/env python3
"""Backtest launch-window buy strategies from native replay sample JSONL files."""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


WAN = Decimal("10000")


@dataclass(frozen=True)
class StrategyParams:
    spent_threshold_v: Decimal
    max_tax_rate: Decimal | None
    fdv_discount: Decimal
    cooldown_sec: int
    burst_limit: int
    burst_window_sec: int
    burst_cooldown_sec: int
    buy_size_v: Decimal
    max_project_spend_v: Decimal
    min_cost_rows: int
    min_whale_rows: int

    def key(self) -> str:
        tax = "none" if self.max_tax_rate is None else fmt_decimal(self.max_tax_rate)
        return "|".join(
            [
                f"spent>={fmt_decimal(self.spent_threshold_v)}",
                f"tax<={tax}",
                f"fdv<=cost*{fmt_decimal(self.fdv_discount)}",
                f"cooldown={self.cooldown_sec}",
                f"burst={self.burst_limit}/{self.burst_window_sec}/{self.burst_cooldown_sec}",
                f"maxSpend={fmt_decimal(self.max_project_spend_v)}",
                f"minCostRows={self.min_cost_rows}",
                f"minWhaleRows={self.min_whale_rows}",
            ]
        )


@dataclass
class Buy:
    index: int
    sim_timestamp: int
    tax_rate: str
    entry_tax_fdv_wan_usd: str
    entry_spot_fdv_wan_usd: str | None
    board_spent_v: str
    board_cost_wan_usd: str
    cost_position: str
    v_cost_position: str
    reason: str


def parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def fmt_decimal(value: Decimal | None, places: int | None = None) -> str | None:
    if value is None:
        return None
    if places is not None:
        quant = Decimal(1).scaleb(-places)
        value = value.quantize(quant)
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def parse_decimal_list(raw: str) -> list[Decimal]:
    values: list[Decimal] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parsed = parse_decimal(item)
        if parsed is None:
            raise ValueError(f"invalid decimal value: {item}")
        values.append(parsed)
    if not values:
        raise ValueError("decimal list cannot be empty")
    return values


def parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    if not values:
        raise ValueError("int list cannot be empty")
    return values


def parse_tax_list(raw: str) -> list[Decimal | None]:
    values: list[Decimal | None] = []
    for item in raw.split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item in {"none", "any", "-"}:
            values.append(None)
            continue
        parsed = parse_decimal(item)
        if parsed is None:
            raise ValueError(f"invalid tax value: {item}")
        values.append(parsed)
    if not values:
        raise ValueError("tax list cannot be empty")
    return values


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda row: int(row.get("simTimestamp") or 0))
    return rows


def spot_fdv_wan(row: dict[str, Any]) -> Decimal | None:
    live_fdv = parse_decimal(row.get("liveFdvUsd"))
    if live_fdv is None:
        return None
    return live_fdv / WAN


def future_values(samples: list[dict[str, Any]], start_index: int) -> list[Decimal]:
    values: list[Decimal] = []
    for row in samples[start_index:]:
        value = spot_fdv_wan(row)
        if value is not None and value > 0:
            values.append(value)
    return values


def should_buy(row: dict[str, Any], params: StrategyParams) -> tuple[bool, str]:
    if row.get("projectStatus") not in {None, "live"}:
        return False, "not_live"
    tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
    board_cost = parse_decimal(row.get("boardCostWanUsd"))
    board_spent = parse_decimal(row.get("boardSpentV")) or Decimal(0)
    tax_rate = parse_decimal(row.get("buyTaxRate"))
    cost_rows = int(row.get("costRows") or 0)
    whale_rows = int(row.get("whaleRows") or 0)

    if tax_fdv is None or tax_fdv <= 0:
        return False, "missing_tax_fdv"
    if board_cost is None or board_cost <= 0:
        return False, "missing_board_cost"
    if board_spent < params.spent_threshold_v:
        return False, "spent_threshold"
    if cost_rows < params.min_cost_rows:
        return False, "min_cost_rows"
    if whale_rows < params.min_whale_rows:
        return False, "min_whale_rows"
    if params.max_tax_rate is not None and (tax_rate is None or tax_rate > params.max_tax_rate):
        return False, "tax_threshold"
    if tax_fdv > board_cost * params.fdv_discount:
        return False, "fdv_not_below_cost"
    return True, "signal"


def evaluate(samples: list[dict[str, Any]], params: StrategyParams, *, label: str) -> dict[str, Any]:
    buys: list[Buy] = []
    buy_timestamps: list[int] = []
    next_allowed_ts = -1
    total_spent = Decimal(0)
    skip_reasons: dict[str, int] = {}

    for index, row in enumerate(samples):
        ts = int(row.get("simTimestamp") or 0)
        ok, reason = should_buy(row, params)
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        if ts < next_allowed_ts:
            skip_reasons["cooldown"] = skip_reasons.get("cooldown", 0) + 1
            continue
        if total_spent + params.buy_size_v > params.max_project_spend_v:
            skip_reasons["max_project_spend"] = skip_reasons.get("max_project_spend", 0) + 1
            continue

        tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        board_cost = parse_decimal(row.get("boardCostWanUsd"))
        entry_spot = spot_fdv_wan(row)
        if tax_fdv is None or board_cost is None:
            continue

        buys.append(
            Buy(
                index=index,
                sim_timestamp=ts,
                tax_rate=str(row.get("buyTaxRate")),
                entry_tax_fdv_wan_usd=fmt_decimal(tax_fdv, 6) or "0",
                entry_spot_fdv_wan_usd=fmt_decimal(entry_spot, 6) if entry_spot is not None else None,
                board_spent_v=fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal(0), 3) or "0",
                board_cost_wan_usd=fmt_decimal(board_cost, 6) or "0",
                cost_position=str(row.get("costPosition") or "-"),
                v_cost_position=str(row.get("vCostPosition") or "-"),
                reason=reason,
            )
        )
        buy_timestamps.append(ts)
        total_spent += params.buy_size_v

        recent = [item for item in buy_timestamps if ts - item <= params.burst_window_sec]
        if params.burst_limit > 0 and len(recent) >= params.burst_limit:
            next_allowed_ts = ts + params.burst_cooldown_sec
        else:
            next_allowed_ts = ts + params.cooldown_sec

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_tax_fdv = parse_decimal(samples[-1].get("estimatedFdvWanUsdWithTax")) if samples else None
    final_value = Decimal(0)
    final_tax_adjusted_value = Decimal(0)
    max_value = Decimal(0)
    min_value: Decimal | None = None
    buy_returns: list[Decimal] = []
    buy_drawdowns: list[Decimal] = []

    for buy in buys:
        entry = parse_decimal(buy.entry_tax_fdv_wan_usd)
        if entry is None or entry <= 0:
            continue
        if final_spot is not None:
            value = params.buy_size_v * final_spot / entry
            final_value += value
            buy_returns.append(value / params.buy_size_v - 1)
        if final_tax_fdv is not None:
            final_tax_adjusted_value += params.buy_size_v * final_tax_fdv / entry
        future = future_values(samples, buy.index)
        if future:
            high_value = params.buy_size_v * max(future) / entry
            low_value = params.buy_size_v * min(future) / entry
            max_value += high_value
            min_value = low_value if min_value is None else min(min_value, low_value)
            buy_drawdowns.append(low_value / params.buy_size_v - 1)

    final_pnl = final_value - total_spent
    final_pnl_pct = (final_pnl / total_spent * 100) if total_spent > 0 else Decimal(0)
    final_tax_adjusted_pnl = final_tax_adjusted_value - total_spent
    final_tax_adjusted_pnl_pct = (
        final_tax_adjusted_pnl / total_spent * 100 if total_spent > 0 else Decimal(0)
    )
    max_runup_pct = (max_value / total_spent - 1) * 100 if total_spent > 0 else Decimal(0)
    worst_drawdown_pct = (
        (min_value / params.buy_size_v - 1) * 100 if min_value is not None else Decimal(0)
    )
    avg_buy_return_pct = (
        Decimal(str(statistics.mean(float(item * 100) for item in buy_returns)))
        if buy_returns
        else Decimal(0)
    )

    score = final_pnl_pct + (max_runup_pct * Decimal("0.15")) + min(worst_drawdown_pct, Decimal(0)) * Decimal("0.5")
    score -= Decimal(len(buys)) * Decimal("0.25")

    return {
        "label": label,
        "params": serialize_params(params),
        "paramKey": params.key(),
        "sampleCount": len(samples),
        "firstTimestamp": samples[0].get("simTimestamp") if samples else None,
        "lastTimestamp": samples[-1].get("simTimestamp") if samples else None,
        "buyCount": len(buys),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "finalTaxAdjustedValueV": fmt_decimal(final_tax_adjusted_value, 6),
        "finalTaxAdjustedPnlPct": fmt_decimal(final_tax_adjusted_pnl_pct, 4),
        "maxRunupPct": fmt_decimal(max_runup_pct, 4),
        "worstDrawdownPct": fmt_decimal(worst_drawdown_pct, 4),
        "avgBuyReturnPct": fmt_decimal(avg_buy_return_pct, 4),
        "score": fmt_decimal(score, 4),
        "finalSpotFdvWanUsd": fmt_decimal(final_spot, 6) if final_spot is not None else None,
        "finalTaxFdvWanUsd": fmt_decimal(final_tax_fdv, 6) if final_tax_fdv is not None else None,
        "skipReasons": skip_reasons,
        "buys": [asdict(item) for item in buys],
    }


def serialize_params(params: StrategyParams) -> dict[str, Any]:
    return {
        "spentThresholdV": fmt_decimal(params.spent_threshold_v),
        "maxTaxRate": fmt_decimal(params.max_tax_rate) if params.max_tax_rate is not None else None,
        "fdvDiscount": fmt_decimal(params.fdv_discount),
        "cooldownSec": params.cooldown_sec,
        "burstLimit": params.burst_limit,
        "burstWindowSec": params.burst_window_sec,
        "burstCooldownSec": params.burst_cooldown_sec,
        "buySizeV": fmt_decimal(params.buy_size_v),
        "maxProjectSpendV": fmt_decimal(params.max_project_spend_v),
        "minCostRows": params.min_cost_rows,
        "minWhaleRows": params.min_whale_rows,
    }


def build_grid(args: argparse.Namespace) -> list[StrategyParams]:
    spent_thresholds = parse_decimal_list(args.spent_thresholds)
    tax_thresholds = parse_tax_list(args.tax_thresholds)
    fdv_discounts = parse_decimal_list(args.fdv_discounts)
    cooldowns = parse_int_list(args.cooldowns_sec)
    burst_limits = parse_int_list(args.burst_limits)
    burst_windows = parse_int_list(args.burst_windows_sec)
    burst_cooldowns = parse_int_list(args.burst_cooldowns_sec)
    max_spends = parse_decimal_list(args.max_project_spends_v)
    buy_size = parse_decimal(args.buy_size_v)
    if buy_size is None or buy_size <= 0:
        raise ValueError("buy size must be positive")

    grid: list[StrategyParams] = []
    for values in itertools.product(
        spent_thresholds,
        tax_thresholds,
        fdv_discounts,
        cooldowns,
        burst_limits,
        burst_windows,
        burst_cooldowns,
        max_spends,
    ):
        spent, tax, discount, cooldown, burst_limit, burst_window, burst_cooldown, max_spend = values
        if max_spend < buy_size:
            continue
        grid.append(
            StrategyParams(
                spent_threshold_v=spent,
                max_tax_rate=tax,
                fdv_discount=discount,
                cooldown_sec=cooldown,
                burst_limit=burst_limit,
                burst_window_sec=burst_window,
                burst_cooldown_sec=burst_cooldown,
                buy_size_v=buy_size,
                max_project_spend_v=max_spend,
                min_cost_rows=args.min_cost_rows,
                min_whale_rows=args.min_whale_rows,
            )
        )
    return grid


def sort_key(result: dict[str, Any], field: str) -> float:
    if field == "buyCount":
        return float(result.get("buyCount") or 0)
    value = result.get(field)
    if value is None:
        return -math.inf
    try:
        return float(value)
    except (TypeError, ValueError):
        return -math.inf


def print_top(results: list[dict[str, Any]], *, field: str, limit: int, title: str) -> None:
    triggered = [item for item in results if int(item.get("buyCount") or 0) > 0]
    ranked = sorted(triggered, key=lambda item: sort_key(item, field), reverse=True)[:limit]
    print(f"\n## {title}")
    for index, item in enumerate(ranked, start=1):
        params = item["params"]
        print(
            json.dumps(
                {
                    "rank": index,
                    "label": item["label"],
                    "buyCount": item["buyCount"],
                    "totalSpentV": item["totalSpentV"],
                    "finalPnlV": item["finalPnlV"],
                    "finalPnlPct": item["finalPnlPct"],
                    "maxRunupPct": item["maxRunupPct"],
                    "worstDrawdownPct": item["worstDrawdownPct"],
                    "score": item["score"],
                    "spentThresholdV": params["spentThresholdV"],
                    "maxTaxRate": params["maxTaxRate"],
                    "fdvDiscount": params["fdvDiscount"],
                    "cooldownSec": params["cooldownSec"],
                    "burstLimit": params["burstLimit"],
                    "maxProjectSpendV": params["maxProjectSpendV"],
                    "firstBuy": item["buys"][0] if item.get("buys") else None,
                },
                ensure_ascii=False,
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest launch-window buy strategies from replay samples.")
    parser.add_argument("--samples", nargs="+", required=True, help="One or more replay *-samples.jsonl files.")
    parser.add_argument("--output", default="data/backtests/launch-strategy-backtest.json")
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--spent-thresholds", default="50000,75000,100000,150000")
    parser.add_argument("--tax-thresholds", default="98,95,92,90,85,80")
    parser.add_argument("--fdv-discounts", default="1,0.98,0.95,0.9")
    parser.add_argument("--cooldowns-sec", default="60,120")
    parser.add_argument("--burst-limits", default="0,2,3")
    parser.add_argument("--burst-windows-sec", default="120")
    parser.add_argument("--burst-cooldowns-sec", default="600")
    parser.add_argument("--buy-size-v", default="50")
    parser.add_argument("--max-project-spends-v", default="300,500,1000")
    parser.add_argument("--min-cost-rows", type=int, default=10)
    parser.add_argument("--min-whale-rows", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    grid = build_grid(args)
    datasets: list[tuple[str, list[dict[str, Any]]]] = []
    for raw_path in args.samples:
        path = Path(raw_path)
        label = path.name.removesuffix("-samples.jsonl")
        datasets.append((label, load_samples(path)))

    results: list[dict[str, Any]] = []
    for label, samples in datasets:
        for params in grid:
            results.append(evaluate(samples, params, label=label))

    report = {
        "samples": [path for path in args.samples],
        "strategyCount": len(grid),
        "resultCount": len(results),
        "assumptions": {
            "signalFdv": "estimatedFdvWanUsdWithTax",
            "entryCost": "tax-adjusted FDV at buy sample",
            "markToMarket": "liveFdvUsd / 10000 at future samples",
            "tradeSize": f"{args.buy_size_v} VIRTUAL per simulated buy",
            "productionDbTouched": False,
        },
        "results": results,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    triggered = sum(1 for item in results if int(item.get("buyCount") or 0) > 0)
    print(
        json.dumps(
            {
                "output": str(output),
                "datasets": len(datasets),
                "strategyCount": len(grid),
                "resultCount": len(results),
                "triggeredResults": triggered,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print_top(results, field="finalPnlV", limit=args.top, title="Top by finalPnlV")
    print_top(results, field="score", limit=args.top, title="Top by risk-adjusted score")
    print_top(results, field="finalPnlPct", limit=args.top, title="Top by finalPnlPct")


if __name__ == "__main__":
    main()
