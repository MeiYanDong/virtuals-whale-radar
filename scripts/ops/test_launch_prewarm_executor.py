#!/usr/bin/env python3
"""Smoke tests for launch_prewarm_executor state restoration."""

from __future__ import annotations

import sys
from argparse import Namespace
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_prewarm_executor import (  # noqa: E402
    compact_runtime_config,
    rebuild_strategy_state_from_sent_rows,
    runtime_dynamic_config,
    runtime_effective_args,
)


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


def test_runtime_config_helpers() -> None:
    row = {
        "version": 3,
        "enabled": 1,
        "mode": "broadcast",
        "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
        "rule_name": "gate_5k_tax95_fdv_one_per_tax",
        "base_buy_v": "100",
        "dip_buy_v": "200",
        "dip_from_own_cost_pct": "25",
        "flat_pause_pct": "12",
        "max_buy_v": "200",
        "max_project_v": "500",
        "updated_at": 123,
    }
    config = runtime_dynamic_config(row)
    assert_eq(config.base_buy_v, Decimal("100"), "runtime base")
    assert_eq(config.dip_buy_v, Decimal("200"), "runtime dip")
    assert_eq(config.dip_from_own_cost_pct, Decimal("25"), "runtime dip threshold")
    assert_eq(config.flat_pause_pct, Decimal("12"), "runtime flat threshold")

    args = Namespace(max_buy_v=Decimal("50"), max_project_v=Decimal("150"), mode="broadcast")
    effective = runtime_effective_args(args, row)
    assert_eq(effective.max_buy_v, Decimal("200"), "effective max buy")
    assert_eq(effective.max_project_v, Decimal("500"), "effective max project")
    assert_eq(args.max_buy_v, Decimal("50"), "original args unchanged")

    compact = compact_runtime_config(row, effective)
    assert_eq(compact["hasOverride"], True, "compact override")
    assert_eq(compact["version"], 3, "compact version")
    assert_eq(compact["baseBuyV"], "100", "compact base")


def main() -> None:
    test_rebuild_strategy_state_from_sent_rows()
    test_runtime_config_helpers()
    print("launch_prewarm_executor tests ok")


if __name__ == "__main__":
    main()
