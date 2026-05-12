#!/usr/bin/env python3
"""Smoke tests for launch_rpc_pressure_probe.py without network."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_rpc_pressure_probe import channel_p90, endpoint_specs, is_green, summarize  # noqa: E402


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_endpoint_specs_dedupes_aliases() -> None:
    cfg = SimpleNamespace(
        http_rpc_url="https://main.example",
        backfill_http_rpc_urls=["https://main.example"],
    )
    specs = endpoint_specs(cfg, "https://exec.example")
    assert_eq(len(specs), 2, "spec count")
    assert_eq(specs[0].label, "main_http", "main label")
    assert_eq(specs[0].aliases, ("backfill_http",), "main aliases")
    assert_eq(specs[1].label, "execution", "execution label")


def test_summary_and_thresholds() -> None:
    samples = [
        {
            "endpoints": [
                {
                    "label": "main_http",
                    "rows": [
                        {"op": "blockNumber", "ok": True, "ms": 100.0},
                        {"op": "gasPrice", "ok": True, "ms": 120.0},
                    ],
                },
                {
                    "label": "execution",
                    "rows": [
                        {"op": "blockNumber", "ok": True, "ms": 200.0},
                        {"op": "gasPrice", "ok": True, "ms": 220.0},
                    ],
                },
            ],
            "market": {"ok": True, "ms": 180.0},
        }
    ]
    summary = summarize(samples)
    assert_eq(channel_p90(summary, "main_http"), 120.0, "main p90")
    assert_eq(channel_p90(summary, "execution"), 220.0, "execution p90")
    assert_eq(channel_p90(summary, "market"), 180.0, "market p90")
    args = SimpleNamespace(max_main_p90_ms=500, max_execution_p90_ms=500, max_market_p90_ms=500)
    assert_eq(is_green(summary, args), True, "green thresholds")
    args = SimpleNamespace(max_main_p90_ms=500, max_execution_p90_ms=210, max_market_p90_ms=500)
    assert_eq(is_green(summary, args), False, "execution threshold blocks")


def test_summary_counts_alias_channels() -> None:
    summary = summarize(
        [
            {
                "endpoints": [
                    {
                        "label": "main_http",
                        "aliases": ["execution"],
                        "rows": [{"op": "blockNumber", "ok": True, "ms": 100.0}],
                    }
                ],
                "market": None,
            }
        ]
    )
    assert_eq(channel_p90(summary, "main_http"), 100.0, "main alias p90")
    assert_eq(channel_p90(summary, "execution"), 100.0, "execution alias p90")


def test_summary_errors_are_not_green() -> None:
    summary = summarize(
        [
            {
                "endpoints": [
                    {
                        "label": "execution",
                        "rows": [{"op": "blockNumber", "ok": False, "ms": 10.0, "error": "boom"}],
                    }
                ],
                "market": None,
            }
        ]
    )
    args = SimpleNamespace(max_main_p90_ms=500, max_execution_p90_ms=500, max_market_p90_ms=500)
    assert_eq(is_green(summary, args), False, "error blocks green")


def main() -> None:
    test_endpoint_specs_dedupes_aliases()
    test_summary_and_thresholds()
    test_summary_counts_alias_channels()
    test_summary_errors_are_not_green()
    print("launch_rpc_pressure_probe tests ok")


if __name__ == "__main__":
    main()
