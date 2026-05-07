#!/usr/bin/env python3
"""Run a read-only Chainstack-focused production readiness test suite."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from argparse import Namespace
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ops import audit_project_window, native_launch_replay  # noqa: E402
from virtuals_bot import RPCClient, TRANSFER_TOPIC0  # noqa: E402


DEFAULT_ENV_FILE = "/etc/virtuals-whale-radar/rpc.env"
DEFAULT_OUTPUT_DIR = "data/audits"
VIRTUAL_TOKEN_ADDR = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
SECRET_KEYS = ("url", "endpoint", "rpc")
URL_RE = re.compile(r"(https?|wss?)://[^\s\"']+")


def now_stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def read_env_file(path: str | None) -> None:
    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def redact_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlparse(value)
    except Exception:
        return value
    if parsed.scheme in {"http", "https", "ws", "wss"} and parsed.netloc:
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/***", "", "", ""))
    return value


def redact(value: Any, key_hint: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, key_hint) for item in value]
    if isinstance(value, str):
        if any(item in key_hint.lower() for item in SECRET_KEYS):
            return redact_url(value)
        return URL_RE.sub(lambda match: redact_url(match.group(0)), value)
    return value


def summarize_block(block: dict[str, Any] | None) -> dict[str, Any]:
    if not block:
        return {"ok": False}
    return {
        "ok": True,
        "number": int(str(block.get("number", "0x0")), 16),
        "timestamp": int(str(block.get("timestamp", "0x0")), 16),
    }


async def timed(label: str, fn: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await fn()
        return {
            "check": label,
            "ok": True,
            "latencyMs": int(round((time.perf_counter() - started) * 1000)),
            "result": result,
        }
    except Exception as exc:
        return {
            "check": label,
            "ok": False,
            "latencyMs": int(round((time.perf_counter() - started) * 1000)),
            "error": f"{type(exc).__name__}: {exc}",
        }


async def run_rpc_smoke(args: argparse.Namespace, http_url: str, wss_url: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    async with RPCClient(http_url, timeout_sec=args.timeout_sec, max_retries=args.max_retries) as rpc:
        latest_result = await timed("eth_blockNumber", rpc.get_latest_block_number)
        checks.append(latest_result)
        latest = int(latest_result.get("result") or 0)
        if latest > 0:
            latest_block = await timed(
                "eth_getBlockByNumber_latest",
                lambda: rpc.get_block_by_number(latest),
            )
            latest_block["result"] = summarize_block(latest_block.get("result"))
            checks.append(latest_block)

            historical_block_number = max(0, latest - args.historical_block_offset)
            historical_block = await timed(
                "eth_getBlockByNumber_historical",
                lambda: rpc.get_block_by_number(historical_block_number),
            )
            historical_block["blockNumber"] = historical_block_number
            historical_block["result"] = summarize_block(historical_block.get("result"))
            checks.append(historical_block)

            logs_started = time.perf_counter()
            try:
                logs = await rpc.get_logs(
                    from_block=max(0, latest - args.logs_window_blocks),
                    to_block=latest,
                    address=VIRTUAL_TOKEN_ADDR,
                    topics=[TRANSFER_TOPIC0],
                )
                checks.append(
                    {
                        "check": "eth_getLogs_recent_window",
                        "ok": True,
                        "latencyMs": int(round((time.perf_counter() - logs_started) * 1000)),
                        "fromBlock": max(0, latest - args.logs_window_blocks),
                        "toBlock": latest,
                        "count": len(logs),
                    }
                )
                if logs:
                    tx_hash = str(logs[-1].get("transactionHash") or "")
                    receipt_check = await timed(
                        "eth_getTransactionReceipt_recent",
                        lambda: rpc.get_receipt(tx_hash),
                    )
                    receipt = receipt_check.get("result")
                    receipt_check["result"] = {
                        "ok": bool(receipt),
                        "blockNumber": int(receipt["blockNumber"], 16) if receipt else None,
                    }
                    checks.append(receipt_check)
                else:
                    checks.append(
                        {
                            "check": "eth_getTransactionReceipt_recent",
                            "ok": None,
                            "skipped": True,
                            "reason": "no recent VIRTUAL transfer logs in smoke window",
                        }
                    )
            except Exception as exc:
                checks.append(
                    {
                        "check": "eth_getLogs_recent_window",
                        "ok": False,
                        "latencyMs": int(round((time.perf_counter() - logs_started) * 1000)),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    wss_started = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout_sec)) as session:
            async with session.ws_connect(wss_url) as ws:
                await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
                msg = await ws.receive()
                body = json.loads(msg.data)
                checks.append(
                    {
                        "check": "wss_eth_blockNumber",
                        "ok": "result" in body,
                        "latencyMs": int(round((time.perf_counter() - wss_started) * 1000)),
                    }
                )
    except Exception as exc:
        checks.append(
            {
                "check": "wss_eth_blockNumber",
                "ok": False,
                "latencyMs": int(round((time.perf_counter() - wss_started) * 1000)),
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    ok = all(item.get("ok") is True or item.get("skipped") for item in checks)
    return {"ok": ok, "checks": checks}


async def fetch_json(session: aiohttp.ClientSession, url: str) -> tuple[bool, Any]:
    async with session.get(url) as resp:
        body = await resp.text()
        if resp.status >= 400:
            return False, {"status": resp.status, "body": body[:500]}
        try:
            return True, json.loads(body)
        except Exception:
            return True, body


async def run_health(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True}
    services: list[dict[str, Any]] = []
    for service in args.services:
        proc = subprocess.run(
            ["systemctl", "is-active", service],
            text=True,
            capture_output=True,
            check=False,
        )
        active = proc.stdout.strip()
        services.append({"service": service, "state": active, "ok": proc.returncode == 0 and active == "active"})
    result["services"] = services
    if any(not item["ok"] for item in services):
        result["ok"] = False

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=args.timeout_sec)) as session:
        signalhub_ok, signalhub_payload = await fetch_json(session, args.signalhub_health_url)
        result["signalhub"] = {
            "ok": signalhub_ok and isinstance(signalhub_payload, dict) and signalhub_payload.get("status") == "ok",
            "payload": signalhub_payload,
        }
        if not result["signalhub"]["ok"]:
            result["ok"] = False

        main_ok, main_payload = await fetch_json(session, args.health_url)
        main_summary: dict[str, Any] = {"ok": False, "payload": main_payload}
        if main_ok and isinstance(main_payload, dict):
            stats = main_payload.get("stats") or {}
            main_summary = {
                "ok": bool(main_payload.get("ok")),
                "role": main_payload.get("role"),
                "runtimePaused": main_payload.get("runtimePaused"),
                "wsConnected": stats.get("ws_connected"),
                "queueSize": main_payload.get("queueSize"),
                "pendingTx": main_payload.get("pendingTx"),
                "lastProcessedBlock": main_payload.get("lastProcessedBlock"),
            }
        result["main"] = main_summary
        if not main_summary.get("ok"):
            result["ok"] = False
    return result


async def run_replay(args: argparse.Namespace, http_url: str) -> dict[str, Any]:
    replay_args = Namespace(
        config=args.config,
        virtuals_id=args.virtuals_id,
        replay_name=args.replay_name,
        duration_minutes=args.replay_duration_minutes,
        speed=args.replay_speed,
        output_dir=args.replay_output_dir,
        api_port=args.replay_api_port,
        serve=False,
        manual=False,
        hold_open_sec=0,
        logs_rpc_url=http_url,
        receipt_rpc_url=http_url,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        min_log_chunk_blocks=args.min_log_chunk_blocks,
        block_time_concurrency=args.block_time_concurrency,
        progress_every=args.replay_progress_every,
        sample_interval_sec=args.sample_interval_sec,
        tick_sec=args.tick_sec,
    )
    stdout = io.StringIO()
    if args.verbose_replay:
        summary = await native_launch_replay.run(replay_args)
    else:
        with contextlib.redirect_stdout(stdout):
            summary = await native_launch_replay.run(replay_args)
    final = summary.get("finalSample") or {}
    samples_path = summary.get("samplesPath")
    summary_path = summary.get("summaryPath")
    if not summary_path and isinstance(samples_path, str) and samples_path.endswith("-samples.jsonl"):
        summary_path = samples_path[: -len("-samples.jsonl")] + "-summary.json"
    checks = [
        {"name": "tx_count_positive", "ok": int(summary.get("txCount") or 0) > 0},
        {
            "name": "parsed_equals_inserted",
            "ok": int(summary.get("parsedEventCount") or -1) == int(summary.get("insertedEventCount") or -2),
        },
        {"name": "historical_eth_call_supported", "ok": summary.get("historicalEthCallSupported") is True},
        {"name": "log_errors_empty", "ok": not summary.get("logErrors")},
        {
            "name": "historical_pool_reserves",
            "ok": final.get("marketPriceSource") == "historical_pool_reserves",
        },
        {"name": "tax_fdv_present", "ok": final.get("estimatedFdvWanUsdWithTax") is not None},
    ]
    return {
        "ok": all(item["ok"] for item in checks),
        "checks": checks,
        "summary": {
            "project": summary.get("project"),
            "virtualsId": summary.get("virtualsId"),
            "txCount": summary.get("txCount"),
            "parsedEventCount": summary.get("parsedEventCount"),
            "insertedEventCount": summary.get("insertedEventCount"),
            "samples": summary.get("samples"),
            "historicalEthCallSupported": summary.get("historicalEthCallSupported"),
            "historicalEthCallFallbackReason": summary.get("historicalEthCallFallbackReason"),
            "logSplits": summary.get("logSplits"),
            "logErrors": summary.get("logErrors"),
            "summaryPath": summary_path,
            "samplesPath": samples_path,
            "sqlitePath": summary.get("sqlitePath"),
            "finalSample": final,
        },
    }


async def run_audit(args: argparse.Namespace, http_url: str) -> dict[str, Any]:
    audit_args = Namespace(
        config=args.config,
        project=args.audit_project,
        sqlite_path=args.audit_sqlite_path,
        from_block=args.audit_from_block,
        to_block=args.audit_to_block,
        logs_rpc_url=http_url,
        block_rpc_url=http_url,
        log_chunk_blocks=args.audit_log_chunk_blocks,
        min_log_chunk_blocks=args.min_log_chunk_blocks,
        timeout_sec=args.timeout_sec,
        max_retries=args.max_retries,
        receipt_concurrency=args.receipt_concurrency,
        expected_events=args.expected_events,
        expected_event_txs=args.expected_event_txs,
        expected_candidate_txs=args.expected_candidate_txs,
        skip_discovery=False,
        include_tx_lists=False,
        write_repair_tx_file=False,
        repair_tx_file=None,
        output=None,
    )
    summary = await audit_project_window.run(audit_args)
    return {
        "ok": summary.get("status") == "green",
        "status": summary.get("status"),
        "blockers": summary.get("blockers"),
        "notes": summary.get("notes"),
        "profile": summary.get("profile"),
        "coverage": summary.get("coverage"),
        "discovery": summary.get("discovery"),
        "repair": summary.get("repair"),
    }


async def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    read_env_file(args.env_file)
    started = int(time.time())
    http_url = os.environ.get("CHAINSTACK_BASE_HTTP_RPC_URL", "").strip()
    wss_url = os.environ.get("CHAINSTACK_BASE_WS_RPC_URL", "").strip()
    result: dict[str, Any] = {
        "suite": "chainstack",
        "startedAt": started,
        "config": args.config,
        "env": {
            "chainstackHttpConfigured": bool(http_url),
            "chainstackWssConfigured": bool(wss_url),
        },
        "steps": {},
    }

    if not http_url:
        result["steps"]["env"] = {"ok": False, "error": "CHAINSTACK_BASE_HTTP_RPC_URL is not configured"}
    if not wss_url:
        result["steps"]["env"] = {"ok": False, "error": "CHAINSTACK_BASE_WS_RPC_URL is not configured"}
    if not http_url or not wss_url:
        result["status"] = "red"
        result["finishedAt"] = int(time.time())
        return result
    result["steps"]["env"] = {"ok": True}

    if not args.skip_rpc_smoke:
        result["steps"]["rpcSmoke"] = await run_rpc_smoke(args, http_url, wss_url)
    else:
        result["steps"]["rpcSmoke"] = {"ok": None, "skipped": True}

    if not args.skip_health:
        result["steps"]["health"] = await run_health(args)
    else:
        result["steps"]["health"] = {"ok": None, "skipped": True}

    if not args.skip_replay:
        result["steps"]["replay"] = await run_replay(args, http_url)
    else:
        result["steps"]["replay"] = {"ok": None, "skipped": True}

    if args.audit_project and not args.skip_audit:
        result["steps"]["audit"] = await run_audit(args, http_url)
    else:
        result["steps"]["audit"] = {"ok": None, "skipped": True}

    result["finishedAt"] = int(time.time())
    required = [step for step in result["steps"].values() if not step.get("skipped")]
    failed = [step for step in required if step.get("ok") is not True]
    skipped = [step for step in result["steps"].values() if step.get("skipped")]
    if failed:
        result["status"] = "red"
    elif skipped:
        result["status"] = "observed"
    else:
        result["status"] = "green"
    return redact(result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Chainstack-only readiness checks.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    parser.add_argument("--output")
    parser.add_argument("--timeout-sec", type=int, default=12)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--logs-window-blocks", type=int, default=50)
    parser.add_argument("--historical-block-offset", type=int, default=50000)
    parser.add_argument(
        "--services",
        nargs="*",
        default=[
            "vwr-signalhub.service",
            "vwr@writer.service",
            "vwr@realtime.service",
            "vwr@backfill.service",
        ],
    )
    parser.add_argument("--health-url", default="http://127.0.0.1:8080/health")
    parser.add_argument("--signalhub-health-url", default="http://127.0.0.1:8000/healthz")
    parser.add_argument("--virtuals-id", default="72752")
    parser.add_argument("--replay-name", default="ISC_CHAINSTACK_SUITE")
    parser.add_argument("--replay-duration-minutes", type=float, default=10.0)
    parser.add_argument("--replay-speed", type=float, default=5.0)
    parser.add_argument("--replay-output-dir", default="data/replay-chainstack-suite")
    parser.add_argument("--replay-api-port", type=int, default=18080)
    parser.add_argument("--replay-progress-every", type=int, default=1000)
    parser.add_argument("--sample-interval-sec", type=float, default=1.0)
    parser.add_argument("--tick-sec", type=float, default=0.2)
    parser.add_argument("--min-log-chunk-blocks", type=int, default=10)
    parser.add_argument("--block-time-concurrency", type=int, default=12)
    parser.add_argument("--audit-project")
    parser.add_argument("--audit-sqlite-path")
    parser.add_argument("--audit-from-block", type=int)
    parser.add_argument("--audit-to-block", type=int)
    parser.add_argument("--audit-log-chunk-blocks", type=int, default=1000)
    parser.add_argument("--receipt-concurrency", type=int, default=16)
    parser.add_argument("--expected-events", type=int)
    parser.add_argument("--expected-event-txs", type=int)
    parser.add_argument("--expected-candidate-txs", type=int)
    parser.add_argument("--skip-rpc-smoke", action="store_true")
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--verbose-replay", action="store_true")
    return parser.parse_args()


def default_output_path() -> str:
    Path(DEFAULT_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    return str(Path(DEFAULT_OUTPUT_DIR) / f"chainstack-suite-{now_stamp()}.json")


def main() -> None:
    args = parse_args()
    output_path = args.output or default_output_path()
    summary = asyncio.run(run_suite(args))
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary.get("status"), "output": output_path}, ensure_ascii=False, indent=2))
    if summary.get("status") == "red":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
