#!/usr/bin/env python3
"""Unified strategy test matrix runner for launch-window buy rules.

Read-only by design:
- consumes replay sample JSONL files;
- writes JSON/Markdown reports;
- does not touch production databases;
- does not send transactions.
"""

from __future__ import annotations

import argparse
import bisect
import copy
import itertools
import json
import math
import statistics
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from backtest_launch_strategy import fmt_decimal, load_samples, parse_decimal, spot_fdv_wan


SNAPSHOT_OFFSETS_SEC = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "10m": 600,
}


@dataclass(frozen=True)
class Rule:
    name: str
    suite: str
    spent_threshold_v: Decimal | None = None
    max_tax_rate: Decimal | None = None
    fdv_discount: Decimal | None = None
    min_cost_rows: int = 5
    min_whale_rows: int = 20
    cooldown_sec: int = 60
    burst_limit: int = 2
    burst_window_sec: int = 120
    burst_cooldown_sec: int = 600
    buy_size_v: Decimal = Decimal("50")
    max_project_spend_v: Decimal = Decimal("300")


@dataclass(frozen=True)
class Scenario:
    name: str
    category: str = "actual"
    sample_every_sec: int = 0
    decision_delay_sec: int = 0
    entry_delay_sec: int = 0
    entry_slippage_pct: Decimal = Decimal("0")
    signal_fdv_scale: Decimal = Decimal("1")
    board_cost_scale: Decimal = Decimal("1")
    board_spent_scale: Decimal = Decimal("1")
    tax_offset: Decimal = Decimal("0")
    tax_missing: bool = False
    price_path: str = "actual"
    buy_failure_every: int = 0


@dataclass(frozen=True)
class Buy:
    index: int
    entry_index: int
    signal_timestamp: int
    trigger_timestamp: int
    entry_timestamp: int
    tax_rate: str | None
    board_spent_v: str | None
    signal_tax_fdv_wan_usd: str | None
    entry_tax_fdv_wan_usd: str | None
    entry_spot_fdv_wan_usd: str | None
    board_cost_wan_usd: str | None
    cost_rows: int
    whale_rows: int
    cost_position: str
    v_cost_position: str
    return_snapshots_pct: dict[str, str | None]


def d(value: str | int | float | Decimal) -> Decimal:
    parsed = parse_decimal(value)
    if parsed is None:
        raise ValueError(f"invalid decimal: {value}")
    return parsed


def pct(value: Decimal | None, places: int = 4) -> str | None:
    return fmt_decimal(value, places) if value is not None else None


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def dataset_label(path: Path) -> str:
    name = path.name.removesuffix("-samples.jsonl")
    return name.replace("_20260507", "").replace("-20260507T090116Z", "")


def timestamps(samples: list[dict[str, Any]]) -> list[int]:
    return [int(row.get("simTimestamp") or 0) for row in samples]


def nearest_index_at_or_after(ts_list: list[int], target_ts: int) -> int:
    if not ts_list:
        return 0
    index = bisect.bisect_left(ts_list, target_ts)
    return min(index, len(ts_list) - 1)


def nearest_index_at_or_before(ts_list: list[int], target_ts: int) -> int:
    if not ts_list:
        return 0
    index = bisect.bisect_right(ts_list, target_ts) - 1
    return max(0, min(index, len(ts_list) - 1))


def set_scaled(row: dict[str, Any], key: str, scale: Decimal) -> None:
    value = parse_decimal(row.get(key))
    if value is not None:
        row[key] = fmt_decimal(value * scale, 12)


def apply_price_path(samples: list[dict[str, Any]], price_path: str) -> list[dict[str, Any]]:
    if price_path == "actual" or not samples:
        return samples

    rows = copy.deepcopy(samples)
    ts_values = timestamps(rows)
    first_ts = ts_values[0]
    duration = max(1, ts_values[-1] - first_ts)

    for row in rows:
        progress = Decimal(int(row.get("simTimestamp") or first_ts) - first_ts) / Decimal(duration)
        scale = Decimal("1")
        if price_path == "price_up_50pct":
            scale = Decimal("1") + Decimal("0.5") * progress
        elif price_path == "price_down_30pct":
            scale = Decimal("1") - Decimal("0.3") * progress
        elif price_path == "late_dump_50pct":
            if progress > Decimal("0.6"):
                scale = Decimal("1") - Decimal("0.5") * ((progress - Decimal("0.6")) / Decimal("0.4"))
        elif price_path == "early_pump_flat":
            if progress <= Decimal("0.25"):
                scale = Decimal("1") + Decimal("0.5") * (progress / Decimal("0.25"))
            else:
                scale = Decimal("1.5") - Decimal("0.5") * ((progress - Decimal("0.25")) / Decimal("0.75"))
        elif price_path == "fast_rebound":
            if progress <= Decimal("0.2"):
                scale = Decimal("0.8") + progress
            else:
                scale = Decimal("1")
        elif price_path == "choppy":
            wave = Decimal("0.12") if int(progress * 20) % 2 == 0 else Decimal("-0.12")
            scale = Decimal("1") + wave
        if scale != Decimal("1"):
            set_scaled(row, "estimatedFdvWanUsdWithTax", scale)
            set_scaled(row, "liveFdvUsd", scale)
    return rows


def scenario_row_values(row: dict[str, Any], scenario: Scenario) -> dict[str, Decimal | None]:
    tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
    board_cost = parse_decimal(row.get("boardCostWanUsd"))
    board_spent = parse_decimal(row.get("boardSpentV")) or Decimal("0")
    tax_rate = parse_decimal(row.get("buyTaxRate"))

    if tax_fdv is not None:
        tax_fdv *= scenario.signal_fdv_scale
    if board_cost is not None:
        board_cost *= scenario.board_cost_scale
    board_spent *= scenario.board_spent_scale
    if scenario.tax_missing:
        tax_rate = None
    elif tax_rate is not None:
        tax_rate += scenario.tax_offset

    return {
        "tax_fdv": tax_fdv,
        "board_cost": board_cost,
        "board_spent": board_spent,
        "tax_rate": tax_rate,
    }


def should_buy(row: dict[str, Any], rule: Rule, scenario: Scenario) -> tuple[bool, str, dict[str, Decimal | None]]:
    if row.get("projectStatus") not in {None, "live"}:
        return False, "not_live", {}

    values = scenario_row_values(row, scenario)
    tax_fdv = values["tax_fdv"]
    board_cost = values["board_cost"]
    board_spent = values["board_spent"] or Decimal("0")
    tax_rate = values["tax_rate"]
    cost_rows = int(row.get("costRows") or 0)
    whale_rows = int(row.get("whaleRows") or 0)

    if tax_fdv is None or tax_fdv <= 0:
        return False, "missing_tax_fdv", values
    if rule.spent_threshold_v is not None and board_spent < rule.spent_threshold_v:
        return False, "spent_threshold", values
    if rule.max_tax_rate is not None and (tax_rate is None or tax_rate > rule.max_tax_rate):
        return False, "tax_threshold", values
    if rule.min_cost_rows > 0 and cost_rows < rule.min_cost_rows:
        return False, "min_cost_rows", values
    if rule.min_whale_rows > 0 and whale_rows < rule.min_whale_rows:
        return False, "min_whale_rows", values
    if rule.fdv_discount is not None:
        if board_cost is None or board_cost <= 0:
            return False, "missing_board_cost", values
        if tax_fdv > board_cost * rule.fdv_discount:
            return False, "fdv_not_below_cost", values
    return True, "signal", values


def return_pct_at(samples: list[dict[str, Any]], ts_values: list[int], entry: Decimal, entry_index: int, target_ts: int) -> str | None:
    if entry <= 0:
        return None
    index = nearest_index_at_or_after(ts_values, target_ts)
    if index < entry_index:
        index = entry_index
    value = spot_fdv_wan(samples[index])
    if value is None or value <= 0:
        return None
    return pct((value / entry - Decimal("1")) * Decimal("100"))


def evaluate(samples_in: list[dict[str, Any]], rule: Rule, scenario: Scenario, *, dataset: str) -> dict[str, Any]:
    samples = apply_price_path(samples_in, scenario.price_path)
    ts_values = timestamps(samples)
    buys: list[Buy] = []
    skip_reasons: dict[str, int] = {}
    next_sample_ts = -1
    next_allowed_ts = -1
    total_spent = Decimal("0")
    buy_timestamps: list[int] = []
    raw_signal_count = 0

    for index, row in enumerate(samples):
        ts = int(row.get("simTimestamp") or 0)
        if scenario.sample_every_sec > 0 and ts < next_sample_ts:
            skip_reasons["sample_interval"] = skip_reasons.get("sample_interval", 0) + 1
            continue
        if scenario.sample_every_sec > 0:
            next_sample_ts = ts + scenario.sample_every_sec

        signal_index = nearest_index_at_or_before(ts_values, ts - scenario.decision_delay_sec)
        signal_row = samples[signal_index]
        ok, reason, values = should_buy(signal_row, rule, scenario)
        if not ok:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue

        raw_signal_count += 1
        if scenario.buy_failure_every > 0 and raw_signal_count % scenario.buy_failure_every == 0:
            skip_reasons["simulated_buy_failure"] = skip_reasons.get("simulated_buy_failure", 0) + 1
            continue
        if ts < next_allowed_ts:
            skip_reasons["cooldown"] = skip_reasons.get("cooldown", 0) + 1
            continue
        if total_spent + rule.buy_size_v > rule.max_project_spend_v:
            skip_reasons["max_project_spend"] = skip_reasons.get("max_project_spend", 0) + 1
            continue

        entry_index = nearest_index_at_or_after(ts_values, ts + scenario.entry_delay_sec)
        entry_row = samples[entry_index]
        entry = parse_decimal(entry_row.get("estimatedFdvWanUsdWithTax"))
        if entry is None or entry <= 0:
            skip_reasons["missing_entry_fdv"] = skip_reasons.get("missing_entry_fdv", 0) + 1
            continue
        entry *= Decimal("1") + scenario.entry_slippage_pct / Decimal("100")
        entry_ts = int(entry_row.get("simTimestamp") or ts)

        snapshots: dict[str, str | None] = {
            name: return_pct_at(samples, ts_values, entry, entry_index, entry_ts + offset)
            for name, offset in SNAPSHOT_OFFSETS_SEC.items()
        }
        final_spot_for_buy = spot_fdv_wan(samples[-1]) if samples else None
        snapshots["end"] = pct((final_spot_for_buy / entry - Decimal("1")) * Decimal("100")) if final_spot_for_buy else None

        buys.append(
            Buy(
                index=index,
                entry_index=entry_index,
                signal_timestamp=int(signal_row.get("simTimestamp") or 0),
                trigger_timestamp=ts,
                entry_timestamp=entry_ts,
                tax_rate=fmt_decimal(values.get("tax_rate")),
                board_spent_v=fmt_decimal(values.get("board_spent"), 3),
                signal_tax_fdv_wan_usd=fmt_decimal(values.get("tax_fdv"), 6),
                entry_tax_fdv_wan_usd=fmt_decimal(entry, 6),
                entry_spot_fdv_wan_usd=fmt_decimal(spot_fdv_wan(entry_row), 6) if spot_fdv_wan(entry_row) is not None else None,
                board_cost_wan_usd=fmt_decimal(values.get("board_cost"), 6),
                cost_rows=int(signal_row.get("costRows") or 0),
                whale_rows=int(signal_row.get("whaleRows") or 0),
                cost_position=str(signal_row.get("costPosition") or "-"),
                v_cost_position=str(signal_row.get("vCostPosition") or "-"),
                return_snapshots_pct=snapshots,
            )
        )
        total_spent += rule.buy_size_v
        buy_timestamps.append(ts)
        recent = [item for item in buy_timestamps if ts - item <= rule.burst_window_sec]
        if rule.burst_limit > 0 and len(recent) >= rule.burst_limit:
            next_allowed_ts = ts + rule.burst_cooldown_sec
        else:
            next_allowed_ts = ts + rule.cooldown_sec

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_value = Decimal("0")
    max_value = Decimal("0")
    min_value: Decimal | None = None
    return_points = {name: Decimal("0") for name in [*SNAPSHOT_OFFSETS_SEC.keys(), "end"]}

    for buy in buys:
        entry = parse_decimal(buy.entry_tax_fdv_wan_usd)
        if entry is None or entry <= 0:
            continue
        if final_spot is not None:
            final_value += rule.buy_size_v * final_spot / entry
        for name, value in buy.return_snapshots_pct.items():
            parsed = parse_decimal(value)
            if parsed is not None:
                return_points[name] += parsed
        future_values = [spot_fdv_wan(row) for row in samples[buy.entry_index :]]
        future_values = [item for item in future_values if item is not None and item > 0]
        if future_values:
            max_value += rule.buy_size_v * max(future_values) / entry
            low = rule.buy_size_v * min(future_values) / entry
            min_value = low if min_value is None else min(min_value, low)

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent else Decimal("0")
    max_runup_pct = max_value / total_spent * Decimal("100") - Decimal("100") if total_spent else Decimal("0")
    worst_drawdown_pct = min_value / rule.buy_size_v * Decimal("100") - Decimal("100") if min_value is not None else Decimal("0")
    score = final_pnl_pct + max_runup_pct * Decimal("0.15") + min(worst_drawdown_pct, Decimal("0")) * Decimal("0.5")
    score -= Decimal(len(buys)) * Decimal("0.25")

    avg_snapshots = {
        name: pct(value / Decimal(len(buys))) if buys else None
        for name, value in return_points.items()
    }
    first_buy = asdict(buys[0]) if buys else None
    low_sample = bool(first_buy and (int(first_buy["cost_rows"]) < 5 or int(first_buy["whale_rows"]) < 20))

    return {
        "dataset": dataset,
        "suite": rule.suite,
        "ruleName": rule.name,
        "scenarioName": scenario.name,
        "scenarioCategory": scenario.category,
        "rule": serialize_rule(rule),
        "scenario": serialize_scenario(scenario),
        "sampleCount": len(samples),
        "buyCount": len(buys),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": pct(final_pnl_pct),
        "maxRunupPct": pct(max_runup_pct),
        "worstDrawdownPct": pct(worst_drawdown_pct),
        "score": pct(score),
        "avgReturnSnapshotsPct": avg_snapshots,
        "firstBuy": first_buy,
        "buys": [asdict(item) for item in buys],
        "skipReasons": skip_reasons,
        "filledMaxSpend": total_spent >= rule.max_project_spend_v,
        "lowSampleFirstBuy": low_sample,
        "riskFlags": risk_flags(rule, scenario, buys, low_sample),
    }


def serialize_rule(rule: Rule) -> dict[str, Any]:
    return {
        "name": rule.name,
        "suite": rule.suite,
        "spentThresholdV": fmt_decimal(rule.spent_threshold_v) if rule.spent_threshold_v is not None else None,
        "maxTaxRate": fmt_decimal(rule.max_tax_rate) if rule.max_tax_rate is not None else None,
        "fdvDiscount": fmt_decimal(rule.fdv_discount) if rule.fdv_discount is not None else None,
        "minRows": rule.min_cost_rows,
        "minCostRows": rule.min_cost_rows,
        "minWhaleRows": rule.min_whale_rows,
        "cooldownSec": rule.cooldown_sec,
        "burstLimit": rule.burst_limit,
        "burstWindowSec": rule.burst_window_sec,
        "burstCooldownSec": rule.burst_cooldown_sec,
        "buySizeV": fmt_decimal(rule.buy_size_v),
        "maxProjectSpendV": fmt_decimal(rule.max_project_spend_v),
    }


def serialize_scenario(scenario: Scenario) -> dict[str, Any]:
    payload = asdict(scenario)
    for key, value in list(payload.items()):
        if isinstance(value, Decimal):
            payload[key] = fmt_decimal(value)
    return payload


def risk_flags(rule: Rule, scenario: Scenario, buys: list[Buy], low_sample: bool) -> list[str]:
    flags: list[str] = []
    if rule.fdv_discount is None:
        flags.append("no_fdv_cost_guard")
    if rule.spent_threshold_v is None:
        flags.append("no_board_spent_guard")
    if rule.max_tax_rate is None:
        flags.append("no_tax_guard")
    if rule.max_project_spend_v >= Decimal("500"):
        flags.append("large_project_budget")
    if low_sample:
        flags.append("low_sample_first_buy")
    if scenario.entry_slippage_pct >= Decimal("5"):
        flags.append("high_slippage")
    if scenario.decision_delay_sec >= 30 or scenario.entry_delay_sec >= 30:
        flags.append("high_latency")
    if scenario.tax_missing or scenario.tax_offset != 0:
        flags.append("tax_signal_risk")
    if len(buys) and all(parse_decimal(buy.board_spent_v) is not None and parse_decimal(buy.board_spent_v) < Decimal("50000") for buy in buys[:1]):
        flags.append("early_board_spent")
    return flags


def make_rule(
    suite: str,
    name: str,
    *,
    spent: int | None = 100000,
    tax: int | None = 92,
    fdv: str | None = "1",
    min_rows: int = 5,
    cooldown: int = 60,
    burst: int = 2,
    max_spend: int = 300,
    min_cost_rows: int | None = None,
    min_whale_rows: int = 20,
) -> Rule:
    return Rule(
        name=name,
        suite=suite,
        spent_threshold_v=d(spent) if spent is not None else None,
        max_tax_rate=d(tax) if tax is not None else None,
        fdv_discount=d(fdv) if fdv is not None else None,
        min_cost_rows=min_rows if min_cost_rows is None else min_cost_rows,
        min_whale_rows=min_whale_rows,
        cooldown_sec=cooldown,
        burst_limit=burst,
        max_project_spend_v=d(max_spend),
    )


def build_rules() -> list[Rule]:
    rules: list[Rule] = []
    spent_values = list(range(0, 210000, 10000))
    tax_values = list(range(99, 79, -1))
    focus_tax_values = [95, 94, 93, 92, 91, 90]
    fdv_values = [None, "1", "0.99", "0.98", "0.95", "0.9"]

    rules.extend(
        make_rule("single_spent_gradient", f"spent={spent}|tax<=92|fdv", spent=spent, tax=92, fdv="1")
        for spent in spent_values
    )
    rules.extend(
        make_rule("single_tax_gradient", f"spent=100k|tax<={tax}|fdv", spent=100000, tax=tax, fdv="1")
        for tax in tax_values
    )
    rules.extend(
        make_rule(
            "single_fdv_discount_gradient",
            f"spent=100k|tax<=92|fdv={fdv_value or 'none'}",
            spent=100000,
            tax=92,
            fdv=fdv_value,
        )
        for fdv_value in fdv_values
    )
    for cooldown in [0, 30, 60, 120, 180, 300, 600]:
        rules.append(make_rule("single_cooldown_gradient", f"cooldown={cooldown}", cooldown=cooldown))
    for burst in [0, 2, 3]:
        rules.append(make_rule("single_burst_gradient", f"burst={burst}", burst=burst))
    for max_spend in [50, 100, 150, 300, 500, 1000]:
        rules.append(make_rule("single_max_spend_gradient", f"maxSpend={max_spend}", max_spend=max_spend))
    for min_rows in [0, 1, 3, 5, 10, 15, 20]:
        rules.append(make_rule("single_min_rows_gradient", f"minRows={min_rows}", min_rows=min_rows))

    rules.extend(
        [
            make_rule("ablation", "all_vars_baseline", spent=100000, tax=92, fdv="1"),
            make_rule("ablation", "only_tax92", spent=None, tax=92, fdv=None, min_rows=0),
            make_rule("ablation", "only_tax95", spent=None, tax=95, fdv=None, min_rows=0),
            make_rule("ablation", "only_spent100k", spent=100000, tax=None, fdv=None, min_rows=0),
            make_rule("ablation", "only_fdv", spent=None, tax=None, fdv="1"),
            make_rule("ablation", "spent100k_plus_tax92", spent=100000, tax=92, fdv=None, min_rows=0),
            make_rule("ablation", "spent100k_plus_fdv", spent=100000, tax=None, fdv="1"),
            make_rule("ablation", "tax92_plus_fdv", spent=None, tax=92, fdv="1"),
            make_rule("ablation", "cancel_cooldown", spent=100000, tax=92, fdv="1", cooldown=0),
            make_rule("ablation", "cancel_max_spend", spent=100000, tax=92, fdv="1", max_spend=1000),
            make_rule("ablation", "cancel_min_rows", spent=100000, tax=92, fdv="1", min_rows=0),
        ]
    )

    for spent, tax in itertools.product(range(0, 210000, 10000), focus_tax_values):
        rules.append(make_rule("combo_spent_x_tax", f"spent={spent}|tax<={tax}|fdv", spent=spent, tax=tax, fdv="1"))
        rules.append(make_rule("combo_spent_x_tax_no_fdv", f"spent={spent}|tax<={tax}|no_fdv", spent=spent, tax=tax, fdv=None, min_rows=0))
    for spent, fdv_value in itertools.product(range(50000, 130000, 10000), fdv_values):
        rules.append(
            make_rule(
                "combo_spent_x_fdv",
                f"spent={spent}|tax<=92|fdv={fdv_value or 'none'}",
                spent=spent,
                tax=92,
                fdv=fdv_value,
                min_rows=0 if fdv_value is None else 5,
            )
        )
    for tax, fdv_value in itertools.product(focus_tax_values, fdv_values):
        rules.append(
            make_rule(
                "combo_tax_x_fdv",
                f"tax<={tax}|fdv={fdv_value or 'none'}",
                spent=None,
                tax=tax,
                fdv=fdv_value,
                min_rows=0 if fdv_value is None else 5,
            )
        )
    for spent, tax, fdv_value in itertools.product(range(50000, 130000, 10000), focus_tax_values, ["1", "0.99", "0.98", "0.95"]):
        rules.append(make_rule("combo_spent_x_tax_x_fdv", f"spent={spent}|tax<={tax}|fdv={fdv_value}", spent=spent, tax=tax, fdv=fdv_value))
    for cooldown, max_spend in itertools.product([0, 30, 60, 120, 180, 300, 600], [50, 100, 150, 300, 500, 1000]):
        rules.append(make_rule("combo_cooldown_x_max_spend", f"cooldown={cooldown}|maxSpend={max_spend}", cooldown=cooldown, max_spend=max_spend))
    for min_rows, spent in itertools.product([0, 1, 3, 5, 10, 15, 20], range(50000, 130000, 10000)):
        rules.append(make_rule("combo_min_rows_x_spent", f"minRows={min_rows}|spent={spent}", spent=spent, min_rows=min_rows))
    for burst, cooldown in itertools.product([0, 2, 3], [0, 30, 60, 120, 180, 300, 600]):
        rules.append(make_rule("combo_burst_x_cooldown", f"burst={burst}|cooldown={cooldown}", burst=burst, cooldown=cooldown))

    rules.extend(
        [
            make_rule("dry_run_candidates", "conservative_100k_tax92_fdv", spent=100000, tax=92, fdv="1"),
            make_rule("dry_run_candidates", "mid_70k_tax95_fdv", spent=70000, tax=95, fdv="1"),
            make_rule("dry_run_candidates", "mid_80k_tax95_fdv", spent=80000, tax=95, fdv="1"),
            make_rule("dry_run_candidates", "mid_90k_tax95_fdv", spent=90000, tax=95, fdv="1"),
            make_rule("dry_run_candidates", "aggressive_50k_tax95_fdv", spent=50000, tax=95, fdv="1"),
            make_rule("dry_run_candidates", "aggressive_50k_tax94_fdv", spent=50000, tax=94, fdv="1"),
            make_rule("dry_run_candidates", "aggressive_50k_tax93_fdv", spent=50000, tax=93, fdv="1"),
            make_rule("control", "control_tax_only_95", spent=None, tax=95, fdv=None, min_rows=0),
            make_rule("control", "control_tax95_fdv_no_spent", spent=None, tax=95, fdv="1"),
        ]
    )
    return rules


def build_scenarios() -> list[Scenario]:
    return [
        Scenario("actual"),
        Scenario("sample_1s", category="data_latency", sample_every_sec=1),
        Scenario("sample_3s", category="data_latency", sample_every_sec=3),
        Scenario("sample_6s", category="data_latency", sample_every_sec=6),
        Scenario("sample_15s", category="data_latency", sample_every_sec=15),
        Scenario("sample_30s", category="data_latency", sample_every_sec=30),
        Scenario("delay_6s", category="data_latency", decision_delay_sec=6),
        Scenario("delay_30s", category="data_latency", decision_delay_sec=30),
        Scenario("delay_60s", category="data_latency", decision_delay_sec=60),
        Scenario("entry_delay_12s", category="execution", entry_delay_sec=12),
        Scenario("entry_delay_30s", category="execution", entry_delay_sec=30),
        Scenario("slippage_0_5pct", category="execution", entry_slippage_pct=Decimal("0.5")),
        Scenario("slippage_1pct", category="execution", entry_slippage_pct=Decimal("1")),
        Scenario("slippage_3pct", category="execution", entry_slippage_pct=Decimal("3")),
        Scenario("slippage_5pct", category="execution", entry_slippage_pct=Decimal("5")),
        Scenario("slippage_10pct", category="execution", entry_slippage_pct=Decimal("10")),
        Scenario("buy_failure_every_3", category="execution", buy_failure_every=3),
        Scenario("board_cost_under_20pct", category="board_bias", board_cost_scale=Decimal("0.8")),
        Scenario("board_cost_over_20pct", category="board_bias", board_cost_scale=Decimal("1.2")),
        Scenario("board_spent_under_20pct", category="board_bias", board_spent_scale=Decimal("0.8")),
        Scenario("board_spent_over_20pct", category="board_bias", board_spent_scale=Decimal("1.2")),
        Scenario("team_low_cost_included", category="team_pollution", board_cost_scale=Decimal("0.6"), board_spent_scale=Decimal("1.4")),
        Scenario("whale_fast_accumulation", category="whale_shape", board_spent_scale=Decimal("1.3")),
        Scenario("whale_slow_accumulation", category="whale_shape", board_spent_scale=Decimal("0.7")),
        Scenario("tax_missing", category="tax_anomaly", tax_missing=True),
        Scenario("tax_offset_minus2", category="tax_anomaly", tax_offset=Decimal("-2")),
        Scenario("tax_offset_plus2", category="tax_anomaly", tax_offset=Decimal("2")),
        Scenario("price_up_50pct", category="price_shape", price_path="price_up_50pct"),
        Scenario("price_down_30pct", category="price_shape", price_path="price_down_30pct"),
        Scenario("late_dump_50pct", category="price_shape", price_path="late_dump_50pct"),
        Scenario("early_pump_flat", category="price_shape", price_path="early_pump_flat"),
        Scenario("fast_rebound", category="price_shape", price_path="fast_rebound"),
        Scenario("choppy", category="price_shape", price_path="choppy"),
        Scenario("combined_bad", category="combined", sample_every_sec=30, decision_delay_sec=30, entry_delay_sec=30, entry_slippage_pct=Decimal("5"), board_cost_scale=Decimal("1.2"), tax_offset=Decimal("1")),
    ]


def dataset_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}
    ts_values = timestamps(samples)
    taxes = [parse_decimal(row.get("buyTaxRate")) for row in samples if parse_decimal(row.get("buyTaxRate")) is not None]
    board_spent = [parse_decimal(row.get("boardSpentV")) or Decimal("0") for row in samples]
    return {
        "sampleCount": len(samples),
        "firstTimestamp": ts_values[0],
        "lastTimestamp": ts_values[-1],
        "durationSec": ts_values[-1] - ts_values[0],
        "taxMin": fmt_decimal(min(taxes)) if taxes else None,
        "taxMax": fmt_decimal(max(taxes)) if taxes else None,
        "boardSpentMaxV": fmt_decimal(max(board_spent), 3) if board_spent else None,
    }


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = [item for item in items if int(item.get("buyCount") or 0) > 0]
    positive = [item for item in triggered if number(item.get("finalPnlPct")) > 0]
    pct_values = [number(item.get("finalPnlPct")) for item in triggered]
    return {
        "count": len(items),
        "triggered": len(triggered),
        "positive": len(positive),
        "positiveRate": round(len(positive) / len(triggered), 4) if triggered else 0,
        "avgFinalPnlPct": round(statistics.mean(pct_values), 4) if pct_values else 0,
        "medianFinalPnlPct": round(statistics.median(pct_values), 4) if pct_values else 0,
        "minFinalPnlPct": round(min(pct_values), 4) if pct_values else 0,
        "maxFinalPnlPct": round(max(pct_values), 4) if pct_values else 0,
    }


def table_line(cells: list[Any]) -> str:
    escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
    return "| " + " | ".join(escaped) + " |"


def compact_result(item: dict[str, Any]) -> str:
    first = item.get("firstBuy") or {}
    return (
        f"{item.get('dataset')} / {item.get('ruleName')} / {item.get('scenarioName')}: "
        f"{item.get('buyCount')} buys, {item.get('totalSpentV')}V, "
        f"{item.get('finalPnlPct')}%, first tax {first.get('tax_rate')}, "
        f"board {first.get('board_spent_v')}"
    )


CRITICAL_RISK_FLAGS = {
    "no_fdv_cost_guard",
    "no_board_spent_guard",
    "low_sample_first_buy",
    "high_slippage",
    "high_latency",
    "tax_signal_risk",
}

REJECT_RISK_FLAGS = {
    "no_fdv_cost_guard",
    "no_board_spent_guard",
    "low_sample_first_buy",
    "high_slippage",
    "high_latency",
    "tax_signal_risk",
}


def build_report(results: list[dict[str, Any]], datasets: dict[str, list[dict[str, Any]]], rules: list[Rule], scenarios: list[Scenario], args: argparse.Namespace) -> dict[str, Any]:
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for item in results:
        by_suite.setdefault(str(item["suite"]), []).append(item)

    suite_summary = {name: summarize(items) for name, items in sorted(by_suite.items())}
    triggered = [item for item in results if int(item.get("buyCount") or 0) > 0]
    top_return = sorted(triggered, key=lambda item: number(item.get("finalPnlPct")), reverse=True)[: args.top]
    safe_triggered = [
        item
        for item in triggered
        if not (set(item.get("riskFlags", [])) & CRITICAL_RISK_FLAGS)
    ]
    top_score_source = safe_triggered or triggered
    top_score = sorted(top_score_source, key=lambda item: number(item.get("score")), reverse=True)[: args.top]
    failure_cases = sorted(triggered, key=lambda item: number(item.get("finalPnlPct")))[: args.top]

    stable_zone = []
    for name, items in sorted(by_suite.items()):
        summary = summarize(items)
        if summary["triggered"] >= 3 and summary["positiveRate"] >= 0.8 and summary["minFinalPnlPct"] > 0:
            stable_zone.append({"suite": name, **summary})
    stable_zone = sorted(stable_zone, key=lambda item: (item["medianFinalPnlPct"], item["positiveRate"]), reverse=True)[: args.top]

    dry_run_candidates = [
        item
        for item in triggered
        if item["suite"] == "dry_run_candidates"
        and item["scenarioName"] == "actual"
        and "low_sample_first_buy" not in item.get("riskFlags", [])
        and number(item.get("finalPnlPct")) > 0
    ]
    reject_list = [
        item
        for item in triggered
        if set(item.get("riskFlags", [])) & REJECT_RISK_FLAGS
        or item["suite"] == "control"
        or (item.get("filledMaxSpend") and number(item.get("finalPnlPct")) <= 0)
        or (number(item.get("worstDrawdownPct")) < -25 and number(item.get("finalPnlPct")) <= 0)
    ][: args.top]

    return {
        "samples": args.samples,
        "datasetStats": {name: dataset_stats(samples) for name, samples in datasets.items()},
        "assumptions": {
            "readOnly": True,
            "productionDbTouched": False,
            "tradeSent": False,
            "objective": "stable profit plus low false-trigger risk",
            "defaultDryRunBudgetV": "300",
            "hardGates": {
                "minWhaleRows": 20,
                "minBoardSpentV": "50000",
                "maxTaxRate": "95",
            },
            "lowSamplePolicy": "cost rows below 5 or whale-board rows below 20 is recorded as risk and excluded from dry-run candidates",
            "returnSnapshots": [*SNAPSHOT_OFFSETS_SEC.keys(), "end"],
        },
        "ruleCount": len(rules),
        "scenarioCount": len(scenarios),
        "resultCount": len(results),
        "suiteSummary": suite_summary,
        "topByFinalReturn": top_return,
        "topByRiskAdjustedScore": top_score,
        "stableZone": stable_zone,
        "failureCases": failure_cases,
        "variableContribution": variable_contribution(results),
        "overfitWarnings": overfit_warnings(results),
        "dryRunCandidates": dry_run_candidates[: args.top],
        "rejectList": reject_list,
        "results": results,
    }


def variable_contribution(results: list[dict[str, Any]]) -> dict[str, Any]:
    sr_actual = [item for item in results if item["dataset"].lower().startswith("sr") and item["scenarioName"] == "actual"]
    preferred = [item for item in sr_actual if item["dataset"] == "sr_chainstack_highres_strategy"]
    actual = preferred or sr_actual
    by_rule: dict[str, dict[str, Any]] = {}
    for item in actual:
        by_rule.setdefault(item["ruleName"], item)
    baseline = by_rule.get("all_vars_baseline") or by_rule.get("conservative_100k_tax92_fdv")
    if not baseline:
        return {}
    base_pct = number(baseline.get("finalPnlPct"))
    keys = [
        "only_tax92",
        "only_tax95",
        "only_spent100k",
        "only_fdv",
        "spent100k_plus_tax92",
        "spent100k_plus_fdv",
        "tax92_plus_fdv",
        "cancel_cooldown",
        "cancel_max_spend",
        "cancel_min_rows",
    ]
    return {
        key: {
            "finalPnlPct": by_rule[key].get("finalPnlPct"),
            "deltaVsBaselinePct": round(number(by_rule[key].get("finalPnlPct")) - base_pct, 4),
            "buyCount": by_rule[key].get("buyCount"),
            "riskFlags": by_rule[key].get("riskFlags"),
        }
        for key in keys
        if key in by_rule
    }


def overfit_warnings(results: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if len({item["dataset"] for item in results}) < 3:
        warnings.append("Less than three datasets were tested; strategy ranking is sample-sensitive.")
    early = [item for item in results if "early_board_spent" in item.get("riskFlags", []) and int(item.get("buyCount") or 0) > 0]
    if early:
        warnings.append("Some high-return cases trigger with boardSpentV below 50k; treat as early-sample risk.")
    no_fdv = [item for item in results if "no_fdv_cost_guard" in item.get("riskFlags", []) and int(item.get("buyCount") or 0) > 0]
    if no_fdv:
        warnings.append("Tax-only or no-FDV-cost cases often buy more exposure; they are controls, not trade candidates.")
    return warnings


def write_markdown(report: dict[str, Any], output: Path, top: int) -> None:
    lines: list[str] = []
    lines.append("# Strategy Test Matrix Report")
    lines.append("")
    lines.append("本报告由 `scripts/ops/strategy_test_matrix_runner.py` 生成。只读 replay samples，不写生产数据库，不发交易。")
    lines.append("")
    lines.append("## Datasets")
    for name, stats in report["datasetStats"].items():
        lines.append(f"- {name}: {stats}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- ruleCount: {report['ruleCount']}")
    lines.append(f"- scenarioCount: {report['scenarioCount']}")
    lines.append(f"- resultCount: {report['resultCount']}")
    lines.append("")
    lines.append("## Report Notes")
    lines.append("- `Top By Risk Adjusted Score` excludes critical-risk cases such as no FDV guard, no board-spent guard, low-sample first buy, high latency, high slippage, or tax-signal anomalies.")
    lines.append("- `Reject List` means rejected as a direct dry-run / trading candidate. Some rejected controls can still be useful as ablation evidence.")
    lines.append("- `Dry-run Candidates` only includes actual-scenario candidates with positive final PnL and no low-sample first buy.")
    lines.append("")
    lines.append("## Suite Summary")
    lines.append(table_line(["Suite", "Count", "Triggered", "Positive", "Positive Rate", "Median PnL %", "Min PnL %", "Max PnL %"]))
    lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]))
    for name, summary in report["suiteSummary"].items():
        lines.append(
            table_line(
                [
                    name,
                    summary["count"],
                    summary["triggered"],
                    summary["positive"],
                    summary["positiveRate"],
                    summary["medianFinalPnlPct"],
                    summary["minFinalPnlPct"],
                    summary["maxFinalPnlPct"],
                ]
            )
        )
    lines.append("")
    append_result_table(lines, "Top By Final Return", report["topByFinalReturn"][:top])
    append_result_table(lines, "Top By Risk Adjusted Score", report["topByRiskAdjustedScore"][:top])
    lines.append("## Stable Zone")
    if report["stableZone"]:
        lines.append(table_line(["Suite", "Triggered", "Positive Rate", "Median PnL %", "Min PnL %", "Max PnL %"]))
        lines.append(table_line(["---", "---:", "---:", "---:", "---:", "---:"]))
        for item in report["stableZone"]:
            lines.append(table_line([item["suite"], item["triggered"], item["positiveRate"], item["medianFinalPnlPct"], item["minFinalPnlPct"], item["maxFinalPnlPct"]]))
    else:
        lines.append("- No stable zone found under current thresholds.")
    lines.append("")
    append_result_table(lines, "Failure Cases", report["failureCases"][:top])
    append_result_table(lines, "Dry-run Candidates", report["dryRunCandidates"][:top])
    append_result_table(lines, "Reject List", report["rejectList"][:top])
    lines.append("## Variable Contribution")
    if report["variableContribution"]:
        lines.append(table_line(["Rule", "PnL %", "Delta vs Baseline", "Buy Count", "Risk Flags"]))
        lines.append(table_line(["---", "---:", "---:", "---:", "---"]))
        for key, item in report["variableContribution"].items():
            lines.append(table_line([key, item["finalPnlPct"], item["deltaVsBaselinePct"], item["buyCount"], ", ".join(item["riskFlags"])]))
    else:
        lines.append("- Not enough baseline data.")
    lines.append("")
    lines.append("## Overfit Warnings")
    for warning in report["overfitWarnings"]:
        lines.append(f"- {warning}")
    if not report["overfitWarnings"]:
        lines.append("- None.")
    lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_result_table(lines: list[str], title: str, items: list[dict[str, Any]]) -> None:
    lines.append(f"## {title}")
    if not items:
        lines.append("- None.")
        lines.append("")
        return
    lines.append(table_line(["Dataset", "Suite", "Rule", "Scenario", "Buys", "Spent V", "PnL %", "Score", "First Buy", "Risk Flags"]))
    lines.append(table_line(["---", "---", "---", "---", "---:", "---:", "---:", "---:", "---", "---"]))
    for item in items:
        first = item.get("firstBuy") or {}
        first_text = "-"
        if first:
            first_text = f"tax {first.get('tax_rate')}, board {first.get('board_spent_v')}, fdv {first.get('entry_tax_fdv_wan_usd')}, cost {first.get('board_cost_wan_usd')}"
        lines.append(
            table_line(
                [
                    item.get("dataset"),
                    item.get("suite"),
                    item.get("ruleName"),
                    item.get("scenarioName"),
                    item.get("buyCount"),
                    item.get("totalSpentV"),
                    item.get("finalPnlPct"),
                    item.get("score"),
                    first_text,
                    ", ".join(item.get("riskFlags") or []),
                ]
            )
        )
    lines.append("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run unified launch strategy test matrix.")
    parser.add_argument("--samples", nargs="+", required=True)
    parser.add_argument("--output-json", default="data/backtests/strategy-test-matrix-report.json")
    parser.add_argument("--output-md", default="docs/phases/phase-052-strategy-test-matrix-report.md")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--actual-only", action="store_true", help="Run only actual scenario for all rules.")
    parser.add_argument("--candidate-scenarios-only", action="store_true", help="Run scenario stress only for dry-run/control candidate rules.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    datasets: dict[str, list[dict[str, Any]]] = {}
    for raw_path in args.samples:
        path = Path(raw_path)
        datasets[dataset_label(path)] = load_samples(path)

    rules = build_rules()
    scenarios = [Scenario("actual")] if args.actual_only else build_scenarios()
    results: list[dict[str, Any]] = []
    for dataset, samples in datasets.items():
        for rule in rules:
            scenario_list = scenarios
            if args.candidate_scenarios_only and rule.suite not in {"dry_run_candidates", "control"}:
                scenario_list = [Scenario("actual")]
            for scenario in scenario_list:
                results.append(evaluate(samples, rule, scenario, dataset=dataset))

    report = build_report(results, datasets, rules, scenarios, args)
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md), args.top)
    print(
        json.dumps(
            {
                "outputJson": args.output_json,
                "outputMd": args.output_md,
                "datasets": len(datasets),
                "rules": len(rules),
                "scenarios": len(scenarios),
                "results": len(results),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
