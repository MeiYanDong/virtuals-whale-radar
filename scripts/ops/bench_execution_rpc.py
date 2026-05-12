#!/usr/bin/env python3
"""Benchmark lightweight execution-RPC calls without printing endpoint tokens."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from typing import Any

import aiohttp


DEFAULT_OWNER = "0x4a371b9b1bf1e7bc0700dff666631f0fc5c96624"
DEFAULT_VIRTUAL = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
DEFAULT_SPENDER = "0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded"


def address_word(address: str) -> str:
    return "0" * 24 + str(address).lower().replace("0x", "")


def encode_balance(owner: str) -> str:
    return "0x70a08231" + address_word(owner)


def encode_allowance(owner: str, spender: str) -> str:
    return "0xdd62ed3e" + address_word(owner) + address_word(spender)


def redact_url(url: str) -> str:
    bits = str(url).split("/")
    if len(bits) > 3 and len(bits[-1]) >= 8:
        return "/".join(bits[:-1] + ["***"])
    return str(url)


def percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(len(ordered) * ratio) - 1))
    return ordered[idx]


async def rpc_call(
    session: aiohttp.ClientSession,
    *,
    url: str,
    method: str,
    params: list[Any],
    request_id: int,
    timeout_sec: float,
) -> tuple[bool, float, int | None, str]:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    started = time.perf_counter()
    try:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout_sec),
        ) as resp:
            text = await resp.text()
            elapsed_ms = (time.perf_counter() - started) * 1000
            ok = resp.status == 200 and '"error"' not in text[:500]
            return ok, elapsed_ms, resp.status, "" if ok else text[:240]
    except Exception as exc:
        return False, (time.perf_counter() - started) * 1000, None, str(exc)[:240]


async def bench_provider(
    *,
    label: str,
    url: str,
    owner: str,
    virtual_token: str,
    spender: str,
    samples: int,
    timeout_sec: float,
) -> dict[str, Any]:
    methods = [
        ("block", "eth_blockNumber", []),
        ("nonce", "eth_getTransactionCount", [owner, "pending"]),
        ("balance", "eth_call", [{"to": virtual_token, "data": encode_balance(owner)}, "latest"]),
        ("allowance", "eth_call", [{"to": virtual_token, "data": encode_allowance(owner, spender)}, "latest"]),
        ("gasPrice", "eth_gasPrice", []),
    ]
    rows: list[dict[str, Any]] = []
    request_id = 1
    async with aiohttp.ClientSession() as session:
        for _ in range(samples):
            for op_name, method, params in methods:
                ok, elapsed_ms, status, error = await rpc_call(
                    session,
                    url=url,
                    method=method,
                    params=params,
                    request_id=request_id,
                    timeout_sec=timeout_sec,
                )
                request_id += 1
                rows.append(
                    {
                        "op": op_name,
                        "ok": ok,
                        "ms": elapsed_ms,
                        "status": status,
                        "error": error,
                    }
                )

    out: dict[str, Any] = {
        "label": label,
        "endpointSha": hashlib.sha256(url.encode()).hexdigest()[:12],
        "url": redact_url(url),
        "ok": sum(1 for row in rows if row["ok"]),
        "total": len(rows),
        "methods": {},
    }
    for op_name in sorted({row["op"] for row in rows}):
        vals = [row["ms"] for row in rows if row["op"] == op_name and row["ok"]]
        errs = [row for row in rows if row["op"] == op_name and not row["ok"]]
        out["methods"][op_name] = {
            "ok": len(vals),
            "err": len(errs),
            "p50ms": round(statistics.median(vals), 1) if vals else None,
            "p90ms": round(percentile(vals, 0.9), 1) if vals else None,
            "maxms": round(max(vals), 1) if vals else None,
            "sampleError": errs[0]["error"] if errs else None,
        }
    all_vals = [row["ms"] for row in rows if row["ok"]]
    out["overall"] = {
        "p50ms": round(statistics.median(all_vals), 1) if all_vals else None,
        "p90ms": round(percentile(all_vals, 0.9), 1) if all_vals else None,
        "maxms": round(max(all_vals), 1) if all_vals else None,
    }
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark execution RPC providers.")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--timeout-sec", type=float, default=8)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--virtual-token", default=DEFAULT_VIRTUAL)
    parser.add_argument("--spender", default=DEFAULT_SPENDER)
    parser.add_argument("--include", default="chainstack,ankr,alchemy")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    mapping = {
        "chainstack": "CHAINSTACK_BASE_HTTP_RPC_URL",
        "ankr": "ANKR_BASE_HTTP_RPC_URL",
        "alchemy": "ALCHEMY_BASE_HTTP_RPC_URL",
        "execution": "VWR_EXEC_HTTP_RPC_URL",
    }
    labels = [item.strip().lower() for item in str(args.include).split(",") if item.strip()]
    results = []
    for label in labels:
        env_key = mapping.get(label)
        if not env_key:
            continue
        url = str(os.environ.get(env_key) or "").strip()
        if not url:
            results.append({"label": label, "missingEnv": env_key})
            continue
        results.append(
            await bench_provider(
                label=label,
                url=url,
                owner=args.owner,
                virtual_token=args.virtual_token,
                spender=args.spender,
                samples=max(1, int(args.samples)),
                timeout_sec=float(args.timeout_sec),
            )
        )
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
