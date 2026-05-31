#!/usr/bin/env python3
"""Realtime launch prewarm executor.

This is the production-path scaffold after the dry-run emitter:
- it watches one whitelisted managed project;
- it evaluates the frozen dynamic strategy;
- on BuyIntent it binds a direct Virtuals buy order and runs simulation;
- in sign-ready mode it signs the prewarmed tx but never prints or persists raw tx;
- in broadcast mode it sends only when both CLI and env allow gates are enabled,
  execution RPC is isolated, active fuse is clear, and risk caps pass.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import os
import signal
import sys
import time
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any

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
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    BURNER_PRIVATE_KEY_ENV,
    DynamicExecutionConfig,
    DynamicAfter1StrategyEvaluator,
    LocalSigner,
    StrategyState,
    TxSimulator,
    VIRTUALS_BUY_SPENDER,
    VirtualsOrderBinder,
    resolve_rule,
)
from live_strategy_dry_run import (  # noqa: E402
    LiveClock,
    append_jsonl,
    compact_sample,
    cst_iso,
    derive_trigger_types,
    find_project,
    fingerprint,
    make_ledger_record,
    poll_interval_for_status,
    utc_iso,
)
from native_launch_replay import build_sample  # noqa: E402
from virtuals_bot import (  # noqa: E402
    DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
    DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
    RPCClient,
    VirtualsBot,
    load_config,
    redact_rpc_url,
)


DEFAULT_FOLLOW_TRADE_WALLET = "0xe0b51bbf7af8bff0a8cd422e4b5f17aa0824969d"
DEFAULT_FOLLOW_TRADE_DIVISOR = Decimal("4")
DEFAULT_FOLLOW_TRADE_STRATEGY = "follow_wallet_v1"
DEFAULT_FOLLOW_TRADE_RULE = "source_spent_v_quarter_floor"
MIN_FOLLOW_TRADE_BUY_V = Decimal("1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime prewarm executor for one Virtuals project.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--mode", choices=["simulate", "sign-ready", "broadcast"], default="simulate")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--min-poll-sec", type=float, default=0.25)
    parser.add_argument("--live-poll-sec", type=float, default=0.25)
    parser.add_argument("--prelaunch-poll-sec", type=float, default=2.0)
    parser.add_argument("--scheduled-poll-sec", type=float, default=20.0)
    parser.add_argument("--heartbeat-log-sec", type=float, default=30.0)
    parser.add_argument("--exit-after-end-sec", type=int, default=0)
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--ignore-active-fuse", action="store_true")
    parser.add_argument("--enable-broadcast", action="store_true", help="Required with VWR_ENABLE_AUTO_BUY_BROADCAST=1.")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--max-buy-v", type=Decimal, default=Decimal("25"))
    parser.add_argument("--max-project-v", type=Decimal, default=Decimal("25"))
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    parser.add_argument("--enable-signed-candidate-cache", action="store_true")
    parser.add_argument("--signed-candidate-ttl-sec", type=float, default=2.0)
    parser.add_argument("--signed-candidate-refresh-min-sec", type=float, default=0.5)
    parser.add_argument("--signed-candidate-max-count", type=int, default=4)
    parser.add_argument(
        "--project-cap-scope",
        choices=["strategy", "project"],
        default="strategy",
        help="Scope used by --max-project-v. 'strategy' preserves legacy behavior; 'project' counts all sent buys for this project.",
    )
    parser.add_argument(
        "--fdv-limit-orders-only",
        action="store_true",
        help="Evaluate independent FDV limit orders, but never run the standard whale-board buy strategy.",
    )
    parser.add_argument(
        "--require-open-sniper-before-fdv-limit",
        action="store_true",
        help="For no-tax launches, keep FDV limit orders read-only until the open-sniper first buy has been sent.",
    )
    parser.add_argument(
        "--follow-wallet",
        default=os.environ.get("VWR_FOLLOW_WALLET", DEFAULT_FOLLOW_TRADE_WALLET),
        help="Wallet to copy during the live window. Default is the configured operator follow wallet.",
    )
    parser.add_argument(
        "--follow-divisor",
        type=Decimal,
        default=Decimal(str(os.environ.get("VWR_FOLLOW_DIVISOR") or DEFAULT_FOLLOW_TRADE_DIVISOR)),
        help="Buy floor(source spent V / divisor) when the follow wallet buys.",
    )
    parser.add_argument(
        "--disable-follow-trade",
        action="store_true",
        help="Disable the default live-window follow-wallet strategy for this executor.",
    )
    return parser.parse_args()


def executor_mode(args: argparse.Namespace) -> str:
    return f"prewarm_{args.mode.replace('-', '_')}"


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def broadcast_enabled(args: argparse.Namespace) -> bool:
    return args.mode == "broadcast" and bool(args.enable_broadcast) and env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST")


def ensure_secret_loaded(path: Path) -> None:
    if str(os.environ.get(BURNER_PRIVATE_KEY_ENV) or "").strip():
        return
    load_secret_file(path)


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    raw = str(value).strip()
    if not raw:
        return default
    return Decimal(raw)


def runtime_dynamic_config(row: dict[str, Any] | None) -> DynamicExecutionConfig:
    if not row:
        return DynamicExecutionConfig()
    return DynamicExecutionConfig(
        name=str(row.get("strategy") or DynamicExecutionConfig().name),
        base_buy_v=decimal_value(row.get("base_buy_v"), DynamicExecutionConfig().base_buy_v),
        dip_buy_v=decimal_value(row.get("dip_buy_v"), DynamicExecutionConfig().dip_buy_v),
        dip_from_own_cost_pct=decimal_value(
            row.get("dip_from_own_cost_pct"),
            DynamicExecutionConfig().dip_from_own_cost_pct,
        ),
        flat_pause_pct=decimal_value(row.get("flat_pause_pct"), DynamicExecutionConfig().flat_pause_pct),
        fdv_limit_enabled=False,
        fdv_limit_wan_usd=None,
        pause_after_buy_count=DynamicExecutionConfig().pause_after_buy_count,
        one_buy_per_tax_rate=DynamicExecutionConfig().one_buy_per_tax_rate,
    )


def follow_ratio_pct_from_divisor(divisor: Any) -> Decimal:
    value = decimal_value(divisor)
    if value <= 0:
        return Decimal("0")
    return Decimal("100") / value


def follow_divisor_from_ratio_pct(ratio_pct: Any, default_divisor: Decimal = DEFAULT_FOLLOW_TRADE_DIVISOR) -> Decimal:
    value = decimal_value(ratio_pct)
    if value <= 0:
        return default_divisor
    return Decimal("100") / value


def runtime_effective_args(args: argparse.Namespace, row: dict[str, Any] | None) -> argparse.Namespace:
    if not row:
        return args
    out = copy.copy(args)
    out.max_buy_v = decimal_value(row.get("max_buy_v"), Decimal(str(args.max_buy_v or "0")))
    out.max_project_v = decimal_value(row.get("max_project_v"), Decimal(str(args.max_project_v or "0")))
    follow_enabled = bool(int(row.get("follow_enabled") if row.get("follow_enabled") is not None else 1))
    out.disable_follow_trade = bool(getattr(args, "disable_follow_trade", False)) or not follow_enabled
    follow_wallet = str(row.get("follow_wallet") or getattr(args, "follow_wallet", DEFAULT_FOLLOW_TRADE_WALLET)).strip()
    if follow_wallet:
        out.follow_wallet = follow_wallet
    out.follow_divisor = follow_divisor_from_ratio_pct(
        row.get("follow_ratio_pct"),
        Decimal(str(getattr(args, "follow_divisor", DEFAULT_FOLLOW_TRADE_DIVISOR))),
    )
    return out


def compact_runtime_config(row: dict[str, Any] | None, args: argparse.Namespace) -> dict[str, Any]:
    follow_enabled = not bool(getattr(args, "disable_follow_trade", False))
    follow_wallet = str(getattr(args, "follow_wallet", DEFAULT_FOLLOW_TRADE_WALLET) or "")
    follow_ratio_pct = follow_ratio_pct_from_divisor(getattr(args, "follow_divisor", DEFAULT_FOLLOW_TRADE_DIVISOR))
    if not row:
        return {
            "hasOverride": False,
            "version": 0,
            "enabled": True,
            "mode": args.mode,
            "strategy": DynamicExecutionConfig().name,
            "baseBuyV": str(DynamicExecutionConfig().base_buy_v),
            "dipBuyV": str(DynamicExecutionConfig().dip_buy_v),
            "fdvLimitEnabled": False,
            "fdvLimitWanUsd": "",
            "followEnabled": follow_enabled,
            "followWallet": follow_wallet,
            "followRatioPct": format(follow_ratio_pct, "f"),
            "maxBuyV": str(args.max_buy_v),
            "maxProjectV": str(args.max_project_v),
        }
    return {
        "hasOverride": True,
        "version": int(row.get("version") or 0),
        "enabled": bool(int(row.get("enabled") or 0)),
        "mode": str(row.get("mode") or "simulate"),
        "strategy": str(row.get("strategy") or ""),
        "ruleName": str(row.get("rule_name") or ""),
        "baseBuyV": str(row.get("base_buy_v") or ""),
        "dipBuyV": str(row.get("dip_buy_v") or ""),
        "dipFromOwnCostPct": str(row.get("dip_from_own_cost_pct") or ""),
        "flatPausePct": str(row.get("flat_pause_pct") or ""),
        "fdvLimitEnabled": False,
        "fdvLimitWanUsd": "",
        "followEnabled": follow_enabled,
        "followWallet": follow_wallet,
        "followRatioPct": format(follow_ratio_pct, "f"),
        "maxBuyV": str(row.get("max_buy_v") or ""),
        "maxProjectV": str(row.get("max_project_v") or ""),
        "updatedAt": int(row.get("updated_at") or 0),
    }


def normalized_tax_key(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = Decimal(raw)
        if parsed == parsed.to_integral_value():
            return str(int(parsed))
        return format(parsed.normalize(), "f")
    except Exception:
        return raw


def signed_candidate_key(*, buy_size_v: Any, tax_rate: Any) -> str:
    buy_size = decimal_value(buy_size_v)
    if buy_size <= 0:
        return ""
    tax_key = normalized_tax_key(tax_rate)
    if not tax_key:
        return ""
    return f"{format(buy_size.normalize(), 'f')}|{tax_key}"


@dataclass
class SignedBuyCandidate:
    key: str
    buy_size_v: str
    tax_rate: str
    built_at: float
    expires_at: float
    signed: Any
    quote: Any
    simulation: dict[str, Any]
    timings_ms: dict[str, float]

    def compact(self) -> dict[str, Any]:
        age_ms = max(0.0, (time.monotonic() - self.built_at) * 1000)
        ttl_ms = max(0.0, (self.expires_at - time.monotonic()) * 1000)
        return {
            "key": self.key,
            "buySizeV": self.buy_size_v,
            "taxRate": self.tax_rate,
            "ageMs": round(age_ms, 1),
            "ttlRemainingMs": round(ttl_ms, 1),
            "signedTxHash": self.signed.tx_hash,
            "signedSummary": {
                "from": self.signed.from_addr,
                "to": self.signed.to,
                "chainId": self.signed.chain_id,
                "nonce": self.signed.nonce,
                "gas": self.signed.gas,
            },
        }


def take_signed_candidate(
    cache: dict[str, SignedBuyCandidate],
    *,
    buy_size_v: Any,
    tax_rate: Any,
) -> SignedBuyCandidate | None:
    key = signed_candidate_key(buy_size_v=buy_size_v, tax_rate=tax_rate)
    if not key:
        return None
    candidate = cache.pop(key, None)
    if not candidate:
        return None
    if time.monotonic() >= candidate.expires_at:
        return None
    # All candidates in one refresh batch usually share the same pending nonce.
    # Once one raw tx is consumed, discard alternatives to avoid nonce reuse.
    cache.clear()
    return candidate


def prune_signed_candidate_cache(cache: dict[str, SignedBuyCandidate]) -> None:
    now = time.monotonic()
    for key in list(cache.keys()):
        if now >= cache[key].expires_at:
            cache.pop(key, None)


def signed_candidate_cache_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enabled": bool(args.enable_signed_candidate_cache),
        "ttlSec": float(args.signed_candidate_ttl_sec),
        "refreshMinSec": float(args.signed_candidate_refresh_min_sec),
        "maxCount": int(args.signed_candidate_max_count),
    }


def compact_fuse(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "project": row.get("project"),
        "strategy": row.get("strategy"),
        "ruleName": row.get("rule_name"),
        "scope": row.get("scope"),
        "isActive": bool(row.get("is_active")),
        "failureStage": row.get("failure_stage"),
        "failureReason": row.get("failure_reason"),
        "sourceIntentId": row.get("source_intent_id"),
        "updatedAt": row.get("updated_at"),
    }


def open_sniper_first_buy_sent(bot: VirtualsBot, *, project_name: str) -> bool:
    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
    return any(
        str(row.get("strategy") or "") == "open_sniper_no_tax"
        and str(row.get("rule_name") or "") == "open_second_first_buy"
        and int(row.get("trade_sent") or 0) == 1
        and str(row.get("status") or "") not in {"receipt_failed", "broadcast_failed", "simulation_failed"}
        for row in rows
    )


def failed_simulation_checks(simulation: dict[str, Any]) -> list[str]:
    checks = simulation.get("checks") or {}
    return [name for name, check in checks.items() if not bool((check or {}).get("ok"))]


def simulation_failure_reason(simulation: dict[str, Any]) -> str:
    failed = set(failed_simulation_checks(simulation))
    if "balance" in failed and "allowance" in failed:
        return "wallet_balance_and_allowance_not_ready"
    if "balance" in failed:
        return "wallet_balance_not_ready"
    if "allowance" in failed:
        return "wallet_allowance_not_ready"
    return "simulation_not_green"


def soft_wallet_readiness_reason(reason: str) -> bool:
    return reason in {
        "wallet_balance_and_allowance_not_ready",
        "wallet_balance_not_ready",
        "wallet_allowance_not_ready",
    }


def update_ledger_stage(
    bot: VirtualsBot,
    *,
    intent_id: str,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    mode: str,
    status: str,
    reason: str,
    action: str = "would_buy",
    simulation: dict[str, Any] | None = None,
    signed_tx_hash: str | None = None,
    broadcast_tx_hash: str | None = None,
    receipt: dict[str, Any] | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    trade_sent: bool = False,
    broadcast_enabled: bool = False,
) -> None:
    bot.storage.upsert_launch_execution_record(
        {
            "intent_id": intent_id,
            "project": project_name,
            "strategy": strategy_name,
            "rule_name": rule_name,
            "mode": mode,
            "status": status,
            "action": action,
            "decision_reason": reason,
            "simulation": simulation,
            "signed_tx_hash": signed_tx_hash,
            "broadcast_tx_hash": broadcast_tx_hash,
            "receipt": receipt,
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
            "trade_sent": trade_sent,
            "broadcast_enabled": broadcast_enabled,
        }
    )


def trigger_fuse(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    intent_id: str,
    failure_stage: str,
    failure_reason: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    return bot.storage.trigger_launch_execution_fuse(
        project=project_name,
        strategy=strategy_name,
        rule_name=rule_name,
        failure_stage=failure_stage,
        failure_reason=failure_reason,
        source_intent_id=intent_id,
        details=details,
    )


def sent_records(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
    return [
        row
        for row in rows
        if str(row.get("strategy") or "") == strategy_name
        and str(row.get("rule_name") or "") == rule_name
        and int(row.get("trade_sent") or 0) == 1
    ]


def sent_project_v(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> Decimal:
    total = Decimal("0")
    for row in sent_records(bot, project_name=project_name, strategy_name=strategy_name, rule_name=rule_name):
        total += decimal_value(row.get("buy_size_v"))
    return total


def sent_project_v_all_strategies(bot: VirtualsBot, *, project_name: str) -> Decimal:
    total = Decimal("0")
    for row in bot.storage.list_launch_execution_records(project_name, limit=500):
        if int(row.get("trade_sent") or 0) != 1:
            continue
        if str(row.get("action") or "") not in {"would_buy", "buy"}:
            continue
        if str(row.get("status") or "") in {"receipt_failed", "prewarm_failed", "simulation_failed"}:
            continue
        total += decimal_value(row.get("buy_size_v"))
    return total


def normalize_address(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw.startswith("0x") else f"0x{raw}"


def floor_v(value: Decimal) -> Decimal:
    return Decimal(value).to_integral_value(rounding=ROUND_FLOOR)


def compact_follow_trade_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enabled": not bool(getattr(args, "disable_follow_trade", False)),
        "wallet": normalize_address(getattr(args, "follow_wallet", "")),
        "divisor": str(getattr(args, "follow_divisor", DEFAULT_FOLLOW_TRADE_DIVISOR)),
        "minBuyV": str(MIN_FOLLOW_TRADE_BUY_V),
        "strategy": DEFAULT_FOLLOW_TRADE_STRATEGY,
        "ruleName": DEFAULT_FOLLOW_TRADE_RULE,
    }


def follow_trade_source_seen(
    bot: VirtualsBot,
    *,
    project_name: str,
    source_tx_hash: str,
) -> bool:
    target = str(source_tx_hash or "").strip().lower()
    if not target:
        return True
    for row in bot.storage.list_launch_execution_records(project_name, limit=500):
        if str(row.get("strategy") or "") != DEFAULT_FOLLOW_TRADE_STRATEGY:
            continue
        raw = str(row.get("intent_json") or "").strip()
        if not raw:
            continue
        with contextlib.suppress(Exception):
            intent = json.loads(raw)
            if str(intent.get("sourceTxHash") or "").strip().lower() == target:
                return True
    return False


def follow_trade_events(
    bot: VirtualsBot,
    *,
    project_name: str,
    source_wallet: str,
    start_at: int,
    end_at: int,
    limit: int = 25,
) -> list[dict[str, Any]]:
    wallet = normalize_address(source_wallet)
    if not wallet:
        return []
    clauses = ["project = ?", "lower(buyer) = lower(?)"]
    params: list[Any] = [project_name, wallet]
    if int(start_at or 0) > 0:
        clauses.append("block_timestamp >= ?")
        params.append(int(start_at))
    if int(end_at or 0) > 0:
        clauses.append("block_timestamp <= ?")
        params.append(int(end_at))
    params.append(max(1, min(int(limit), 100)))
    rows = bot.storage.conn.execute(
        f"""
        SELECT *
        FROM events
        WHERE {' AND '.join(clauses)}
        ORDER BY block_number ASC, id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def follow_trade_source_spent(row: dict[str, Any]) -> tuple[Decimal, str]:
    for field in ("spent_v_actual", "spent_v_est"):
        value = decimal_value(row.get(field))
        if value > 0:
            return value, field
    return Decimal("0"), ""


def follow_trade_buy_size(
    *,
    source_spent_v: Decimal,
    divisor: Decimal,
    sent_project_v: Decimal,
    max_project_v: Decimal | None,
) -> tuple[Decimal, bool, Decimal | None]:
    if divisor <= 0:
        return Decimal("0"), False, None
    requested = floor_v(source_spent_v / divisor)
    if requested < MIN_FOLLOW_TRADE_BUY_V:
        return Decimal("0"), False, None
    if max_project_v is None or max_project_v <= 0:
        return requested, False, None
    remaining = floor_v(max_project_v - sent_project_v)
    if remaining < MIN_FOLLOW_TRADE_BUY_V:
        return Decimal("0"), False, remaining
    if requested > remaining:
        return remaining, True, remaining
    return requested, False, remaining


def follow_trade_intent(
    *,
    row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    source_spent_v: Decimal,
    source_spent_field: str,
    buy_size_v: Decimal,
    divisor: Decimal,
    clamped: bool,
    remaining_project_v: Decimal | None,
) -> dict[str, Any]:
    return {
        "project": project_name,
        "index": sample_index,
        "timestamp": int(sample.get("simTimestamp") or row.get("block_timestamp") or 0),
        "tax_rate": str(sample.get("buyTaxRate") or ""),
        "buy_size_v": format(buy_size_v, "f"),
        "entry_tax_fdv_wan_usd": str(sample.get("estimatedFdvWanUsdWithTax") or ""),
        "entry_spot_fdv_wan_usd": str(sample.get("spotFdvWanUsd") or ""),
        "own_weighted_cost_before_wan_usd": None,
        "own_weighted_cost_after_wan_usd": str(sample.get("estimatedFdvWanUsdWithTax") or ""),
        "board_spent_v": str(sample.get("boardSpentV") or "0"),
        "board_cost_wan_usd": str(sample.get("boardCostWanUsd") or ""),
        "cost_rows": int(sample.get("costRows") or 0),
        "whale_rows": int(sample.get("whaleRows") or 0),
        "trigger_types": ["follow_wallet"],
        "reason": "follow_wallet_source_spent_quarter_floor",
        "sourceWallet": normalize_address(row.get("buyer")),
        "sourceTxHash": str(row.get("tx_hash") or "").strip().lower(),
        "sourceBlockNumber": int(row.get("block_number") or 0),
        "sourceBlockTimestamp": int(row.get("block_timestamp") or 0),
        "sourceSpentV": str(source_spent_v),
        "sourceSpentField": source_spent_field,
        "followDivisor": str(divisor),
        "amountClampedByProjectCap": bool(clamped),
        "remainingProjectVBefore": str(remaining_project_v) if remaining_project_v is not None else None,
    }


def follow_trade_skip_payload(
    *,
    bot: VirtualsBot,
    project_row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    row: dict[str, Any],
    reason: str,
    source_spent_v: Decimal,
    divisor: Decimal,
    effective_args: argparse.Namespace,
    rpc_selection: Any,
) -> dict[str, Any]:
    intent = follow_trade_intent(
        row=row,
        project_name=project_name,
        sample=sample,
        sample_index=sample_index,
        source_spent_v=source_spent_v,
        source_spent_field="",
        buy_size_v=Decimal("0"),
        divisor=divisor,
        clamped=False,
        remaining_project_v=None,
    )
    record = make_ledger_record(
        project_row=project_row,
        project_name=project_name,
        rule_name=DEFAULT_FOLLOW_TRADE_RULE,
        strategy_name=DEFAULT_FOLLOW_TRADE_STRATEGY,
        action="would_buy",
        reason=reason,
        sample_index=sample_index,
        sample=sample,
        intent=intent,
        pause=None,
    )
    record.update({"status": "skipped", "failure_stage": "strategy", "failure_reason": reason})
    bot.storage.upsert_launch_execution_record(record)
    return {
        "event": "follow_trade_skipped",
        "reason": reason,
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "rule": DEFAULT_FOLLOW_TRADE_RULE,
        "strategy": DEFAULT_FOLLOW_TRADE_STRATEGY,
        "mode": executor_mode(effective_args),
        "sampleIndex": sample_index,
        "readOnly": True,
        "tradeSent": False,
        "broadcastEnabled": False,
        "runtimeStrategyConfig": compact_runtime_config(None, effective_args),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "followTrade": {
            "sourceWallet": normalize_address(row.get("buyer")),
            "sourceTxHash": str(row.get("tx_hash") or "").strip().lower(),
            "sourceSpentV": str(source_spent_v),
            "divisor": str(divisor),
            "buySizeV": "0",
        },
        "sample": compact_sample(sample),
    }


async def attempt_follow_trades(
    *,
    args: argparse.Namespace,
    effective_args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
    rpc_selection: Any,
) -> tuple[bool, list[dict[str, Any]]]:
    if bool(getattr(args, "disable_follow_trade", False)):
        return False, []
    if str(sample.get("projectStatus") or "").lower() != "live":
        return False, []
    divisor = Decimal(str(getattr(args, "follow_divisor", DEFAULT_FOLLOW_TRADE_DIVISOR)))
    if divisor <= 0:
        return False, []
    events = follow_trade_events(
        bot,
        project_name=project_name,
        source_wallet=str(getattr(args, "follow_wallet", DEFAULT_FOLLOW_TRADE_WALLET)),
        start_at=int(project_row.get("start_at") or 0),
        end_at=int(project_row.get("resolved_end_at") or 0),
    )
    payloads: list[dict[str, Any]] = []
    attempted_trade = False
    next_nonce_override: int | None = None
    for row in events:
        source_tx_hash = str(row.get("tx_hash") or "").strip().lower()
        if not source_tx_hash or follow_trade_source_seen(
            bot,
            project_name=project_name,
            source_tx_hash=source_tx_hash,
        ):
            continue
        source_spent_v, source_spent_field = follow_trade_source_spent(row)
        sent_v = sent_project_v_all_strategies(bot, project_name=project_name)
        max_project_v = Decimal(str(effective_args.max_project_v)) if effective_args.max_project_v is not None else None
        buy_size_v, clamped, remaining_project_v = follow_trade_buy_size(
            source_spent_v=source_spent_v,
            divisor=divisor,
            sent_project_v=sent_v,
            max_project_v=max_project_v,
        )
        if buy_size_v < MIN_FOLLOW_TRADE_BUY_V:
            reason = "follow_buy_size_below_1v" if source_spent_v > 0 else "follow_source_spent_missing"
            if remaining_project_v is not None and remaining_project_v < MIN_FOLLOW_TRADE_BUY_V:
                reason = "project_cap_exhausted"
            payloads.append(
                follow_trade_skip_payload(
                    bot=bot,
                    project_row=project_row,
                    project_name=project_name,
                    sample=sample,
                    sample_index=sample_index,
                    row=row,
                    reason=reason,
                    source_spent_v=source_spent_v,
                    divisor=divisor,
                    effective_args=effective_args,
                    rpc_selection=rpc_selection,
                )
            )
            continue
        attempted_trade = True
        follow_args = copy.copy(effective_args)
        follow_args.max_buy_v = buy_size_v
        follow_args.project_cap_scope = "project"
        intent = follow_trade_intent(
            row=row,
            project_name=project_name,
            sample=sample,
            sample_index=sample_index,
            source_spent_v=source_spent_v,
            source_spent_field=source_spent_field,
            buy_size_v=buy_size_v,
            divisor=divisor,
            clamped=clamped,
            remaining_project_v=remaining_project_v,
        )
        payload = await prewarm_intent(
            args=follow_args,
            cfg=cfg,
            bot=bot,
            rpc=rpc,
            project_row=project_row,
            project_name=project_name,
            rule_name=DEFAULT_FOLLOW_TRADE_RULE,
            strategy_name=DEFAULT_FOLLOW_TRADE_STRATEGY,
            sample=sample,
            sample_index=sample_index,
            intent=intent,
            nonce_override=next_nonce_override,
            skip_tax_rate_guard=True,
            force_no_wait_receipt=True,
            signed_candidate=None,
        )
        payload["followTrade"] = {
            "sourceWallet": normalize_address(row.get("buyer")),
            "sourceTxHash": source_tx_hash,
            "sourceSpentV": str(source_spent_v),
            "sourceSpentField": source_spent_field,
            "divisor": str(divisor),
            "buySizeV": str(buy_size_v),
            "clampedByProjectCap": bool(clamped),
            "remainingProjectVBefore": str(remaining_project_v) if remaining_project_v is not None else None,
        }
        payloads.append(payload)
        if payload.get("tradeSent"):
            with contextlib.suppress(Exception):
                next_nonce_override = int((payload.get("signedSummary") or {}).get("nonce")) + 1
    return attempted_trade, payloads


def tax_rate_already_sent(
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
    tax_rate: Any,
) -> bool:
    target = normalized_tax_key(tax_rate)
    if not target:
        return False
    for row in sent_records(bot, project_name=project_name, strategy_name=strategy_name, rule_name=rule_name):
        if normalized_tax_key(row.get("tax_rate")) == target:
            return True
    return False


def rebuild_strategy_state_from_sent_rows(rows: list[dict[str, Any]]) -> StrategyState:
    state = StrategyState()
    last_buy: dict[str, Any] | None = None
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.get("created_at") or 0),
            int(row.get("updated_at") or 0),
            int(row.get("id") or 0),
        ),
    )
    for row in ordered:
        action = str(row.get("action") or "").strip()
        if action not in {"would_buy", "buy"}:
            continue
        tax_key = normalized_tax_key(row.get("tax_rate"))
        buy_size = decimal_value(row.get("buy_size_v"))
        entry = decimal_value(row.get("entry_tax_fdv_wan_usd"))
        if tax_key:
            state.bought_tax_rates.add(tax_key)
        if buy_size > 0 and entry > 0:
            state.total_spent_v += buy_size
            state.weighted_cost_numerator += buy_size * entry
            if tax_key:
                last_buy = {"taxRate": tax_key, "entryTaxFdvWanUsd": str(entry)}
    state.pending_pause_buy = last_buy
    return state


def restore_strategy_state_from_ledger(
    evaluator: DynamicAfter1StrategyEvaluator,
    bot: VirtualsBot,
    *,
    project_name: str,
    strategy_name: str,
    rule_name: str,
) -> StrategyState:
    evaluator.state = rebuild_strategy_state_from_sent_rows(
        sent_records(
            bot,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
        )
    )
    return evaluator.state


def compact_strategy_state(state: StrategyState) -> dict[str, Any]:
    return {
        "boughtTaxRates": sorted(state.bought_tax_rates),
        "pendingPauseBuy": state.pending_pause_buy,
        "totalSpentV": str(state.total_spent_v),
        "ownWeightedCostWanUsd": str(state.own_weighted_cost) if state.own_weighted_cost is not None else None,
    }


def sample_tax_fdv_wan(sample: dict[str, Any]) -> Decimal | None:
    value = decimal_value(sample.get("estimatedFdvWanUsdWithTax"))
    return value if value > 0 else None


def compact_fdv_limit_order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "enabled": bool(int(row.get("enabled") or 0)),
        "status": str(row.get("status") or ""),
        "triggerFdvWanUsd": str(row.get("trigger_fdv_wan_usd") or ""),
        "buyV": str(row.get("buy_v") or ""),
        "attemptCount": int(row.get("attempt_count") or 0),
        "txHash": str(row.get("broadcast_tx_hash") or ""),
        "ledgerIntentId": str(row.get("ledger_intent_id") or ""),
    }


def eligible_fdv_limit_orders(
    rows: list[dict[str, Any]],
    *,
    tax_fdv_wan_usd: Decimal | None,
    project_status: str,
) -> list[dict[str, Any]]:
    if str(project_status or "").lower() != "live":
        return []
    if tax_fdv_wan_usd is None:
        return []
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if not bool(int(row.get("enabled") or 0)):
            continue
        if str(row.get("status") or "") != "pending":
            continue
        trigger = decimal_value(row.get("trigger_fdv_wan_usd"))
        buy_v = decimal_value(row.get("buy_v"))
        if trigger <= 0 or buy_v <= 0:
            continue
        if tax_fdv_wan_usd <= trigger:
            eligible.append(row)
    return sorted(
        eligible,
        key=lambda row: (
            -decimal_value(row.get("trigger_fdv_wan_usd")),
            int(row.get("sort_order") or 0),
            int(row.get("id") or 0),
        ),
    )


def fdv_limit_order_intent(
    *,
    row: dict[str, Any],
    project_name: str,
    sample: dict[str, Any],
    sample_index: int,
) -> dict[str, Any]:
    entry = sample_tax_fdv_wan(sample) or Decimal("0")
    buy_v = decimal_value(row.get("buy_v"))
    return {
        "project": project_name,
        "index": sample_index,
        "timestamp": int(sample.get("simTimestamp") or 0),
        "tax_rate": str(sample.get("buyTaxRate") or ""),
        "buy_size_v": str(buy_v),
        "entry_tax_fdv_wan_usd": str(entry),
        "entry_spot_fdv_wan_usd": str(sample.get("liveFdvUsd") or ""),
        "own_weighted_cost_before_wan_usd": None,
        "own_weighted_cost_after_wan_usd": str(entry),
        "board_spent_v": str(sample.get("boardSpentV") or ""),
        "board_cost_wan_usd": str(sample.get("boardCostWanUsd") or ""),
        "cost_rows": int(sample.get("costRows") or 0),
        "whale_rows": int(sample.get("whaleRows") or 0),
        "trigger_types": ["fdv_limit_order"],
        "reason": "tax_fdv_limit_order_triggered",
        "fdvLimitOrderId": int(row.get("id") or 0),
        "fdvLimitTriggerWanUsd": str(row.get("trigger_fdv_wan_usd") or ""),
        "speedPriority": True,
    }


def receipt_summary(receipt: dict[str, Any] | None, receipt_deltas: dict[str, Any] | None) -> dict[str, Any] | None:
    if not receipt and not receipt_deltas:
        return None
    return {
        "status": receipt.get("status") if receipt else None,
        "blockNumber": receipt.get("blockNumber") if receipt else None,
        "gasUsed": receipt.get("gasUsed") if receipt else None,
        "transferDeltas": receipt_deltas,
    }


def candidate_buy_sizes(
    *,
    effective_args: argparse.Namespace,
    runtime_config: DynamicExecutionConfig,
    pending_limit_orders: list[dict[str, Any]],
) -> list[Decimal]:
    sizes: list[Decimal] = []
    for value in (runtime_config.base_buy_v, runtime_config.dip_buy_v):
        parsed = decimal_value(value)
        if parsed > 0:
            sizes.append(parsed)
    for row in pending_limit_orders:
        if not bool(int(row.get("enabled") or 0)):
            continue
        if str(row.get("status") or "") != "pending":
            continue
        parsed = decimal_value(row.get("buy_v"))
        if parsed > 0:
            sizes.append(parsed)

    unique: list[Decimal] = []
    seen: set[str] = set()
    max_buy = Decimal(effective_args.max_buy_v) if effective_args.max_buy_v is not None else Decimal("0")
    for size in sizes:
        if max_buy > 0 and size > max_buy:
            continue
        key = format(size.normalize(), "f")
        if key in seen:
            continue
        seen.add(key)
        unique.append(size)
    return unique


async def build_signed_buy_candidate(
    *,
    args: argparse.Namespace,
    cfg: Any,
    rpc: RPCClient,
    project_row: dict[str, Any],
    sample: dict[str, Any],
    buy_size_v: Decimal,
) -> SignedBuyCandidate:
    tax_rate = sample.get("buyTaxRate")
    key = signed_candidate_key(buy_size_v=buy_size_v, tax_rate=tax_rate)
    if not key:
        raise ValueError("missing buy size or tax rate for signed candidate")
    token_addr = str(project_row.get("token_addr") or "").strip()
    pool_addr = str(project_row.get("internal_pool_addr") or "").strip()
    if not token_addr or not pool_addr:
        raise ValueError("missing token or internal pool")

    timings: dict[str, float] = {}
    start = time.perf_counter()
    bound = await VirtualsOrderBinder(
        rpc,
        virtual_token_addr=cfg.virtual_token_addr,
        slippage_bps=int(args.slippage_bps),
        deadline_offset_sec=int(args.deadline_offset_sec),
    ).bind_buy(
        chain_id=cfg.chain_id,
        from_addr=args.from_address,
        token_addr=token_addr,
        pool_addr=pool_addr,
        amount_in_v=buy_size_v,
        buy_tax_rate_pct=tax_rate,
        now_ts=int(time.time()),
    )
    timings["bindBuyMs"] = elapsed_ms(start)

    start = time.perf_counter()
    simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
    timings["simulateMs"] = elapsed_ms(start)
    simulation_compact = compact_simulation(simulation)
    if not simulation["green"]:
        raise ValueError(simulation_failure_reason(simulation))

    start = time.perf_counter()
    fees = await suggest_fees(
        rpc,
        max_fee_gwei=args.max_fee_gwei,
        priority_gwei=args.max_priority_fee_gwei,
    )
    timings["feeSuggestMs"] = elapsed_ms(start)
    gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
    gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
    nonce_to_use = int(simulation["checks"]["nonce"]["pendingNonce"])
    tx = replace(
        bound.tx,
        nonce=nonce_to_use,
        gas=gas,
        max_fee_per_gas=str(fees["maxFeePerGas"]),
        max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
    )
    start = time.perf_counter()
    signed = LocalSigner().sign(tx)
    timings["signMs"] = elapsed_ms(start)

    built_at = time.monotonic()
    return SignedBuyCandidate(
        key=key,
        buy_size_v=format(buy_size_v.normalize(), "f"),
        tax_rate=normalized_tax_key(tax_rate),
        built_at=built_at,
        expires_at=built_at + max(0.1, float(args.signed_candidate_ttl_sec)),
        signed=signed,
        quote=bound.quote,
        simulation=simulation_compact,
        timings_ms=timings,
    )


async def refresh_signed_candidates(
    *,
    args: argparse.Namespace,
    cfg: Any,
    rpc: RPCClient,
    project_row: dict[str, Any],
    sample: dict[str, Any],
    buy_sizes: list[Decimal],
) -> dict[str, Any]:
    if not bool(args.enable_signed_candidate_cache):
        return {"candidates": [], "errors": [], "skipped": "disabled"}
    if args.mode not in {"sign-ready", "broadcast"}:
        return {"candidates": [], "errors": [], "skipped": "mode_not_signing"}
    if str(sample.get("projectStatus") or "").lower() != "live":
        return {"candidates": [], "errors": [], "skipped": "project_not_live"}
    if not buy_sizes:
        return {"candidates": [], "errors": [], "skipped": "no_candidate_size"}

    candidates: list[SignedBuyCandidate] = []
    errors: list[dict[str, Any]] = []
    for buy_size in buy_sizes[: max(1, int(args.signed_candidate_max_count))]:
        try:
            candidate = await build_signed_buy_candidate(
                args=args,
                cfg=cfg,
                rpc=rpc,
                project_row=project_row,
                sample=sample,
                buy_size_v=buy_size,
            )
            candidates.append(candidate)
        except Exception as exc:
            errors.append({"buySizeV": format(buy_size.normalize(), "f"), "reason": str(exc)})
    return {"candidates": candidates, "errors": errors, "skipped": ""}


async def prewarm_intent(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    rule_name: str,
    strategy_name: str,
    sample: dict[str, Any],
    sample_index: int,
    intent: dict[str, Any],
    nonce_override: int | None = None,
    skip_tax_rate_guard: bool = False,
    force_no_wait_receipt: bool = False,
    signed_candidate: SignedBuyCandidate | None = None,
) -> dict[str, Any]:
    mode = executor_mode(args)
    ledger_record = make_ledger_record(
        project_row=project_row,
        project_name=project_name,
        rule_name=rule_name,
        strategy_name=strategy_name,
        action="would_buy",
        reason="signal",
        sample_index=sample_index,
        sample=sample,
        intent=intent,
        pause=None,
    )
    ledger_record["mode"] = mode
    bot.storage.upsert_launch_execution_record(ledger_record)
    intent_id = ledger_record["intent_id"]

    payload: dict[str, Any] = {
        "event": "prewarm_intent",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": project_name,
        "rule": rule_name,
        "strategy": strategy_name,
        "mode": mode,
        "ledgerIntentId": intent_id,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "intent": intent,
        "sample": compact_sample(sample),
    }

    active_fuse = bot.storage.get_active_launch_execution_fuse(
        project=project_name,
        strategy=strategy_name,
        rule_name=rule_name,
    )
    if active_fuse and not args.ignore_active_fuse:
        payload["event"] = "blocked_by_active_fuse"
        payload["activeFuse"] = compact_fuse(active_fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="blocked_by_active_fuse",
            reason="active_fuse",
            failure_stage="fuse",
            failure_reason="active_fuse",
        )
        return payload

    if args.mode == "broadcast":
        if not broadcast_enabled(args):
            payload["event"] = "blocked_by_broadcast_gate"
            payload["reason"] = "missing_cli_or_env_broadcast_gate"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_broadcast_gate",
                reason="missing_cli_or_env_broadcast_gate",
                failure_stage="broadcast_gate",
                failure_reason="broadcast_not_enabled",
            )
            return payload

        buy_size = decimal_value(intent.get("buy_size_v"))
        if args.max_buy_v is not None and Decimal(args.max_buy_v) > 0 and buy_size > Decimal(args.max_buy_v):
            payload["event"] = "blocked_by_single_tx_cap"
            payload["reason"] = "buy_size_exceeds_max_buy_v"
            payload["maxBuyV"] = str(args.max_buy_v)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_single_tx_cap",
                reason="buy_size_exceeds_max_buy_v",
                failure_stage="risk_limit",
                failure_reason="buy_size_exceeds_max_buy_v",
            )
            return payload

        if not skip_tax_rate_guard and tax_rate_already_sent(
            bot,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            tax_rate=sample.get("buyTaxRate"),
        ):
            payload["event"] = "blocked_by_tax_already_sent"
            payload["reason"] = "same_tax_rate_already_broadcast"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_tax_already_sent",
                reason="same_tax_rate_already_broadcast",
                failure_stage="risk_limit",
                failure_reason="same_tax_rate_already_broadcast",
            )
            return payload

        if str(getattr(args, "project_cap_scope", "strategy")) == "project":
            existing_project_v = sent_project_v_all_strategies(bot, project_name=project_name)
        else:
            existing_project_v = sent_project_v(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
            )
        projected_project_v = existing_project_v + buy_size
        if (
            args.max_project_v is not None
            and Decimal(args.max_project_v) > 0
            and projected_project_v > Decimal(args.max_project_v)
        ):
            payload["event"] = "blocked_by_project_cap"
            payload["reason"] = "project_sent_v_exceeds_max_project_v"
            payload["sentProjectV"] = str(existing_project_v)
            payload["projectedProjectV"] = str(projected_project_v)
            payload["maxProjectV"] = str(args.max_project_v)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="blocked_by_project_cap",
                reason="project_sent_v_exceeds_max_project_v",
                failure_stage="risk_limit",
                failure_reason="project_sent_v_exceeds_max_project_v",
            )
            return payload

    token_addr = str(project_row.get("token_addr") or "").strip()
    pool_addr = str(project_row.get("internal_pool_addr") or "").strip()
    if not token_addr or not pool_addr:
        reason = "missing_token_or_pool"
        payload["event"] = "prewarm_failed"
        payload["reason"] = reason
        should_fuse = args.mode != "simulate"
        payload["fuseTriggered"] = should_fuse
        if should_fuse:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="order_binding",
                failure_reason=reason,
                details={"tokenAddr": token_addr, "poolAddr": pool_addr},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="order_binding_failed",
            reason=reason,
            failure_stage="order_binding" if should_fuse else None,
            failure_reason=reason if should_fuse else None,
        )
        return payload

    timings: dict[str, float] = {}
    try:
        if signed_candidate is not None and args.mode in {"sign-ready", "broadcast"}:
            timings.update(signed_candidate.timings_ms)
            simulation_compact = signed_candidate.simulation
            signed = signed_candidate.signed
            payload.update(
                {
                    "event": "signed_ready",
                    "signed": True,
                    "signedTxHash": signed.tx_hash,
                    "signedCandidate": signed_candidate.compact(),
                    "quote": asdict(signed_candidate.quote),
                    "simulation": simulation_compact,
                    "signedSummary": {
                        "from": signed.from_addr,
                        "to": signed.to,
                        "chainId": signed.chain_id,
                        "nonce": signed.nonce,
                        "gas": signed.gas,
                    },
                    "timingsMs": timings,
                    "reason": "signed_candidate_cache_hit_no_raw_tx_persisted",
                }
            )
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="signed_ready",
                reason="signed_candidate_cache_hit_no_raw_tx_persisted",
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
                    "reason": "send_presigned_raw_transaction_ack",
                }
            )
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="broadcast_sent",
                reason="send_presigned_raw_transaction_ack",
                simulation=simulation_compact,
                signed_tx_hash=signed.tx_hash,
                broadcast_tx_hash=str(sent_hash),
                trade_sent=True,
                broadcast_enabled=True,
            )

            skip_receipt_wait = bool(args.no_wait_receipt or force_no_wait_receipt)
            if skip_receipt_wait:
                payload["receiptSkipped"] = True
                payload["reason"] = "receipt_wait_skipped"
                update_ledger_stage(
                    bot,
                    intent_id=intent_id,
                    project_name=project_name,
                    strategy_name=strategy_name,
                    rule_name=rule_name,
                    mode=mode,
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
                    strategy_name=strategy_name,
                    rule_name=rule_name,
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
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
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

        start = time.perf_counter()
        bound = await VirtualsOrderBinder(
            rpc,
            virtual_token_addr=cfg.virtual_token_addr,
            slippage_bps=int(args.slippage_bps),
            deadline_offset_sec=int(args.deadline_offset_sec),
        ).bind_buy(
            chain_id=cfg.chain_id,
            from_addr=args.from_address,
            token_addr=token_addr,
            pool_addr=pool_addr,
            amount_in_v=Decimal(str(intent["buy_size_v"])),
            buy_tax_rate_pct=sample.get("buyTaxRate"),
            now_ts=int(time.time()),
        )
        timings["bindBuyMs"] = elapsed_ms(start)

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
            failed_checks = failed_simulation_checks(simulation)
            payload["reason"] = reason
            payload["failedChecks"] = failed_checks
            soft_readiness = args.mode == "broadcast" and soft_wallet_readiness_reason(reason)
            should_fuse = args.mode != "simulate" and not soft_readiness
            payload["fuseTriggered"] = should_fuse
            if should_fuse:
                fuse = trigger_fuse(
                    bot,
                    project_name=project_name,
                    strategy_name=strategy_name,
                    rule_name=rule_name,
                    intent_id=intent_id,
                    failure_stage="simulation",
                    failure_reason=reason,
                    details={"simulation": simulation_compact, "failedChecks": failed_checks},
                )
                payload["activeFuse"] = compact_fuse(fuse)
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
                status="readiness_not_ready" if args.mode == "simulate" or soft_readiness else "simulation_failed",
                reason=reason,
                simulation=simulation_compact,
                failure_stage=None if args.mode == "simulate" or soft_readiness else "simulation",
                failure_reason=None if args.mode == "simulate" or soft_readiness else reason,
                broadcast_enabled=broadcast_enabled(args),
            )
            return payload

        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
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
        nonce_to_use = int(nonce_override) if nonce_override is not None else int(simulation["checks"]["nonce"]["pendingNonce"])
        tx = replace(
            bound.tx,
            nonce=nonce_to_use,
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
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
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
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="broadcast_sent",
            reason="send_raw_transaction_ack",
            simulation=simulation_compact,
            signed_tx_hash=signed.tx_hash,
            broadcast_tx_hash=str(sent_hash),
            trade_sent=True,
            broadcast_enabled=True,
        )

        skip_receipt_wait = bool(args.no_wait_receipt or force_no_wait_receipt)
        if skip_receipt_wait:
            payload["receiptSkipped"] = True
            payload["reason"] = "receipt_wait_skipped"
            update_ledger_stage(
                bot,
                intent_id=intent_id,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                mode=mode,
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
                strategy_name=strategy_name,
                rule_name=rule_name,
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
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
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
        payload.update({"event": "prewarm_failed", "reason": reason, "timingsMs": timings})
        should_fuse = args.mode != "simulate"
        payload["fuseTriggered"] = should_fuse
        if should_fuse:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="prewarm",
                failure_reason=reason,
                details={"event": payload.get("event"), "timingsMs": timings},
            )
            payload["activeFuse"] = compact_fuse(fuse)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="prewarm_failed",
            reason=reason,
            failure_stage="prewarm" if should_fuse else None,
            failure_reason=reason if should_fuse else None,
        )
        return payload


async def reconcile_fdv_limit_order_receipts(
    *,
    args: argparse.Namespace,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_fdv_limit_orders(
        project_id=int(project_row.get("id") or 0),
        statuses=["broadcast_sent"],
        limit=50,
    )
    token_addr = str(project_row.get("token_addr") or "").strip()
    reconciled: list[dict[str, Any]] = []
    for row in rows:
        tx_hash = str(row.get("broadcast_tx_hash") or "").strip()
        intent_id = str(row.get("ledger_intent_id") or "").strip()
        if not tx_hash or not intent_id:
            continue
        try:
            receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:
            reconciled.append(
                {
                    "order": compact_fdv_limit_order(row),
                    "status": "receipt_lookup_failed",
                    "error": str(exc),
                }
            )
            continue
        if not receipt:
            continue

        receipt_status = str(receipt.get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=args.from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        reason = "receipt_observed" if receipt_ok else "receipt_failed"
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
            rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
            mode=executor_mode(args),
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason=reason,
            receipt=receipt_payload,
            broadcast_tx_hash=tx_hash,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else "receipt_failed",
            trade_sent=True,
            broadcast_enabled=True,
        )
        bot.storage.mark_launch_fdv_limit_order_receipt(
            int(row.get("id") or 0),
            ok=receipt_ok,
            error="" if receipt_ok else "receipt_failed",
        )
        if not receipt_ok:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason="receipt_failed",
                details={"txHash": tx_hash, "receipt": receipt_payload},
            )
            active_fuse = compact_fuse(fuse)
        else:
            active_fuse = None
        reconciled.append(
            {
                "order": compact_fdv_limit_order(row),
                "status": "receipt_success" if receipt_ok else "receipt_failed",
                "receipt": receipt_payload,
                "activeFuse": active_fuse,
            }
        )
    return reconciled


async def reconcile_standard_buy_receipts(
    *,
    cfg: Any,
    bot: VirtualsBot,
    rpc: RPCClient,
    project_row: dict[str, Any],
    project_name: str,
    from_address: str,
) -> list[dict[str, Any]]:
    rows = bot.storage.list_launch_execution_records(project_name, limit=500)
    token_addr = str(project_row.get("token_addr") or "").strip()
    reconciled: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("strategy") or "") == DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY:
            continue
        if str(row.get("action") or "") != "would_buy":
            continue
        if int(row.get("trade_sent") or 0) != 1:
            continue
        if str(row.get("status") or "") != "broadcast_sent_no_receipt_wait":
            continue
        if str(row.get("receipt_json") or "").strip():
            continue
        tx_hash = str(row.get("broadcast_tx_hash") or "").strip()
        intent_id = str(row.get("intent_id") or "").strip()
        strategy_name = str(row.get("strategy") or "").strip()
        rule_name = str(row.get("rule_name") or "").strip()
        mode = str(row.get("mode") or "prewarm_broadcast").strip()
        if not tx_hash or not intent_id or not strategy_name or not rule_name:
            continue
        try:
            receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
        except Exception as exc:
            reconciled.append(
                {
                    "intentId": intent_id,
                    "txHash": tx_hash,
                    "status": "receipt_lookup_failed",
                    "error": str(exc),
                }
            )
            continue
        if not receipt:
            continue

        receipt_status = str(receipt.get("status") or "")
        receipt_ok = receipt_status in {"0x1", "1"}
        receipt_deltas = receipt_transfer_deltas(
            receipt,
            owner=from_address,
            virtual_token=cfg.virtual_token_addr,
            target_token=token_addr,
        )
        receipt_payload = receipt_summary(receipt, receipt_deltas)
        update_ledger_stage(
            bot,
            intent_id=intent_id,
            project_name=project_name,
            strategy_name=strategy_name,
            rule_name=rule_name,
            mode=mode,
            status="receipt_success" if receipt_ok else "receipt_failed",
            reason="receipt_observed" if receipt_ok else "receipt_failed",
            simulation=json.loads(row.get("simulation_json") or "null"),
            signed_tx_hash=str(row.get("signed_tx_hash") or "") or None,
            broadcast_tx_hash=tx_hash,
            receipt=receipt_payload,
            failure_stage=None if receipt_ok else "receipt",
            failure_reason=None if receipt_ok else "receipt_failed",
            trade_sent=True,
            broadcast_enabled=True,
        )
        active_fuse = None
        if not receipt_ok:
            fuse = trigger_fuse(
                bot,
                project_name=project_name,
                strategy_name=strategy_name,
                rule_name=rule_name,
                intent_id=intent_id,
                failure_stage="receipt",
                failure_reason="receipt_failed",
                details={"txHash": tx_hash, "receipt": receipt_payload},
            )
            active_fuse = compact_fuse(fuse)
        reconciled.append(
            {
                "intentId": intent_id,
                "strategy": strategy_name,
                "rule": rule_name,
                "txHash": tx_hash,
                "status": "receipt_success" if receipt_ok else "receipt_failed",
                "receipt": receipt_payload,
                "activeFuse": active_fuse,
            }
        )
    return reconciled


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    if args.mode == "sign-ready":
        ensure_secret_loaded(Path(args.secret_file))

    rpc_selection = apply_execution_rpc_to_config(cfg)

    if args.mode == "broadcast":
        if args.max_buy_v is not None and Decimal(args.max_buy_v) < 0:
            raise SystemExit("--max-buy-v cannot be negative")
        if args.max_project_v is not None and Decimal(args.max_project_v) < 0:
            raise SystemExit("--max-project-v cannot be negative")
        if not args.enable_broadcast:
            raise SystemExit("broadcast mode requires --enable-broadcast")
        if not env_flag_enabled("VWR_ENABLE_AUTO_BUY_BROADCAST"):
            raise SystemExit("broadcast mode requires VWR_ENABLE_AUTO_BUY_BROADCAST=1")
        require_isolated_execution_rpc(
            rpc_selection,
            action="broadcast mode",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )
        ensure_secret_loaded(Path(args.secret_file))

    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/launch-prewarm-executor-{str(args.project).strip().upper()}.jsonl"
    )
    stop_event = asyncio.Event()

    def on_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, on_stop)

    rule = resolve_rule(str(args.rule))
    clock = LiveClock()
    previous_sample: dict[str, Any] | None = None
    previous_fingerprint: tuple[Any, ...] | None = None
    last_logged_heartbeat = 0.0
    sample_count = 0
    counts = {"would_buy": 0, "prewarm": 0, "fdv_limit_order": 0, "pause": 0, "skip": 0}
    signed_candidate_cache: dict[str, SignedBuyCandidate] = {}
    signed_candidate_refresh_task: asyncio.Task[dict[str, Any]] | None = None
    last_signed_candidate_refresh_started = 0.0

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        runtime_config_row = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
        runtime_config_version = int(runtime_config_row.get("version") or 0) if runtime_config_row else 0
        evaluator = DynamicAfter1StrategyEvaluator(
            project=project_name,
            rule=rule,
            config=runtime_dynamic_config(runtime_config_row),
        )
        effective_args = runtime_effective_args(args, runtime_config_row)
        restored_state = restore_strategy_state_from_ledger(
            evaluator,
            bot,
            project_name=project_name,
            strategy_name=evaluator.config.name,
            rule_name=rule.name,
        )

        service_meta = {
            "event": "service_start",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "managedProjectId": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "rule": rule.name,
            "strategy": evaluator.config.name,
            "mode": executor_mode(args),
            "readOnly": args.mode != "broadcast",
            "tradeSent": False,
            "broadcastEnabled": broadcast_enabled(args),
            "rpc": redact_rpc_url(cfg.http_rpc_url),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "outputJsonl": str(output_jsonl),
            "maxBuyV": str(effective_args.max_buy_v),
            "maxProjectV": str(effective_args.max_project_v),
            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
            "restoredStrategyState": compact_strategy_state(restored_state),
            "signedCandidateCache": signed_candidate_cache_config(args),
        }
        append_jsonl(output_jsonl, service_meta)
        print(json.dumps(service_meta, ensure_ascii=False), flush=True)

        async with RPCClient(cfg.http_rpc_url, max_retries=3, timeout_sec=20) as rpc:
            while not stop_event.is_set():
                loop_started = time.monotonic()
                now_ts = int(time.time())
                project_row = find_project(bot, str(args.project))
                sample_count += 1
                try:
                    sample = await build_sample(bot, project_row, clock)
                    sample["triggerTypes"] = derive_trigger_types(previous_sample, sample)
                    current_fingerprint = fingerprint(sample)
                    if signed_candidate_refresh_task is not None and signed_candidate_refresh_task.done():
                        refresh_payload: dict[str, Any] | None = None
                        try:
                            refresh_result = signed_candidate_refresh_task.result()
                            candidates = refresh_result.get("candidates") or []
                            errors = refresh_result.get("errors") or []
                            for candidate in candidates:
                                signed_candidate_cache[candidate.key] = candidate
                            if candidates or errors:
                                refresh_payload = {
                                    "event": "signed_candidate_cache_refreshed",
                                    "at": utc_iso(),
                                    "atCst": cst_iso(),
                                    "project": project_name,
                                    "rule": rule.name,
                                    "strategy": evaluator.config.name,
                                    "mode": executor_mode(args),
                                    "readOnly": args.mode != "broadcast",
                                    "tradeSent": False,
                                    "broadcastEnabled": broadcast_enabled(args),
                                    "candidateCount": len(candidates),
                                    "candidates": [candidate.compact() for candidate in candidates],
                                    "errors": errors[:3],
                                }
                        except Exception as exc:
                            refresh_payload = {
                                "event": "signed_candidate_cache_refresh_failed",
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "rule": rule.name,
                                "strategy": evaluator.config.name,
                                "mode": executor_mode(args),
                                "readOnly": args.mode != "broadcast",
                                "tradeSent": False,
                                "broadcastEnabled": broadcast_enabled(args),
                                "reason": str(exc),
                            }
                        finally:
                            signed_candidate_refresh_task = None
                        if refresh_payload:
                            append_jsonl(output_jsonl, refresh_payload)
                            print(json.dumps(refresh_payload, ensure_ascii=False), flush=True)
                    prune_signed_candidate_cache(signed_candidate_cache)
                    reconciled_limit_orders = await reconcile_fdv_limit_order_receipts(
                        args=effective_args if "effective_args" in locals() else args,
                        cfg=cfg,
                        bot=bot,
                        rpc=rpc,
                        project_row=project_row,
                        project_name=project_name,
                    )
                    if reconciled_limit_orders:
                        receipt_payload = {
                            "event": "fdv_limit_order_receipts",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                            "strategy": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "orders": reconciled_limit_orders,
                        }
                        append_jsonl(output_jsonl, receipt_payload)
                        print(json.dumps(receipt_payload, ensure_ascii=False), flush=True)
                    reconciled_standard_buys = await reconcile_standard_buy_receipts(
                        cfg=cfg,
                        bot=bot,
                        rpc=rpc,
                        project_row=project_row,
                        project_name=project_name,
                        from_address=args.from_address,
                    )
                    if reconciled_standard_buys:
                        standard_receipt_payload = {
                            "event": "standard_buy_receipts",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "receipts": reconciled_standard_buys,
                        }
                        append_jsonl(output_jsonl, standard_receipt_payload)
                        print(json.dumps(standard_receipt_payload, ensure_ascii=False), flush=True)
                    latest_runtime_config = bot.storage.get_launch_strategy_runtime_config_by_project(project_name)
                    latest_runtime_version = int(latest_runtime_config.get("version") or 0) if latest_runtime_config else 0
                    if latest_runtime_version != runtime_config_version:
                        runtime_config_version = latest_runtime_version
                        runtime_config_row = latest_runtime_config
                        evaluator.config = runtime_dynamic_config(runtime_config_row)
                        effective_args = runtime_effective_args(args, runtime_config_row)
                        reload_payload = {
                            "event": "strategy_config_reloaded",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                        }
                        append_jsonl(output_jsonl, reload_payload)
                        print(json.dumps(reload_payload, ensure_ascii=False), flush=True)
                    else:
                        runtime_config_row = latest_runtime_config
                        effective_args = runtime_effective_args(args, runtime_config_row)

                    runtime_block_reason = ""
                    if runtime_config_row and not bool(int(runtime_config_row.get("enabled") or 0)):
                        runtime_block_reason = "runtime_config_disabled"
                    elif (
                        runtime_config_row
                        and args.mode == "broadcast"
                        and str(runtime_config_row.get("mode") or "simulate") != "broadcast"
                    ):
                        runtime_block_reason = "runtime_config_mode_not_broadcast"

                    open_limit_orders: list[dict[str, Any]] = []
                    should_log = False
                    standard_buy_attempted = False
                    follow_trade_attempted = False
                    if runtime_block_reason:
                        counts["skip"] = counts.get("skip", 0) + 1
                        payload = {
                            "event": "runtime_config_blocked",
                            "reason": runtime_block_reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": True,
                            "tradeSent": False,
                            "broadcastEnabled": False,
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        should_log = (
                            current_fingerprint != previous_fingerprint
                            or (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec)
                        )
                    elif bool(args.fdv_limit_orders_only):
                        counts["skip"] = counts.get("skip", 0) + 1
                        payload = {
                            "event": "standard_buy_skipped_fdv_limit_orders_only",
                            "reason": "fdv_limit_orders_only",
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        should_log = (
                            current_fingerprint != previous_fingerprint
                            or (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec)
                        )
                    else:
                        state_before_decision = copy.deepcopy(evaluator.state) if args.mode == "broadcast" else None
                        decision = evaluator.evaluate(sample, index=sample_count - 1)
                        counts[decision.action] = counts.get(decision.action, 0) + 1

                        payload = {
                            "event": decision.action,
                            "reason": decision.reason,
                            "at": utc_iso(),
                            "atCst": cst_iso(),
                            "project": project_name,
                            "rule": rule.name,
                            "strategy": evaluator.config.name,
                            "mode": executor_mode(args),
                            "sampleIndex": sample_count - 1,
                            "readOnly": args.mode != "broadcast",
                            "tradeSent": False,
                            "broadcastEnabled": broadcast_enabled(args),
                            "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                            "executionRpcSource": rpc_selection.source,
                            "sample": compact_sample(sample),
                        }
                        if decision.intent is not None:
                            standard_buy_attempted = True
                            counts["prewarm"] = counts.get("prewarm", 0) + 1
                            payload = await prewarm_intent(
                                args=effective_args,
                                cfg=cfg,
                                bot=bot,
                                rpc=rpc,
                                project_row=project_row,
                                project_name=project_name,
                                rule_name=rule.name,
                                strategy_name=evaluator.config.name,
                                sample=sample,
                                sample_index=sample_count - 1,
                                intent=asdict(decision.intent),
                                signed_candidate=take_signed_candidate(
                                    signed_candidate_cache,
                                    buy_size_v=decision.intent.buy_size_v,
                                    tax_rate=sample.get("buyTaxRate"),
                                ),
                            )
                            payload["runtimeStrategyConfig"] = compact_runtime_config(runtime_config_row, effective_args)
                            if args.mode == "broadcast" and not bool(payload.get("tradeSent")) and state_before_decision is not None:
                                evaluator.state = state_before_decision
                            should_log = True
                        elif decision.pause is not None:
                            payload["pause"] = decision.pause
                            should_log = True
                        elif current_fingerprint != previous_fingerprint:
                            payload["event"] = "state_change"
                            should_log = True
                        elif (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec):
                            payload["event"] = "heartbeat"
                            should_log = True

                    if not runtime_block_reason and not standard_buy_attempted and not bool(args.fdv_limit_orders_only):
                        follow_trade_attempted, follow_payloads = await attempt_follow_trades(
                            args=args,
                            effective_args=effective_args,
                            cfg=cfg,
                            bot=bot,
                            rpc=rpc,
                            project_row=project_row,
                            project_name=project_name,
                            sample=sample,
                            sample_index=sample_count - 1,
                            rpc_selection=rpc_selection,
                        )
                        for follow_payload in follow_payloads:
                            if follow_payload.get("event") != "follow_trade_skipped":
                                counts["follow_trade"] = counts.get("follow_trade", 0) + 1
                            append_jsonl(output_jsonl, follow_payload)
                            print(json.dumps(follow_payload, ensure_ascii=False), flush=True)

                    if not runtime_block_reason and not standard_buy_attempted and not follow_trade_attempted:
                        fdv_limit_gate_reason = ""
                        if (
                            bool(args.require_open_sniper_before_fdv_limit)
                            and not open_sniper_first_buy_sent(bot, project_name=project_name)
                        ):
                            fdv_limit_gate_reason = "open_sniper_first_buy_not_sent"
                        if fdv_limit_gate_reason:
                            counts["skip"] = counts.get("skip", 0) + 1
                            fdv_gate_payload = {
                                "event": "fdv_limit_order_blocked_by_open_sniper_gate",
                                "reason": fdv_limit_gate_reason,
                                "at": utc_iso(),
                                "atCst": cst_iso(),
                                "project": project_name,
                                "rule": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                                "strategy": DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                                "mode": executor_mode(args),
                                "sampleIndex": sample_count - 1,
                                "readOnly": True,
                                "tradeSent": False,
                                "broadcastEnabled": False,
                                "runtimeStrategyConfig": compact_runtime_config(runtime_config_row, effective_args),
                                "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                                "executionRpcSource": rpc_selection.source,
                                "openLimitOrderCount": len(open_limit_orders),
                                "sample": compact_sample(sample),
                            }
                            if (
                                current_fingerprint != previous_fingerprint
                                or (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec)
                            ):
                                append_jsonl(output_jsonl, fdv_gate_payload)
                                print(json.dumps(fdv_gate_payload, ensure_ascii=False), flush=True)
                        else:
                            open_limit_orders = bot.storage.list_launch_fdv_limit_orders(
                                project_id=int(project_row.get("id") or 0),
                                statuses=["pending"],
                                limit=100,
                            )
                            limit_orders = eligible_fdv_limit_orders(
                                open_limit_orders,
                                tax_fdv_wan_usd=sample_tax_fdv_wan(sample),
                                project_status=str(sample.get("projectStatus") or ""),
                            )
                            next_nonce_override: int | None = None
                            for limit_order in limit_orders:
                                claimed = bot.storage.mark_launch_fdv_limit_order_triggering(int(limit_order.get("id") or 0))
                                if not claimed or str(claimed.get("status") or "") != "triggering":
                                    continue
                                counts["fdv_limit_order"] = counts.get("fdv_limit_order", 0) + 1
                                fdv_args = copy.copy(effective_args)
                                fdv_args.project_cap_scope = "project"
                                order_buy_v = decimal_value(claimed.get("buy_v"))
                                if fdv_args.max_buy_v is None or Decimal(fdv_args.max_buy_v) < order_buy_v:
                                    fdv_args.max_buy_v = order_buy_v
                                limit_payload = await prewarm_intent(
                                    args=fdv_args,
                                    cfg=cfg,
                                    bot=bot,
                                    rpc=rpc,
                                    project_row=project_row,
                                    project_name=project_name,
                                    rule_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_RULE,
                                    strategy_name=DEFAULT_LAUNCH_FDV_LIMIT_ORDER_STRATEGY,
                                    sample=sample,
                                    sample_index=sample_count - 1,
                                    intent=fdv_limit_order_intent(
                                        row=claimed,
                                        project_name=project_name,
                                        sample=sample,
                                        sample_index=sample_count - 1,
                                    ),
                                    nonce_override=next_nonce_override,
                                    skip_tax_rate_guard=True,
                                    force_no_wait_receipt=True,
                                    signed_candidate=(
                                        None
                                        if next_nonce_override is not None
                                        else take_signed_candidate(
                                            signed_candidate_cache,
                                            buy_size_v=claimed.get("buy_v"),
                                            tax_rate=sample.get("buyTaxRate"),
                                        )
                                    ),
                                )
                                limit_payload["fdvLimitOrder"] = compact_fdv_limit_order(claimed)
                                if limit_payload.get("tradeSent"):
                                    bot.storage.mark_launch_fdv_limit_order_broadcast_sent(
                                        int(claimed.get("id") or 0),
                                        tx_hash=str(limit_payload.get("txHash") or ""),
                                        ledger_intent_id=str(limit_payload.get("ledgerIntentId") or ""),
                                    )
                                    with contextlib.suppress(Exception):
                                        next_nonce_override = int((limit_payload.get("signedSummary") or {}).get("nonce")) + 1
                                else:
                                    reason = str(limit_payload.get("reason") or limit_payload.get("event") or "")
                                    if args.mode != "broadcast" or reason in {
                                        "simulate_mode_no_sign",
                                        "signed_no_raw_tx_persisted",
                                        "wallet_balance_and_allowance_not_ready",
                                        "wallet_balance_not_ready",
                                        "wallet_allowance_not_ready",
                                        "missing_cli_or_env_broadcast_gate",
                                        "active_fuse",
                                    }:
                                        bot.storage.mark_launch_fdv_limit_order_retryable(
                                            int(claimed.get("id") or 0),
                                            error=reason,
                                        )
                                    else:
                                        bot.storage.mark_launch_fdv_limit_order_failed(
                                            int(claimed.get("id") or 0),
                                            error=reason,
                                        )
                                append_jsonl(output_jsonl, limit_payload)
                                print(json.dumps(limit_payload, ensure_ascii=False), flush=True)

                    if should_log:
                        append_jsonl(output_jsonl, payload)
                        print(json.dumps(payload, ensure_ascii=False), flush=True)
                        if payload["event"] == "heartbeat":
                            last_logged_heartbeat = time.monotonic()

                    if (
                        bool(args.enable_signed_candidate_cache)
                        and not runtime_block_reason
                        and args.mode in {"sign-ready", "broadcast"}
                        and str(sample.get("projectStatus") or "").lower() == "live"
                        and signed_candidate_refresh_task is None
                        and (time.monotonic() - last_signed_candidate_refresh_started)
                        >= max(0.1, float(args.signed_candidate_refresh_min_sec))
                    ):
                        sizes = candidate_buy_sizes(
                            effective_args=effective_args,
                            runtime_config=evaluator.config,
                            pending_limit_orders=open_limit_orders,
                        )
                        if sizes:
                            signed_candidate_refresh_task = asyncio.create_task(
                                refresh_signed_candidates(
                                    args=effective_args,
                                    cfg=cfg,
                                    rpc=rpc,
                                    project_row=project_row,
                                    sample=sample,
                                    buy_sizes=sizes,
                                )
                            )
                            last_signed_candidate_refresh_started = time.monotonic()

                    previous_sample = dict(sample)
                    previous_fingerprint = current_fingerprint

                    projected_status = str(sample.get("projectStatus") or "")
                    end_at = int(project_row.get("resolved_end_at") or 0)
                    if args.once:
                        break
                    if args.max_samples and sample_count >= int(args.max_samples):
                        break
                    if (
                        args.exit_after_end_sec > 0
                        and projected_status == "ended"
                        and end_at > 0
                        and now_ts >= end_at + int(args.exit_after_end_sec)
                    ):
                        break
                    sleep_for = poll_interval_for_status(args, projected_status)
                except Exception as exc:
                    payload = {
                        "event": "error",
                        "at": utc_iso(),
                        "atCst": cst_iso(),
                        "project": str(args.project),
                        "rule": rule.name,
                        "mode": executor_mode(args),
                        "readOnly": args.mode != "broadcast",
                        "tradeSent": False,
                        "broadcastEnabled": broadcast_enabled(args),
                        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                        "executionRpcSource": rpc_selection.source,
                        "error": str(exc),
                    }
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    sleep_for = max(1.0, float(args.prelaunch_poll_sec))

                elapsed = time.monotonic() - loop_started
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, sleep_for - elapsed))

    summary = {
        "event": "service_stop",
        "at": utc_iso(),
        "atCst": cst_iso(),
        "project": str(args.project),
        "rule": str(args.rule),
        "mode": executor_mode(args),
        "sampleCount": sample_count,
        "decisionCounts": counts,
        "readOnly": args.mode != "broadcast",
        "tradeSent": False,
        "broadcastEnabled": broadcast_enabled(args),
        "outputJsonl": str(output_jsonl),
    }
    append_jsonl(output_jsonl, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
