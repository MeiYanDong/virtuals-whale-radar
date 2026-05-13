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


def signal(
    *,
    roi: str | None = None,
    buy_v: str | None = None,
    tx: str | None = None,
    ts: int = 100,
) -> DualSellInput:
    return DualSellInput(
        timestamp=ts,
        tax_rate=Decimal("30"),
        current_roi_pct=Decimal(roi) if roi is not None else None,
        current_balance_raw=1000,
        latest_buy_v=Decimal(buy_v) if buy_v is not None else None,
        latest_buy_tx_hash=tx,
    )


def test_roi_or_large_buy_alone_does_not_sell() -> None:
    state = DualSellState(total_position_raw=1000)
    roi_only = evaluate_dual_sell(state=state, signal=signal(roi="55"))
    assert_eq(roi_only.should_sell, False, "roi alone no sell")
    assert_eq(roi_only.reason, "large_buy_roi_not_confirmed", "roi alone reason")

    large_only = evaluate_dual_sell(state=state, signal=signal(buy_v="8000", tx="0xaaa"))
    assert_eq(large_only.should_sell, False, "large buy alone no sell")
    assert_eq(large_only.reason, "large_buy_roi_not_confirmed", "large alone reason")
    assert_eq(large_only.large_buy_tx_hash, "0xaaa", "large tx surfaced for explanation")


def test_large_buy_requires_roi_confirmation() -> None:
    state = DualSellState(total_position_raw=1000)
    decision = evaluate_dual_sell(state=state, signal=signal(roi="32", buy_v="5000", tx="0xaaa"))
    assert_eq(decision.should_sell, True, "large 5k + roi 30 sell")
    assert_eq(decision.total_sell_pct, Decimal("30"), "confirmed 5k pct")
    assert_eq(decision.amount_raw, 300, "confirmed 5k amount")
    assert_eq(decision.roi_delta_pct, Decimal("0"), "confirmed roi tracked as gate")
    assert_eq(decision.large_buy_delta_pct, Decimal("30"), "confirmed large pct")
    assert_eq(decision.trigger_reasons, ("大额买入且收益率达标",), "confirmed reason")

    apply_successful_sell(state=state, decision=decision, timestamp=100)
    repeat = evaluate_dual_sell(state=state, signal=signal(roi="40", buy_v="5500", tx="0xaaa", ts=200))
    assert_eq(repeat.should_sell, False, "same tx ignored after success")
    upgrade = evaluate_dual_sell(state=state, signal=signal(roi="55", buy_v="8000", tx="0xbbb", ts=200))
    assert_eq(upgrade.total_sell_pct, Decimal("20"), "large 8k upgrade pct")
    assert_eq(upgrade.amount_raw, 200, "large 8k upgrade amount")


def test_threshold_pair_uses_lower_confirmed_tier() -> None:
    state = DualSellState(total_position_raw=1000)
    roi_high_large_low = evaluate_dual_sell(state=state, signal=signal(roi="55", buy_v="5000", tx="0xbbb"))
    assert_eq(roi_high_large_low.total_sell_pct, Decimal("30"), "roi high but 5k large pct")
    assert_eq(roi_high_large_low.amount_raw, 300, "roi high but 5k large amount")

    roi_low_large_high = evaluate_dual_sell(state=state, signal=signal(roi="32", buy_v="8200", tx="0xccc"))
    assert_eq(roi_low_large_high.total_sell_pct, Decimal("30"), "8k large but roi low pct")
    assert_eq(roi_low_large_high.amount_raw, 300, "8k large but roi low amount")

    both_high = evaluate_dual_sell(state=state, signal=signal(roi="55", buy_v="8200", tx="0xddd"))
    assert_eq(both_high.total_sell_pct, Decimal("50"), "both high pct")
    assert_eq(both_high.amount_raw, 500, "both high amount")


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
    assert_eq(capped.requested_total_sell_pct, Decimal("50"), "capped requested pct")
    assert_eq(capped.total_sell_pct, Decimal("12"), "capped actual pct")
    assert_eq(capped.amount_raw, 120, "capped amount")
    assert_eq(capped.roi_delta_pct, Decimal("0"), "capped roi pct")
    assert_eq(capped.large_buy_delta_pct, Decimal("12.0"), "capped large pct")
    state_after_cap = DualSellState(total_position_raw=1000)
    apply_successful_sell(state=state_after_cap, decision=capped, timestamp=300)
    assert_eq(state_after_cap.roi_sold_pct, Decimal("0"), "capped applied roi")
    assert_eq(state_after_cap.large_buy_sold_pct, Decimal("12.0"), "capped applied large")


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
    assert_eq(below.large_buy_tx_hash, None, "below threshold tx not surfaced")


def main() -> None:
    test_roi_or_large_buy_alone_does_not_sell()
    test_large_buy_requires_roi_confirmation()
    test_threshold_pair_uses_lower_confirmed_tier()
    test_cooldown_and_balance_cap()
    test_tax_gate_and_threshold_boundaries()
    print("launch_sell_strategy tests ok")


if __name__ == "__main__":
    main()
