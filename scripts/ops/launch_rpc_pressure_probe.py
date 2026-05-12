#!/usr/bin/env python3
"""Read-only RPC pressure probe for the launch execution chain.

This script measures main collection RPC, backfill RPC, execution RPC, and
optional project market-reserve latency in one report. It never signs or
broadcasts transactions and never prints raw RPC endpoint tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from execution_rpc import resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    GET_RESERVES_SELECTOR,
    VIRTUALS_BUY_SPENDER,
    encode_erc20_allowance,
    encode_erc20_balance_of,
    normalize_hex_address,
)
from live_strategy_dry_run import cst_iso, utc_iso  # noqa: E402
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


DEFAULT_OWNER = "0x4a371b9b1bf1e7bc0700dff666631f0fc5c96624"


@dataclass(frozen=True)
class EndpointSpec:
    label: str
    url: str
    aliases: tuple[str, ...] = ()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only launch RPC pressure probe.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", help="Managed project name/id/SignalHub id for market latency probe.")
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--spender", default=VIRTUALS_BUY_SPENDER)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--interval-sec", type=float, default=0.5)
    parser.add_argument("--timeout-sec", type=int, default=8)
    parser.add_argument("--max-main-p90-ms", type=float, default=1000)
    parser.add_argument("--max-execution-p90-ms", type=float, default=1000)
    parser.add_argument("--max-market-p90-ms", type=float, default=1000)
    parser.add_argument("--output-json")
    parser.add_argument("--output-jsonl")
    return parser.parse_args()


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * ratio) - 1))
    return ordered[idx]


def metric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "p50ms": None, "p90ms": None, "maxms": None}
    return {
        "count": len(values),
        "p50ms": round(statistics.median(values), 1),
        "p90ms": round(percentile(values, 0.9) or 0, 1),
        "maxms": round(max(values), 1),
    }


def endpoint_specs(cfg: Any, execution_url: str) -> list[EndpointSpec]:
    raw = [
        ("main_http", cfg.http_rpc_url),
        ("backfill_http", (cfg.backfill_http_rpc_urls or [cfg.http_rpc_url])[0]),
        ("execution", execution_url),
    ]
    by_url: dict[str, list[str]] = {}
    for label, url in raw:
        url = str(url or "").strip()
        if not url:
            continue
        by_url.setdefault(url, []).append(label)
    specs: list[EndpointSpec] = []
    for url, labels in by_url.items():
        specs.append(EndpointSpec(label=labels[0], url=url, aliases=tuple(labels[1:])))
    return specs


def find_project(sqlite_path: str, project: str | None) -> dict[str, Any] | None:
    target = str(project or "").strip()
    if not target:
        return None
    path = Path(sqlite_path)
    if not path.exists():
        return {"error": f"sqlite_not_found:{path}"}
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM managed_projects
            ORDER BY start_at DESC, updated_at DESC, name ASC
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        item = dict(row)
        if str(item.get("name") or "").strip().lower() == target.lower():
            return item
        if str(item.get("signalhub_project_id") or "").strip() == target:
            return item
        if str(item.get("id") or "").strip() == target:
            return item
    return {"error": f"managed_project_not_found:{target}"}


async def timed_rpc_call(rpc: RPCClient, *, op: str, method: str, params: list[Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = await rpc.call(method, params)
    except Exception as exc:
        return {"op": op, "ok": False, "ms": elapsed_ms(started), "error": str(exc)[:240]}
    out: dict[str, Any] = {"op": op, "ok": True, "ms": elapsed_ms(started)}
    if op == "blockNumber":
        out["blockNumber"] = int(str(result), 16)
    elif op == "gasPrice":
        out["gasPriceWei"] = str(int(str(result), 16))
    elif op == "nonce":
        out["pendingNonce"] = int(str(result), 16)
    return out


async def probe_endpoint(
    spec: EndpointSpec,
    *,
    cfg: Any,
    owner: str,
    spender: str,
    timeout_sec: int,
) -> dict[str, Any]:
    ops = [
        ("blockNumber", "eth_blockNumber", []),
        ("gasPrice", "eth_gasPrice", []),
        ("nonce", "eth_getTransactionCount", [owner, "pending"]),
        (
            "virtualBalance",
            "eth_call",
            [{"to": cfg.virtual_token_addr, "data": encode_erc20_balance_of(owner)}, "latest"],
        ),
        (
            "virtualAllowance",
            "eth_call",
            [{"to": cfg.virtual_token_addr, "data": encode_erc20_allowance(owner, spender)}, "latest"],
        ),
    ]
    async with RPCClient(spec.url, max_retries=1, timeout_sec=timeout_sec) as rpc:
        rows = await asyncio.gather(
            *(timed_rpc_call(rpc, op=op, method=method, params=params) for op, method, params in ops)
        )
    return {
        "label": spec.label,
        "aliases": list(spec.aliases),
        "rpc": redact_rpc_url(spec.url),
        "rows": rows,
    }


async def probe_market(
    *,
    cfg: Any,
    project_row: dict[str, Any] | None,
    timeout_sec: int,
) -> dict[str, Any] | None:
    if project_row is None:
        return None
    if project_row.get("error"):
        return {"ok": False, "error": project_row["error"]}
    token = str(project_row.get("token_addr") or "").strip()
    pool = str(project_row.get("internal_pool_addr") or "").strip()
    if not token or not pool:
        return {
            "ok": False,
            "project": project_row.get("name"),
            "error": "missing_token_or_pool",
            "tokenAddr": token,
            "poolAddr": pool,
        }
    started = time.perf_counter()
    async with RPCClient(cfg.http_rpc_url, max_retries=1, timeout_sec=timeout_sec) as rpc:
        block_row, reserve_row = await asyncio.gather(
            timed_rpc_call(rpc, op="marketBlockNumber", method="eth_blockNumber", params=[]),
            timed_rpc_call(rpc, op="poolGetReserves", method="eth_call", params=[{"to": pool, "data": GET_RESERVES_SELECTOR}, "latest"]),
        )
    ok = bool(block_row.get("ok")) and bool(reserve_row.get("ok"))
    return {
        "ok": ok,
        "project": project_row.get("name"),
        "tokenAddr": token,
        "poolAddr": pool,
        "ms": elapsed_ms(started),
        "block": block_row,
        "reserves": reserve_row,
    }


def flatten_rows(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        for endpoint in sample.get("endpoints") or []:
            labels = [endpoint.get("label"), *(endpoint.get("aliases") or [])]
            for row in endpoint.get("rows") or []:
                for label in labels:
                    rows.append({"channel": label, **row})
        market = sample.get("market")
        if market:
            rows.append(
                {
                    "channel": "market",
                    "op": "marketSnapshot",
                    "ok": bool(market.get("ok")),
                    "ms": market.get("ms"),
                    "error": market.get("error"),
                }
            )
    return rows


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = flatten_rows(samples)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row.get("channel")), str(row.get("op"))), []).append(row)
    summary: dict[str, Any] = {}
    for (channel, op), items in sorted(groups.items()):
        ok_values = [float(item["ms"]) for item in items if item.get("ok") and item.get("ms") is not None]
        errors = [item for item in items if not item.get("ok")]
        summary.setdefault(channel, {})[op] = {
            **metric_summary(ok_values),
            "ok": len(ok_values),
            "err": len(errors),
            "sampleError": (errors[0].get("error") if errors else None),
        }
    return summary


def channel_p90(summary: dict[str, Any], channel: str) -> float | None:
    values = [
        float(item["p90ms"])
        for item in (summary.get(channel) or {}).values()
        if item.get("p90ms") is not None
    ]
    return max(values) if values else None


def is_green(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    for ops in summary.values():
        for item in ops.values():
            if int(item.get("err") or 0) > 0:
                return False
    main_p90 = channel_p90(summary, "main_http")
    exec_p90 = channel_p90(summary, "execution")
    market_p90 = channel_p90(summary, "market")
    if main_p90 is not None and main_p90 > float(args.max_main_p90_ms):
        return False
    if exec_p90 is not None and exec_p90 > float(args.max_execution_p90_ms):
        return False
    if market_p90 is not None and market_p90 > float(args.max_market_p90_ms):
        return False
    return True


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    owner = normalize_hex_address(args.owner)
    spender = normalize_hex_address(args.spender)
    execution = resolve_execution_rpc_url(cfg)
    project_row = find_project(cfg.sqlite_path, args.project)
    specs = endpoint_specs(cfg, execution.rpc_url)
    samples: list[dict[str, Any]] = []
    jsonl_path = Path(args.output_jsonl) if args.output_jsonl else None
    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    for i in range(max(1, int(args.samples))):
        endpoint_results, market = await asyncio.gather(
            asyncio.gather(
                *(probe_endpoint(spec, cfg=cfg, owner=owner, spender=spender, timeout_sec=int(args.timeout_sec)) for spec in specs)
            ),
            probe_market(cfg=cfg, project_row=project_row, timeout_sec=int(args.timeout_sec)),
        )
        sample = {
            "i": i,
            "at": utc_iso(),
            "atCst": cst_iso(),
            "tradeSent": False,
            "broadcasted": False,
            "executionRpcSharedWithMain": execution.rpc_shared_with_main,
            "executionRpcSource": execution.source,
            "executionRpcSourceDetail": execution.source_detail,
            "executionRpcLoadedFromProjectEnvFile": execution.loaded_from_project_env_file,
            "endpoints": endpoint_results,
            "market": market,
        }
        samples.append(sample)
        if jsonl_path:
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
        if i + 1 < max(1, int(args.samples)):
            await asyncio.sleep(max(0.0, float(args.interval_sec)))

    summary = summarize(samples)
    output = {
        "generatedAt": utc_iso(),
        "generatedAtCst": cst_iso(),
        "readOnly": True,
        "tradeSent": False,
        "broadcasted": False,
        "samplesRequested": int(args.samples),
        "singleActiveRpcPolicy": "local_same_shape_test_then_sync_production",
        "executionRpcSharedWithMain": execution.rpc_shared_with_main,
        "executionRpcSource": execution.source,
        "executionRpcSourceDetail": execution.source_detail,
        "executionRpcLoadedFromProjectEnvFile": execution.loaded_from_project_env_file,
        "localProjectEnvBroadcastBlockedByDefault": execution.loaded_from_project_env_file,
        "project": None
        if project_row is None
        else {
            "name": project_row.get("name"),
            "id": project_row.get("id"),
            "signalhubProjectId": project_row.get("signalhub_project_id"),
            "error": project_row.get("error"),
        },
        "summary": summary,
        "green": is_green(summary, args),
        "samples": samples,
    }
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "green": output["green"],
                "executionRpcSharedWithMain": output["executionRpcSharedWithMain"],
                "executionRpcSource": output["executionRpcSource"],
                "executionRpcSourceDetail": output["executionRpcSourceDetail"],
                "executionRpcLoadedFromProjectEnvFile": output["executionRpcLoadedFromProjectEnvFile"],
                "singleActiveRpcPolicy": output["singleActiveRpcPolicy"],
                "mainP90Ms": channel_p90(summary, "main_http"),
                "executionP90Ms": channel_p90(summary, "execution"),
                "marketP90Ms": channel_p90(summary, "market"),
                "outputJson": args.output_json,
                "outputJsonl": args.output_jsonl,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
