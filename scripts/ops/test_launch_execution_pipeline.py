#!/usr/bin/env python3
"""Smoke tests for launch_execution_pipeline.py without network or signing."""

from __future__ import annotations

import json
import os
import sys
import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    GET_RESERVES_SELECTOR,
    LocalSigner,
    TOKEN0_SELECTOR,
    TOKEN1_SELECTOR,
    VIRTUALS_BUY_ROUTER,
    VIRTUALS_BUY_SPENDER,
    TxSimulator,
    VirtualsOrderBinder,
    VirtualsOrderBuilder,
    decode_virtuals_buy_calldata,
    encode_virtuals_buy_calldata,
    get_amount_out_uniswap_v2,
    load_samples,
    resolve_rule,
    run_dry_run,
    SafeBroadcaster,
)
from virtuals_bot import Storage  # noqa: E402


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


VIRTUAL_TOKEN = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
TARGET_TOKEN = "0x10c56f005a379f8eafc88ff5c3f40d30f0031ac9"
POOL_ADDR = "0x2222222222222222222222222222222222222222"


def word(value: int) -> str:
    return f"{value:064x}"


def address_result(addr: str) -> str:
    return "0x" + ("0" * 24) + addr.lower().removeprefix("0x")


class FakeRPC:
    def __init__(
        self,
        *,
        balance_wei: int,
        allowance_wei: int,
        eth_call_ok: bool = True,
        token_addr: str = TARGET_TOKEN,
        virtual_addr: str = VIRTUAL_TOKEN,
        pool_addr: str = POOL_ADDR,
        reserve_virtual_wei: int = 1_000_000 * 10**18,
        reserve_token_raw: int = 2_000_000_000 * 10**18,
    ) -> None:
        self.balance_wei = balance_wei
        self.allowance_wei = allowance_wei
        self.eth_call_ok = eth_call_ok
        self.token_addr = token_addr.lower()
        self.virtual_addr = virtual_addr.lower()
        self.pool_addr = pool_addr.lower()
        self.reserve_virtual_wei = reserve_virtual_wei
        self.reserve_token_raw = reserve_token_raw

    async def call(self, method: str, params: list) -> str:
        if method == "eth_getTransactionCount":
            return "0x7"
        if method == "eth_estimateGas":
            return "0x186a0"
        if method != "eth_call":
            raise AssertionError(f"unexpected method: {method}")

        to = str(params[0].get("to") or "").lower()
        data = str(params[0].get("data") or "")
        if data.startswith("0x70a08231"):
            return hex(self.balance_wei)
        if data.startswith("0xdd62ed3e"):
            return hex(self.allowance_wei)
        if to == self.pool_addr and data == TOKEN0_SELECTOR:
            return address_result(self.virtual_addr)
        if to == self.pool_addr and data == TOKEN1_SELECTOR:
            return address_result(self.token_addr)
        if to == self.pool_addr and data == GET_RESERVES_SELECTOR:
            return "0x" + word(self.reserve_virtual_wei) + word(self.reserve_token_raw) + word(0)
        if to in {self.token_addr, self.virtual_addr} and data == "0x313ce567":
            return hex(18)
        if self.eth_call_ok:
            return "0x"
        raise RuntimeError("execution reverted")


def test_virtuals_buy_calldata_parity() -> None:
    canonical_sr_buy = (
        "0x706910ff"
        "0000000000000000000000000000000000000000000000056bc75e2d63100000"
        "00000000000000000000000010c56f005a379f8eafc88ff5c3f40d30f0031ac9"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000069deff92"
    )
    decoded = decode_virtuals_buy_calldata(canonical_sr_buy)
    assert_eq(decoded["amountInWei"], "100000000000000000000", "SR amountInWei")
    assert_eq(decoded["tokenAddress"], "0x10c56f005a379f8eafc88ff5c3f40d30f0031ac9", "SR token")
    assert_eq(decoded["amountOutMinWei"], "0", "SR amountOutMinWei")
    assert_eq(decoded["deadline"], 1776222098, "SR deadline")
    assert_eq(decoded["exactCanonical"], True, "SR exactCanonical")
    assert_eq(
        encode_virtuals_buy_calldata(
            amount_in_wei=100_000_000_000_000_000_000,
            token_addr="0x10c56f005a379f8eafc88ff5c3f40d30f0031ac9",
            amount_out_min_wei=0,
            deadline=1776222098,
        ),
        canonical_sr_buy,
        "SR canonical parity",
    )

    tagged_sr_buy = (
        "0x706910ff"
        "000000000000000000000000000000000000000000000145fedde817cc452000"
        "00000000000000000000000010c56f005a379f8eafc88ff5c3f40d30f0031ac9"
        "000000000000000000000000000000000000000000009894c849a9add2a43800"
        "0000000000000000000000000000000000000000000000000000000069dc5e2b"
        "62635f7a677a65663138360b0080218021802180218021802180218021"
    )
    tagged = decode_virtuals_buy_calldata(tagged_sr_buy)
    assert_eq(tagged["exactCanonical"], False, "tagged exactCanonical")
    assert_eq(tagged["canonicalPrefix"], True, "tagged canonicalPrefix")
    assert_eq(tagged["tailBytes"], 29, "tagged tailBytes")

    builder = VirtualsOrderBuilder()
    unsigned = builder.build_buy(
        chain_id=8453,
        from_addr="0x1111111111111111111111111111111111111111",
        token_addr="0x10c56f005a379f8eafc88ff5c3f40d30f0031ac9",
        amount_in_v="25",
        amount_out_min_wei=0,
        deadline=1776222098,
    )
    assert_eq(unsigned.to, VIRTUALS_BUY_ROUTER, "builder router")
    assert_eq(unsigned.value_wei, "0", "builder value")
    assert_eq(
        decode_virtuals_buy_calldata(unsigned.data)["amountInWei"],
        "25000000000000000000",
        "builder amountInWei",
    )


async def test_tx_simulator_green_and_blocked() -> None:
    builder = VirtualsOrderBuilder()
    unsigned = builder.build_buy(
        chain_id=8453,
        from_addr="0x1111111111111111111111111111111111111111",
        token_addr=TARGET_TOKEN,
        amount_in_v="25",
        amount_out_min_wei=1,
        deadline=1000,
    )

    enough = 100 * 10**18
    simulator = TxSimulator(
        FakeRPC(balance_wei=enough, allowance_wei=enough),
        virtual_token_addr=VIRTUAL_TOKEN,
    )
    report = await simulator.simulate(unsigned, now_ts=100)
    assert_eq(report["green"], True, "simulator green")
    assert_eq(report["tradeSent"], False, "simulator tradeSent")
    assert_eq(report["checks"]["balance"]["ok"], True, "simulator balance")
    assert_eq(report["checks"]["allowance"]["ok"], True, "simulator allowance")
    assert_eq(report["checks"]["amountOutMin"]["ok"], True, "simulator amountOutMin")
    assert_eq(report["checks"]["ethCall"]["ok"], True, "simulator ethCall")
    assert_eq(report["checks"]["estimateGas"]["gas"], "100000", "simulator gas")
    assert_eq(report["checks"]["allowance"]["spender"], VIRTUALS_BUY_SPENDER, "simulator spender")

    blocked = TxSimulator(
        FakeRPC(balance_wei=enough, allowance_wei=10 * 10**18),
        virtual_token_addr=VIRTUAL_TOKEN,
    )
    blocked_report = await blocked.simulate(unsigned, now_ts=100)
    assert_eq(blocked_report["green"], False, "simulator blocked")
    assert_eq(blocked_report["checks"]["allowance"]["ok"], False, "simulator blocked allowance")


async def test_order_binder_quote_and_min_out() -> None:
    fake = FakeRPC(balance_wei=100 * 10**18, allowance_wei=100 * 10**18)
    bound = await VirtualsOrderBinder(
        fake,
        virtual_token_addr=VIRTUAL_TOKEN,
        slippage_bps=DEFAULT_LAUNCH_SLIPPAGE_BPS,
        deadline_offset_sec=180,
    ).bind_buy(
        chain_id=8453,
        from_addr="0x1111111111111111111111111111111111111111",
        token_addr=TARGET_TOKEN,
        pool_addr=POOL_ADDR,
        amount_in_v="25",
        now_ts=1000,
    )
    quote = get_amount_out_uniswap_v2(
        amount_in=25 * 10**18,
        reserve_in=fake.reserve_virtual_wei,
        reserve_out=fake.reserve_token_raw,
    )
    expected_min = quote * (10_000 - DEFAULT_LAUNCH_SLIPPAGE_BPS) // 10_000
    decoded = decode_virtuals_buy_calldata(bound.tx.data)
    assert_eq(decoded["amountOutMinWei"], str(expected_min), "binder amountOutMin")
    assert_eq(decoded["deadline"], 1180, "binder deadline")
    assert_eq(bound.quote.quoted_amount_out_raw, str(quote), "binder quote")
    assert_eq(bound.quote.token_index, 1, "binder token index")


async def test_order_binder_tax_adjusts_min_out() -> None:
    fake = FakeRPC(balance_wei=100 * 10**18, allowance_wei=100 * 10**18)
    bound = await VirtualsOrderBinder(
        fake,
        virtual_token_addr=VIRTUAL_TOKEN,
        slippage_bps=DEFAULT_LAUNCH_SLIPPAGE_BPS,
        deadline_offset_sec=180,
    ).bind_buy(
        chain_id=8453,
        from_addr="0x1111111111111111111111111111111111111111",
        token_addr=TARGET_TOKEN,
        pool_addr=POOL_ADDR,
        amount_in_v="25",
        buy_tax_rate_pct="95",
        now_ts=1000,
    )
    quote = get_amount_out_uniswap_v2(
        amount_in=25 * 10**18,
        reserve_in=fake.reserve_virtual_wei,
        reserve_out=fake.reserve_token_raw,
    )
    tax_adjusted = quote * 500 // 10_000
    expected_min = tax_adjusted * (10_000 - DEFAULT_LAUNCH_SLIPPAGE_BPS) // 10_000
    decoded = decode_virtuals_buy_calldata(bound.tx.data)
    assert_eq(decoded["amountOutMinWei"], str(expected_min), "tax-adjusted binder amountOutMin")
    assert_eq(bound.quote.buy_tax_rate_pct, "95", "binder tax rate")
    assert_eq(bound.quote.effective_slippage_bps, 9750, "binder effective slippage")


def test_local_signer_signs_and_recovers_without_broadcast() -> None:
    try:
        from eth_account import Account
    except Exception as exc:
        raise AssertionError("eth-account must be installed for signer test") from exc

    account = Account.create()
    builder = VirtualsOrderBuilder()
    tx = builder.build_buy(
        chain_id=8453,
        from_addr=account.address,
        token_addr=TARGET_TOKEN,
        amount_in_v="25",
        amount_out_min_wei=1,
        deadline=2000,
    )
    tx = replace(
        tx,
        nonce=7,
        gas=180_000,
        max_fee_per_gas=str(10 * 10**9),
        max_priority_fee_per_gas=str(1 * 10**9),
    )

    old_value = os.environ.get(BURNER_PRIVATE_KEY_ENV)
    os.environ[BURNER_PRIVATE_KEY_ENV] = account.key.hex()
    try:
        signed = LocalSigner().sign(tx)
    finally:
        if old_value is None:
            os.environ.pop(BURNER_PRIVATE_KEY_ENV, None)
        else:
            os.environ[BURNER_PRIVATE_KEY_ENV] = old_value

    assert_eq(signed.from_addr, account.address.lower(), "signed from")
    assert_eq(signed.to, VIRTUALS_BUY_ROUTER, "signed to")
    assert_eq(signed.chain_id, 8453, "signed chain")
    assert_eq(signed.nonce, 7, "signed nonce")
    assert_eq(signed.broadcast_allowed, False, "signed broadcast disabled")
    assert_eq(LocalSigner.recover_sender(signed.raw_tx), account.address.lower(), "recover sender")


def test_launch_execution_ledger_storage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(str(Path(tmp) / "ledger.db"))
        try:
            row = storage.upsert_launch_execution_record(
                {
                    "intent_id": "lexec_test_1",
                    "project": "LEDGER_TEST",
                    "managed_project_id": 1,
                    "signalhub_project_id": "42",
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "mode": "dry_run",
                    "status": "intent_recorded",
                    "action": "would_buy",
                    "decision_reason": "signal",
                    "sample_index": 7,
                    "snapshot_ts": 1770000000,
                    "tax_rate": "95",
                    "buy_size_v": "25",
                    "entry_tax_fdv_wan_usd": "297.5",
                    "board_spent_v": "10000",
                    "board_cost_wan_usd": "440",
                    "trigger_types": ["tax_tick"],
                    "snapshot": {"projectStatus": "live", "buyTaxRate": "95"},
                    "intent": {"buy_size_v": "25"},
                    "trade_sent": False,
                    "broadcast_enabled": False,
                }
            )
            assert_eq(row["intent_id"], "lexec_test_1", "ledger intent id")
            assert_eq(row["status"], "intent_recorded", "ledger initial status")
            assert_eq(json.loads(row["trigger_types_json"]), ["tax_tick"], "ledger trigger json")

            updated = storage.upsert_launch_execution_record(
                {
                    "intent_id": "lexec_test_1",
                    "project": "LEDGER_TEST",
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "status": "simulation_failed",
                    "action": "would_buy",
                    "decision_reason": "signal",
                    "simulation": {"green": False},
                    "failure_stage": "simulation",
                    "failure_reason": "allowance",
                }
            )
            assert_eq(updated["status"], "simulation_failed", "ledger updated status")
            assert_eq(updated["buy_size_v"], "25", "ledger preserves buy size")
            assert_eq(json.loads(updated["intent_json"]), {"buy_size_v": "25"}, "ledger preserves intent json")
            assert_eq(updated["failure_stage"], "simulation", "ledger failure stage")
            assert_eq(json.loads(updated["simulation_json"]), {"green": False}, "ledger simulation json")
            signed = storage.upsert_launch_execution_record(
                {
                    "intent_id": "lexec_test_1",
                    "project": "LEDGER_TEST",
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "status": "signed_ready",
                    "action": "would_buy",
                    "decision_reason": "signed_no_raw_tx_persisted",
                    "signed_tx_hash": "0x" + "1" * 64,
                    "trade_sent": False,
                    "broadcast_enabled": False,
                }
            )
            assert_eq(signed["status"], "signed_ready", "ledger signed status")
            assert_eq(signed["signed_tx_hash"], "0x" + "1" * 64, "ledger signed hash")
            assert_eq(signed["trade_sent"], 0, "ledger signed trade flag")
            receipt = storage.upsert_launch_execution_record(
                {
                    "intent_id": "lexec_test_1",
                    "project": "LEDGER_TEST",
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "status": "receipt_success",
                    "action": "would_buy",
                    "decision_reason": "receipt_observed",
                    "broadcast_tx_hash": "0x" + "2" * 64,
                    "receipt": {"status": "0x1", "blockNumber": "0x2a"},
                    "trade_sent": True,
                    "broadcast_enabled": True,
                }
            )
            assert_eq(receipt["status"], "receipt_success", "ledger receipt status")
            assert_eq(receipt["signed_tx_hash"], "0x" + "1" * 64, "ledger preserves signed hash")
            assert_eq(receipt["broadcast_tx_hash"], "0x" + "2" * 64, "ledger broadcast hash")
            assert_eq(json.loads(receipt["receipt_json"]), {"blockNumber": "0x2a", "status": "0x1"}, "ledger receipt json")
            assert_eq(receipt["trade_sent"], 1, "ledger receipt trade flag")
            failed_after_send = storage.upsert_launch_execution_record(
                {
                    "intent_id": "lexec_test_1",
                    "project": "LEDGER_TEST",
                    "strategy": "dynamic_25v_dip20_after1_flat10_no_cap",
                    "rule_name": "gate_5k_tax95_fdv_one_per_tax",
                    "status": "prewarm_failed",
                    "action": "would_buy",
                    "decision_reason": "receipt_timeout_after_send",
                    "failure_stage": "receipt",
                    "failure_reason": "timeout",
                }
            )
            assert_eq(failed_after_send["trade_sent"], 1, "ledger preserves trade sent after later failure")
            assert_eq(
                failed_after_send["broadcast_enabled"],
                1,
                "ledger preserves broadcast enabled after later failure",
            )
            assert_eq(
                failed_after_send["broadcast_tx_hash"],
                "0x" + "2" * 64,
                "ledger preserves broadcast hash after later failure",
            )
            assert_eq(len(storage.list_launch_execution_records("LEDGER_TEST")), 1, "ledger list")

            fuse = storage.trigger_launch_execution_fuse(
                project="LEDGER_TEST",
                strategy="dynamic_25v_dip20_after1_flat10_no_cap",
                rule_name="gate_5k_tax95_fdv_one_per_tax",
                failure_stage="simulation",
                failure_reason="allowance",
                source_intent_id="lexec_test_1",
                details={"green": False},
            )
            assert_eq(fuse["is_active"], 1, "fuse active")
            assert_eq(fuse["failure_stage"], "simulation", "fuse stage")
            assert_eq(json.loads(fuse["details_json"]), {"green": False}, "fuse details json")
            active = storage.get_active_launch_execution_fuse(
                project="LEDGER_TEST",
                strategy="dynamic_25v_dip20_after1_flat10_no_cap",
                rule_name="gate_5k_tax95_fdv_one_per_tax",
            )
            assert_eq(active["failure_reason"], "allowance", "active fuse reason")
            assert_eq(len(storage.list_launch_execution_fuses("LEDGER_TEST", active_only=True)), 1, "active fuse list")
            cleared = storage.clear_launch_execution_fuse(
                project="LEDGER_TEST",
                strategy="dynamic_25v_dip20_after1_flat10_no_cap",
                rule_name="gate_5k_tax95_fdv_one_per_tax",
                cleared_reason="manual_test_clear",
            )
            assert_eq(cleared["is_active"], 0, "fuse cleared")
            assert_eq(
                storage.get_active_launch_execution_fuse(
                    project="LEDGER_TEST",
                    strategy="dynamic_25v_dip20_after1_flat10_no_cap",
                    rule_name="gate_5k_tax95_fdv_one_per_tax",
                ),
                None,
                "no active fuse after clear",
            )
        finally:
            storage.close()


def main() -> None:
    test_virtuals_buy_calldata_parity()
    asyncio.run(test_tx_simulator_green_and_blocked())
    asyncio.run(test_order_binder_quote_and_min_out())
    test_local_signer_signs_and_recovers_without_broadcast()
    test_launch_execution_ledger_storage()

    cases = [
        {
            "project": "SR_EVENT_REPLAY",
            "samples": "data/replay-event-level/sr_event_replay-20260510T073102Z-samples.jsonl",
            "rule": "gate_5k_tax95_fdv_one_per_tax",
            "buyIntentCount": 5,
            "pauseCount": 2,
            "totalIntentV": "125",
            "firstTax": "95",
            "pauseTaxes": ["91", "89"],
        },
        {
            "project": "ISC_EVENT_REPLAY",
            "samples": "data/replay-event-level/isc_event_replay-20260510T085419Z-samples.jsonl",
            "rule": "gate_5k_tax89_fdv_one_per_tax",
            "buyIntentCount": 14,
            "pauseCount": 14,
            "totalIntentV": "350",
            "firstTax": "89",
            "pauseTaxes": ["88", "86", "84"],
        },
    ]

    summary = []
    for case in cases:
        report = run_dry_run(
            project=case["project"],
            samples=load_samples(Path(case["samples"])),
            rule=resolve_rule(case["rule"]),
        )
        assert_eq(report["tradeSent"], False, f"{case['project']} tradeSent")
        assert_eq(report["buyIntentCount"], case["buyIntentCount"], f"{case['project']} buyIntentCount")
        assert_eq(report["pauseCount"], case["pauseCount"], f"{case['project']} pauseCount")
        assert_eq(report["totalIntentV"], case["totalIntentV"], f"{case['project']} totalIntentV")
        assert_eq(report["intents"][0]["tax_rate"], case["firstTax"], f"{case['project']} firstTax")
        actual_pause_taxes = [row["taxRate"] for row in report["pauses"][: len(case["pauseTaxes"])]]
        assert_eq(actual_pause_taxes, case["pauseTaxes"], f"{case['project']} pauseTaxes")
        summary.append(
            {
                "project": case["project"],
                "buyIntentCount": report["buyIntentCount"],
                "pauseCount": report["pauseCount"],
                "totalIntentV": report["totalIntentV"],
                "finalPnlPct": report["finalPnlPct"],
            }
        )

    try:
        SafeBroadcaster().broadcast("0xdeadbeef")
    except RuntimeError:
        pass
    else:
        raise AssertionError("SafeBroadcaster must reject broadcast by default")

    print(json.dumps({"ok": True, "cases": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
