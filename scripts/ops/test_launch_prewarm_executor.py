#!/usr/bin/env python3
"""Smoke tests for launch_prewarm_executor state restoration."""

from __future__ import annotations

import asyncio
import sys
from argparse import Namespace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_prewarm_executor import (  # noqa: E402
    DEFAULT_FOLLOW_TRADE_RULE,
    DEFAULT_FOLLOW_TRADE_STRATEGY,
    SignedBuyCandidate,
    compact_runtime_config,
    eligible_fdv_limit_orders,
    fdv_limit_order_retryable_reason,
    fdv_limit_order_intent,
    follow_trade_buy_size,
    follow_trade_source_seen,
    open_sniper_first_buy_sent,
    rebuild_strategy_state_from_sent_rows,
    reconcile_standard_buy_receipts,
    runtime_dynamic_config,
    runtime_effective_args,
    sample_tax_fdv_wan,
    sent_project_v_all_strategies,
    signed_candidate_key,
    take_signed_candidate,
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
        "fdv_limit_enabled": 1,
        "fdv_limit_wan_usd": "300",
        "follow_enabled": 1,
        "follow_wallet": "0xe0b51bbf7af8bff0a8cd422e4b5f17aa0824969d",
        "follow_ratio_pct": "50",
        "max_buy_v": "200",
        "max_project_v": "500",
        "updated_at": 123,
    }
    config = runtime_dynamic_config(row)
    assert_eq(config.base_buy_v, Decimal("100"), "runtime base")
    assert_eq(config.dip_buy_v, Decimal("200"), "runtime dip")
    assert_eq(config.dip_from_own_cost_pct, Decimal("25"), "runtime dip threshold")
    assert_eq(config.flat_pause_pct, Decimal("12"), "runtime flat threshold")
    assert_eq(config.fdv_limit_enabled, False, "legacy fdv cap ignored by executor")
    assert_eq(config.fdv_limit_wan_usd, None, "legacy fdv cap value ignored by executor")

    args = Namespace(
        max_buy_v=Decimal("50"),
        max_project_v=Decimal("150"),
        mode="broadcast",
        disable_follow_trade=False,
        follow_wallet="0xe0b51bbf7af8bff0a8cd422e4b5f17aa0824969d",
        follow_divisor=Decimal("4"),
    )
    effective = runtime_effective_args(args, row)
    assert_eq(effective.max_buy_v, Decimal("200"), "effective max buy")
    assert_eq(effective.max_project_v, Decimal("500"), "effective max project")
    assert_eq(effective.disable_follow_trade, False, "effective follow enabled")
    assert_eq(effective.follow_divisor, Decimal("2"), "effective follow divisor from ratio")
    assert_eq(args.max_buy_v, Decimal("50"), "original args unchanged")

    compact = compact_runtime_config(row, effective)
    assert_eq(compact["hasOverride"], True, "compact override")
    assert_eq(compact["version"], 3, "compact version")
    assert_eq(compact["baseBuyV"], "100", "compact base")
    assert_eq(compact["fdvLimitEnabled"], False, "compact fdv cap hidden")
    assert_eq(compact["fdvLimitWanUsd"], "", "compact fdv cap value hidden")
    assert_eq(compact["followEnabled"], True, "compact follow enabled")
    assert_eq(compact["followRatioPct"], "50", "compact follow ratio")

    disabled = dict(row)
    disabled["follow_enabled"] = 0
    disabled_effective = runtime_effective_args(args, disabled)
    assert_eq(disabled_effective.disable_follow_trade, True, "effective follow disabled")


def test_fdv_limit_order_helpers() -> None:
    sample = {
        "simTimestamp": 123,
        "buyTaxRate": "91",
        "estimatedFdvWanUsdWithTax": "280",
        "liveFdvUsd": "2700000",
        "boardSpentV": "6000",
        "boardCostWanUsd": "310",
        "costRows": 5,
        "whaleRows": 20,
    }
    rows = [
        {"id": 1, "enabled": 1, "status": "pending", "trigger_fdv_wan_usd": "300", "buy_v": "25", "sort_order": 0},
        {"id": 2, "enabled": 1, "status": "pending", "trigger_fdv_wan_usd": "250", "buy_v": "25", "sort_order": 1},
        {"id": 3, "enabled": 0, "status": "pending", "trigger_fdv_wan_usd": "500", "buy_v": "25", "sort_order": 2},
        {"id": 4, "enabled": 1, "status": "filled", "trigger_fdv_wan_usd": "500", "buy_v": "25", "sort_order": 3},
    ]
    assert_eq(sample_tax_fdv_wan(sample), Decimal("280"), "sample tax fdv")
    assert_eq(
        eligible_fdv_limit_orders(rows, tax_fdv_wan_usd=sample_tax_fdv_wan(sample), project_status="ended"),
        [],
        "fdv limit orders require live status",
    )
    eligible = eligible_fdv_limit_orders(rows, tax_fdv_wan_usd=sample_tax_fdv_wan(sample), project_status="live")
    assert_eq([row["id"] for row in eligible], [1], "eligible fdv limit orders")
    intent = fdv_limit_order_intent(row=eligible[0], project_name="LMT", sample=sample, sample_index=7)
    assert_eq(intent["reason"], "tax_fdv_limit_order_triggered", "fdv order intent reason")
    assert_eq(intent["buy_size_v"], "25", "fdv order buy size")
    assert_eq(intent["fdvLimitOrderId"], 1, "fdv order id")


def test_signed_candidate_cache_take_once_and_clear_batch() -> None:
    assert_eq(signed_candidate_key(buy_size_v="25.0", tax_rate="92.0"), "25|92", "candidate key normalizes")
    signed = SimpleNamespace(
        tx_hash="0xsigned",
        from_addr="0x" + "1" * 40,
        to="0x" + "2" * 40,
        chain_id=8453,
        nonce=9,
        gas=123456,
        raw_tx="0xraw",
    )
    candidate = SignedBuyCandidate(
        key="25|92",
        buy_size_v="25",
        tax_rate="92",
        built_at=100.0,
        expires_at=9999999999.0,
        signed=signed,
        quote=SimpleNamespace(),
        simulation={"green": True},
        timings_ms={"signMs": 1.0},
    )
    alternative = SignedBuyCandidate(
        key="50|92",
        buy_size_v="50",
        tax_rate="92",
        built_at=100.0,
        expires_at=9999999999.0,
        signed=signed,
        quote=SimpleNamespace(),
        simulation={"green": True},
        timings_ms={"signMs": 1.0},
    )
    cache = {"25|92": candidate, "50|92": alternative}
    taken = take_signed_candidate(cache, buy_size_v="25", tax_rate="92")
    assert_eq(taken, candidate, "candidate hit")
    assert_eq(cache, {}, "candidate batch cleared after hit")
    assert_eq(take_signed_candidate(cache, buy_size_v="25", tax_rate="92"), None, "candidate is single-use")


def test_fdv_limit_order_simulation_revert_is_retryable() -> None:
    assert_eq(
        fdv_limit_order_retryable_reason(mode="broadcast", reason="simulation_not_green"),
        True,
        "fdv order simulation revert retryable",
    )
    assert_eq(
        fdv_limit_order_retryable_reason(mode="broadcast", reason="receipt_failed"),
        False,
        "fdv order receipt failure is not soft retry",
    )
    assert_eq(
        fdv_limit_order_retryable_reason(mode="simulate", reason="receipt_failed"),
        True,
        "simulate mode never fails live order",
    )


def test_project_scope_cap_counts_all_sent_buys() -> None:
    class Storage:
        def list_launch_execution_records(self, project_name: str, limit: int = 500):
            return [
                {
                    "project": project_name,
                    "strategy": "open_sniper_no_tax",
                    "rule_name": "open_second_first_buy",
                    "status": "broadcast_sent_no_receipt_wait",
                    "action": "would_buy",
                    "trade_sent": 1,
                    "buy_size_v": "100",
                },
                {
                    "project": project_name,
                    "strategy": "tax_fdv_limit_order",
                    "rule_name": "tax_fdv_limit_order",
                    "status": "broadcast_sent_no_receipt_wait",
                    "action": "would_buy",
                    "trade_sent": 1,
                    "buy_size_v": "25",
                },
                {
                    "project": project_name,
                    "strategy": "tax_fdv_limit_order",
                    "rule_name": "tax_fdv_limit_order",
                    "status": "simulation_failed",
                    "action": "would_buy",
                    "trade_sent": 1,
                    "buy_size_v": "999",
                },
            ]

    bot = SimpleNamespace(storage=Storage())
    assert_eq(sent_project_v_all_strategies(bot, project_name="ORION"), Decimal("125"), "global project cap V")
    assert_eq(open_sniper_first_buy_sent(bot, project_name="ORION"), True, "open sniper gate sees first buy")

    class FailedOnlyStorage:
        def list_launch_execution_records(self, project_name: str, limit: int = 500):
            return [
                {
                    "project": project_name,
                    "strategy": "open_sniper_no_tax",
                    "rule_name": "open_second_first_buy",
                    "status": "broadcast_failed",
                    "action": "would_buy",
                    "trade_sent": 1,
                    "buy_size_v": "100",
                }
            ]

    failed_bot = SimpleNamespace(storage=FailedOnlyStorage())
    assert_eq(open_sniper_first_buy_sent(failed_bot, project_name="ORION"), False, "failed first buy does not open gate")


def test_follow_trade_buy_size_floor_and_project_cap() -> None:
    buy_size, clamped, remaining = follow_trade_buy_size(
        source_spent_v=Decimal("101.9"),
        divisor=Decimal("4"),
        sent_project_v=Decimal("0"),
        max_project_v=Decimal("150"),
    )
    assert_eq(buy_size, Decimal("25"), "follow floor quarter")
    assert_eq(clamped, False, "follow unclamped")
    assert_eq(remaining, Decimal("150"), "follow remaining")

    tiny, tiny_clamped, _ = follow_trade_buy_size(
        source_spent_v=Decimal("3.99"),
        divisor=Decimal("4"),
        sent_project_v=Decimal("0"),
        max_project_v=Decimal("150"),
    )
    assert_eq(tiny, Decimal("0"), "follow skips below 1V")
    assert_eq(tiny_clamped, False, "tiny unclamped")

    capped, capped_clamped, capped_remaining = follow_trade_buy_size(
        source_spent_v=Decimal("400"),
        divisor=Decimal("4"),
        sent_project_v=Decimal("137.2"),
        max_project_v=Decimal("150"),
    )
    assert_eq(capped, Decimal("12"), "follow clamps to integer remaining project cap")
    assert_eq(capped_clamped, True, "follow cap clamp flag")
    assert_eq(capped_remaining, Decimal("12"), "follow cap remaining")


def test_follow_trade_source_tx_dedupes_from_ledger_intent() -> None:
    class Storage:
        def list_launch_execution_records(self, project_name: str, limit: int = 500):
            return [
                {
                    "strategy": DEFAULT_FOLLOW_TRADE_STRATEGY,
                    "rule_name": DEFAULT_FOLLOW_TRADE_RULE,
                    "intent_json": '{"sourceTxHash":"0xabc"}',
                },
                {
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "intent_json": '{"sourceTxHash":"0xdef"}',
                },
            ]

    bot = SimpleNamespace(storage=Storage())
    assert_eq(follow_trade_source_seen(bot, project_name="EXY", source_tx_hash="0xABC"), True, "follow source seen")
    assert_eq(follow_trade_source_seen(bot, project_name="EXY", source_tx_hash="0xdef"), False, "other strategy ignored")


class FakeStorage:
    def __init__(self) -> None:
        self.updates = []
        self.fuses = []

    def list_launch_execution_records(self, project_name: str, limit: int = 500):
        return [
            {
                "intent_id": "standard-1",
                "project": project_name,
                "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                "mode": "prewarm_broadcast",
                "status": "broadcast_sent_no_receipt_wait",
                "action": "would_buy",
                "trade_sent": 1,
                "broadcast_tx_hash": "0xabc",
                "signed_tx_hash": "0xdef",
                "simulation_json": '{"green":true}',
            },
            {
                "intent_id": "limit-1",
                "project": project_name,
                "strategy": "tax_fdv_limit_order",
                "rule_name": "tax_fdv_limit_order",
                "mode": "prewarm_broadcast",
                "status": "broadcast_sent_no_receipt_wait",
                "action": "would_buy",
                "trade_sent": 1,
                "broadcast_tx_hash": "0xlimit",
                "simulation_json": '{"green":true}',
            },
        ]

    def upsert_launch_execution_record(self, record):
        self.updates.append(record)
        return record

    def trigger_launch_execution_fuse(self, **kwargs):
        self.fuses.append(kwargs)
        return {
            "is_active": 1,
            "project": kwargs.get("project"),
            "strategy": kwargs.get("strategy"),
            "rule_name": kwargs.get("rule_name"),
            "failure_stage": kwargs.get("failure_stage"),
            "failure_reason": kwargs.get("failure_reason"),
        }


class FakeBot:
    def __init__(self) -> None:
        self.storage = FakeStorage()


class FakeRpc:
    async def call(self, method, params):
        assert_eq(method, "eth_getTransactionReceipt", "receipt lookup method")
        assert_eq(params, ["0xabc"], "receipt lookup tx")
        return {"status": "0x1", "blockNumber": "0x1", "gasUsed": "0x5208", "logs": []}


def test_reconcile_standard_buy_receipts_updates_only_standard_buys() -> None:
    bot = FakeBot()
    cfg = Namespace(virtual_token_addr="0x" + "1" * 40)
    rows = asyncio.run(
        reconcile_standard_buy_receipts(
            cfg=cfg,
            bot=bot,  # type: ignore[arg-type]
            rpc=FakeRpc(),  # type: ignore[arg-type]
            project_row={"token_addr": "0x" + "2" * 40},
            project_name="TST",
            from_address="0x" + "3" * 40,
        )
    )
    assert_eq(len(rows), 1, "standard receipt count")
    assert_eq(rows[0]["status"], "receipt_success", "standard receipt status")
    assert_eq(len(bot.storage.updates), 1, "ledger update count")
    assert_eq(bot.storage.updates[0]["intent_id"], "standard-1", "standard receipt intent")
    assert_eq(bot.storage.updates[0]["status"], "receipt_success", "standard ledger status")
    assert_eq(bot.storage.fuses, [], "no fuse on successful receipt")


def main() -> None:
    test_rebuild_strategy_state_from_sent_rows()
    test_runtime_config_helpers()
    test_fdv_limit_order_helpers()
    test_signed_candidate_cache_take_once_and_clear_batch()
    test_fdv_limit_order_simulation_revert_is_retryable()
    test_project_scope_cap_counts_all_sent_buys()
    test_follow_trade_buy_size_floor_and_project_cap()
    test_follow_trade_source_tx_dedupes_from_ledger_intent()
    test_reconcile_standard_buy_receipts_updates_only_standard_buys()
    print("launch_prewarm_executor tests ok")


if __name__ == "__main__":
    main()
