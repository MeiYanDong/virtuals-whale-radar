#!/usr/bin/env python3
"""Full-window data-driven auto buy/sell canary.

This local canary proves the automatic trigger path, not manual trading:
- iterates a deterministic launch window sample stream;
- lets the production DynamicAfter1StrategyEvaluator emit BuyIntent;
- calls launch_prewarm_executor.prewarm_intent for real broadcast;
- later lets the production sell evaluator emit SellIntent from sample data;
- calls launch_sell_executor.execute_sell_decision for real approve/sell.

The deterministic samples are synthetic control data. They are useful for
proving that data can trigger production executors, but they are not proof of a
real project's official tax schedule. Safety defaults are intentionally tiny,
bounded, and production-like. The script still requires the normal broadcast
env gates and an isolated execution RPC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import load_secret_file, read_erc20_balance  # noqa: E402
from execution_rpc import apply_execution_rpc_to_config, require_isolated_execution_rpc  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    DynamicAfter1StrategyEvaluator,
    DynamicExecutionConfig,
    normalize_hex_address,
    resolve_rule,
)
from launch_prewarm_executor import prewarm_intent  # noqa: E402
from launch_sell_executor import (  # noqa: E402
    build_position_from_records,
    current_roi_pct,
    execute_sell_decision,
    multi_state_from_position,
)
from launch_sell_strategy import (  # noqa: E402
    CustomSellCondition,
    CustomSellConfig,
    CustomSellRule,
    MultiSellInput,
    evaluate_custom_sell,
)
from live_strategy_dry_run import append_jsonl, cst_iso, find_project, utc_iso  # noqa: E402
from runtime_control_launch_simulator import build_fixture_samples  # noqa: E402
from virtuals_bot import RPCClient, VirtualsBot, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one full-window real auto-trigger canary.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True)
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--amount-v", type=Decimal, default=Decimal("0.1"))
    parser.add_argument("--sell-pct", type=Decimal, default=Decimal("100"))
    parser.add_argument("--sell-roi-pct", type=Decimal, default=Decimal("1"))
    parser.add_argument("--sell-max-tax-rate", type=Decimal, default=Decimal("30"))
    parser.add_argument(
        "--force-high-tax-sell-canary",
        action="store_true",
        help="Allow sell canary above 30%% tax. This only proves executor triggering, not production sell strategy.",
    )
    parser.add_argument("--max-ticks", type=int, default=99)
    parser.add_argument("--sleep-sec", type=Decimal, default=Decimal("0"))
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--sell-slippage-bps", type=int, default=500)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--post-buy-balance-timeout-sec", type=int, default=20)
    parser.add_argument("--post-buy-balance-interval-sec", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--ignore-active-fuse", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    return parser.parse_args()


def make_buy_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        config=args.config,
        project=args.project,
        from_address=normalize_hex_address(args.from_address),
        secret_file=args.secret_file,
        rule="gate_5k_tax95_fdv_one_per_tax",
        mode="broadcast",
        output_jsonl="",
        once=False,
        max_samples=0,
        min_poll_sec=0.25,
        live_poll_sec=0.25,
        prelaunch_poll_sec=2.0,
        scheduled_poll_sec=20.0,
        heartbeat_log_sec=30.0,
        exit_after_end_sec=0,
        slippage_bps=int(args.slippage_bps),
        deadline_offset_sec=DEFAULT_DEADLINE_OFFSET_SEC,
        gas_buffer_bps=2000,
        max_fee_gwei=None,
        max_priority_fee_gwei=None,
        ignore_active_fuse=bool(args.ignore_active_fuse),
        enable_broadcast=True,
        allow_shared_rpc_broadcast=bool(args.allow_shared_rpc_broadcast),
        max_buy_v=Decimal(str(args.amount_v)),
        max_project_v=Decimal(str(args.amount_v)),
        receipt_timeout_sec=int(args.receipt_timeout_sec),
        no_wait_receipt=False,
    )


def make_sell_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        config=args.config,
        project=args.project,
        from_address=normalize_hex_address(args.from_address),
        secret_file=args.secret_file,
        rule="auto_trigger_canary_sell",
        mode="broadcast",
        output_jsonl="",
        once=False,
        max_samples=0,
        min_poll_sec=0.25,
        live_poll_sec=0.25,
        prelaunch_poll_sec=2.0,
        scheduled_poll_sec=20.0,
        heartbeat_log_sec=30.0,
        catch_up_events_sec=120,
        exit_after_end_sec=300,
        slippage_bps=int(args.sell_slippage_bps),
        deadline_offset_sec=DEFAULT_DEADLINE_OFFSET_SEC,
        gas_buffer_bps=2000,
        max_fee_gwei=None,
        max_priority_fee_gwei=None,
        receipt_timeout_sec=int(args.receipt_timeout_sec),
        no_wait_receipt=False,
        enable_broadcast=True,
        allow_shared_rpc_broadcast=bool(args.allow_shared_rpc_broadcast),
        auto_approve=True,
        ignore_active_fuse=bool(args.ignore_active_fuse),
    )


def make_sell_config(args: argparse.Namespace, *, strategy_name: str) -> CustomSellConfig:
    return CustomSellConfig(
        name=strategy_name,
        max_tax_rate=Decimal(str(args.sell_max_tax_rate)),
        cooldown_sec=0,
        rules=(
            CustomSellRule(
                id="roi_full_exit_canary",
                type="condition_group",
                enabled=True,
                sell_pct=Decimal(str(args.sell_pct)),
                operator="and",
                conditions=(
                    CustomSellCondition(type="roi", roi_threshold_pct=Decimal(str(args.sell_roi_pct))),
                ),
                label="收益率触发清仓 canary",
            ),
        ),
    )


def compact_event(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "event",
        "reason",
        "project",
        "sampleIndex",
        "taxRate",
        "tradeSent",
        "broadcastEnabled",
        "txHash",
        "ledgerIntentId",
        "receipt",
        "timingsMs",
    ]
    return {key: payload.get(key) for key in keys if key in payload}


def current_run_records(rows: list[dict[str, Any]], *, buy_strategy: str, sell_strategy: str) -> list[dict[str, Any]]:
    allowed = {str(buy_strategy).strip(), str(sell_strategy).strip()}
    return [row for row in rows if str(row.get("strategy") or "").strip() in allowed]


async def wait_token_balance_visible(
    rpc: RPCClient,
    *,
    token: str,
    owner: str,
    timeout_sec: int,
    interval_sec: Decimal,
) -> tuple[int, list[str]]:
    deadline = time.time() + max(0, int(timeout_sec))
    reads: list[str] = []
    last = 0
    while True:
        last = await read_erc20_balance(rpc, token=token, owner=owner)
        reads.append(str(last))
        if last > 0:
            return last, reads
        if time.time() >= deadline:
            return last, reads
        await asyncio.sleep(float(interval_sec))


async def wait_token_balance_zero(
    rpc: RPCClient,
    *,
    token: str,
    owner: str,
    timeout_sec: int,
    interval_sec: Decimal,
) -> tuple[int, list[str]]:
    deadline = time.time() + max(0, int(timeout_sec))
    reads: list[str] = []
    last = 0
    while True:
        last = await read_erc20_balance(rpc, token=token, owner=owner)
        reads.append(str(last))
        if last == 0:
            return last, reads
        if time.time() >= deadline:
            return last, reads
        await asyncio.sleep(float(interval_sec))


async def async_main() -> None:
    args = parse_args()
    if Decimal(str(args.sell_max_tax_rate)) > Decimal("30") and not bool(args.force_high_tax_sell_canary):
        raise SystemExit(
            "--sell-max-tax-rate above 30 requires --force-high-tax-sell-canary; "
            "high-tax sells are path canaries, not production strategy validation"
        )
    cfg = load_config(args.config)
    rpc_selection = apply_execution_rpc_to_config(cfg)
    require_isolated_execution_rpc(
        rpc_selection,
        action="full-window auto-trigger canary",
        allow_shared=bool(args.allow_shared_rpc_broadcast),
    )
    if str(os.environ.get("VWR_ENABLE_AUTO_BUY_BROADCAST") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("requires VWR_ENABLE_AUTO_BUY_BROADCAST=1")
    if str(os.environ.get("VWR_ENABLE_AUTO_SELL_BROADCAST") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("requires VWR_ENABLE_AUTO_SELL_BROADCAST=1")
    if str(os.environ.get("VWR_ENABLE_AUTO_SELL_APPROVE") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("requires VWR_ENABLE_AUTO_SELL_APPROVE=1")

    load_secret_file(Path(args.secret_file))
    owner = normalize_hex_address(args.from_address)
    try:
        from eth_account import Account
        from eth_utils import to_checksum_address
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("eth-account and eth-utils are required") from exc
    account = Account.from_key(os.environ[BURNER_PRIVATE_KEY_ENV])
    if normalize_hex_address(account.address) != owner:
        raise ValueError("secret file private key does not match --from-address")

    run_id = time.strftime("%Y%m%d-%H%M%S")
    output_jsonl = Path(args.output_jsonl or f"data/execution/full-window-auto-trigger-canary-{args.project}-{run_id}.jsonl")
    summary_json = Path(args.summary_json) if args.summary_json else output_jsonl.with_suffix(".summary.json")
    buy_strategy_name = f"auto_trigger_canary_buy_{run_id.replace('-', '_')}"
    sell_strategy_name = f"auto_trigger_canary_sell_{run_id.replace('-', '_')}"
    buy_args = make_buy_args(args)
    sell_args = make_sell_args(args)
    rule = resolve_rule(buy_args.rule)
    evaluator = DynamicAfter1StrategyEvaluator(
        project=str(args.project),
        rule=rule,
        config=DynamicExecutionConfig(
            name=buy_strategy_name,
            base_buy_v=Decimal(str(args.amount_v)),
            dip_buy_v=Decimal(str(args.amount_v)),
            dip_from_own_cost_pct=Decimal("20"),
            flat_pause_pct=Decimal("10"),
        ),
    )
    sell_config = make_sell_config(args, strategy_name=sell_strategy_name)
    samples = build_fixture_samples(start_ts=int(time.time()), max_ticks=max(1, int(args.max_ticks)))
    counts: dict[str, int] = {}
    buy_payloads: list[dict[str, Any]] = []
    sell_payloads: list[dict[str, Any]] = []
    last_buy_receipt_sample_index: int | None = None
    sell_done = False
    buy_sent = False

    start_payload = {
        "event": "service_start",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": str(args.project),
        "autoTrigger": True,
        "paperOnly": False,
        "mode": "broadcast",
        "rpc": redact_rpc_url(cfg.http_rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "buyStrategy": buy_strategy_name,
        "sellStrategy": sell_strategy_name,
        "amountV": str(args.amount_v),
        "sellPct": str(args.sell_pct),
        "sellRoiPct": str(args.sell_roi_pct),
        "sampleCount": len(samples),
    }
    append_jsonl(output_jsonl, start_payload)
    print(json.dumps(start_payload, ensure_ascii=False), flush=True)

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        token = normalize_hex_address(str(project_row.get("token_addr") or ""))
        pool = normalize_hex_address(str(project_row.get("internal_pool_addr") or ""))
        async with RPCClient(cfg.http_rpc_url, max_retries=3, timeout_sec=20) as rpc:
            for index, sample in enumerate(samples):
                sample["projectStatus"] = "live"
                sample["triggerTypes"] = sample.get("triggerTypes") or ["fixture_tax_tick"]
                sample["tokenPriceUsd"] = sample.get("tokenPriceUsd") or "0.001"
                sample["tokenPriceV"] = sample.get("tokenPriceV") or "0.001"
                counts["ticks"] = counts.get("ticks", 0) + 1

                if not buy_sent:
                    decision = evaluator.evaluate(sample, index=index)
                    if decision.intent is not None:
                        payload = await prewarm_intent(
                            args=buy_args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            project_row=project_row,
                            project_name=project_name,
                            rule_name=rule.name,
                            strategy_name=buy_strategy_name,
                            sample=sample,
                            sample_index=index,
                            intent=decision.intent.__dict__,
                        )
                        payload["autoTriggerSource"] = "sample_stream"
                        payload["taxRate"] = sample.get("buyTaxRate")
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        buy_payloads.append(payload)
                        counts[payload.get("event", "buy_unknown")] = counts.get(payload.get("event", "buy_unknown"), 0) + 1
                        if payload.get("event") == "receipt_success" and payload.get("tradeSent"):
                            buy_sent = True
                            last_buy_receipt_sample_index = index
                            visible_balance, balance_reads = await wait_token_balance_visible(
                                rpc,
                                token=token,
                                owner=owner,
                                timeout_sec=int(args.post_buy_balance_timeout_sec),
                                interval_sec=Decimal(str(args.post_buy_balance_interval_sec)),
                            )
                            balance_payload = {
                                "event": "post_buy_balance_visible" if visible_balance > 0 else "post_buy_balance_not_visible",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "sampleIndex": index,
                                "taxRate": sample.get("buyTaxRate"),
                                "tokenBalanceRaw": str(visible_balance),
                                "reads": balance_reads,
                                "tradeSent": False,
                                "broadcastEnabled": False,
                            }
                            append_jsonl(output_jsonl, balance_payload)
                            print(json.dumps(compact_event(balance_payload), ensure_ascii=False), flush=True)
                            counts[balance_payload["event"]] = counts.get(balance_payload["event"], 0) + 1

                if buy_sent and not sell_done and last_buy_receipt_sample_index is not None and index > last_buy_receipt_sample_index:
                    current_balance_raw = await read_erc20_balance(rpc, token=token, owner=owner)
                    rows = current_run_records(
                        bot.storage.list_launch_execution_records(project_name, limit=500),
                        buy_strategy=buy_strategy_name,
                        sell_strategy=sell_strategy_name,
                    )
                    position = build_position_from_records(rows=rows, current_balance_raw=current_balance_raw)
                    roi_pct = current_roi_pct(position, sample)
                    sell_decision = evaluate_custom_sell(
                        state=multi_state_from_position(position),
                        signal=MultiSellInput(
                            timestamp=int(sample.get("simTimestamp") or time.time()),
                            tax_rate=Decimal(str(sample.get("buyTaxRate") or "0")),
                            current_roi_pct=roi_pct,
                            token_price_usd=None,
                            token_price_v=None,
                            recent_large_buys=(),
                        ),
                        config=sell_config,
                    )
                    if sell_decision.should_sell:
                        payload = await execute_sell_decision(
                            args=sell_args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            account=account,
                            to_checksum_address=to_checksum_address,
                            project_row=project_row,
                            project_name=project_name,
                            strategy_name=sell_strategy_name,
                            rule_name=sell_config.name,
                            sample=sample,
                            sample_index=index,
                            decision=sell_decision,
                            position=position,
                            sell_config=sell_config,
                            owner=owner,
                            token=token,
                            pool=pool,
                        )
                        payload["autoTriggerSource"] = "sample_stream"
                        payload["taxRate"] = sample.get("buyTaxRate")
                        payload["currentRoiPct"] = str(roi_pct) if roi_pct is not None else None
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(compact_event(payload), ensure_ascii=False), flush=True)
                        sell_payloads.append(payload)
                        counts[payload.get("event", "sell_unknown")] = counts.get(payload.get("event", "sell_unknown"), 0) + 1
                        if payload.get("event") == "sell_receipt_success" and payload.get("tradeSent"):
                            sell_done = True
                            zero_balance, zero_reads = await wait_token_balance_zero(
                                rpc,
                                token=token,
                                owner=owner,
                                timeout_sec=int(args.post_buy_balance_timeout_sec),
                                interval_sec=Decimal(str(args.post_buy_balance_interval_sec)),
                            )
                            balance_payload = {
                                "event": "post_sell_balance_zero" if zero_balance == 0 else "post_sell_balance_not_zero",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "sampleIndex": index,
                                "taxRate": sample.get("buyTaxRate"),
                                "tokenBalanceRaw": str(zero_balance),
                                "reads": zero_reads,
                                "tradeSent": False,
                                "broadcastEnabled": False,
                            }
                            append_jsonl(output_jsonl, balance_payload)
                            print(json.dumps(compact_event(balance_payload), ensure_ascii=False), flush=True)
                            counts[balance_payload["event"]] = counts.get(balance_payload["event"], 0) + 1

                if args.sleep_sec > 0 and index < len(samples) - 1:
                    await asyncio.sleep(float(args.sleep_sec))

            tds_balance = await read_erc20_balance(rpc, token=token, owner=owner)

    summary = {
        "ok": bool(
            buy_payloads
            and sell_payloads
            and buy_payloads[-1].get("event") == "receipt_success"
            and sell_payloads[-1].get("event") == "sell_receipt_success"
        ),
        "project": str(args.project),
        "autoTrigger": True,
        "paperOnly": False,
        "sampleCount": len(samples),
        "counts": counts,
        "buyTx": buy_payloads[-1].get("txHash") if buy_payloads else None,
        "buyReceiptStatus": (buy_payloads[-1].get("receipt") or {}).get("status") if buy_payloads else None,
        "sellTx": sell_payloads[-1].get("txHash") if sell_payloads else None,
        "sellReceiptStatus": (sell_payloads[-1].get("receipt") or {}).get("status") if sell_payloads else None,
        "tdsBalanceRawAfter": str(tds_balance),
        "outputJsonl": str(output_jsonl),
    }
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_jsonl(output_jsonl, {"event": "service_stop", "summary": summary, "at": utc_iso(), "atCst": cst_iso()})
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
