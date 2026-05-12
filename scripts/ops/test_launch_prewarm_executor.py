#!/usr/bin/env python3
"""Smoke tests for launch_prewarm_executor state restoration."""

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

from launch_prewarm_executor import rebuild_strategy_state_from_sent_rows  # noqa: E402


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_rebuild_strategy_state_from_sent_rows() -> None:
    state = rebuild_strategy_state_from_sent_rows(
        [
            {
                "id": 2,
                "created_at": 200,
                "updated_at": 200,
                "action": "would_buy",
                "tax_rate": "92",
                "buy_size_v": "50",
                "entry_tax_fdv_wan_usd": "331",
            },
            {
                "id": 3,
                "created_at": 300,
                "updated_at": 300,
                "action": "sell",
                "tax_rate": "91",
                "buy_size_v": "100",
                "entry_tax_fdv_wan_usd": "100",
            },
            {
                "id": 1,
                "created_at": 100,
                "updated_at": 100,
                "action": "would_buy",
                "tax_rate": "93",
                "buy_size_v": "25",
                "entry_tax_fdv_wan_usd": "219",
            },
        ]
    )

    assert_eq(state.bought_tax_rates, {"92", "93"}, "bought tax rates")
    assert_eq(state.total_spent_v, Decimal("75"), "total spent")
    assert_eq(state.weighted_cost_numerator, Decimal("22025"), "weighted numerator")
    assert_eq(state.own_weighted_cost, Decimal("22025") / Decimal("75"), "weighted cost")
    assert_eq(state.pending_pause_buy, {"taxRate": "92", "entryTaxFdvWanUsd": "331"}, "pending pause")


def main() -> None:
    test_rebuild_strategy_state_from_sent_rows()
    print("launch_prewarm_executor tests ok")


if __name__ == "__main__":
    main()
