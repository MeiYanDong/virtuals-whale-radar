#!/usr/bin/env python3
"""SR launch strategy gradient and scenario stress suite.

This script is intentionally read-only. It consumes native replay sample JSONL
files and writes JSON/Markdown reports for strategy review.
"""

from __future__ import annotations

import argparse
import bisect
import json
import random
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal
from copy import deepcopy
from pathlib import Path
from typing import Any

from backtest_launch_strategy import StrategyParams, fmt_decimal, load_samples, parse_decimal, spot_fdv_wan


WAN = Decimal("10000")


@dataclass(frozen=True)
class Scenario:
    name: str
    sample_every_sec: int = 0
    decision_delay_sec: int = 0
    entry_slippage_pct: Decimal = Decimal("0")
    signal_fdv_scale: Decimal = Decimal("1")
    board_cost_scale: Decimal = Decimal("1")
    board_spent_scale: Decimal = Decimal("1")
    tax_offset: Decimal = Decimal("0")


@dataclass(frozen=True)
class BuyEvent:
    index: int
    sim_timestamp: int
    signal_timestamp: int
    tax_rate: str | None
    entry_tax_fdv_wan_usd: str
    signal_tax_fdv_wan_usd: str | None
    entry_spot_fdv_wan_usd: str | None
    board_spent_v: str | None
    board_cost_wan_usd: str | None
    cost_position: str
    v_cost_position: str


def d(value: str | int | float) -> Decimal:
    parsed = parse_decimal(value)
    if parsed is None:
        raise ValueError(f"invalid decimal: {value}")
    return parsed


def make_params(
    *,
    spent: str | int,
    tax: str | int | None,
    discount: str = "1",
    cooldown: int = 60,
    burst_limit: int = 2,
    burst_window: int = 120,
    burst_cooldown: int = 600,
    max_spend: str | int = 300,
    min_rows: int = 10,
) -> StrategyParams:
    return StrategyParams(
        spent_threshold_v=d(spent),
        max_tax_rate=d(tax) if tax is not None else None,
        fdv_discount=d(discount),
        cooldown_sec=cooldown,
        burst_limit=burst_limit,
        burst_window_sec=burst_window,
        burst_cooldown_sec=burst_cooldown,
        buy_size_v=Decimal("50"),
        max_project_spend_v=d(max_spend),
        min_cost_rows=min_rows,
        min_whale_rows=min_rows,
    )


def pct(value: Decimal | None, places: int = 4) -> str | None:
    return fmt_decimal(value, places) if value is not None else None


def scaled_decimal(row: dict[str, Any], key: str, scale: Decimal) -> Decimal | None:
    value = parse_decimal(row.get(key))
    if value is None:
        return None
    return value * scale


def delayed_index(timestamps: list[int], current_index: int, delay_sec: int) -> int:
    if delay_sec <= 0:
        return current_index
    target = timestamps[current_index] - delay_sec
    return max(0, bisect.bisect_right(timestamps, target) - 1)


def scenario_should_buy(
    *,
    signal_row: dict[str, Any],
    params: StrategyParams,
    scenario: Scenario,
) -> tuple[bool, str, dict[str, Decimal | None]]:
    if signal_row.get("projectStatus") not in {None, "live"}:
        return False, "not_live", {}

    tax_fdv = scaled_decimal(signal_row, "estimatedFdvWanUsdWithTax", scenario.signal_fdv_scale)
    board_cost = scaled_decimal(signal_row, "boardCostWanUsd", scenario.board_cost_scale)
    board_spent = scaled_decimal(signal_row, "boardSpentV", scenario.board_spent_scale) or Decimal(0)
    tax_rate_raw = parse_decimal(signal_row.get("buyTaxRate"))
    tax_rate = tax_rate_raw + scenario.tax_offset if tax_rate_raw is not None else None
    cost_rows = int(signal_row.get("costRows") or 0)
    whale_rows = int(signal_row.get("whaleRows") or 0)

    values = {
        "tax_fdv": tax_fdv,
        "board_cost": board_cost,
        "board_spent": board_spent,
        "tax_rate": tax_rate,
    }

    if tax_fdv is None or tax_fdv <= 0:
        return False, "missing_tax_fdv", values
    if board_cost is None or board_cost <= 0:
        return False, "missing_board_cost", values
    if board_spent < params.spent_threshold_v:
        return False, "spent_threshold", values
    if cost_rows < params.min_cost_rows:
        return False, "min_cost_rows", values
    if whale_rows < params.min_whale_rows:
        return False, "min_whale_rows", values
    if params.max_tax_rate is not None and (tax_rate is None or tax_rate > params.max_tax_rate):
        return False, "tax_threshold", values
    if tax_fdv > board_cost * params.fdv_discount:
        return False, "fdv_not_below_cost", values
    return True, "signal", values


def future_spot_values(samples: list[dict[str, Any]], start_index: int) -> list[Decimal]:
    values: list[Decimal] = []
    for row in samples[start_index:]:
        value = spot_fdv_wan(row)
        if value is not None and value > 0:
            values.append(value)
    return values


def evaluate_scenario(
    samples: list[dict[str, Any]],
    timestamps: list[int],
    params: StrategyParams,
    scenario: Scenario,
    *,
    label: str,
) -> dict[str, Any]:
    buys: list[BuyEvent] = []
    buy_timestamps: list[int] = []
    next_allowed_ts = -1
    next_sample_ts = -1
    total_spent = Decimal(0)
    skip_reasons: dict[str, int] = {}

    for index, row in enumerate(samples):
        ts = int(row.get("simTimestamp") or 0)
        if scenario.sample_every_sec > 0 and ts < next_sample_ts:
            skip_reasons["sample_interval"] = skip_reasons.get("sample_interval", 0) + 1
            continue
        if scenario.sample_every_sec > 0:
            next_sample_ts = ts + scenario.sample_every_sec

        signal_index = delayed_index(timestamps, index, scenario.decision_delay_sec)
        signal_row = samples[signal_index]
        ok, reason, values = scenario_should_buy(signal_row=signal_row, params=params, scenario=scenario)
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        if ts < next_allowed_ts:
            skip_reasons["cooldown"] = skip_reasons.get("cooldown", 0) + 1
            continue
        if total_spent + params.buy_size_v > params.max_project_spend_v:
            skip_reasons["max_project_spend"] = skip_reasons.get("max_project_spend", 0) + 1
            continue

        entry_tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        if entry_tax_fdv is None or entry_tax_fdv <= 0:
            skip_reasons["missing_entry_fdv"] = skip_reasons.get("missing_entry_fdv", 0) + 1
            continue
        entry_tax_fdv *= Decimal("1") + scenario.entry_slippage_pct / Decimal("100")
        entry_spot = spot_fdv_wan(row)

        buys.append(
            BuyEvent(
                index=index,
                sim_timestamp=ts,
                signal_timestamp=int(signal_row.get("simTimestamp") or 0),
                tax_rate=fmt_decimal(values.get("tax_rate")),
                entry_tax_fdv_wan_usd=fmt_decimal(entry_tax_fdv, 6) or "0",
                signal_tax_fdv_wan_usd=fmt_decimal(values.get("tax_fdv"), 6),
                entry_spot_fdv_wan_usd=fmt_decimal(entry_spot, 6) if entry_spot is not None else None,
                board_spent_v=fmt_decimal(values.get("board_spent"), 3),
                board_cost_wan_usd=fmt_decimal(values.get("board_cost"), 6),
                cost_position=str(signal_row.get("costPosition") or "-"),
                v_cost_position=str(signal_row.get("vCostPosition") or "-"),
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
    returns: list[Decimal] = []

    for buy in buys:
        entry = parse_decimal(buy.entry_tax_fdv_wan_usd)
        if entry is None or entry <= 0:
            continue
        if final_spot is not None:
            value = params.buy_size_v * final_spot / entry
            final_value += value
            returns.append(value / params.buy_size_v - 1)
        if final_tax_fdv is not None:
            final_tax_adjusted_value += params.buy_size_v * final_tax_fdv / entry
        future = future_spot_values(samples, buy.index)
        if future:
            max_value += params.buy_size_v * max(future) / entry
            low_value = params.buy_size_v * min(future) / entry
            min_value = low_value if min_value is None else min(min_value, low_value)

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent else Decimal("0")
    tax_adj_pnl = final_tax_adjusted_value - total_spent
    tax_adj_pnl_pct = tax_adj_pnl / total_spent * Decimal("100") if total_spent else Decimal("0")
    max_runup_pct = max_value / total_spent * Decimal("100") - Decimal("100") if total_spent else Decimal("0")
    worst_drawdown_pct = min_value / params.buy_size_v * Decimal("100") - Decimal("100") if min_value else Decimal("0")
    avg_return_pct = Decimal(str(statistics.mean(float(item * 100) for item in returns))) if returns else Decimal("0")
    score = final_pnl_pct + max_runup_pct * Decimal("0.15") + min(worst_drawdown_pct, Decimal("0")) * Decimal("0.5")
    score -= Decimal(len(buys)) * Decimal("0.25")

    return {
        "label": label,
        "scenario": asdict(scenario),
        "params": {
            "spentThresholdV": fmt_decimal(params.spent_threshold_v),
            "maxTaxRate": fmt_decimal(params.max_tax_rate) if params.max_tax_rate is not None else None,
            "fdvDiscount": fmt_decimal(params.fdv_discount),
            "cooldownSec": params.cooldown_sec,
            "burstLimit": params.burst_limit,
            "burstWindowSec": params.burst_window_sec,
            "burstCooldownSec": params.burst_cooldown_sec,
            "maxProjectSpendV": fmt_decimal(params.max_project_spend_v),
            "minRows": params.min_cost_rows,
        },
        "buyCount": len(buys),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": pct(final_pnl_pct),
        "finalTaxAdjustedPnlPct": pct(tax_adj_pnl_pct),
        "maxRunupPct": pct(max_runup_pct),
        "worstDrawdownPct": pct(worst_drawdown_pct),
        "avgBuyReturnPct": pct(avg_return_pct),
        "score": pct(score),
        "skipReasons": skip_reasons,
        "buys": [asdict(item) for item in buys],
    }


def scalar(result: dict[str, Any], key: str) -> float:
    try:
        return float(result.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = [item for item in results if int(item.get("buyCount") or 0) > 0]
    pct_values = [scalar(item, "finalPnlPct") for item in triggered]
    return {
        "count": len(results),
        "triggered": len(triggered),
        "avgFinalPnlPct": round(statistics.mean(pct_values), 4) if pct_values else 0,
        "medianFinalPnlPct": round(statistics.median(pct_values), 4) if pct_values else 0,
        "minFinalPnlPct": round(min(pct_values), 4) if pct_values else 0,
        "maxFinalPnlPct": round(max(pct_values), 4) if pct_values else 0,
        "best": max(triggered, key=lambda item: scalar(item, "score"), default=None),
        "worst": min(triggered, key=lambda item: scalar(item, "finalPnlPct"), default=None),
    }


def base_params() -> StrategyParams:
    return make_params(spent=100000, tax=92, discount="1", cooldown=60, burst_limit=2, max_spend=300)


def named_candidates() -> dict[str, StrategyParams]:
    return {
        "baseline_100k_tax92": base_params(),
        "conservative_100k_tax90": make_params(spent=100000, tax=90, discount="1", cooldown=60, max_spend=300),
        "strict_100k_tax92_discount98": make_params(spent=100000, tax=92, discount="0.98", cooldown=60, max_spend=300),
        "aggressive_50k_tax98_discount98": make_params(
            spent=50000, tax=98, discount="0.98", cooldown=180, burst_limit=2, max_spend=300
        ),
        "aggressive_50k_tax98_discount100": make_params(
            spent=50000, tax=98, discount="1", cooldown=60, burst_limit=2, max_spend=300
        ),
        "capital_cap_100k_tax92_max100": make_params(
            spent=100000, tax=92, discount="1", cooldown=60, burst_limit=2, max_spend=100
        ),
        "no_burst_100k_tax92": make_params(
            spent=100000, tax=92, discount="1", cooldown=60, burst_limit=0, max_spend=300
        ),
    }


def base_scenarios() -> list[Scenario]:
    return [
        Scenario("actual"),
        Scenario("sample_15s", sample_every_sec=15),
        Scenario("sample_30s", sample_every_sec=30),
        Scenario("sample_60s", sample_every_sec=60),
        Scenario("delay_6s", decision_delay_sec=6),
        Scenario("delay_12s", decision_delay_sec=12),
        Scenario("delay_30s", decision_delay_sec=30),
        Scenario("delay_60s", decision_delay_sec=60),
        Scenario("slippage_1pct", entry_slippage_pct=Decimal("1")),
        Scenario("slippage_3pct", entry_slippage_pct=Decimal("3")),
        Scenario("slippage_5pct", entry_slippage_pct=Decimal("5")),
        Scenario("slippage_10pct", entry_slippage_pct=Decimal("10")),
        Scenario("board_cost_under_20pct", board_cost_scale=Decimal("0.8")),
        Scenario("board_cost_under_10pct", board_cost_scale=Decimal("0.9")),
        Scenario("board_cost_over_10pct", board_cost_scale=Decimal("1.1")),
        Scenario("board_cost_over_20pct", board_cost_scale=Decimal("1.2")),
        Scenario("board_spent_under_20pct", board_spent_scale=Decimal("0.8")),
        Scenario("board_spent_over_20pct", board_spent_scale=Decimal("1.2")),
        Scenario("tax_offset_minus2", tax_offset=Decimal("-2")),
        Scenario("tax_offset_plus2", tax_offset=Decimal("2")),
        Scenario(
            "combined_fast_realistic",
            sample_every_sec=15,
            decision_delay_sec=6,
            entry_slippage_pct=Decimal("1"),
        ),
        Scenario(
            "combined_slow_bad",
            sample_every_sec=30,
            decision_delay_sec=30,
            entry_slippage_pct=Decimal("5"),
            board_cost_scale=Decimal("1.1"),
            board_spent_scale=Decimal("1.2"),
            tax_offset=Decimal("1"),
        ),
        Scenario(
            "combined_conservative_miss",
            sample_every_sec=30,
            decision_delay_sec=30,
            entry_slippage_pct=Decimal("3"),
            board_cost_scale=Decimal("0.9"),
            board_spent_scale=Decimal("0.8"),
            tax_offset=Decimal("-1"),
        ),
    ]


def gradient_params() -> dict[str, list[tuple[str, StrategyParams]]]:
    base = base_params()
    gradients: dict[str, list[tuple[str, StrategyParams]]] = {}
    gradients["spent_threshold"] = [
        (str(value), make_params(spent=value, tax=92, discount="1", cooldown=60, burst_limit=2, max_spend=300))
        for value in range(10000, 351000, 10000)
    ]
    gradients["tax_threshold"] = [
        (str(value), make_params(spent=100000, tax=value, discount="1", cooldown=60, burst_limit=2, max_spend=300))
        for value in range(99, 49, -1)
    ]
    gradients["fdv_discount"] = [
        (f"{value / 100:.2f}", make_params(spent=100000, tax=92, discount=f"{value / 100:.2f}", cooldown=60, burst_limit=2, max_spend=300))
        for value in range(100, 74, -1)
    ]
    gradients["cooldown"] = [
        (str(value), make_params(spent=100000, tax=92, discount="1", cooldown=value, burst_limit=2, max_spend=300))
        for value in [0, 15, 30, 60, 90, 120, 180, 300, 600]
    ]
    gradients["burst_limit"] = [
        (str(value), make_params(spent=100000, tax=92, discount="1", cooldown=60, burst_limit=value, max_spend=300))
        for value in [0, 2, 3, 4]
    ]
    gradients["max_project_spend"] = [
        (str(value), make_params(spent=100000, tax=92, discount="1", cooldown=60, burst_limit=2, max_spend=value))
        for value in [50, 100, 150, 200, 300, 500, 1000]
    ]
    gradients["min_rows"] = [
        (str(value), make_params(spent=100000, tax=92, discount="1", cooldown=60, burst_limit=2, max_spend=300, min_rows=value))
        for value in [1, 3, 5, 10, 15, 20]
    ]
    gradients["base"] = [("base", base)]
    return gradients


def two_dimensional_params() -> dict[str, list[tuple[str, StrategyParams]]]:
    grids: dict[str, list[tuple[str, StrategyParams]]] = {}
    grids["spent_x_tax"] = [
        (
            f"spent={spent}|tax={tax}",
            make_params(spent=spent, tax=tax, discount="1", cooldown=60, burst_limit=2, max_spend=300),
        )
        for spent in range(10000, 351000, 10000)
        for tax in range(99, 49, -1)
    ]
    grids["spent_x_discount"] = [
        (
            f"spent={spent}|discount={discount / 100:.2f}",
            make_params(spent=spent, tax=92, discount=f"{discount / 100:.2f}", cooldown=60, burst_limit=2, max_spend=300),
        )
        for spent in range(10000, 351000, 10000)
        for discount in range(100, 74, -1)
    ]
    grids["tax_x_discount"] = [
        (
            f"tax={tax}|discount={discount / 100:.2f}",
            make_params(spent=100000, tax=tax, discount=f"{discount / 100:.2f}", cooldown=60, burst_limit=2, max_spend=300),
        )
        for tax in range(99, 49, -1)
        for discount in range(100, 74, -1)
    ]
    return grids


def run_gradient_suite(samples: list[dict[str, Any]], timestamps: list[int], label: str) -> dict[str, Any]:
    scenario = Scenario("actual")
    output: dict[str, Any] = {}
    for name, cases in gradient_params().items():
        results = [
            {"case": case_name, **evaluate_scenario(samples, timestamps, params, scenario, label=label)}
            for case_name, params in cases
        ]
        output[name] = {
            "summary": summarize_results(results),
            "results": results,
        }
    return output


def run_two_dimensional_suite(samples: list[dict[str, Any]], timestamps: list[int], label: str) -> dict[str, Any]:
    scenario = Scenario("actual")
    output: dict[str, Any] = {}
    for name, cases in two_dimensional_params().items():
        results = [
            {"case": case_name, **evaluate_scenario(samples, timestamps, params, scenario, label=label)}
            for case_name, params in cases
        ]
        triggered = [item for item in results if int(item.get("buyCount") or 0) > 0]
        best_score = sorted(triggered, key=lambda item: scalar(item, "score"), reverse=True)[:20]
        best_pct = sorted(triggered, key=lambda item: scalar(item, "finalPnlPct"), reverse=True)[:20]
        output[name] = {
            "summary": summarize_results(results),
            "bestByScore": best_score,
            "bestByFinalPnlPct": best_pct,
        }
    return output


def run_scenario_suite(samples: list[dict[str, Any]], timestamps: list[int], label: str) -> dict[str, Any]:
    scenarios = base_scenarios()
    candidates = named_candidates()
    by_candidate: dict[str, Any] = {}
    all_results: list[dict[str, Any]] = []
    for candidate_name, params in candidates.items():
        results = []
        for scenario in scenarios:
            result = evaluate_scenario(samples, timestamps, params, scenario, label=label)
            result["candidate"] = candidate_name
            results.append(result)
            all_results.append(result)
        by_candidate[candidate_name] = {
            "summary": summarize_results(results),
            "actual": next((item for item in results if item["scenario"]["name"] == "actual"), None),
            "worstScenarios": sorted(
                [item for item in results if int(item.get("buyCount") or 0) > 0],
                key=lambda item: scalar(item, "finalPnlPct"),
            )[:5],
        }
    return {
        "scenarioCount": len(scenarios),
        "candidateCount": len(candidates),
        "byCandidate": by_candidate,
        "allResults": all_results,
    }


def run_monte_carlo_suite(
    samples: list[dict[str, Any]], timestamps: list[int], label: str, *, iterations: int, seed: int
) -> dict[str, Any]:
    rng = random.Random(seed)
    candidates = {
        "baseline_100k_tax92": named_candidates()["baseline_100k_tax92"],
        "strict_100k_tax92_discount98": named_candidates()["strict_100k_tax92_discount98"],
        "aggressive_50k_tax98_discount98": named_candidates()["aggressive_50k_tax98_discount98"],
    }
    output: dict[str, Any] = {}
    for candidate_name, params in candidates.items():
        results = []
        for index in range(iterations):
            scenario = Scenario(
                name=f"mc_{index:04d}",
                sample_every_sec=rng.choice([0, 6, 12, 15, 30, 60]),
                decision_delay_sec=rng.choice([0, 6, 12, 18, 30, 60]),
                entry_slippage_pct=Decimal(str(round(rng.uniform(0, 8), 4))),
                signal_fdv_scale=Decimal(str(round(rng.uniform(0.92, 1.08), 4))),
                board_cost_scale=Decimal(str(round(rng.uniform(0.8, 1.2), 4))),
                board_spent_scale=Decimal(str(round(rng.uniform(0.75, 1.25), 4))),
                tax_offset=Decimal(str(rng.choice([-2, -1, 0, 1, 2]))),
            )
            result = evaluate_scenario(samples, timestamps, params, scenario, label=label)
            result["candidate"] = candidate_name
            results.append(result)
        triggered = [item for item in results if int(item.get("buyCount") or 0) > 0]
        pct_values = sorted(scalar(item, "finalPnlPct") for item in triggered)
        p5 = pct_values[int(len(pct_values) * 0.05)] if pct_values else 0
        p95 = pct_values[min(len(pct_values) - 1, int(len(pct_values) * 0.95))] if pct_values else 0
        output[candidate_name] = {
            "summary": summarize_results(results),
            "p5FinalPnlPct": round(p5, 4),
            "p95FinalPnlPct": round(p95, 4),
            "worst": min(triggered, key=lambda item: scalar(item, "finalPnlPct"), default=None),
            "best": max(triggered, key=lambda item: scalar(item, "finalPnlPct"), default=None),
        }
    return output


def set_scaled(row: dict[str, Any], key: str, scale: Decimal) -> None:
    value = parse_decimal(row.get(key))
    if value is not None:
        row[key] = fmt_decimal(value * scale, 12)


def make_synthetic_variant(samples: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    rows = deepcopy(samples)
    if not rows:
        return rows
    first_ts = int(rows[0].get("simTimestamp") or 0)
    last_ts = int(rows[-1].get("simTimestamp") or first_ts)
    duration = max(1, last_ts - first_ts)

    for row in rows:
        ts = int(row.get("simTimestamp") or first_ts)
        progress = Decimal(ts - first_ts) / Decimal(duration)
        scale = Decimal("1")
        board_cost_scale = Decimal("1")
        board_spent_scale = Decimal("1")

        if name == "price_up_50pct":
            scale = Decimal("1") + Decimal("0.5") * progress
        elif name == "price_down_30pct":
            scale = Decimal("1") - Decimal("0.3") * progress
        elif name == "late_dump_50pct":
            if progress > Decimal("0.6"):
                local = (progress - Decimal("0.6")) / Decimal("0.4")
                scale = Decimal("1") - Decimal("0.5") * local
        elif name == "early_pump_then_flat":
            if progress <= Decimal("0.25"):
                scale = Decimal("1") + Decimal("0.5") * (progress / Decimal("0.25"))
            else:
                scale = Decimal("1.5") - Decimal("0.5") * ((progress - Decimal("0.25")) / Decimal("0.75"))
        elif name == "team_low_cost_included":
            board_cost_scale = Decimal("0.6")
            board_spent_scale = Decimal("1.4")
        elif name == "board_cost_overstated":
            board_cost_scale = Decimal("1.5")
            board_spent_scale = Decimal("1.2")
        elif name == "whale_slow_accumulation":
            board_spent_scale = Decimal("0.5") + Decimal("0.5") * progress
        elif name == "whale_fast_accumulation":
            board_spent_scale = Decimal("1.5") - Decimal("0.3") * progress

        if scale != Decimal("1"):
            set_scaled(row, "estimatedFdvWanUsdWithTax", scale)
            set_scaled(row, "liveFdvUsd", scale)
        if board_cost_scale != Decimal("1"):
            set_scaled(row, "boardCostWanUsd", board_cost_scale)
        if board_spent_scale != Decimal("1"):
            set_scaled(row, "boardSpentV", board_spent_scale)
    return rows


def run_synthetic_dataset_suite(samples: list[dict[str, Any]], label: str) -> dict[str, Any]:
    variant_names = [
        "actual",
        "price_up_50pct",
        "price_down_30pct",
        "late_dump_50pct",
        "early_pump_then_flat",
        "team_low_cost_included",
        "board_cost_overstated",
        "whale_slow_accumulation",
        "whale_fast_accumulation",
    ]
    candidates = named_candidates()
    by_variant: dict[str, Any] = {}
    all_results: list[dict[str, Any]] = []
    for variant_name in variant_names:
        variant_samples = samples if variant_name == "actual" else make_synthetic_variant(samples, variant_name)
        timestamps = [int(row.get("simTimestamp") or 0) for row in variant_samples]
        results = []
        for candidate_name, params in candidates.items():
            result = evaluate_scenario(variant_samples, timestamps, params, Scenario("actual"), label=f"{label}:{variant_name}")
            result["candidate"] = candidate_name
            result["variant"] = variant_name
            results.append(result)
            all_results.append(result)
        by_variant[variant_name] = {
            "summary": summarize_results(results),
            "best": max([item for item in results if int(item.get("buyCount") or 0) > 0], key=lambda item: scalar(item, "score"), default=None),
            "worst": min([item for item in results if int(item.get("buyCount") or 0) > 0], key=lambda item: scalar(item, "finalPnlPct"), default=None),
            "results": results,
        }
    return {
        "variantCount": len(variant_names),
        "candidateCount": len(candidates),
        "byVariant": by_variant,
        "allResults": all_results,
    }


def dataset_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}
    timestamps = [int(row.get("simTimestamp") or 0) for row in samples]
    taxes = [parse_decimal(row.get("buyTaxRate")) for row in samples if parse_decimal(row.get("buyTaxRate")) is not None]
    board_spent = [parse_decimal(row.get("boardSpentV")) or Decimal("0") for row in samples]
    board_cost = [parse_decimal(row.get("boardCostWanUsd")) for row in samples if parse_decimal(row.get("boardCostWanUsd"))]
    return {
        "sampleCount": len(samples),
        "firstTimestamp": timestamps[0],
        "lastTimestamp": timestamps[-1],
        "durationSec": timestamps[-1] - timestamps[0],
        "taxMin": fmt_decimal(min(taxes)) if taxes else None,
        "taxMax": fmt_decimal(max(taxes)) if taxes else None,
        "boardSpentMaxV": fmt_decimal(max(board_spent), 3) if board_spent else None,
        "boardCostMaxWanUsd": fmt_decimal(max(board_cost), 6) if board_cost else None,
        "boardCostMinWanUsd": fmt_decimal(min(board_cost), 6) if board_cost else None,
    }


def table_line(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def compact_result(result: dict[str, Any] | None) -> str:
    if not result:
        return "-"
    buys = result.get("buys") or []
    first = buys[0] if buys else {}
    return (
        f"{result.get('buyCount')} buys, spent {result.get('totalSpentV')}V, "
        f"pnl {result.get('finalPnlV')}V/{result.get('finalPnlPct')}%, "
        f"first tax {first.get('tax_rate')}, spent {first.get('board_spent_v')}, "
        f"entry {first.get('entry_tax_fdv_wan_usd')}, cost {first.get('board_cost_wan_usd')}"
    )


def write_markdown(report: dict[str, Any], output: Path) -> None:
    lines: list[str] = []
    lines.append("# SR 策略梯度与场景压力测试")
    lines.append("")
    lines.append("本报告只读 replay 样本，不写生产数据库，不发交易。")
    lines.append("")
    lines.append("## 样本")
    for key, value in report["datasetStats"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## 单参数梯度摘要")
    lines.append(table_line(["维度", "测试数量", "触发数量", "平均收益率", "中位收益率", "最差收益率", "最好收益率", "最佳 case"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---"]))
    for name, payload in report["gradient"].items():
        summary = payload["summary"]
        best = summary.get("best") or {}
        lines.append(
            table_line(
                [
                    name,
                    summary["count"],
                    summary["triggered"],
                    summary["avgFinalPnlPct"],
                    summary["medianFinalPnlPct"],
                    summary["minFinalPnlPct"],
                    summary["maxFinalPnlPct"],
                    best.get("case", "-"),
                ]
            )
        )
    lines.append("")
    lines.append("## 二维组合梯度摘要")
    lines.append(table_line(["维度", "测试数量", "触发数量", "平均收益率", "中位收益率", "最差收益率", "最好收益率", "最佳 case"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---"]))
    for name, payload in report["twoDimensional"].items():
        summary = payload["summary"]
        best = summary.get("best") or {}
        lines.append(
            table_line(
                [
                    name,
                    summary["count"],
                    summary["triggered"],
                    summary["avgFinalPnlPct"],
                    summary["medianFinalPnlPct"],
                    summary["minFinalPnlPct"],
                    summary["maxFinalPnlPct"],
                    best.get("case", "-"),
                ]
            )
        )
    lines.append("")
    lines.append("## 候选策略场景压力测试")
    lines.append(table_line(["候选", "真实 SR", "场景数", "触发场景", "中位收益率", "最差收益率", "最坏场景"]))
    lines.append(table_line(["---", "---", "---:", "---:", "---:", "---:", "---"]))
    for name, payload in report["scenarios"]["byCandidate"].items():
        summary = payload["summary"]
        worst = payload["worstScenarios"][0] if payload["worstScenarios"] else None
        lines.append(
            table_line(
                [
                    name,
                    compact_result(payload.get("actual")),
                    summary["count"],
                    summary["triggered"],
                    summary["medianFinalPnlPct"],
                    summary["minFinalPnlPct"],
                    worst["scenario"]["name"] if worst else "-",
                ]
            )
        )
    lines.append("")
    lines.append("## 蒙特卡洛扰动")
    lines.append(table_line(["候选", "运行次数", "触发次数", "P5", "中位", "P95", "最差", "最好"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]))
    for name, payload in report["monteCarlo"].items():
        summary = payload["summary"]
        lines.append(
            table_line(
                [
                    name,
                    summary["count"],
                    summary["triggered"],
                    payload["p5FinalPnlPct"],
                    summary["medianFinalPnlPct"],
                    payload["p95FinalPnlPct"],
                    summary["minFinalPnlPct"],
                    summary["maxFinalPnlPct"],
                ]
            )
        )
    lines.append("")
    lines.append("## 合成数据形态测试")
    lines.append(table_line(["形态", "候选数", "触发数", "中位收益率", "最差收益率", "最好收益率", "最佳候选", "最坏候选"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---", "---"]))
    for name, payload in report["syntheticDatasets"]["byVariant"].items():
        summary = payload["summary"]
        best = payload.get("best") or {}
        worst = payload.get("worst") or {}
        lines.append(
            table_line(
                [
                    name,
                    summary["count"],
                    summary["triggered"],
                    summary["medianFinalPnlPct"],
                    summary["minFinalPnlPct"],
                    summary["maxFinalPnlPct"],
                    best.get("candidate", "-"),
                    worst.get("candidate", "-"),
                ]
            )
        )
    lines.append("")
    lines.append("## 当前解释")
    lines.append("- 上一次结论只能证明历史 SR 上几个点位有效，不能证明策略稳健。")
    lines.append("- 这次测试覆盖单参数梯度、二维组合梯度、采样/延迟/滑点/榜单偏差/税率偏差和组合坏情况。")
    lines.append("- 自动买入仍不应直接上线；下一步应先做实时 dry-run 信号记录，并用真实新项目验证。")
    lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SR launch strategy gradient and scenario suite.")
    parser.add_argument("--samples", required=True)
    parser.add_argument("--output-json", default="data/backtests/sr-strategy-scenario-suite.json")
    parser.add_argument("--output-md", default="docs/sr-strategy-scenario-suite-2026-05-07.md")
    parser.add_argument("--monte-carlo", type=int, default=300)
    parser.add_argument("--seed", type=int, default=20260507)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sample_path = Path(args.samples)
    samples = load_samples(sample_path)
    timestamps = [int(row.get("simTimestamp") or 0) for row in samples]
    label = sample_path.name.removesuffix("-samples.jsonl")
    report = {
        "samples": str(sample_path),
        "datasetStats": dataset_stats(samples),
        "assumptions": {
            "readOnly": True,
            "entryCost": "execution-row tax-adjusted FDV, with optional slippage",
            "signalData": "optionally delayed/scaled signal row",
            "markToMarket": "final liveFdvUsd / 10000",
            "tradeSize": "50 VIRTUAL per simulated buy",
        },
        "gradient": run_gradient_suite(samples, timestamps, label),
        "twoDimensional": run_two_dimensional_suite(samples, timestamps, label),
        "scenarios": run_scenario_suite(samples, timestamps, label),
        "monteCarlo": run_monte_carlo_suite(samples, timestamps, label, iterations=args.monte_carlo, seed=args.seed),
        "syntheticDatasets": run_synthetic_dataset_suite(samples, label),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(
        json.dumps(
            {
                "outputJson": str(output_json),
                "outputMd": args.output_md,
                "sampleCount": report["datasetStats"].get("sampleCount"),
                "gradientSuites": len(report["gradient"]),
                "twoDimensionalSuites": len(report["twoDimensional"]),
                "scenarioCandidates": report["scenarios"]["candidateCount"],
                "scenarioCount": report["scenarios"]["scenarioCount"],
                "monteCarlo": args.monte_carlo,
                "syntheticVariants": report["syntheticDatasets"]["variantCount"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
