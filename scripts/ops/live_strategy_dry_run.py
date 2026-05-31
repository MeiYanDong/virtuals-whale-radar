#!/usr/bin/env python3
"""Realtime launch-strategy dry-run emitter.

This service is deliberately read-only:
- it never reads a private key;
- it never builds, signs, or broadcasts a transaction;
- it writes JSONL would-buy/pause/heartbeat observations for one whitelisted
  project.

It can use an execution RPC through VWR_EXEC_HTTP_RPC_URL. The output marks
rpcSharedWithMain=true when that endpoint is absent or equal to the main config
RPC pool.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from execution_rpc import apply_execution_rpc_to_config  # noqa: E402
from launch_execution_pipeline import DynamicAfter1StrategyEvaluator, resolve_rule  # noqa: E402
from native_launch_replay import build_sample  # noqa: E402
from virtuals_bot import VirtualsBot, load_config, redact_rpc_url  # noqa: E402


class LiveClock:
    def __init__(self) -> None:
        self.real_started_at = time.monotonic()

    def now(self) -> int:
        return int(time.time())


def utc_iso(ts: int | None = None) -> str:
    value = int(time.time()) if ts is None else int(ts)
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def cst_iso(ts: int | None = None) -> str:
    value = int(time.time()) if ts is None else int(ts)
    return datetime.fromtimestamp(value, timezone.utc).astimezone().isoformat()


def compact_sample(sample: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "realElapsedSec",
        "simTimestamp",
        "projectStatus",
        "events",
        "priceBlockNumber",
        "priceLatencyMs",
        "marketPriceSource",
        "tokenPriceV",
        "tokenPriceUsd",
        "liveFdvUsd",
        "buyTaxRate",
        "estimatedFdvWanUsdWithTax",
        "sumTaxV",
        "whaleRows",
        "costRows",
        "excludedRows",
        "boardSpentV",
        "boardCostWanUsd",
        "costPosition",
        "vCostPosition",
        "triggerTypes",
    ]
    return {key: sample.get(key) for key in keys if key in sample}


def fingerprint(sample: dict[str, Any]) -> tuple[Any, ...]:
    return (
        sample.get("projectStatus"),
        sample.get("events"),
        sample.get("buyTaxRate"),
        sample.get("estimatedFdvWanUsdWithTax"),
        sample.get("boardSpentV"),
        sample.get("boardCostWanUsd"),
        sample.get("priceBlockNumber"),
    )


def derive_trigger_types(previous: dict[str, Any] | None, sample: dict[str, Any]) -> list[str]:
    triggers: set[str] = set()
    if previous is None:
        triggers.add("heartbeat")
    else:
        if str(previous.get("buyTaxRate")) != str(sample.get("buyTaxRate")):
            triggers.add("tax_tick")
        if int(previous.get("events") or 0) != int(sample.get("events") or 0):
            triggers.add("pool_state_change")
        if str(previous.get("estimatedFdvWanUsdWithTax")) != str(sample.get("estimatedFdvWanUsdWithTax")):
            triggers.add("market_update")
    if not triggers:
        triggers.add("heartbeat")
    return sorted(triggers)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def sample_archive_record(
    *,
    project: str,
    rule: str,
    sample_index: int,
    sample: dict[str, Any],
    decision_action: str | None,
    decision_reason: str | None,
    rpc_shared_with_main: bool,
    execution_rpc_source: str,
) -> dict[str, Any]:
    record = dict(compact_sample(sample))
    record.update(
        {
            "_recordType": "launch_sample",
            "_recordedAt": utc_iso(),
            "_recordedAtCst": cst_iso(),
            "_project": project,
            "_rule": rule,
            "_sampleIndex": sample_index,
            "_decisionAction": decision_action,
            "_decisionReason": decision_reason,
            "_rpcSharedWithMain": rpc_shared_with_main,
            "_executionRpcSource": execution_rpc_source,
        }
    )
    return record


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_ledger_intent_id(
    *,
    project_name: str,
    signalhub_project_id: Any,
    rule_name: str,
    strategy_name: str,
    action: str,
    reason: str,
    sample: dict[str, Any],
    intent: dict[str, Any] | None,
    pause: dict[str, Any] | None,
) -> str:
    payload = {
        "project": project_name,
        "signalhubProjectId": signalhub_project_id,
        "rule": rule_name,
        "strategy": strategy_name,
        "action": action,
        "reason": reason,
        "simTimestamp": sample.get("simTimestamp"),
        "taxRate": sample.get("buyTaxRate"),
        "entryTaxFdv": (intent or pause or {}).get("entry_tax_fdv_wan_usd")
        or (intent or pause or {}).get("taxFdvWanUsd"),
        "buySizeV": (intent or {}).get("buy_size_v"),
    }
    extra = intent or pause or {}
    for key in ("sourceTxHash", "fdvLimitOrderId", "sourceWallet"):
        value = extra.get(key)
        if value not in (None, ""):
            payload[key] = value
    digest = hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()[:24]
    return f"lexec_{digest}"


def make_ledger_record(
    *,
    project_row: dict[str, Any],
    project_name: str,
    rule_name: str,
    strategy_name: str,
    action: str,
    reason: str,
    sample_index: int,
    sample: dict[str, Any],
    intent: dict[str, Any] | None,
    pause: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = compact_sample(sample)
    entry = intent or pause or {}
    intent_id = make_ledger_intent_id(
        project_name=project_name,
        signalhub_project_id=project_row.get("signalhub_project_id"),
        rule_name=rule_name,
        strategy_name=strategy_name,
        action=action,
        reason=reason,
        sample=sample,
        intent=intent,
        pause=pause,
    )
    return {
        "intent_id": intent_id,
        "project": project_name,
        "managed_project_id": project_row.get("id"),
        "signalhub_project_id": project_row.get("signalhub_project_id"),
        "strategy": strategy_name,
        "rule_name": rule_name,
        "mode": "dry_run",
        "status": "intent_recorded" if intent is not None else "paused",
        "action": action,
        "decision_reason": reason,
        "sample_index": sample_index,
        "snapshot_ts": sample.get("simTimestamp"),
        "tax_rate": sample.get("buyTaxRate"),
        "buy_size_v": entry.get("buy_size_v"),
        "entry_tax_fdv_wan_usd": entry.get("entry_tax_fdv_wan_usd") or entry.get("taxFdvWanUsd"),
        "board_spent_v": snapshot.get("boardSpentV"),
        "board_cost_wan_usd": snapshot.get("boardCostWanUsd"),
        "trigger_types": sample.get("triggerTypes") or [],
        "snapshot": snapshot,
        "intent": intent or {},
        "failure_stage": "strategy" if pause is not None else None,
        "failure_reason": reason if pause is not None else None,
        "trade_sent": False,
        "broadcast_enabled": False,
    }


def find_project(bot: VirtualsBot, project: str) -> dict[str, Any]:
    target = str(project or "").strip()
    if not target:
        raise ValueError("project cannot be empty")
    for row in bot.storage.list_managed_projects():
        if str(row.get("name") or "").strip().lower() == target.lower():
            return dict(row)
        if str(row.get("signalhub_project_id") or "").strip() == target:
            return dict(row)
        if str(row.get("id") or "").strip() == target:
            return dict(row)
    raise ValueError(f"managed project not found: {project}")


def poll_interval_for_status(args: argparse.Namespace, status: str) -> float:
    normalized = str(status or "").strip().lower()
    if normalized == "live":
        return max(float(args.min_poll_sec), float(args.live_poll_sec))
    if normalized == "prelaunch":
        return max(float(args.min_poll_sec), float(args.prelaunch_poll_sec))
    return max(float(args.min_poll_sec), float(args.scheduled_poll_sec))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime dry-run would-buy emitter for one Virtuals project.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True, help="Managed project name, id, or SignalHub project id.")
    parser.add_argument("--rule", default="gate_5k_tax95_fdv_one_per_tax")
    parser.add_argument("--output-jsonl", default="")
    parser.add_argument(
        "--full-samples-jsonl",
        default="",
        help="Optional JSONL path that receives every sampled launch snapshot for replay/backtest archives.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument("--min-poll-sec", type=float, default=0.25)
    parser.add_argument("--live-poll-sec", type=float, default=0.25)
    parser.add_argument("--prelaunch-poll-sec", type=float, default=2.0)
    parser.add_argument("--scheduled-poll-sec", type=float, default=20.0)
    parser.add_argument("--heartbeat-log-sec", type=float, default=30.0)
    parser.add_argument("--exit-after-end-sec", type=int, default=0)
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    rpc_selection = apply_execution_rpc_to_config(cfg)

    # This process must not bootstrap users or send email while only observing.
    cfg.bootstrap_admin_email = None
    cfg.bootstrap_admin_password = None
    cfg.email_enabled = False

    output_jsonl = Path(
        args.output_jsonl
        or f"data/execution/live-strategy-dry-run-{str(args.project).strip().upper()}.jsonl"
    )
    full_samples_jsonl = Path(args.full_samples_jsonl) if str(args.full_samples_jsonl or "").strip() else None
    if full_samples_jsonl is not None and full_samples_jsonl.resolve() == output_jsonl.resolve():
        raise RuntimeError("--full-samples-jsonl must be different from --output-jsonl")
    stop_event = asyncio.Event()

    def on_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, on_stop)

    rule = resolve_rule(str(args.rule))
    clock = LiveClock()
    last_logged_heartbeat = 0.0
    previous_sample: dict[str, Any] | None = None
    previous_fingerprint: tuple[Any, ...] | None = None
    sample_count = 0
    decisions = {"would_buy": 0, "pause": 0, "skip": 0}

    async with VirtualsBot(cfg, role="backfill") as bot:
        project_row = find_project(bot, str(args.project))
        project_name = str(project_row.get("name") or args.project).strip()
        evaluator = DynamicAfter1StrategyEvaluator(project=project_name, rule=rule)
        service_meta = {
            "event": "service_start",
            "at": utc_iso(),
            "atCst": cst_iso(),
            "project": project_name,
            "managedProjectId": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "rule": rule.name,
            "strategy": evaluator.config.name,
            "readOnly": True,
            "tradeSent": False,
            "broadcastEnabled": False,
            "rpc": redact_rpc_url(cfg.http_rpc_url),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "outputJsonl": str(output_jsonl),
            "fullSamplesJsonl": str(full_samples_jsonl) if full_samples_jsonl else "",
        }
        append_jsonl(output_jsonl, service_meta)
        print(json.dumps(service_meta, ensure_ascii=False), flush=True)

        while not stop_event.is_set():
            loop_started = time.monotonic()
            now_ts = int(time.time())
            project_row = find_project(bot, str(args.project))
            sample_count += 1
            try:
                sample = await build_sample(bot, project_row, clock)
                sample["triggerTypes"] = derive_trigger_types(previous_sample, sample)
                current_fingerprint = fingerprint(sample)
                decision = evaluator.evaluate(sample, index=sample_count - 1)
                decisions[decision.action] = decisions.get(decision.action, 0) + 1
                if full_samples_jsonl is not None:
                    append_jsonl(
                        full_samples_jsonl,
                        sample_archive_record(
                            project=project_name,
                            rule=rule.name,
                            sample_index=sample_count - 1,
                            sample=sample,
                            decision_action=decision.action,
                            decision_reason=decision.reason,
                            rpc_shared_with_main=rpc_selection.rpc_shared_with_main,
                            execution_rpc_source=rpc_selection.source,
                        ),
                    )

                should_log = False
                payload: dict[str, Any] = {
                    "event": decision.action,
                    "reason": decision.reason,
                    "at": utc_iso(),
                    "atCst": cst_iso(),
                    "project": project_name,
                    "rule": rule.name,
                    "sampleIndex": sample_count - 1,
                    "readOnly": True,
                    "tradeSent": False,
                    "broadcastEnabled": False,
                    "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                    "executionRpcSource": rpc_selection.source,
                    "sample": compact_sample(sample),
                }
                if decision.intent is not None:
                    payload["intent"] = asdict(decision.intent)
                    ledger_record = make_ledger_record(
                        project_row=project_row,
                        project_name=project_name,
                        rule_name=rule.name,
                        strategy_name=evaluator.config.name,
                        action=decision.action,
                        reason=decision.reason,
                        sample_index=sample_count - 1,
                        sample=sample,
                        intent=payload["intent"],
                        pause=None,
                    )
                    try:
                        bot.storage.upsert_launch_execution_record(ledger_record)
                        payload["ledgerIntentId"] = ledger_record["intent_id"]
                    except Exception as exc:
                        payload["ledgerError"] = str(exc)
                    should_log = True
                elif decision.pause is not None:
                    payload["pause"] = decision.pause
                    ledger_record = make_ledger_record(
                        project_row=project_row,
                        project_name=project_name,
                        rule_name=rule.name,
                        strategy_name=evaluator.config.name,
                        action=decision.action,
                        reason=decision.reason,
                        sample_index=sample_count - 1,
                        sample=sample,
                        intent=None,
                        pause=decision.pause,
                    )
                    try:
                        bot.storage.upsert_launch_execution_record(ledger_record)
                        payload["ledgerIntentId"] = ledger_record["intent_id"]
                    except Exception as exc:
                        payload["ledgerError"] = str(exc)
                    should_log = True
                elif current_fingerprint != previous_fingerprint:
                    payload["event"] = "state_change"
                    should_log = True
                elif (time.monotonic() - last_logged_heartbeat) >= float(args.heartbeat_log_sec):
                    payload["event"] = "heartbeat"
                    should_log = True

                if should_log:
                    append_jsonl(output_jsonl, payload)
                    print(json.dumps(payload, ensure_ascii=False), flush=True)
                    if payload["event"] == "heartbeat":
                        last_logged_heartbeat = time.monotonic()

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
                    "readOnly": True,
                    "tradeSent": False,
                    "broadcastEnabled": False,
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
        "sampleCount": sample_count,
        "decisionCounts": decisions,
        "readOnly": True,
        "tradeSent": False,
        "broadcastEnabled": False,
        "outputJsonl": str(output_jsonl),
        "fullSamplesJsonl": str(full_samples_jsonl) if full_samples_jsonl else "",
    }
    append_jsonl(output_jsonl, summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
