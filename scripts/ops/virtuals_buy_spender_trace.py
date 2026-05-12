#!/usr/bin/env python3
"""Trace historical Virtuals direct buys to identify the real VIRTUAL spender.

Read-only script:
- fetches public tx + debug_traceTransaction data;
- finds VIRTUAL transferFrom calls;
- verifies balance and allowance at the block before the buy.

It does not sign, simulate, or broadcast.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_execution_pipeline import (  # noqa: E402
    VIRTUALS_BUY_ROUTER,
    VIRTUALS_BUY_SPENDER,
    encode_erc20_allowance,
    encode_erc20_balance_of,
    parse_rpc_int,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


TRANSFER_FROM_SELECTOR = "0x23b872dd"
DEFAULT_OUTPUT_JSON = "data/backtests/virtuals-buy-spender-trace-20260510.json"
DEFAULT_OUTPUT_MD = "docs/phases/phase-053-virtuals-buy-spender-trace-2026-05-10.md"


@dataclass(frozen=True)
class TraceSample:
    project: str
    tx_hash: str
    required_wei: int


DEFAULT_SAMPLES = [
    TraceSample(
        project="SR_EVENT_REPLAY",
        tx_hash="0x598d50a883fd27f0a787cd5ad313d031d243c333ac990b11f45594dccdab760e",
        required_wei=100_000_000_000_000_000_000,
    ),
    TraceSample(
        project="ISC_EVENT_REPLAY",
        tx_hash="0x38d9b3f3cb17eb6dd5eb99fdb990cfa9bf5fd27577a090ba3827629f5e982840",
        required_wei=600_000_000_000_000_000_000,
    ),
]


def word_address(word: str) -> str:
    return "0x" + word[-40:]


def decode_transfer_from(data: str) -> dict[str, Any] | None:
    raw = str(data or "").lower()
    if not raw.startswith(TRANSFER_FROM_SELECTOR):
        return None
    body = raw[10:]
    words = [body[i : i + 64] for i in range(0, len(body), 64)]
    if len(words) < 3:
        return None
    return {
        "from": word_address(words[0]),
        "to": word_address(words[1]),
        "amountWei": int(words[2], 16),
    }


def walk_calls(node: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for child in node.get("calls") or []:
        rows.append(child)
        rows.extend(walk_calls(child))
    return rows


async def eth_call_at(rpc: RPCClient, *, to: str, data: str, block_number: int) -> int:
    return parse_rpc_int(await rpc.call("eth_call", [{"to": to, "data": data}, hex(block_number)]))


async def analyze_sample(rpc: RPCClient, *, virtual_token_addr: str, sample: TraceSample) -> dict[str, Any]:
    tx = await rpc.call("eth_getTransactionByHash", [sample.tx_hash])
    trace = await rpc.call("debug_traceTransaction", [sample.tx_hash, {"tracer": "callTracer", "timeout": "20s"}])
    owner = str(tx.get("from") or "").lower()
    block_number = parse_rpc_int(tx.get("blockNumber"))
    spender_totals: dict[str, int] = defaultdict(int)
    transfer_from_calls: list[dict[str, Any]] = []

    for call in walk_calls(trace):
        if str(call.get("to") or "").lower() != virtual_token_addr.lower():
            continue
        decoded = decode_transfer_from(str(call.get("input") or ""))
        if not decoded or decoded["from"].lower() != owner:
            continue
        spender = str(call.get("from") or "").lower()
        spender_totals[spender] += int(decoded["amountWei"])
        transfer_from_calls.append(
            {
                "spender": spender,
                "to": decoded["to"],
                "amountWei": str(decoded["amountWei"]),
            }
        )

    previous_block = block_number - 1
    owner_balance = await eth_call_at(
        rpc,
        to=virtual_token_addr,
        data=encode_erc20_balance_of(owner),
        block_number=previous_block,
    )
    router_allowance = await eth_call_at(
        rpc,
        to=virtual_token_addr,
        data=encode_erc20_allowance(owner, VIRTUALS_BUY_ROUTER),
        block_number=previous_block,
    )
    spenders = []
    for spender, total in sorted(spender_totals.items()):
        allowance = await eth_call_at(
            rpc,
            to=virtual_token_addr,
            data=encode_erc20_allowance(owner, spender),
            block_number=previous_block,
        )
        spenders.append(
            {
                "spender": spender,
                "transferFromTotalWei": str(total),
                "allowanceWei": str(allowance),
                "allowanceCoversTransfers": allowance >= total,
                "matchesExpectedSpender": spender == VIRTUALS_BUY_SPENDER,
            }
        )
    return {
        "project": sample.project,
        "txHash": sample.tx_hash,
        "blockNumber": block_number,
        "preBlockNumber": previous_block,
        "owner": owner,
        "requiredWei": str(sample.required_wei),
        "ownerBalanceWei": str(owner_balance),
        "ownerBalanceOk": owner_balance >= sample.required_wei,
        "routerAllowanceWei": str(router_allowance),
        "routerAllowanceOk": router_allowance >= sample.required_wei,
        "expectedSpender": VIRTUALS_BUY_SPENDER,
        "spenders": spenders,
        "transferFromCalls": transfer_from_calls,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 053 - Virtuals Buy Spender Trace",
        "",
        "## 结论",
        "",
        f"- 直接买入入口 router 仍然是 `{VIRTUALS_BUY_ROUTER}`。",
        f"- 但 VIRTUAL `transferFrom` 的实际 spender 是 `{VIRTUALS_BUY_SPENDER}`。",
        "- 因此 TxSimulator 的 allowance 检查必须查 `allowance(owner, spender)`，不能查 `allowance(owner, router)`。",
        "- SR/ISC 历史样本在交易前一个 block：owner balance 足够、router allowance 不足、actual spender allowance 足够。",
        "- 本阶段仍然不签名、不广播。",
        "",
        "## 样本",
        "",
        "| Project | Tx | Owner Balance OK | Router Allowance OK | Actual Spender OK | Actual Spender |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["samples"]:
        tx = str(row["txHash"])
        short_tx = f"{tx[:10]}...{tx[-8:]}"
        actual = next((item for item in row["spenders"] if item["matchesExpectedSpender"]), None)
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["project"]),
                    f"`{short_tx}`",
                    "yes" if row["ownerBalanceOk"] else "no",
                    "yes" if row["routerAllowanceOk"] else "no",
                    "yes" if actual and actual["allowanceCoversTransfers"] else "no",
                    f"`{actual['spender']}`" if actual else "-",
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace Virtuals buy spender from historical txs.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_url = (cfg.backfill_http_rpc_urls or [cfg.http_rpc_url])[0]
    async with RPCClient(rpc_url, max_retries=2, timeout_sec=30) as rpc:
        samples = [
            await analyze_sample(rpc, virtual_token_addr=cfg.virtual_token_addr, sample=sample)
            for sample in DEFAULT_SAMPLES
        ]
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rpc": redact_rpc_url(rpc_url),
        "readOnly": True,
        "tradeSent": False,
        "router": VIRTUALS_BUY_ROUTER,
        "expectedSpender": VIRTUALS_BUY_SPENDER,
        "samples": samples,
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(
        json.dumps(
            {
                "outputJson": str(output_json),
                "outputMd": args.output_md,
                "samples": len(samples),
                "expectedSpender": VIRTUALS_BUY_SPENDER,
                "allActualSpenderAllowanceOk": all(
                    any(item["matchesExpectedSpender"] and item["allowanceCoversTransfers"] for item in row["spenders"])
                    for row in samples
                ),
                "allRouterAllowanceInsufficient": all(not row["routerAllowanceOk"] for row in samples),
                "tradeSent": False,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
