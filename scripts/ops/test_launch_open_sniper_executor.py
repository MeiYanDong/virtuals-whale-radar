#!/usr/bin/env python3
"""Smoke tests for launch_open_sniper_executor.py without network or signing."""

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

from launch_open_sniper_executor import (  # noqa: E402
    OPEN_SNIPER_RULE,
    OPEN_SNIPER_STRATEGY,
    build_direct_open_buy_order,
    bump_fee_value,
    compact_rpc_pool,
    direct_fire_due,
    extract_revert_selector,
    launch_phase,
    no_tax_schedule_context,
    open_sniper_already_sent,
    open_sniper_intent,
    open_sniper_sample,
    probe_needs_requote,
    probe_workers_for_phase,
    project_sent_buy_v,
    resolve_rpc_url_pool,
    rpc_url_label,
    gwei_to_wei,
    should_refresh_prepared_open_tx,
    sleep_interval,
    validate_args,
)


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


class FakeTaxBot:
    def resolve_buy_tax_schedule(self, *, factory, category, anti_sniper_tax_type, is_project_60days=None):
        if str(factory).upper() in {"ERC20", "ERC20_PRO", "BONDING"}:
            return {"known": True, "status": "legacy_no_anti_sniper", "duration_value": 0, "unit_seconds": 1}
        if str(factory).upper() == "BONDING_V5" and str(anti_sniper_tax_type) == "0":
            return {"known": True, "status": "bonding_v5_anti_sniper_off", "duration_value": 0, "unit_seconds": 1}
        if str(factory).upper() == "BONDING_V5" and str(anti_sniper_tax_type) == "2":
            return {"known": True, "status": "bonding_v5_98m", "duration_value": 98, "unit_seconds": 60}
        return {"known": False, "status": "unknown", "duration_value": 0, "unit_seconds": 1}

    def compute_buy_tax_rate(self, **kwargs):
        return 1 if str(kwargs.get("anti_sniper_tax_type")) == "0" else 99


class FakeStatusBot:
    def derive_managed_project_status(self, project_row, now_ts=None):
        start_at = int(project_row.get("start_at") or 0)
        end_at = int(project_row.get("resolved_end_at") or 0)
        if now_ts is not None and end_at and int(now_ts) >= end_at:
            return "ended"
        if now_ts is not None and start_at and int(now_ts) >= start_at:
            return "live"
        return "scheduled"


class FakeStorage:
    def __init__(self, rows):
        self.rows = rows

    def list_launch_execution_records(self, project_name, limit=500):
        return list(self.rows)


class FakeBot:
    def __init__(self, rows):
        self.storage = FakeStorage(rows)


class FakePreparedTx:
    def __init__(self, *, built_at: float, expires_at: float):
        self.built_at = built_at
        self.expires_at = expires_at


def test_no_tax_schedule_context_accepts_only_no_anti_sniper() -> None:
    bot = FakeTaxBot()
    project = {"start_at": 1770000000}
    no_tax = no_tax_schedule_context(
        bot,  # type: ignore[arg-type]
        {
            "factory": "BONDING_V5",
            "category": "IP MIRROR",
            "launchedAt": "2026-05-25T16:00:54.000Z",
            "launchInfo": {"antiSniperTaxType": 0, "isProject60days": False},
        },
        project,
    )
    assert_eq(no_tax["ok"], True, "no-tax context ok")
    assert_eq(no_tax["status"], "bonding_v5_anti_sniper_off", "no-tax status")
    assert_eq(no_tax["buyTaxRate"], 1, "base buy tax")

    taxed = no_tax_schedule_context(
        bot,  # type: ignore[arg-type]
        {"factory": "BONDING_V5", "category": "IP MIRROR", "launchInfo": {"antiSniperTaxType": 2}},
        project,
    )
    assert_eq(taxed["ok"], False, "98m project rejected")
    assert_eq(taxed["status"], "bonding_v5_98m", "98m status")


def test_open_sniper_intent_and_sample() -> None:
    sample = open_sniper_sample(
        FakeStatusBot(),  # type: ignore[arg-type]
        {"start_at": 1000, "resolved_end_at": 2000},
        now_ts=1001,
        buy_tax_rate=1,
        attempt=3,
    )
    assert_eq(sample["projectStatus"], "live", "sample status")
    assert_eq(sample["buyTaxRate"], "1", "sample tax")
    assert_eq(sample["openSniperAttempt"], 3, "sample attempt")

    intent = open_sniper_intent(project_name="ORION", sample=sample, sample_index=7, buy_v=Decimal("100"))
    assert_eq(intent["project"], "ORION", "intent project")
    assert_eq(intent["buy_size_v"], "100", "intent buy size")
    assert_eq(intent["trigger_types"], ["open_second_no_tax"], "intent trigger")
    assert_eq(intent["reason"], "open_second_no_tax_first_buy", "intent reason")


def test_sent_project_v_and_existing_open_sniper_guard() -> None:
    rows = [
        {
            "strategy": OPEN_SNIPER_STRATEGY,
            "rule_name": OPEN_SNIPER_RULE,
            "action": "would_buy",
            "trade_sent": 1,
            "status": "broadcast_sent_no_receipt_wait",
            "buy_size_v": "100",
        },
        {
            "strategy": "tax_fdv_limit_order",
            "rule_name": "tax_fdv_limit_order",
            "action": "would_buy",
            "trade_sent": 1,
            "status": "broadcast_sent_no_receipt_wait",
            "buy_size_v": "25",
        },
        {
            "strategy": OPEN_SNIPER_STRATEGY,
            "rule_name": OPEN_SNIPER_RULE,
            "action": "would_buy",
            "trade_sent": 0,
            "status": "simulation_green",
            "buy_size_v": "100",
        },
    ]
    bot = FakeBot(rows)
    assert_eq(project_sent_buy_v(bot, project_name="ORION"), Decimal("125"), "project sent V")
    assert_eq(open_sniper_already_sent(bot, project_name="ORION"), True, "existing open sniper sent")
    assert_eq(open_sniper_already_sent(FakeBot(rows[1:]), project_name="ORION"), False, "fdv order is not open sniper")


def test_validate_args_and_sleep_interval() -> None:
    selection = Namespace(rpc_shared_with_main=False)
    args = Namespace(
        mode="simulate",
        skip_official_no_tax_check=False,
        enable_broadcast=False,
        allow_shared_rpc_broadcast=False,
        buy_v=Decimal("100"),
        max_buy_v=Decimal("100"),
        max_project_v=Decimal("100"),
        prepare_before_sec=600,
        high_probe_before_sec=300,
        ultra_probe_before_sec=90,
        prepare_poll_sec=1,
        high_probe_poll_sec=0.25,
        ultra_probe_poll_sec=0.05,
        high_probe_workers=1,
        ultra_probe_workers=3,
        probe_race_timeout_sec=0.7,
        broadcast_fanout_timeout_sec=0.8,
        arm_before_sec=30,
        trigger_offset_sec=0,
        scheduled_poll_sec=5,
        prelaunch_poll_sec=0.05,
        min_poll_sec=0.02,
        presign_refresh_sec=0.5,
        requote_revert_selectors="0x850c6f76",
        disable_reprobe_after_requote=False,
        post_trigger_direct_fire=False,
        direct_fire_max_age_sec=1.0,
        open_buy_amount_out_min_wei=1,
        post_broadcast_confirm_sec=2.0,
        receipt_poll_sec=0.2,
        replacement_after_sec=1.2,
        replacement_bump_bps=15000,
        replacement_min_priority_fee_gwei=Decimal("8"),
        replacement_min_max_fee_gwei=Decimal("10"),
    )
    validate_args(args, selection)
    standby = launch_phase(args, now_float=300, start_at=1000)
    assert_eq(standby["phase"], "standby", "standby phase")
    assert_eq(standby["shouldPrepare"], False, "standby does not prepare")
    assert_eq(standby["shouldProbe"], False, "standby does not probe")

    prepare = launch_phase(args, now_float=500, start_at=1000)
    assert_eq(prepare["phase"], "prepare", "prepare phase")
    assert_eq(prepare["shouldPrepare"], True, "prepare does prepare")
    assert_eq(prepare["shouldProbe"], False, "prepare does not probe")

    high = launch_phase(args, now_float=750, start_at=1000)
    assert_eq(high["phase"], "high_probe", "high probe phase")
    assert_eq(high["pollSec"], 0.25, "high probe poll")
    assert_eq(high["shouldProbe"], True, "high probe enabled")

    ultra = launch_phase(args, now_float=950, start_at=1000)
    assert_eq(ultra["phase"], "ultra_probe", "ultra probe phase")
    assert_eq(ultra["pollSec"], 0.05, "ultra probe poll")
    assert_eq(ultra["shouldProbe"], True, "ultra probe enabled")

    assert_eq(sleep_interval(args, now_float=300, start_at=1000, sent=False), 5, "scheduled sleep")
    assert_eq(sleep_interval(args, now_float=750, start_at=1000, sent=False), 0.25, "high-probe sleep")
    assert_eq(sleep_interval(args, now_float=950, start_at=1000, sent=False), 0.05, "ultra-probe sleep")
    assert_eq(probe_workers_for_phase(args, "high_probe"), 1, "high-probe workers")
    assert_eq(probe_workers_for_phase(args, "ultra_probe"), 3, "ultra-probe workers")

    bad = Namespace(**{**vars(args), "buy_v": Decimal("101")})
    try:
        validate_args(bad, selection)
    except SystemExit:
        pass
    else:
        raise AssertionError("buy_v > max_buy_v should fail")

    bad_replacement = Namespace(**{**vars(args), "replacement_min_max_fee_gwei": Decimal("7")})
    try:
        validate_args(bad_replacement, selection)
    except SystemExit:
        pass
    else:
        raise AssertionError("replacement max fee below priority fee should fail")


def test_rpc_pool_helpers() -> None:
    label = rpc_url_label("https://rpc.ankr.com/base/secret-token", 2)
    assert_eq(label, "ankr-2", "ankr url label")
    pool = resolve_rpc_url_pool("MISSING_TEST_RPC_POOL_ENV", primary_url="https://base-mainnet.core.chainstack.com/secret")
    assert_eq(pool, ["https://base-mainnet.core.chainstack.com/secret"], "fallback rpc pool")
    compact = compact_rpc_pool(["https://base-mainnet.core.chainstack.com/secret", "https://rpc.ankr.com/base/secret"])
    assert_eq(compact["count"], 2, "compact pool count")
    assert_eq(compact["labels"], ["chainstack-1", "ankr-2"], "compact pool labels")


def test_direct_open_buy_order_uses_minimal_min_out() -> None:
    args = Namespace(
        buy_v=Decimal("300"),
        from_address="0x4a371b9b1bf1e7bc0700dff666631f0fc5c96624",
        deadline_offset_sec=180,
        open_buy_amount_out_min_wei=1,
    )
    cfg = Namespace(chain_id=8453, virtual_token_addr="0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b")
    bound = build_direct_open_buy_order(
        args=args,
        cfg=cfg,
        project_row={"token_addr": "0x1111111111111111111111111111111111111111"},
        buy_tax_rate=1,
        now_ts=1000,
    )
    assert_eq(bound.quote.amount_in_wei, "300000000000000000000", "direct amount in")
    assert_eq(bound.quote.amount_out_min_wei, "1", "direct minimal min out")
    assert_eq(bound.quote.quoted_amount_out_raw, "0", "direct buy does not bind quote")
    assert_eq(bound.quote.deadline, 1180, "direct deadline")
    assert_eq(bound.tx.data[0:10], "0x706910ff", "direct buy selector")


def test_replacement_fee_bump_helpers() -> None:
    assert_eq(gwei_to_wei(Decimal("8")), 8_000_000_000, "gwei conversion")
    assert_eq(
        bump_fee_value(current_wei="6000000000", min_gwei=Decimal("10"), bump_bps=15000),
        "10000000000",
        "replacement max fee honors min",
    )
    assert_eq(
        bump_fee_value(current_wei="10000000000", min_gwei=Decimal("8"), bump_bps=15000),
        "15000000000",
        "replacement fee honors bump",
    )


def test_hot_presign_refresh_and_requote_helpers() -> None:
    args = Namespace(
        disable_presigned_open_tx=False,
        presign_refresh_sec=0.5,
        requote_revert_selectors="0x850c6f76",
        post_trigger_direct_fire=True,
        direct_fire_max_age_sec=1.0,
    )
    prepared = FakePreparedTx(built_at=100.0, expires_at=300.0)
    assert_eq(
        should_refresh_prepared_open_tx(
            args,
            prepared=prepared,  # type: ignore[arg-type]
            phase_name="ultra_probe",
            phase_changed=False,
            last_presign_refresh_started=100.0,
            now_monotonic=100.6,
        ),
        True,
        "ultra phase refreshes on presign interval",
    )
    assert_eq(
        should_refresh_prepared_open_tx(
            args,
            prepared=prepared,  # type: ignore[arg-type]
            phase_name="standby",
            phase_changed=False,
            last_presign_refresh_started=100.0,
            now_monotonic=200.0,
        ),
        False,
        "standby does not presign",
    )
    assert_eq(
        extract_revert_selector("RPC error: {'data': '0x850c6f76'}"),
        "0x850c6f76",
        "extract revert selector",
    )
    assert_eq(
        probe_needs_requote(
            args,
            probe={"ready": False, "error": "RPC error: {'data': '0x850c6f76'}"},
            phase_info={"secondsToTrigger": -1},
        ),
        True,
        "post-trigger stale quote selector requotes",
    )
    assert_eq(
        probe_needs_requote(
            args,
            probe={"ready": False, "error": "RPC error: {'data': '0x850c6f76'}"},
            phase_info={"secondsToTrigger": 1},
        ),
        False,
        "pre-trigger selector does not requote",
    )
    assert_eq(
        direct_fire_due(
            args,
            phase_info={"secondsToTrigger": -0.1},
            prepared=prepared,  # type: ignore[arg-type]
            already_attempted=False,
            now_monotonic=100.5,
        ),
        True,
        "post-trigger direct fire requires fresh prepared tx",
    )
    assert_eq(
        direct_fire_due(
            args,
            phase_info={"secondsToTrigger": -0.1},
            prepared=prepared,  # type: ignore[arg-type]
            already_attempted=False,
            now_monotonic=102.0,
        ),
        False,
        "stale prepared tx does not direct fire",
    )


def main() -> None:
    test_no_tax_schedule_context_accepts_only_no_anti_sniper()
    test_open_sniper_intent_and_sample()
    test_sent_project_v_and_existing_open_sniper_guard()
    test_validate_args_and_sleep_interval()
    test_rpc_pool_helpers()
    test_direct_open_buy_order_uses_minimal_min_out()
    test_replacement_fee_bump_helpers()
    test_hot_presign_refresh_and_requote_helpers()
    print("launch_open_sniper_executor tests ok")


if __name__ == "__main__":
    main()
