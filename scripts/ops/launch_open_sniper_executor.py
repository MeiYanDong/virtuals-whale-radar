#!/usr/bin/env python3
"""Open-second buyer for launches with no anti-sniper tax.

This executor is intentionally separate from the whale-board strategy. It only
handles the first open-second buy for projects whose Virtuals launch config says
there is no anti-sniper window. After the first sent trade, it exits; follow-up
entries should be handled by the independent FDV limit-order executor.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import (  # noqa: E402
    compact_simulation,
    elapsed_ms,
    load_secret_file,
    read_allowance,
    read_erc20_balance,
    receipt_transfer_deltas,
    suggest_fees,
    wait_receipt,
)
from execution_rpc import apply_execution_rpc_to_config, require_isolated_execution_rpc  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    BoundBuyOrder,
    DEFAULT_DEADLINE_OFFSET_SEC,
    PoolQuote,
    TxSimulator,
    decimal_v_to_wei,
    hex_quantity,
    LocalSigner,
    VIRTUALS_BUY_SPENDER,
    VirtualsOrderBuilder,
)
from launch_prewarm_executor import (  # noqa: E402
    compact_fuse,
    decimal_value,
    failed_simulation_checks,
    receipt_summary,
    simulation_failure_reason,
    trigger_fuse,
    update_ledger_stage,
)
from live_strategy_dry_run import append_jsonl, compact_sample, cst_iso, find_project, make_ledger_record, utc_iso  # noqa: E402
from virtuals_bot import RPCClient, VirtualsBot, load_config, parse_virtuals_timestamp, redact_rpc_url  # noqa: E402


OPEN_SNIPER_STRATEGY = "open_sniper_no_tax"
OPEN_SNIPER_RULE = "open_second_first_buy"
OPEN_SNIPER_TRIGGER = "open_second_no_tax"
PROBE_RPC_URLS_ENV = "VWR_PROBE_HTTP_RPC_URLS"
BROADCAST_RPC_URLS_ENV = "VWR_BROADCAST_HTTP_RPC_URLS"
DEFAULT_REQUOTE_REVERT_SELECTORS = "0x850c6f76"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open-second no-anti-sniper launch buyer.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--mode", choices=["simulate", "sign-ready", "broadcast"], default="simulate")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=0)
    parser.add_argument("--buy-v", type=Decimal, default=Decimal("100"))
    parser.add_argument("--max-buy-v", type=Decimal, default=Decimal("100"))
    parser.add_argument("--max-project-v", type=Decimal, default=Decimal("100"))
    parser.add_argument("--min-poll-sec", type=float, default=0.02)
    parser.add_argument("--prelaunch-poll-sec", type=float, default=0.05)
    parser.add_argument("--scheduled-poll-sec", type=float, default=5.0)
    parser.add_argument("--heartbeat-log-sec", type=float, default=2.0)
    parser.add_argument("--arm-before-sec", type=float, default=30.0)
    parser.add_argument("--prepare-before-sec", type=float, default=600.0)
    parser.add_argument("--high-probe-before-sec", type=float, default=300.0)
    parser.add_argument("--ultra-probe-before-sec", type=float, default=90.0)
    parser.add_argument("--prepare-poll-sec", type=float, default=1.0)
    parser.add_argument("--high-probe-poll-sec", type=float, default=0.25)
    parser.add_argument("--ultra-probe-poll-sec", type=float, default=0.05)
    parser.add_argument("--high-probe-workers", type=int, default=2)
    parser.add_argument("--ultra-probe-workers", type=int, default=2)
    parser.add_argument("--probe-race-timeout-sec", type=float, default=0.7)
    parser.add_argument("--broadcast-fanout-timeout-sec", type=float, default=0.8)
    parser.add_argument("--log-every-probe", action="store_true")
    parser.add_argument("--trigger-offset-sec", type=float, default=0.0)
    parser.add_argument("--exit-after-end-sec", type=int, default=300)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--open-buy-amount-out-min-wei", type=int, default=1)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--static-gas", type=int, default=450000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    parser.add_argument("--post-broadcast-confirm-sec", type=float, default=2.0)
    parser.add_argument("--receipt-poll-sec", type=float, default=0.2)
    parser.add_argument("--disable-replacement-bump", action="store_true")
    parser.add_argument("--replacement-after-sec", type=float, default=1.2)
    parser.add_argument("--replacement-bump-bps", type=int, default=15000)
    parser.add_argument("--replacement-min-priority-fee-gwei", type=Decimal, default=Decimal("8"))
    parser.add_argument("--replacement-min-max-fee-gwei", type=Decimal, default=Decimal("10"))
    parser.add_argument("--ignore-active-fuse", action="store_true")
    parser.add_argument("--enable-broadcast", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--disable-presigned-open-tx", action="store_true")
    parser.add_argument("--presign-refresh-sec", type=float, default=0.5)
    parser.add_argument("--requote-revert-selectors", default=DEFAULT_REQUOTE_REVERT_SELECTORS)
    parser.add_argument("--disable-reprobe-after-requote", action="store_true")
    parser.add_argument("--post-trigger-direct-fire", action="store_true")
    parser.add_argument("--direct-fire-max-age-sec", type=float, default=1.0)
    parser.add_argument(
        "--skip-official-no-tax-check",
        action="store_true",
        help="Only allowed outside broadcast mode; useful for local simulator tests.",
    )
    return parser.parse_args()


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def broadcast_enabled(args: argparse.Namespace) -> bool:
    return args.mode == "broadcast" and bool(args.enable_broadcast) and env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST")


def executor_mode(args: argparse.Namespace) -> str:
    return f"open_sniper_{args.mode.replace('-', '_')}"


def ensure_secret_loaded(path: Path) -> None:
    if str(os.environ.get(BURNER_PRIVATE_KEY_ENV) or "").strip():
        return
    load_secret_file(path)


def build_direct_open_buy_order(
    *,
    args: argparse.Namespace,
    cfg: Any,
    project_row: dict[str, Any],
    buy_tax_rate: Any,
    now_ts: int,
) -> BoundBuyOrder:
    token_addr = str(project_row.get("token_addr") or "").strip()
    if not token_addr:
        raise ValueError("missing_token")
    buy_size = Decimal(args.buy_v)
    amount_in_wei = decimal_v_to_wei(buy_size)
    amount_out_min = int(args.open_buy_amount_out_min_wei)
    deadline = int(now_ts) + int(args.deadline_offset_sec)
    tx = VirtualsOrderBuilder().build_buy(
        chain_id=cfg.chain_id,
        from_addr=args.from_address,
        token_addr=token_addr,
        amount_in_v=buy_size,
        amount_out_min_wei=amount_out_min,
        deadline=deadline,
    )
    quote = PoolQuote(
        pool_addr=str(project_row.get("internal_pool_addr") or ""),
        token_addr=token_addr,
        virtual_token_addr=cfg.virtual_token_addr,
        token0=cfg.virtual_token_addr,
        token1=token_addr,
        token_decimals=18,
        virtual_decimals=18,
        token_index=-1,
        reserve_virtual_wei="0",
        reserve_token_raw="0",
        amount_in_wei=str(amount_in_wei),
        quoted_amount_out_raw="0",
        amount_out_min_wei=str(amount_out_min),
        slippage_bps=9999,
        effective_slippage_bps=9999,
        buy_tax_rate_pct=str(buy_tax_rate) if buy_tax_rate not in (None, "") else None,
        tax_adjusted_amount_out_raw="0",
        lp_fee_bps=0,
        deadline=deadline,
    )
    return BoundBuyOrder(tx=tx, quote=quote)


@dataclass
class PreparedOpenTx:
    built_at: float
    expires_at: float
    signed: Any | None
    tx: Any
    quote: Any
    call_payload: dict[str, Any]
    timings_ms: dict[str, float]
    balance_wei: str
    allowance_wei: str

    def compact(self) -> dict[str, Any]:
        quote_summary = {
            "amountInWei": str(getattr(self.quote, "amount_in_wei", "")),
            "quotedAmountOutRaw": str(getattr(self.quote, "quoted_amount_out_raw", "")),
            "amountOutMinWei": str(getattr(self.quote, "amount_out_min_wei", "")),
            "slippageBps": getattr(self.quote, "slippage_bps", None),
            "deadline": getattr(self.quote, "deadline", None),
        }
        return {
            "ageMs": round(max(0.0, (time.monotonic() - self.built_at) * 1000), 1),
            "ttlRemainingMs": round(max(0.0, (self.expires_at - time.monotonic()) * 1000), 1),
            "signed": self.signed is not None,
            "signedTxHash": self.signed.tx_hash if self.signed is not None else None,
            "signedSummary": (
                {
                    "from": self.signed.from_addr,
                    "to": self.signed.to,
                    "chainId": self.signed.chain_id,
                    "nonce": self.signed.nonce,
                    "gas": self.signed.gas,
                }
                if self.signed is not None
                else None
            ),
            "tx": {
                "gas": self.tx.gas,
                "maxFeePerGas": self.tx.max_fee_per_gas,
                "maxPriorityFeePerGas": self.tx.max_priority_fee_per_gas,
            },
            "quote": quote_summary,
            "balanceWei": self.balance_wei,
            "allowanceWei": self.allowance_wei,
            "timingsMs": self.timings_ms,
        }


@dataclass(frozen=True)
class RpcEndpoint:
    label: str
    url: str
    client: RPCClient


def split_rpc_urls(value: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").replace("\n", ",").split(","):
        url = raw.strip()
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def rpc_url_label(url: str, index: int) -> str:
    parsed = urlparse(str(url))
    host = parsed.netloc or parsed.path.split("/")[0] or "rpc"
    host = host.split("@")[-1]
    if "chainstack" in host.lower():
        provider = "chainstack"
    elif "ankr" in host.lower():
        provider = "ankr"
    elif "alchemy" in host.lower():
        provider = "alchemy"
    else:
        provider = host.split(":")[0]
    return f"{provider}-{index}"


def resolve_rpc_url_pool(env_name: str, *, primary_url: str) -> list[str]:
    urls = [str(primary_url or "").strip()]
    urls.extend(split_rpc_urls(os.environ.get(env_name, "")))
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        out.append(url)
        seen.add(url)
    return out


def compact_rpc_pool(urls: list[str]) -> dict[str, Any]:
    return {
        "count": len(urls),
        "labels": [rpc_url_label(url, idx + 1) for idx, url in enumerate(urls)],
    }


def normalize_revert_selectors(value: str) -> set[str]:
    return {
        item.lower()
        for item in re.findall(r"0x[0-9a-fA-F]{8}", str(value or ""))
    }


def extract_revert_selector(error: str) -> str:
    match = re.search(r"0x[0-9a-fA-F]{8}", str(error or ""))
    return match.group(0).lower() if match else ""


def probe_workers_for_phase(args: argparse.Namespace, phase_name: str) -> int:
    if phase_name == "ultra_probe":
        return max(1, int(args.ultra_probe_workers))
    if phase_name == "high_probe":
        return max(1, int(args.high_probe_workers))
    return 1


def no_tax_schedule_context(bot: VirtualsBot, virtuals_data: dict[str, Any], project_row: dict[str, Any]) -> dict[str, Any]:
    launch_info = virtuals_data.get("launchInfo") if isinstance(virtuals_data.get("launchInfo"), dict) else {}
    factory = virtuals_data.get("factory")
    category = virtuals_data.get("category")
    schedule = bot.resolve_buy_tax_schedule(
        factory=factory,
        category=category,
        anti_sniper_tax_type=launch_info.get("antiSniperTaxType"),
        is_project_60days=launch_info.get("isProject60days"),
    )
    start_at = parse_virtuals_timestamp(virtuals_data.get("launchedAt")) or int(project_row.get("start_at") or 0)
    buy_tax_rate = bot.compute_buy_tax_rate(
        tax_start_at=start_at,
        factory=factory,
        category=category,
        anti_sniper_tax_type=launch_info.get("antiSniperTaxType"),
        is_project_60days=launch_info.get("isProject60days"),
        now_ts=max(int(time.time()), int(start_at or 0)),
    )
    status = str(schedule.get("status") or "")
    return {
        "ok": bool(schedule.get("known")) and status in {"bonding_v5_anti_sniper_off", "legacy_no_anti_sniper"},
        "status": status,
        "factory": factory,
        "category": category,
        "antiSniperTaxType": launch_info.get("antiSniperTaxType"),
        "isProject60days": launch_info.get("isProject60days"),
        "launchedAt": virtuals_data.get("launchedAt"),
        "taxStartAt": start_at,
        "buyTaxRate": buy_tax_rate if buy_tax_rate is not None else 0,
        "warning": schedule.get("warning"),
    }


async def official_no_tax_context(bot: VirtualsBot, project_row: dict[str, Any]) -> dict[str, Any]:
    signalhub_project_id = str(project_row.get("signalhub_project_id") or "").strip()
    if not signalhub_project_id:
        return {"ok": False, "status": "missing_signalhub_project_id", "buyTaxRate": 0}
    virtuals_data = await bot.fetch_virtuals_launch_info(signalhub_project_id)
    if not virtuals_data:
        virtuals_data = await fetch_virtuals_launch_info_with_user_agent(signalhub_project_id)
    if not virtuals_data:
        return {"ok": False, "status": "official_config_missing", "buyTaxRate": 0}
    return no_tax_schedule_context(bot, virtuals_data, project_row)


async def fetch_virtuals_launch_info_with_user_agent(project_id: str) -> dict[str, Any]:
    url = f"https://api2.virtuals.io/api/virtuals/{project_id}"
    timeout = aiohttp.ClientTimeout(total=8)
    headers = {"User-Agent": "virtuals-whale-radar/open-sniper"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, params={"populate[0]": "launchInfo"}) as resp:
            if resp.status != 200:
                return {}
            body = await resp.json(content_type=None)
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


def open_sniper_sample(
    bot: VirtualsBot,
    project_row: dict[str, Any],
    *,
    now_ts: int,
    buy_tax_rate: Any,
    attempt: int,
) -> dict[str, Any]:
    status = bot.derive_managed_project_status(project_row, now_ts=now_ts)
    return {
        "realElapsedSec": 0,
        "simTimestamp": int(now_ts),
        "projectStatus": status,
        "events": None,
        "buyTaxRate": str(buy_tax_rate if buy_tax_rate is not None else 0),
        "estimatedFdvWanUsdWithTax": None,
        "liveFdvUsd": None,
        "boardSpentV": None,
        "boardCostWanUsd": None,
        "costRows": 0,
        "whaleRows": 0,
        "triggerTypes": [OPEN_SNIPER_TRIGGER],
        "openSniperAttempt": int(attempt),
    }


def open_sniper_intent(
    *,
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    buy_v: Decimal,
) -> dict[str, Any]:
    return {
        "project": project_name,
        "index": int(sample_index),
        "timestamp": int(sample.get("simTimestamp") or 0),
        "tax_rate": str(sample.get("buyTaxRate") or "0"),
        "buy_size_v": format(Decimal(buy_v).normalize(), "f"),
        "entry_tax_fdv_wan_usd": None,
        "entry_spot_fdv_wan_usd": None,
        "own_weighted_cost_before_wan_usd": None,
        "own_weighted_cost_after_wan_usd": None,
        "board_spent_v": None,
        "board_cost_wan_usd": None,
        "cost_rows": 0,
        "whale_rows": 0,
        "trigger_types": [OPEN_SNIPER_TRIGGER],
        "reason": "open_second_no_tax_first_buy",
        "speedPriority": True,
    }


def sent_buy_records(bot: VirtualsBot, *, project_name: str) -> list[dict[str, Any]]:
    return [
        row
        for row in bot.storage.list_launch_execution_records(project_name, limit=500)
        if int(row.get("trade_sent") or 0) == 1
        and str(row.get("action") or "") in {"would_buy", "buy"}
        and str(row.get("status") or "") not in {"receipt_failed", "prewarm_failed", "simulation_failed"}
    ]


def project_sent_buy_v(bot: VirtualsBot, *, project_name: str) -> Decimal:
    total = Decimal("0")
    for row in sent_buy_records(bot, project_name=project_name):
        total += decimal_value(row.get("buy_size_v"))
    return total


def open_sniper_already_sent(bot: VirtualsBot, *, project_name: str) -> bool:
    return any(
        str(row.get("strategy") or "") == OPEN_SNIPER_STRATEGY
        and str(row.get("rule_name") or "") == OPEN_SNIPER_RULE
        for row in sent_buy_records(bot, project_name=project_name)
    )


async def build_prepared_open_tx(
    *,
    args: argparse.Namespace,
    cfg: Any,
    rpc: RPCClient,
    project_row: dict[str, Any],
    buy_tax_rate: Any,
) -> PreparedOpenTx:
    token_addr = str(project_row.get("token_addr") or "").strip()
    if not token_addr:
        raise ValueError("missing_token")
    if int(args.static_gas) <= 0:
        raise ValueError("--static-gas must be positive")

    buy_size = Decimal(args.buy_v)
    amount_in_wei = int(buy_size * Decimal(10**18))
    timings: dict[str, float] = {}
    start = time.perf_counter()
    balance_wei, allowance_wei = await asyncio.gather(
        read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=args.from_address),
        read_allowance(rpc, token=cfg.virtual_token_addr, owner=args.from_address, spender=VIRTUALS_BUY_SPENDER),
    )
    timings["readBalanceAllowanceMs"] = elapsed_ms(start)
    if int(balance_wei) < amount_in_wei:
        raise ValueError("wallet_balance_not_ready")
    if int(allowance_wei) < amount_in_wei:
        raise ValueError("wallet_allowance_not_ready")

    start_at = int(project_row.get("start_at") or 0)
    tx_now_ts = max(int(time.time()), start_at)
    start = time.perf_counter()
    bound = build_direct_open_buy_order(
        args=args,
        cfg=cfg,
        project_row=project_row,
        buy_tax_rate=buy_tax_rate,
        now_ts=tx_now_ts,
    )
    timings["buildDirectBuyMs"] = elapsed_ms(start)

    tx = bound.tx
    signed = None
    if args.mode in {"sign-ready", "broadcast"}:
        start = time.perf_counter()
        nonce_hex, fees = await asyncio.gather(
            rpc.call("eth_getTransactionCount", [args.from_address, "pending"]),
            suggest_fees(rpc, max_fee_gwei=args.max_fee_gwei, priority_gwei=args.max_priority_fee_gwei),
        )
        timings["nonceAndFeesMs"] = elapsed_ms(start)
        tx = replace(
            bound.tx,
            nonce=int(str(nonce_hex), 16),
            gas=int(args.static_gas),
            max_fee_per_gas=str(fees["maxFeePerGas"]),
            max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
        )
        start = time.perf_counter()
        signed = LocalSigner().sign(tx)
        timings["signMs"] = elapsed_ms(start)
    built_at = time.monotonic()
    return PreparedOpenTx(
        built_at=built_at,
        expires_at=built_at + max(0.1, float(args.deadline_offset_sec) - 5.0),
        signed=signed,
        tx=tx,
        quote=bound.quote,
        call_payload={
            "from": tx.from_addr,
            "to": tx.to,
            "value": hex_quantity(tx.value_wei),
            "data": tx.data,
        },
        timings_ms=timings,
        balance_wei=str(balance_wei),
        allowance_wei=str(allowance_wei),
    )


def validate_args(args: argparse.Namespace, rpc_selection: Any) -> None:
    for field in ("buy_v", "max_buy_v", "max_project_v"):
        value = Decimal(str(getattr(args, field)))
        if value <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    if Decimal(args.buy_v) > Decimal(args.max_buy_v):
        raise SystemExit("--buy-v cannot exceed --max-buy-v")
    if Decimal(args.buy_v) > Decimal(args.max_project_v):
        raise SystemExit("--buy-v cannot exceed --max-project-v")
    if float(args.prepare_before_sec) < float(args.high_probe_before_sec):
        raise SystemExit("--prepare-before-sec must be >= --high-probe-before-sec")
    if float(args.high_probe_before_sec) < float(args.ultra_probe_before_sec):
        raise SystemExit("--high-probe-before-sec must be >= --ultra-probe-before-sec")
    if float(args.ultra_probe_before_sec) < 0:
        raise SystemExit("--ultra-probe-before-sec cannot be negative")
    for field in ("prepare_poll_sec", "high_probe_poll_sec", "ultra_probe_poll_sec", "min_poll_sec"):
        if float(getattr(args, field)) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    for field in ("high_probe_workers", "ultra_probe_workers"):
        if int(getattr(args, field)) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    for field in ("probe_race_timeout_sec", "broadcast_fanout_timeout_sec"):
        if float(getattr(args, field)) <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    if float(args.presign_refresh_sec) <= 0:
        raise SystemExit("--presign-refresh-sec must be positive")
    if float(args.direct_fire_max_age_sec) <= 0:
        raise SystemExit("--direct-fire-max-age-sec must be positive")
    if int(args.open_buy_amount_out_min_wei) <= 0:
        raise SystemExit("--open-buy-amount-out-min-wei must be positive")
    if float(args.post_broadcast_confirm_sec) < 0:
        raise SystemExit("--post-broadcast-confirm-sec cannot be negative")
    if float(args.receipt_poll_sec) <= 0:
        raise SystemExit("--receipt-poll-sec must be positive")
    if float(args.replacement_after_sec) <= 0:
        raise SystemExit("--replacement-after-sec must be positive")
    if int(args.replacement_bump_bps) <= 10_000:
        raise SystemExit("--replacement-bump-bps must be greater than 10000")
    if Decimal(args.replacement_min_priority_fee_gwei) <= 0:
        raise SystemExit("--replacement-min-priority-fee-gwei must be positive")
    if Decimal(args.replacement_min_max_fee_gwei) <= 0:
        raise SystemExit("--replacement-min-max-fee-gwei must be positive")
    if Decimal(args.replacement_min_max_fee_gwei) < Decimal(args.replacement_min_priority_fee_gwei):
        raise SystemExit("--replacement-min-max-fee-gwei must be >= --replacement-min-priority-fee-gwei")
    if args.mode == "broadcast":
        if args.skip_official_no_tax_check:
            raise SystemExit("broadcast mode cannot skip official no-tax check")
        if not args.enable_broadcast:
            raise SystemExit("broadcast mode requires --enable-broadcast")
        if not env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST"):
            raise SystemExit("broadcast mode requires VWR_ENABLE_AUTO_BUY_BROADCAST=1")
        require_isolated_execution_rpc(
            rpc_selection,
            action="open sniper broadcast mode",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )


def launch_phase(args: argparse.Namespace, *, now_float: float, start_at: int) -> dict[str, Any]:
    if start_at <= 0:
        return {
            "phase": "unknown_start",
            "secondsToTrigger": None,
            "shouldPrepare": False,
            "shouldProbe": False,
            "pollSec": float(args.scheduled_poll_sec),
        }
    trigger_at = float(start_at) + float(args.trigger_offset_sec)
    seconds_to_trigger = trigger_at - now_float
    if seconds_to_trigger > float(args.prepare_before_sec):
        phase = "standby"
        poll_sec = min(float(args.scheduled_poll_sec), seconds_to_trigger - float(args.prepare_before_sec))
    elif seconds_to_trigger > float(args.high_probe_before_sec):
        phase = "prepare"
        poll_sec = min(float(args.prepare_poll_sec), seconds_to_trigger - float(args.high_probe_before_sec))
    elif seconds_to_trigger > float(args.ultra_probe_before_sec):
        phase = "high_probe"
        poll_sec = min(float(args.high_probe_poll_sec), seconds_to_trigger - float(args.ultra_probe_before_sec))
    else:
        phase = "ultra_probe"
        poll_sec = float(args.ultra_probe_poll_sec)
    poll_sec = max(float(args.min_poll_sec), float(poll_sec))
    return {
        "phase": phase,
        "secondsToTrigger": round(seconds_to_trigger, 3),
        "triggerAt": trigger_at,
        "shouldPrepare": phase in {"prepare", "high_probe", "ultra_probe"},
        "shouldProbe": phase in {"high_probe", "ultra_probe"},
        "pollSec": poll_sec,
    }


def sleep_interval(args: argparse.Namespace, *, now_float: float, start_at: int, sent: bool) -> float:
    if sent:
        return 0.0
    phase = launch_phase(args, now_float=now_float, start_at=start_at)
    return max(0.001, float(phase["pollSec"]))


def should_refresh_prepared_open_tx(
    args: argparse.Namespace,
    *,
    prepared: PreparedOpenTx | None,
    phase_name: str,
    phase_changed: bool,
    last_presign_refresh_started: float,
    now_monotonic: float | None = None,
) -> bool:
    if args.disable_presigned_open_tx:
        return False
    if phase_name not in {"prepare", "high_probe", "ultra_probe"}:
        return False
    now_mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
    if prepared is None:
        return True
    if now_mono >= prepared.expires_at:
        return True
    if phase_changed:
        return True
    return (now_mono - float(last_presign_refresh_started)) >= float(args.presign_refresh_sec)


def probe_needs_requote(args: argparse.Namespace, *, probe: dict[str, Any], phase_info: dict[str, Any]) -> bool:
    if probe.get("ready"):
        return False
    seconds_to_trigger = phase_info.get("secondsToTrigger")
    if seconds_to_trigger is None or float(seconds_to_trigger) > 0:
        return False
    selectors = normalize_revert_selectors(str(args.requote_revert_selectors))
    if not selectors:
        return False
    return extract_revert_selector(str(probe.get("error") or "")) in selectors


def direct_fire_due(
    args: argparse.Namespace,
    *,
    phase_info: dict[str, Any],
    prepared: PreparedOpenTx | None,
    already_attempted: bool,
    now_monotonic: float | None = None,
) -> bool:
    if not bool(args.post_trigger_direct_fire) or already_attempted or prepared is None:
        return False
    seconds_to_trigger = phase_info.get("secondsToTrigger")
    if seconds_to_trigger is None or float(seconds_to_trigger) > 0:
        return False
    now_mono = time.monotonic() if now_monotonic is None else float(now_monotonic)
    return (now_mono - prepared.built_at) <= float(args.direct_fire_max_age_sec)


def update_phase_metrics(metrics: dict[str, dict[str, Any]], *, phase: str, probe: dict[str, Any]) -> None:
    row = metrics.setdefault(
        phase,
        {
            "probes": 0,
            "ready": 0,
            "errors": 0,
            "totalProbeMs": 0.0,
            "minProbeMs": None,
            "maxProbeMs": None,
            "lastProbeMs": None,
            "avgProbeMs": None,
            "lastError": "",
        },
    )
    probe_ms = float(probe.get("probeMs") or 0)
    row["probes"] += 1
    row["totalProbeMs"] = round(float(row["totalProbeMs"]) + probe_ms, 3)
    row["lastProbeMs"] = round(probe_ms, 3)
    row["minProbeMs"] = round(probe_ms, 3) if row["minProbeMs"] is None else round(min(float(row["minProbeMs"]), probe_ms), 3)
    row["maxProbeMs"] = round(probe_ms, 3) if row["maxProbeMs"] is None else round(max(float(row["maxProbeMs"]), probe_ms), 3)
    row["avgProbeMs"] = round(float(row["totalProbeMs"]) / max(1, int(row["probes"])), 3)
    if probe.get("ready"):
        row["ready"] += 1
    if probe.get("error"):
        row["errors"] += 1
        row["lastError"] = str(probe.get("error") or "")[:240]


async def probe_prepared_open_tx(*, rpc: RPCClient, prepared: PreparedOpenTx) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = await rpc.call("eth_call", [prepared.call_payload, "latest"])
        return {
            "ready": True,
            "ethCallOk": True,
            "probeMs": elapsed_ms(start),
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ready": False,
            "ethCallOk": False,
            "probeMs": elapsed_ms(start),
            "result": None,
            "error": str(exc),
        }


async def probe_prepared_open_tx_endpoint(*, endpoint: RpcEndpoint, prepared: PreparedOpenTx, worker_index: int) -> dict[str, Any]:
    probe = await probe_prepared_open_tx(rpc=endpoint.client, prepared=prepared)
    probe["provider"] = endpoint.label
    probe["workerIndex"] = worker_index
    return probe


async def probe_prepared_open_tx_race(
    *,
    endpoints: list[RpcEndpoint],
    prepared: PreparedOpenTx,
    worker_count: int,
    timeout_sec: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not endpoints:
        return {
            "ready": False,
            "ethCallOk": False,
            "probeMs": elapsed_ms(started),
            "result": None,
            "error": "missing_probe_rpc_endpoint",
            "results": [],
            "workerCount": 0,
        }
    selected = [endpoints[index % len(endpoints)] for index in range(max(1, int(worker_count)))]
    tasks = []
    task_meta: dict[asyncio.Task[dict[str, Any]], tuple[RpcEndpoint, int]] = {}
    for index, endpoint in enumerate(selected):
        task = asyncio.create_task(
            probe_prepared_open_tx_endpoint(endpoint=endpoint, prepared=prepared, worker_index=index + 1)
        )
        tasks.append(task)
        task_meta[task] = (endpoint, index + 1)
    pending: set[asyncio.Task[dict[str, Any]]] = set(tasks)
    results: list[dict[str, Any]] = []
    first_ready: dict[str, Any] | None = None
    deadline = time.perf_counter() + max(0.05, float(timeout_sec))
    while pending:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        done, pending = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            break
        for task in done:
            with contextlib.suppress(asyncio.CancelledError):
                result = await task
                results.append(result)
                if result.get("ready") and first_ready is None:
                    first_ready = result
        if first_ready is not None:
            break
    for task in pending:
        task.cancel()
    for task in pending:
        endpoint, worker_index = task_meta.get(task, (selected[0], 0))
        results.append(
            {
                "ready": False,
                "ethCallOk": False,
                "probeMs": round(max(0.0, (time.perf_counter() - started) * 1000), 3),
                "result": None,
                "error": "probe_cancelled_after_ready" if first_ready is not None else "probe_timeout",
                "provider": endpoint.label,
                "workerIndex": worker_index,
            }
        )
    results.sort(key=lambda row: (not bool(row.get("ready")), float(row.get("probeMs") or 0)))
    first_ready = first_ready or next((row for row in results if row.get("ready")), None)
    winner = first_ready or (results[0] if results else None)
    return {
        "ready": bool(first_ready),
        "ethCallOk": bool(first_ready),
        "probeMs": elapsed_ms(started),
        "result": first_ready.get("result") if first_ready else None,
        "error": "" if first_ready else (str((winner or {}).get("error") or "") if winner else "probe_no_result"),
        "provider": str((winner or {}).get("provider") or ""),
        "workerIndex": (winner or {}).get("workerIndex"),
        "results": results,
        "workerCount": len(selected),
        "providerCount": len(endpoints),
    }


def is_raw_tx_propagation_success(error: str) -> bool:
    lowered = str(error or "").lower()
    return any(
        marker in lowered
        for marker in (
            "already known",
            "already imported",
            "known transaction",
            "transaction already exists",
            "nonce too low",
        )
    )


async def send_raw_transaction_endpoint(
    *,
    endpoint: RpcEndpoint,
    raw_tx: str,
    signed_tx_hash: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        tx_hash = await endpoint.client.call("eth_sendRawTransaction", [raw_tx])
        return {
            "ok": True,
            "provider": endpoint.label,
            "txHash": str(tx_hash),
            "sendRawMs": elapsed_ms(started),
            "reason": "send_raw_transaction_ack",
        }
    except Exception as exc:
        reason = str(exc)
        if is_raw_tx_propagation_success(reason):
            return {
                "ok": True,
                "provider": endpoint.label,
                "txHash": signed_tx_hash,
                "sendRawMs": elapsed_ms(started),
                "reason": "raw_transaction_already_propagated",
                "providerMessage": reason[:240],
            }
        return {
            "ok": False,
            "provider": endpoint.label,
            "txHash": "",
            "sendRawMs": elapsed_ms(started),
            "reason": reason[:240],
        }


async def send_raw_transaction_fanout(
    *,
    endpoints: list[RpcEndpoint],
    raw_tx: str,
    signed_tx_hash: str,
    timeout_sec: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not endpoints:
        return {
            "ok": False,
            "txHash": "",
            "sendRawMs": elapsed_ms(started),
            "responses": [],
            "reason": "missing_broadcast_rpc_endpoint",
        }
    tasks = [
        asyncio.create_task(
            send_raw_transaction_endpoint(endpoint=endpoint, raw_tx=raw_tx, signed_tx_hash=signed_tx_hash)
        )
        for endpoint in endpoints
    ]
    done, pending = await asyncio.wait(tasks, timeout=max(0.05, float(timeout_sec)))
    for task in pending:
        task.cancel()
    responses: list[dict[str, Any]] = []
    for task in done:
        with contextlib.suppress(asyncio.CancelledError):
            responses.append(await task)
    for endpoint in [endpoints[index] for index, task in enumerate(tasks) if task in pending]:
        responses.append(
            {
                "ok": False,
                "provider": endpoint.label,
                "txHash": "",
                "sendRawMs": round(max(0.0, float(timeout_sec) * 1000), 3),
                "reason": "broadcast_timeout",
            }
        )
    responses.sort(key=lambda row: (not bool(row.get("ok")), float(row.get("sendRawMs") or 0)))
    winner = next((row for row in responses if row.get("ok")), None)
    return {
        "ok": bool(winner),
        "txHash": str((winner or {}).get("txHash") or ""),
        "sendRawMs": elapsed_ms(started),
        "winnerProvider": str((winner or {}).get("provider") or ""),
        "responses": responses,
        "reason": str((winner or {}).get("reason") or (responses[0].get("reason") if responses else "broadcast_no_result")),
    }


def gwei_to_wei(value: Decimal | str | int | float) -> int:
    return int(Decimal(str(value)) * Decimal("1000000000"))


def bump_fee_value(*, current_wei: Any, min_gwei: Decimal, bump_bps: int) -> str:
    current = int(current_wei or 0)
    bumped = current * int(bump_bps) // 10_000
    return str(max(bumped, gwei_to_wei(min_gwei)))


def build_replacement_open_tx(args: argparse.Namespace, prepared: PreparedOpenTx) -> PreparedOpenTx:
    if prepared.signed is None:
        raise ValueError("missing_signed_tx_for_replacement")
    started = time.perf_counter()
    tx = replace(
        prepared.tx,
        nonce=prepared.signed.nonce,
        gas=prepared.signed.gas,
        max_fee_per_gas=bump_fee_value(
            current_wei=prepared.tx.max_fee_per_gas,
            min_gwei=Decimal(args.replacement_min_max_fee_gwei),
            bump_bps=int(args.replacement_bump_bps),
        ),
        max_priority_fee_per_gas=bump_fee_value(
            current_wei=prepared.tx.max_priority_fee_per_gas,
            min_gwei=Decimal(args.replacement_min_priority_fee_gwei),
            bump_bps=int(args.replacement_bump_bps),
        ),
    )
    signed = LocalSigner().sign(tx)
    built_at = time.monotonic()
    timings = dict(prepared.timings_ms)
    timings["replacementSignMs"] = elapsed_ms(started)
    return PreparedOpenTx(
        built_at=built_at,
        expires_at=prepared.expires_at,
        signed=signed,
        tx=tx,
        quote=prepared.quote,
        call_payload=prepared.call_payload,
        timings_ms=timings,
        balance_wei=prepared.balance_wei,
        allowance_wei=prepared.allowance_wei,
    )


async def observe_open_tx_status(
    *,
    rpc: RPCClient,
    tx_hash: str,
    from_address: str,
    nonce: int,
    timeout_sec: float,
    poll_sec: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    deadline = started + max(0.0, float(timeout_sec))
    last_pending_nonce: int | None = None
    last_latest_nonce: int | None = None
    last_error = ""
    receipt: dict[str, Any] | None = None
    while True:
        try:
            receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
            if receipt:
                status = str(receipt.get("status") or "")
                return {
                    "receipt": receipt,
                    "receiptOk": status in {"0x1", "1"},
                    "status": "receipt_observed",
                    "nonceConsumed": True,
                    "pendingNonce": last_pending_nonce,
                    "latestNonce": last_latest_nonce,
                    "waitMs": elapsed_ms(started),
                    "error": "",
                }
            pending_hex, latest_hex = await asyncio.gather(
                rpc.call("eth_getTransactionCount", [from_address, "pending"]),
                rpc.call("eth_getTransactionCount", [from_address, "latest"]),
            )
            last_pending_nonce = int(str(pending_hex), 16)
            last_latest_nonce = int(str(latest_hex), 16)
            if last_latest_nonce > int(nonce):
                return {
                    "receipt": None,
                    "receiptOk": False,
                    "status": "nonce_mined_without_receipt",
                    "nonceConsumed": True,
                    "pendingNonce": last_pending_nonce,
                    "latestNonce": last_latest_nonce,
                    "waitMs": elapsed_ms(started),
                    "error": "",
                }
        except Exception as exc:
            last_error = str(exc)
        if time.perf_counter() >= deadline:
            break
        await asyncio.sleep(max(0.01, min(float(poll_sec), deadline - time.perf_counter())))
    return {
        "receipt": None,
        "receiptOk": False,
        "status": "not_confirmed",
        "nonceConsumed": bool(last_pending_nonce is not None and last_pending_nonce > int(nonce)),
        "pendingNonce": last_pending_nonce,
        "latestNonce": last_latest_nonce,
        "waitMs": elapsed_ms(started),
        "error": last_error[:240],
    }


async def execute_open_sniper_attempt(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    output_jsonl: Path,
) -> dict[str, Any]:
    intent = open_sniper_intent(
        project_name=project_name,
        sample=sample,
        sample_index=sample_index,
        buy_v=Decimal(args.buy_v),
    )
    ledger_record = make_ledger_record(
        project_row=project_row,
        project_name=project_name,
        rule_name=OPEN_SNIPER_RULE,
        strategy_name=OPEN_SNIPER_STRATEGY,
        action="would_buy",
        reason=intent["reason"],
        sample_index=sample_index,
        sample=sample,
        intent=intent,
        pause=None,
    )
    ledger_record["mode"] = executor_mode(args)
    bot.storage.upsert_launch_execution_record(ledger_record)
    intent_id = ledger_record["intent_id"]

    payload: dict[str, Any] = {
        "event": "open_sniper_attempt",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "rule": OPEN_SNIPER_RULE,
        "strategy": OPEN_SNIPER_STRATEGY,
        "mode": executor_mode(args),
        "ledgerIntentId": intent_id,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "intent": intent,
        "sample": compact_sample(sample),
    }

    active_fuse = bot.storage.get_active_launch_execution_fuse(
        project=project_name,
        strategy=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
    )
    if active_fuse and not args.ignore_active_fuse:
        payload.update({"event": "blocked_by_active_fuse", "reason": "active_fuse", "activeFuse": compact_fuse(active_fuse)})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_active_fuse",
            reason="active_fuse",
            failure_stage="fuse",
            failure_reason="active_fuse",
        )
        return payload

    if args.mode == "broadcast" and not broadcast_enabled(args):
        payload.update({"event": "blocked_by_broadcast_gate", "reason": "missing_cli_or_env_broadcast_gate"})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_broadcast_gate",
            reason="missing_cli_or_env_broadcast_gate",
            failure_stage="broadcast_gate",
            failure_reason="broadcast_not_enabled",
        )
        return payload

    buy_size = Decimal(args.buy_v)
    existing_project_v = project_sent_buy_v(bot, project_name=project_name)
    if existing_project_v + buy_size > Decimal(args.max_project_v):
        payload.update(
            {
                "event": "blocked_by_project_cap",
                "reason": "project_sent_v_exceeds_max_project_v",
                "sentProjectV": str(existing_project_v),
                "projectedProjectV": str(existing_project_v + buy_size),
                "maxProjectV": str(args.max_project_v),
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_project_cap",
            reason="project_sent_v_exceeds_max_project_v",
            failure_stage="risk_limit",
            failure_reason="project_sent_v_exceeds_max_project_v",
        )
        return payload

    token_addr = str(project_row.get("token_addr") or "").strip()
    if not token_addr:
        payload.update({"event": "open_sniper_not_ready", "reason": "missing_token"})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="not_ready",
            reason="missing_token",
        )
        return payload

    timings: dict[str, float] = {}
    try:
        start = time.perf_counter()
        bound = build_direct_open_buy_order(
            args=args,
            cfg=cfg,
            project_row=project_row,
            buy_tax_rate=sample.get("buyTaxRate"),
            now_ts=int(time.time()),
        )
        timings["buildDirectBuyMs"] = elapsed_ms(start)

        start = time.perf_counter()
        simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
        timings["simulateMs"] = elapsed_ms(start)
        simulation_compact = compact_simulation(simulation)
        payload.update(
            {
                "event": "simulation_green" if simulation["green"] else "simulation_failed",
                "quote": asdict(bound.quote),
                "simulation": simulation_compact,
                "timingsMs": timings,
            }
        )
        if not simulation["green"]:
            reason = simulation_failure_reason(simulation)
            payload["reason"] = reason
            payload["failedChecks"] = failed_simulation_checks(simulation)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=OPEN_SNIPER_STRATEGY,
                rule_name=OPEN_SNIPER_RULE,
                mode=executor_mode(args),
                status="readiness_not_ready",
                reason=reason,
                simulation=simulation_compact,
                broadcast_enabled=broadcast_enabled(args),
            )
            return payload

        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="simulation_green",
            reason="simulation_green",
            simulation=simulation_compact,
        )
        if args.mode == "simulate":
            payload["reason"] = "simulate_mode_no_sign"
            return payload

        start = time.perf_counter()
        fees = await suggest_fees(
            rpc,
            max_fee_gwei=args.max_fee_gwei,
            priority_gwei=args.max_priority_fee_gwei,
        )
        timings["feeSuggestMs"] = elapsed_ms(start)
        gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
        gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
        tx = replace(
            bound.tx,
            nonce=int(simulation["checks"]["nonce"]["pendingNonce"]),
            gas=gas,
            max_fee_per_gas=str(fees["maxFeePerGas"]),
            max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
        )
        start = time.perf_counter()
        signed = LocalSigner().sign(tx)
        timings["signMs"] = elapsed_ms(start)
        payload.update(
            {
                "event": "signed_ready",
                "signed": True,
                "signedTxHash": signed.tx_hash,
                "signedSummary": {
                    "from": signed.from_addr,
                    "to": signed.to,
                    "chainId": signed.chain_id,
                    "nonce": signed.nonce,
                    "gas": signed.gas,
                    "maxFeePerGas": tx.max_fee_per_gas,
                    "maxPriorityFeePerGas": tx.max_priority_fee_per_gas,
                },
                "timingsMs": timings,
                "reason": "signed_no_raw_tx_persisted",
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="signed_ready",
            reason="signed_no_raw_tx_persisted",
            simulation=simulation_compact,
            signed_tx_hash=signed.tx_hash,
        )
        if args.mode == "sign-ready":
            return payload

        start = time.perf_counter()
        send_start = time.perf_counter()
        sent_hash = await rpc.call("eth_sendRawTransaction", [signed.raw_tx])
        timings["sendRawMs"] = elapsed_ms(send_start)
        timings["triggerToSendAckMs"] = elapsed_ms(start)
        payload.update(
            {
                "event": "broadcast_sent",
                "readOnly": False,
                "broadcasted": True,
                "tradeSent": True,
                "broadcastEnabled": True,
                "txHash": str(sent_hash),
                "timingsMs": timings,
                "reason": "send_raw_transaction_ack",
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="broadcast_sent",
            reason="send_raw_transaction_ack",
            simulation=simulation_compact,
            signed_tx_hash=signed.tx_hash,
            broadcast_tx_hash=str(sent_hash),
            trade_sent=True,
            broadcast_enabled=True,
        )
        if args.no_wait_receipt:
            payload["receiptSkipped"] = True
            payload["reason"] = "receipt_wait_skipped"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=OPEN_SNIPER_STRATEGY,
                rule_name=OPEN_SNIPER_RULE,
                mode=executor_mode(args),
                status="broadcast_sent_no_receipt_wait",
                reason="receipt_wait_skipped",
                simulation=simulation_compact,
                signed_tx_hash=signed.tx_hash,
                broadcast_tx_hash=str(sent_hash),
                trade_sent=True,
                broadcast_enabled=True,
            )
            return payload

        receipt_start = time.perf_counter()
        receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
        timings["waitReceiptMs"] = elapsed_ms(receipt_start)
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=args.from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        balance_start = time.perf_counter()
        virtual_after, token_after, allowance_after = await asyncio.gather(
            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=args.from_address),
            read_erc20_balance(rpc, token=token_addr, owner=args.from_address),
            read_allowance(rpc, token=cfg.virtual_token_addr, owner=args.from_address, spender=VIRTUALS_BUY_SPENDER),
        )
        timings["readAfterMs"] = elapsed_ms(balance_start)
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        receipt_status = str((receipt or {}).get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        payload.update(
            {
                "event": "receipt_success" if receipt_ok else "receipt_failed",
                "receiptSkipped": False,
                "receipt": receipt_payload,
                "balancesAfter": {
                    "virtualWei": str(virtual_after),
                    "targetTokenRaw": str(token_after),
                    "allowanceWei": str(allowance_after),
                },
                "timingsMs": timings,
                "reason": "receipt_observed" if receipt is not None else "receipt_timeout",
            }
        )
        if not receipt_ok:
            reason = "receipt_timeout" if receipt is None else "receipt_failed"
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=OPEN_SNIPER_STRATEGY,
                rule_name=OPEN_SNIPER_RULE,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason=reason,
                details={"txHash": str(sent_hash), "receipt": receipt_payload},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason="receipt_observed" if receipt is not None else "receipt_timeout",
            simulation=simulation_compact,
            signed_tx_hash=signed.tx_hash,
            broadcast_tx_hash=str(sent_hash),
            receipt=receipt_payload,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else ("receipt_timeout" if receipt is None else "receipt_failed"),
            trade_sent=True,
            broadcast_enabled=True,
        )
        return payload
    except Exception as exc:
        reason = str(exc)
        payload.update({"event": "open_sniper_not_ready", "reason": reason, "timingsMs": timings})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="not_ready",
            reason=reason,
        )
        return payload


async def send_prepared_open_tx(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    broadcast_endpoints: list[RpcEndpoint],
    project_row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    prepared: PreparedOpenTx,
) -> dict[str, Any]:
    if prepared.signed is None:
        return {
            "event": "open_sniper_probe_ready",
            "reason": "simulate_mode_no_signed_tx",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "rule": OPEN_SNIPER_RULE,
            "strategy": OPEN_SNIPER_STRATEGY,
            "mode": executor_mode(args),
            "sampleIndex": sample_index,
            "readOnly": True,
            "tradeSent": False,
            "broadcastEnabled": broadcast_enabled(args),
            "sample": compact_sample(sample),
            "signedPreparedOpenTx": prepared.compact(),
            "quote": asdict(prepared.quote),
        }
    intent = open_sniper_intent(
        project_name=project_name,
        sample=sample,
        sample_index=sample_index,
        buy_v=Decimal(args.buy_v),
    )
    ledger_record = make_ledger_record(
        project_row=project_row,
        project_name=project_name,
        rule_name=OPEN_SNIPER_RULE,
        strategy_name=OPEN_SNIPER_STRATEGY,
        action="would_buy",
        reason=intent["reason"],
        sample_index=sample_index,
        sample=sample,
        intent=intent,
        pause=None,
    )
    ledger_record["mode"] = executor_mode(args)
    bot.storage.upsert_launch_execution_record(ledger_record)
    intent_id = ledger_record["intent_id"]
    timings = dict(prepared.timings_ms)
    payload: dict[str, Any] = {
        "event": "signed_ready",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "rule": OPEN_SNIPER_RULE,
        "strategy": OPEN_SNIPER_STRATEGY,
        "mode": executor_mode(args),
        "ledgerIntentId": intent_id,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "intent": intent,
        "sample": compact_sample(sample),
        "signed": True,
        "signedTxHash": prepared.signed.tx_hash,
        "signedPreparedOpenTx": prepared.compact(),
        "quote": asdict(prepared.quote),
        "timingsMs": timings,
        "reason": "presigned_open_tx_ready",
    }
    update_ledger_stage(
        bot,
        intent_id=intent_id,
        project_name=project_name,
        strategy_name=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
        mode=executor_mode(args),
        status="signed_ready",
        reason="presigned_open_tx_ready",
        simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
        signed_tx_hash=prepared.signed.tx_hash,
    )
    active_fuse = bot.storage.get_active_launch_execution_fuse(
        project=project_name,
        strategy=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
    )
    if active_fuse and not args.ignore_active_fuse:
        payload.update({"event": "blocked_by_active_fuse", "reason": "active_fuse", "activeFuse": compact_fuse(active_fuse)})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_active_fuse",
            reason="active_fuse",
            failure_stage="fuse",
            failure_reason="active_fuse",
        )
        return payload
    if args.mode == "sign-ready":
        return payload
    if args.mode != "broadcast":
        payload["reason"] = "simulate_mode_no_broadcast"
        return payload
    if not broadcast_enabled(args):
        payload.update({"event": "blocked_by_broadcast_gate", "reason": "missing_cli_or_env_broadcast_gate"})
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_broadcast_gate",
            reason="missing_cli_or_env_broadcast_gate",
            failure_stage="broadcast_gate",
            failure_reason="broadcast_not_enabled",
        )
        return payload
    existing_project_v = project_sent_buy_v(bot, project_name=project_name)
    projected_project_v = existing_project_v + Decimal(args.buy_v)
    if projected_project_v > Decimal(args.max_project_v):
        payload.update(
            {
                "event": "blocked_by_project_cap",
                "reason": "project_sent_v_exceeds_max_project_v",
                "sentProjectV": str(existing_project_v),
                "projectedProjectV": str(projected_project_v),
                "maxProjectV": str(args.max_project_v),
            }
        )
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="blocked_by_project_cap",
            reason="project_sent_v_exceeds_max_project_v",
            failure_stage="risk_limit",
            failure_reason="project_sent_v_exceeds_max_project_v",
        )
        return payload

    start = time.perf_counter()
    try:
        fanout = await send_raw_transaction_fanout(
            endpoints=broadcast_endpoints or [RpcEndpoint(label="execution-1", url=rpc.url, client=rpc)],
            raw_tx=prepared.signed.raw_tx,
            signed_tx_hash=prepared.signed.tx_hash,
            timeout_sec=float(args.broadcast_fanout_timeout_sec),
        )
        if not fanout.get("ok"):
            raise RuntimeError(str(fanout.get("reason") or "broadcast_fanout_failed"))
        sent_hash = str(fanout.get("txHash") or prepared.signed.tx_hash)
    except Exception as exc:
        reason = str(exc)
        timings["sendRawMs"] = elapsed_ms(start)
        payload.update(
            {
                "event": "broadcast_failed",
                "reason": reason,
                "timingsMs": timings,
            }
        )
        fuse = trigger_fuse(
            bot,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            intent_id=intent_id,
            failure_stage="broadcast",
            failure_reason=reason,
            details={"signedTxHash": prepared.signed.tx_hash, "timingsMs": timings},
        )
        payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=OPEN_SNIPER_STRATEGY,
            rule_name=OPEN_SNIPER_RULE,
            mode=executor_mode(args),
            status="broadcast_failed",
            reason=reason,
            simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
            signed_tx_hash=prepared.signed.tx_hash,
            failure_stage="broadcast",
            failure_reason=reason,
            broadcast_enabled=True,
        )
        return payload
    timings["sendRawMs"] = elapsed_ms(start)
    timings["triggerToSendAckMs"] = timings["sendRawMs"]
    payload.update(
        {
            "event": "broadcast_sent",
            "readOnly": False,
            "broadcasted": True,
            "tradeSent": True,
            "broadcastEnabled": True,
            "txHash": str(sent_hash),
            "timingsMs": timings,
            "broadcastFanout": {
                "providerCount": len(broadcast_endpoints or []),
                "winnerProvider": fanout.get("winnerProvider"),
                "responses": fanout.get("responses"),
                "sendRawMs": fanout.get("sendRawMs"),
            },
            "reason": "send_presigned_open_tx_ack",
        }
    )
    update_ledger_stage(
        bot,
        intent_id=intent_id,
        project_name=project_name,
        strategy_name=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
        mode=executor_mode(args),
        status="broadcast_sent_no_receipt_wait" if args.no_wait_receipt else "broadcast_sent",
        reason="receipt_wait_skipped" if args.no_wait_receipt else "send_presigned_open_tx_ack",
        simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
        signed_tx_hash=prepared.signed.tx_hash,
        broadcast_tx_hash=str(sent_hash),
        trade_sent=True,
        broadcast_enabled=True,
    )
    token_addr = str(project_row.get("token_addr") or "").strip()
    initial_confirm_sec = (
        float(args.receipt_timeout_sec)
        if not args.no_wait_receipt
        else max(float(args.post_broadcast_confirm_sec), 0.0 if args.disable_replacement_bump else float(args.replacement_after_sec))
    )
    confirmation: dict[str, Any] | None = None
    if initial_confirm_sec > 0:
        confirmation = await observe_open_tx_status(
            rpc=rpc,
            tx_hash=str(sent_hash),
            from_address=args.from_address,
            nonce=prepared.signed.nonce,
            timeout_sec=initial_confirm_sec,
            poll_sec=float(args.receipt_poll_sec),
        )
        timings["postBroadcastConfirmMs"] = confirmation.get("waitMs")
        receipt = confirmation.get("receipt")
        receipt_payload = (
            receipt_summary(
                receipt,
                receipt_transfer_deltas(
                    receipt,
                    owner=args.from_address,
                    virtual_token=cfg.virtual_token_addr,
                    target_token=token_addr,
                ),
            )
            if receipt
            else None
        )
        payload["postBroadcastCheck"] = {key: value for key, value in confirmation.items() if key != "receipt"}
        if receipt_payload is not None:
            payload["receipt"] = receipt_payload
        if confirmation.get("receiptOk"):
            payload.update(
                {
                    "event": "receipt_success",
                    "receiptSkipped": False,
                    "reason": "receipt_observed",
                    "timingsMs": timings,
                }
            )
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=OPEN_SNIPER_STRATEGY,
                rule_name=OPEN_SNIPER_RULE,
                mode=executor_mode(args),
                status="receipt_success",
                reason="receipt_observed",
                simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
                signed_tx_hash=prepared.signed.tx_hash,
                broadcast_tx_hash=str(sent_hash),
                receipt=receipt_payload,
                trade_sent=True,
                broadcast_enabled=True,
            )
            return payload

    should_replace = (
        args.mode == "broadcast"
        and not bool(args.disable_replacement_bump)
        and prepared.signed is not None
        and (confirmation is None or not confirmation.get("receiptOk"))
        and (confirmation is None or confirmation.get("status") != "nonce_mined_without_receipt")
        and int(time.time()) < int(getattr(prepared.quote, "deadline", 0) or 0)
    )
    if should_replace:
        try:
            replacement_start = time.perf_counter()
            replacement = build_replacement_open_tx(args, prepared)
            timings["replacementBuildMs"] = elapsed_ms(replacement_start)
            replacement_fanout = await send_raw_transaction_fanout(
                endpoints=broadcast_endpoints or [RpcEndpoint(label="execution-1", url=rpc.url, client=rpc)],
                raw_tx=replacement.signed.raw_tx,
                signed_tx_hash=replacement.signed.tx_hash,
                timeout_sec=float(args.broadcast_fanout_timeout_sec),
            )
            if replacement_fanout.get("ok"):
                replacement_hash = str(replacement_fanout.get("txHash") or replacement.signed.tx_hash)
                payload["replacement"] = {
                    "sent": True,
                    "txHash": replacement_hash,
                    "signedTxHash": replacement.signed.tx_hash,
                    "signedSummary": replacement.compact().get("signedSummary"),
                    "fanout": {
                        "winnerProvider": replacement_fanout.get("winnerProvider"),
                        "responses": replacement_fanout.get("responses"),
                        "sendRawMs": replacement_fanout.get("sendRawMs"),
                    },
                }
                update_ledger_stage(
                    bot,
                    intent_id=intent_id,
                    project_name=project_name,
                    strategy_name=OPEN_SNIPER_STRATEGY,
                    rule_name=OPEN_SNIPER_RULE,
                    mode=executor_mode(args),
                    status="broadcast_replacement_sent_no_receipt_wait" if args.no_wait_receipt else "broadcast_replacement_sent",
                    reason="replacement_bump_sent",
                    simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
                    signed_tx_hash=replacement.signed.tx_hash,
                    broadcast_tx_hash=replacement_hash,
                    trade_sent=True,
                    broadcast_enabled=True,
                )
                if float(args.post_broadcast_confirm_sec) > 0:
                    replacement_confirmation = await observe_open_tx_status(
                        rpc=rpc,
                        tx_hash=replacement_hash,
                        from_address=args.from_address,
                        nonce=replacement.signed.nonce,
                        timeout_sec=float(args.post_broadcast_confirm_sec),
                        poll_sec=float(args.receipt_poll_sec),
                    )
                    payload["replacement"]["postBroadcastCheck"] = {
                        key: value for key, value in replacement_confirmation.items() if key != "receipt"
                    }
                    replacement_receipt = replacement_confirmation.get("receipt")
                    if replacement_receipt:
                        replacement_receipt_payload = receipt_summary(
                            replacement_receipt,
                            receipt_transfer_deltas(
                                replacement_receipt,
                                owner=args.from_address,
                                virtual_token=cfg.virtual_token_addr,
                                target_token=token_addr,
                            ),
                        )
                        payload["replacement"]["receipt"] = replacement_receipt_payload
                        if replacement_confirmation.get("receiptOk"):
                            payload.update(
                                {
                                    "event": "receipt_success",
                                    "receiptSkipped": False,
                                    "txHash": replacement_hash,
                                    "reason": "replacement_receipt_observed",
                                    "timingsMs": timings,
                                }
                            )
                            update_ledger_stage(
                                bot,
                                intent_id=intent_id,
                                project_name=project_name,
                                strategy_name=OPEN_SNIPER_STRATEGY,
                                rule_name=OPEN_SNIPER_RULE,
                                mode=executor_mode(args),
                                status="receipt_success",
                                reason="replacement_receipt_observed",
                                simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
                                signed_tx_hash=replacement.signed.tx_hash,
                                broadcast_tx_hash=replacement_hash,
                                receipt=replacement_receipt_payload,
                                trade_sent=True,
                                broadcast_enabled=True,
                            )
                            return payload
            else:
                payload["replacement"] = {
                    "sent": False,
                    "reason": replacement_fanout.get("reason"),
                    "responses": replacement_fanout.get("responses"),
                }
        except Exception as exc:
            payload["replacement"] = {"sent": False, "reason": str(exc)}

    if args.no_wait_receipt:
        payload["receiptSkipped"] = not bool((payload.get("postBroadcastCheck") or {}).get("receiptOk"))
        payload["reason"] = "receipt_wait_skipped_after_fast_confirm"
        payload["timingsMs"] = timings
        return payload

    reason = "receipt_timeout" if confirmation is None or not confirmation.get("receipt") else "receipt_failed"
    payload.update({"event": "receipt_failed", "reason": reason, "receiptSkipped": False, "timingsMs": timings})
    fuse = trigger_fuse(
        bot,
        project_name=project_name,
        strategy_name=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
        intent_id=intent_id,
        failure_stage="receipt",
        failure_reason=reason,
        details={"txHash": str(sent_hash), "confirmation": {key: value for key, value in (confirmation or {}).items() if key != "receipt"}},
    )
    payload["activeFuse"] = compact_fuse(fuse)
    update_ledger_stage(
        bot,
        intent_id=intent_id,
        project_name=project_name,
        strategy_name=OPEN_SNIPER_STRATEGY,
        rule_name=OPEN_SNIPER_RULE,
        mode=executor_mode(args),
        status="receipt_failed",
        reason=reason,
        simulation={"green": True, "preSignedNoSimulation": True, "quote": asdict(prepared.quote)},
        signed_tx_hash=prepared.signed.tx_hash,
        broadcast_tx_hash=str(sent_hash),
        failure_stage="receipt",
        failure_reason=reason,
        trade_sent=True,
        broadcast_enabled=True,
    )
    return payload


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_selection = apply_execution_rpc_to_config(cfg)
    validate_args(args, rpc_selection)
    if args.mode in {"sign-ready", "broadcast"}:
        ensure_secret_loaded(Path(args.secret_file))

    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/launch-open-sniper-{str(args.project).strip().upper()}.jsonl"
    )
    stop_event = asyncio.Event()

    def on_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, on_stop)

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        official_context = {"ok": True, "status": "skipped", "buyTaxRate": 0}
        if not args.skip_official_no_tax_check:
            official_context = await official_no_tax_context(bot, project_row)
            if not official_context.get("ok"):
                payload = {
                    "event": "service_blocked",
                    "reason": "official_no_tax_check_failed",
                    "at": utc_iso(),
                    "atCst": cst_iso(),
                    "project": project_name,
                    "strategy": OPEN_SNIPER_STRATEGY,
                    "rule": OPEN_SNIPER_RULE,
                    "mode": executor_mode(args),
                    "readOnly": args.mode != "broadcast",
                    "tradeSent": False,
                    "broadcastEnabled": broadcast_enabled(args),
                    "officialTaxContext": official_context,
                }
                append_jsonl(output_jsonl, payload)
                print(json.dumps(payload, ensure_ascii=False), flush=True)
                return

        buy_tax_rate = official_context.get("buyTaxRate")
        probe_rpc_urls = resolve_rpc_url_pool(PROBE_RPC_URLS_ENV, primary_url=cfg.http_rpc_url)
        broadcast_rpc_urls = resolve_rpc_url_pool(BROADCAST_RPC_URLS_ENV, primary_url=cfg.http_rpc_url)
        service_meta = {
            "event": "service_start",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "managedProjectId": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "strategy": OPEN_SNIPER_STRATEGY,
            "rule": OPEN_SNIPER_RULE,
            "mode": executor_mode(args),
            "readOnly": args.mode != "broadcast",
            "tradeSent": False,
            "broadcastEnabled": broadcast_enabled(args),
            "buyV": str(args.buy_v),
            "maxBuyV": str(args.max_buy_v),
            "maxProjectV": str(args.max_project_v),
            "startAt": int(project_row.get("start_at") or 0),
            "phasePlan": {
                "serviceStartBeforeSec": 1800,
                "prepareBeforeSec": float(args.prepare_before_sec),
                "highProbeBeforeSec": float(args.high_probe_before_sec),
                "ultraProbeBeforeSec": float(args.ultra_probe_before_sec),
                "preparePollSec": float(args.prepare_poll_sec),
                "highProbePollSec": float(args.high_probe_poll_sec),
                "ultraProbePollSec": float(args.ultra_probe_poll_sec),
                "highProbeWorkers": int(args.high_probe_workers),
                "ultraProbeWorkers": int(args.ultra_probe_workers),
                "probeRaceTimeoutSec": float(args.probe_race_timeout_sec),
                "broadcastFanoutTimeoutSec": float(args.broadcast_fanout_timeout_sec),
                "presignRefreshSec": float(args.presign_refresh_sec),
                "requoteRevertSelectors": sorted(normalize_revert_selectors(str(args.requote_revert_selectors))),
                "reprobeAfterRequote": not bool(args.disable_reprobe_after_requote),
                "postTriggerDirectFire": bool(args.post_trigger_direct_fire),
                "directFireMaxAgeSec": float(args.direct_fire_max_age_sec),
            },
            "triggerOffsetSec": float(args.trigger_offset_sec),
            "minPollSec": float(args.min_poll_sec),
            "rpc": redact_rpc_url(cfg.http_rpc_url),
            "probeRpcPool": compact_rpc_pool(probe_rpc_urls),
            "broadcastRpcPool": compact_rpc_pool(broadcast_rpc_urls),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "officialTaxContext": official_context,
            "outputJsonl": str(output_jsonl),
        }
        append_jsonl(output_jsonl, service_meta)
        print(json.dumps(service_meta, ensure_ascii=False), flush=True)

        sample_count = 0
        last_heartbeat = 0.0
        attempt_count = 0
        sent = False
        prepared_open_tx: PreparedOpenTx | None = None
        last_presign_refresh_started = 0.0
        direct_fire_attempted = False
        phase_metrics: dict[str, dict[str, Any]] = {}
        last_phase_name = ""

        async with contextlib.AsyncExitStack() as stack:
            rpc = await stack.enter_async_context(RPCClient(cfg.http_rpc_url, max_retries=1, timeout_sec=8))
            endpoint_clients: dict[str, RPCClient] = {cfg.http_rpc_url: rpc}
            for url in [*probe_rpc_urls, *broadcast_rpc_urls]:
                if url in endpoint_clients:
                    continue
                endpoint_clients[url] = await stack.enter_async_context(RPCClient(url, max_retries=1, timeout_sec=8))
            probe_endpoints = [
                RpcEndpoint(label=rpc_url_label(url, index + 1), url=url, client=endpoint_clients[url])
                for index, url in enumerate(probe_rpc_urls)
            ]
            broadcast_endpoints = [
                RpcEndpoint(label=rpc_url_label(url, index + 1), url=url, client=endpoint_clients[url])
                for index, url in enumerate(broadcast_rpc_urls)
            ]
            while not stop_event.is_set():
                loop_started = time.monotonic()
                project_row = find_project(bot, str(args.project))
                project_name = str(project_row.get("name") or args.project).strip()
                now_float = time.time()
                now_ts = int(now_float)
                start_at = int(project_row.get("start_at") or 0)
                end_at = int(project_row.get("resolved_end_at") or 0)
                sample_count += 1

                if open_sniper_already_sent(bot, project_name=project_name):
                    payload = {
                        "event": "service_stop_after_existing_sent",
                        "reason": "open_sniper_already_sent",
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": project_name,
                        "strategy": OPEN_SNIPER_STRATEGY,
                        "rule": OPEN_SNIPER_RULE,
                        "sampleCount": sample_count,
                        "tradeSent": False,
                        "broadcastEnabled": broadcast_enabled(args),
                    }
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    return

                phase_info = launch_phase(args, now_float=now_float, start_at=start_at)
                phase_name = str(phase_info["phase"])
                phase_changed = phase_name != last_phase_name
                last_phase_name = phase_name
                if (
                    should_refresh_prepared_open_tx(
                        args,
                        prepared=prepared_open_tx,
                        phase_name=phase_name,
                        phase_changed=phase_changed,
                        last_presign_refresh_started=last_presign_refresh_started,
                    )
                    and bool(phase_info["shouldPrepare"])
                    and start_at > 0
                ):
                    last_presign_refresh_started = time.monotonic()
                    try:
                        prepared_open_tx = await build_prepared_open_tx(
                            args=args,
                            cfg=cfg,
                            rpc=rpc,
                            project_row=project_row,
                            buy_tax_rate=buy_tax_rate,
                        )
                        payload = {
                            "event": "presigned_open_tx_ready",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "strategy": OPEN_SNIPER_STRATEGY,
                            "rule": OPEN_SNIPER_RULE,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "phase": phase_name,
                            "phaseInfo": phase_info,
                            "preparedOpenTx": prepared_open_tx.compact(),
                        }
                    except Exception as exc:
                        prepared_open_tx = None
                        payload = {
                            "event": "presigned_open_tx_not_ready",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "strategy": OPEN_SNIPER_STRATEGY,
                            "rule": OPEN_SNIPER_RULE,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "phase": phase_name,
                            "phaseInfo": phase_info,
                            "reason": str(exc),
                        }
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)

                if direct_fire_due(
                    args,
                    phase_info=phase_info,
                    prepared=prepared_open_tx,
                    already_attempted=direct_fire_attempted,
                ):
                    direct_fire_attempted = True
                    attempt_count += 1
                    sample = open_sniper_sample(
                        bot,
                        project_row,
                        now_ts=now_ts,
                        buy_tax_rate=buy_tax_rate,
                        attempt=attempt_count,
                    )
                    payload = await send_prepared_open_tx(
                        args=args,
                        cfg=cfg,
                        bot=bot,
                        rpc=rpc,
                        broadcast_endpoints=broadcast_endpoints,
                        project_row=project_row,
                        project_name=project_name,
                        sample=sample,
                        sample_index=sample_count - 1,
                        prepared=prepared_open_tx,
                    )
                    payload["phase"] = phase_name
                    payload["phaseInfo"] = phase_info
                    payload["triggerMode"] = "post_trigger_direct_fire"
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    sent = bool(payload.get("tradeSent"))
                    if sent or args.mode != "broadcast" or args.once or (args.max_attempts and attempt_count >= int(args.max_attempts)):
                        break

                if bool(phase_info["shouldProbe"]) and prepared_open_tx is not None:
                    probe = await probe_prepared_open_tx_race(
                        endpoints=probe_endpoints,
                        prepared=prepared_open_tx,
                        worker_count=probe_workers_for_phase(args, phase_name),
                        timeout_sec=float(args.probe_race_timeout_sec),
                    )
                    update_phase_metrics(phase_metrics, phase=phase_name, probe=probe)
                    probe_payload = {
                        "event": "open_sniper_probe_ready" if probe.get("ready") else "open_sniper_probe_not_ready",
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": project_name,
                        "strategy": OPEN_SNIPER_STRATEGY,
                        "rule": OPEN_SNIPER_RULE,
                        "mode": executor_mode(args),
                        "readOnly": args.mode != "broadcast",
                        "tradeSent": False,
                        "broadcastEnabled": broadcast_enabled(args),
                        "phase": phase_name,
                        "phaseInfo": phase_info,
                        "probe": {
                            "ready": bool(probe.get("ready")),
                            "ethCallOk": bool(probe.get("ethCallOk")),
                            "probeMs": probe.get("probeMs"),
                            "error": str(probe.get("error") or "")[:240],
                            "provider": probe.get("provider"),
                            "workerIndex": probe.get("workerIndex"),
                            "workerCount": probe.get("workerCount"),
                            "providerCount": probe.get("providerCount"),
                            "results": [
                                {
                                    "ready": bool(item.get("ready")),
                                    "ethCallOk": bool(item.get("ethCallOk")),
                                    "probeMs": item.get("probeMs"),
                                    "provider": item.get("provider"),
                                    "workerIndex": item.get("workerIndex"),
                                    "error": str(item.get("error") or "")[:160],
                                }
                                for item in list(probe.get("results") or [])[:8]
                            ],
                        },
                        "phaseMetrics": phase_metrics,
                    }
                    if args.log_every_probe or probe.get("ready") or last_heartbeat <= 0 or (time.monotonic() - last_heartbeat) >= float(args.heartbeat_log_sec):
                        append_jsonl(output_jsonl, probe_payload)
                        print(json.dumps(probe_payload, ensure_ascii=False), flush=True)
                        last_heartbeat = time.monotonic()
                    if probe_needs_requote(args, probe=probe, phase_info=phase_info):
                        last_presign_refresh_started = time.monotonic()
                        try:
                            prepared_open_tx = await build_prepared_open_tx(
                                args=args,
                                cfg=cfg,
                                rpc=rpc,
                                project_row=project_row,
                                buy_tax_rate=buy_tax_rate,
                            )
                            payload = {
                                "event": "presigned_open_tx_ready_after_requote",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "strategy": OPEN_SNIPER_STRATEGY,
                                "rule": OPEN_SNIPER_RULE,
                                "mode": executor_mode(args),
                                "readOnly": args.mode != "broadcast",
                                "tradeSent": False,
                                "broadcastEnabled": broadcast_enabled(args),
                                "phase": phase_name,
                                "phaseInfo": phase_info,
                                "triggerProbe": probe_payload["probe"],
                                "revertSelector": extract_revert_selector(str(probe.get("error") or "")),
                                "preparedOpenTx": prepared_open_tx.compact(),
                            }
                        except Exception as exc:
                            prepared_open_tx = None
                            payload = {
                                "event": "presigned_open_tx_requote_failed",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "strategy": OPEN_SNIPER_STRATEGY,
                                "rule": OPEN_SNIPER_RULE,
                                "mode": executor_mode(args),
                                "readOnly": args.mode != "broadcast",
                                "tradeSent": False,
                                "broadcastEnabled": broadcast_enabled(args),
                                "phase": phase_name,
                                "phaseInfo": phase_info,
                                "triggerProbe": probe_payload["probe"],
                                "reason": str(exc),
                            }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                        if prepared_open_tx is not None and not bool(args.disable_reprobe_after_requote):
                            probe = await probe_prepared_open_tx_race(
                                endpoints=probe_endpoints,
                                prepared=prepared_open_tx,
                                worker_count=probe_workers_for_phase(args, phase_name),
                                timeout_sec=float(args.probe_race_timeout_sec),
                            )
                            update_phase_metrics(phase_metrics, phase=phase_name, probe=probe)
                            probe_payload = {
                                "event": "open_sniper_probe_ready_after_requote" if probe.get("ready") else "open_sniper_probe_not_ready_after_requote",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "strategy": OPEN_SNIPER_STRATEGY,
                                "rule": OPEN_SNIPER_RULE,
                                "mode": executor_mode(args),
                                "readOnly": args.mode != "broadcast",
                                "tradeSent": False,
                                "broadcastEnabled": broadcast_enabled(args),
                                "phase": phase_name,
                                "phaseInfo": phase_info,
                                "probe": {
                                    "ready": bool(probe.get("ready")),
                                    "ethCallOk": bool(probe.get("ethCallOk")),
                                    "probeMs": probe.get("probeMs"),
                                    "error": str(probe.get("error") or "")[:240],
                                    "provider": probe.get("provider"),
                                    "workerIndex": probe.get("workerIndex"),
                                    "workerCount": probe.get("workerCount"),
                                    "providerCount": probe.get("providerCount"),
                                    "results": [
                                        {
                                            "ready": bool(item.get("ready")),
                                            "ethCallOk": bool(item.get("ethCallOk")),
                                            "probeMs": item.get("probeMs"),
                                            "provider": item.get("provider"),
                                            "workerIndex": item.get("workerIndex"),
                                            "error": str(item.get("error") or "")[:160],
                                        }
                                        for item in list(probe.get("results") or [])[:8]
                                    ],
                                },
                                "phaseMetrics": phase_metrics,
                            }
                            append_jsonl(output_jsonl, probe_payload)
                            print(json.dumps(probe_payload, ensure_ascii=False), flush=True)
                            last_heartbeat = time.monotonic()
                    if probe.get("ready"):
                        attempt_count += 1
                        sample = open_sniper_sample(
                            bot,
                            project_row,
                            now_ts=now_ts,
                            buy_tax_rate=buy_tax_rate,
                            attempt=attempt_count,
                        )
                        payload = await send_prepared_open_tx(
                            args=args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            broadcast_endpoints=broadcast_endpoints,
                            project_row=project_row,
                            project_name=project_name,
                            sample=sample,
                            sample_index=sample_count - 1,
                            prepared=prepared_open_tx,
                        )
                        payload["phase"] = phase_name
                        payload["phaseInfo"] = phase_info
                        payload["triggerProbe"] = probe_payload["probe"]
                        payload["phaseMetrics"] = phase_metrics
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                        sent = bool(payload.get("tradeSent"))
                        if sent or args.mode != "broadcast" or args.once or (args.max_attempts and attempt_count >= int(args.max_attempts)):
                            break
                elif bool(phase_info["shouldProbe"]) and prepared_open_tx is None and bool(args.disable_presigned_open_tx):
                    attempt_count += 1
                    sample = open_sniper_sample(
                        bot,
                        project_row,
                        now_ts=now_ts,
                        buy_tax_rate=buy_tax_rate,
                        attempt=attempt_count,
                    )
                    if (
                        prepared_open_tx is not None
                        and args.mode in {"sign-ready", "broadcast"}
                        and time.monotonic() < prepared_open_tx.expires_at
                    ):
                        payload = await send_prepared_open_tx(
                            args=args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            broadcast_endpoints=broadcast_endpoints,
                            project_row=project_row,
                            project_name=project_name,
                            sample=sample,
                            sample_index=sample_count - 1,
                            prepared=prepared_open_tx,
                        )
                    else:
                        payload = await execute_open_sniper_attempt(
                            args=args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            project_row=project_row,
                            project_name=project_name,
                            sample=sample,
                            sample_index=sample_count - 1,
                            output_jsonl=output_jsonl,
                        )
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    sent = bool(payload.get("tradeSent"))
                    if sent or args.once or (args.max_attempts and attempt_count >= int(args.max_attempts)):
                        break
                else:
                    if last_heartbeat <= 0 or (time.monotonic() - last_heartbeat) >= float(args.heartbeat_log_sec):
                        payload = {
                            "event": "waiting_for_probe_window" if phase_name in {"standby", "prepare"} else "waiting_for_prepared_tx",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "strategy": OPEN_SNIPER_STRATEGY,
                            "rule": OPEN_SNIPER_RULE,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "phase": phase_name,
                            "phaseInfo": phase_info,
                            "startAt": start_at,
                            "phaseMetrics": phase_metrics,
                            "preparedOpenTx": prepared_open_tx.compact() if prepared_open_tx is not None else None,
                        }
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                        last_heartbeat = time.monotonic()
                    if args.once:
                        break
                sleep_for = sleep_interval(args, now_float=now_float, start_at=start_at, sent=False)

                if (
                    args.exit_after_end_sec > 0
                    and end_at > 0
                    and now_ts >= end_at + int(args.exit_after_end_sec)
                ):
                    break
                elapsed = time.monotonic() - loop_started
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, sleep_for - elapsed))

        summary = {
            "event": "service_stop",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "strategy": OPEN_SNIPER_STRATEGY,
            "rule": OPEN_SNIPER_RULE,
            "mode": executor_mode(args),
            "sampleCount": sample_count,
            "attemptCount": attempt_count,
            "tradeSent": sent,
            "broadcastEnabled": broadcast_enabled(args),
            "phaseMetrics": phase_metrics,
            "outputJsonl": str(output_jsonl),
        }
        append_jsonl(output_jsonl, summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
