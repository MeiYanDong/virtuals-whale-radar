#!/usr/bin/env python3
"""Smoke tests for launch_sell_executor.py pure state reconstruction."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_sell_executor import (  # noqa: E402
    build_position_from_records,
    current_roi_pct,
    dual_state_from_position,
    latest_unseen_buy_event,
)


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def receipt(deltas: dict) -> str:
    return json.dumps({"status": "0x1", "transferDeltas": deltas}, separators=(",", ":"))


def intent(decision: dict | None = None) -> str:
    return json.dumps({"decision": decision or {}}, separators=(",", ":"))


def test_position_rebuild_from_buy_and_sell_receipts() -> None:
    rows = [
        {
            "action": "would_buy",
            "status": "receipt_success",
            "trade_sent": 1,
            "buy_size_v": "25",
            "entry_tax_fdv_wan_usd": "100",
            "receipt_json": receipt({"targetReceivedRaw": "1000", "virtualSpentWei": str(25 * 10**18)}),
            "intent_json": "{}",
        },
        {
            "action": "sell",
            "status": "receipt_success",
            "trade_sent": 1,
            "receipt_json": receipt({"soldTokenSpentRaw": "300", "virtualReceivedWei": str(40 * 10**18)}),
            "intent_json": intent(
                {
                    "amountRaw": "300",
                    "totalSellPct": "30",
                    "roiDeltaPct": "30",
                    "largeBuyDeltaPct": "0",
                    "largeBuyTxHash": None,
                }
            ),
            "updated_at": 1000,
        },
        {
            "action": "sell",
            "status": "receipt_success",
            "trade_sent": 1,
            "receipt_json": receipt({"soldTokenSpentRaw": "200", "virtualReceivedWei": str(35 * 10**18)}),
            "intent_json": intent(
                {
                    "amountRaw": "200",
                    "totalSellPct": "20",
                    "roiDeltaPct": "0",
                    "largeBuyDeltaPct": "20",
                    "largeBuyTxHash": "0xabc",
                }
            ),
            "updated_at": 1100,
        },
    ]
    position = build_position_from_records(rows=rows, current_balance_raw=500)
    assert_eq(position["totalPositionRaw"], 1000, "total position")
    assert_eq(position["currentBalanceRaw"], 500, "current balance")
    assert_eq(position["soldTokenRaw"], 500, "sold raw")
    assert_eq(position["totalSpentV"], Decimal("25"), "spent v")
    assert_eq(position["buyUnits"], Decimal("0.25"), "buy units")
    assert_eq(position["roiSoldPct"], Decimal("30"), "roi sold pct")
    assert_eq(position["largeBuySoldPct"], Decimal("20"), "large sold pct")
    assert_eq(position["cooldownUntil"], 1160, "cooldown")

    state = dual_state_from_position(position)
    assert_eq(state.total_position_raw, 1000, "state total")
    assert_eq(state.roi_sold_pct, Decimal("30"), "state roi")
    assert_eq(state.large_buy_sold_pct, Decimal("20"), "state large")
    assert_eq("0xabc" in state.processed_large_buy_txs, True, "processed large tx")


def test_roi_uses_auto_buy_units_and_spot_fdv() -> None:
    position = {
        "totalSpentV": Decimal("25"),
        "buyUnits": Decimal("0.25"),
    }
    roi = current_roi_pct(position, {"liveFdvUsd": "1500000"})
    assert_eq(roi, Decimal("50.0"), "roi pct")


def test_latest_unseen_buy_event_marks_seen() -> None:
    class Cursor:
        def fetchall(self):
            return [
                {"tx_hash": "0x1", "block_timestamp": 100, "block_number": 1, "buyer": "a", "spent_v_est": "6000"},
                {"tx_hash": "0x2", "block_timestamp": 101, "block_number": 2, "buyer": "b", "spent_v_est": "8000"},
            ]

    class Conn:
        def execute(self, *_args):
            return Cursor()

    class Storage:
        conn = Conn()

    class Bot:
        storage = Storage()

    seen: set[str] = set()
    event = latest_unseen_buy_event(Bot(), project_name="T", since_ts=0, seen_txs=seen)
    assert_eq(event["tx_hash"], "0x2", "largest unseen")
    assert_eq(seen, {"0x1", "0x2"}, "seen set")
    assert_eq(latest_unseen_buy_event(Bot(), project_name="T", since_ts=0, seen_txs=seen), None, "no repeats")


def main() -> None:
    test_position_rebuild_from_buy_and_sell_receipts()
    test_roi_uses_auto_buy_units_and_spot_fdv()
    test_latest_unseen_buy_event_marks_seen()
    print("launch_sell_executor tests ok")


if __name__ == "__main__":
    main()
