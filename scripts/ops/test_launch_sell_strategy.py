#!/usr/bin/env python3
"""Smoke tests for launch_sell_strategy.py."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_sell_strategy import (  # noqa: E402
    DualSellInput,
    DualSellState,
    apply_successful_sell,
    evaluate_dual_sell,
)


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def signal(*, roi: str | None = None, buy_v: str | None = None, tx: str | None = None, ts: int = 100) -> DualSellInput:
    return DualSellInput(
        timestamp=ts,
        tax_rate=Decimal("30"),
        current_roi_pct=Decimal(roi) if roi is not None else None,
        current_balance_raw=1000,
        latest_buy_v=Decimal(buy_v) if buy_v is not None else None,
        latest_buy_tx_hash=tx,
    )


def test_roi_track_sells_independently() -> None:
    state = DualSellState(total_position_raw=1000)
    decision = evaluate_dual_sell(state=state, signal=signal(roi="32"))
    assert_eq(decision.should_sell, True, "roi 30 sell")
    assert_eq(decision.total_sell_pct, Decimal("30"), "roi 30 pct")
    assert_eq(decision.amount_raw, 300, "roi 30 amount")
    assert_eq(decision.trigger_reasons, ("收益率达标",), "roi reason")

    apply_successful_sell(state=state, decision=decision, timestamp=100)
    later = evaluate_dual_sell(state=state, signal=signal(roi="55", ts=200))
    assert_eq(later.total_sell_pct, Decimal("20"), "roi upgrade pct")
    assert_eq(later.amount_raw, 200, "roi upgrade amount")


def test_large_buy_track_sells_independently() -> None:
    state = DualSellState(total_position_raw=1000)
    decision = evaluate_dual_sell(state=state, signal=signal(buy_v="5000", tx="0xaaa"))
    assert_eq(decision.should_sell, True, "large 5k sell")
    assert_eq(decision.total_sell_pct, Decimal("30"), "large 5k pct")
    assert_eq(decision.amount_raw, 300, "large 5k amount")
    assert_eq(decision.trigger_reasons, ("大额买入达标",), "large reason")

    apply_successful_sell(state=state, decision=decision, timestamp=100)
    repeat = evaluate_dual_sell(state=state, signal=signal(buy_v="5500", tx="0xaaa", ts=200))
    assert_eq(repeat.should_sell, False, "same tx ignored after success")
    upgrade = evaluate_dual_sell(state=state, signal=signal(buy_v="8000", tx="0xbbb", ts=200))
    assert_eq(upgrade.total_sell_pct, Decimal("20"), "large 8k upgrade pct")
    assert_eq(upgrade.amount_raw, 200, "large 8k upgrade amount")


def test_simultaneous_triggers_merge_into_one_order() -> None:
    state = DualSellState(total_position_raw=1000)
    decision = evaluate_dual_sell(state=state, signal=signal(roi="55", buy_v="8200", tx="0xbbb"))
    assert_eq(decision.should_sell, True, "simultaneous sell")
    assert_eq(decision.roi_delta_pct, Decimal("50"), "simultaneous roi pct")
    assert_eq(decision.large_buy_delta_pct, Decimal("50"), "simultaneous large pct")
    assert_eq(decision.total_sell_pct, Decimal("100"), "simultaneous total pct")
    assert_eq(decision.amount_raw, 1000, "simultaneous amount")
    assert_eq(decision.trigger_reasons, ("收益率达标", "大额买入达标"), "simultaneous reasons")


def test_cooldown_and_balance_cap() -> None:
    state = DualSellState(total_position_raw=1000, cooldown_until=200)
    blocked = evaluate_dual_sell(state=state, signal=signal(roi="55", ts=150))
    assert_eq(blocked.should_sell, False, "cooldown blocked")
    assert_eq(blocked.reason, "cooldown", "cooldown reason")

    capped = evaluate_dual_sell(
        state=DualSellState(total_position_raw=1000),
        signal=DualSellInput(
            timestamp=300,
            tax_rate=Decimal("30"),
            current_roi_pct=Decimal("55"),
            current_balance_raw=120,
            latest_buy_v=Decimal("8200"),
            latest_buy_tx_hash="0xccc",
        ),
    )
    assert_eq(capped.requested_total_sell_pct, Decimal("100"), "capped requested pct")
    assert_eq(capped.total_sell_pct, Decimal("12"), "capped actual pct")
    assert_eq(capped.amount_raw, 120, "capped amount")
    assert_eq(capped.roi_delta_pct, Decimal("6.0"), "capped roi pct")
    assert_eq(capped.large_buy_delta_pct, Decimal("6.0"), "capped large pct")
    state_after_cap = DualSellState(total_position_raw=1000)
    apply_successful_sell(state=state_after_cap, decision=capped, timestamp=300)
    assert_eq(state_after_cap.roi_sold_pct, Decimal("6.0"), "capped applied roi")
    assert_eq(state_after_cap.large_buy_sold_pct, Decimal("6.0"), "capped applied large")


def test_tax_gate_and_threshold_boundaries() -> None:
    outside = evaluate_dual_sell(
        state=DualSellState(total_position_raw=1000),
        signal=DualSellInput(
            timestamp=100,
            tax_rate=Decimal("31"),
            current_roi_pct=Decimal("80"),
            current_balance_raw=1000,
            latest_buy_v=Decimal("9000"),
            latest_buy_tx_hash="0xddd",
        ),
    )
    assert_eq(outside.should_sell, False, "tax outside blocked")
    assert_eq(outside.reason, "tax_not_in_sell_window", "tax outside reason")

    below = evaluate_dual_sell(
        state=DualSellState(total_position_raw=1000),
        signal=signal(roi="29.9999", buy_v="4999.9999", tx="0xeee"),
    )
    assert_eq(below.should_sell, False, "below thresholds no sell")


def main() -> None:
    test_roi_track_sells_independently()
    test_large_buy_track_sells_independently()
    test_simultaneous_triggers_merge_into_one_order()
    test_cooldown_and_balance_cap()
    test_tax_gate_and_threshold_boundaries()
    print("launch_sell_strategy tests ok")


if __name__ == "__main__":
    main()
