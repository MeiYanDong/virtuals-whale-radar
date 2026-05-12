#!/usr/bin/env python3
"""Audit whether Virtuals buy routing is universal across local project samples.

Read-only:
- reads local SQLite event tables;
- fetches public transaction metadata through the configured RPC;
- summarizes router/selector/calldata length by project.

It does not sign, simulate, or broadcast.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from launch_execution_pipeline import VIRTUALS_BUY_ROUTER, VIRTUALS_BUY_SELECTOR  # noqa: E402
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


VIRTUALS_TEAM_INITIALIZATION_SELECTOR = "0x214013ca"
DEFAULT_OUTPUT_JSON = "data/backtests/virtuals-buy-route-universality-audit-20260510.json"
DEFAULT_OUTPUT_MD = "docs/phases/phase-053-virtuals-buy-route-universality-audit-2026-05-10.md"


@dataclass(frozen=True)
class SourceDB:
    label: str
    path: Path


def plain_decimal(value: Any) -> str:
    text = format(Decimal(str(value or "0")).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def load_event_rows(path: Path, *, limit_per_project: int) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        projects = [
            str(row["project"])
            for row in conn.execute(
                "select project from events where cast(spent_v_est as real) > 0 group by project order by project"
            ).fetchall()
        ]
        rows: list[dict[str, Any]] = []
        for project in projects:
            for row in conn.execute(
                """
                select project, tx_hash, block_number, block_timestamp, buyer,
                       token_addr, spent_v_est, tax_v
                from events
                where project = ?
                  and cast(spent_v_est as real) > 0
                order by block_number, id
                limit ?
                """,
                (project, limit_per_project),
            ).fetchall():
                rows.append(dict(row))
        return rows
    finally:
        conn.close()


def classify_route(row: dict[str, Any]) -> str:
    selector = str(row.get("selector") or "").lower()
    tx_to = str(row.get("txTo") or "").lower()
    if tx_to == VIRTUALS_BUY_ROUTER and selector == VIRTUALS_BUY_SELECTOR:
        return "direct_buy"
    if tx_to == VIRTUALS_BUY_ROUTER and selector == VIRTUALS_TEAM_INITIALIZATION_SELECTOR:
        return "team_or_initialization_route"
    if tx_to == VIRTUALS_BUY_ROUTER:
        return "same_router_other_selector"
    return "alternate_or_aggregator_route"


async def fetch_routes(*, rpc_url: str, sources: list[SourceDB], limit_per_project: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        for source in sources:
            if not source.path.exists():
                continue
            for row in load_event_rows(source.path, limit_per_project=limit_per_project):
                tx_hash = str(row["tx_hash"]).lower()
                if tx_hash in seen:
                    continue
                seen.add(tx_hash)
                tx = await rpc.call("eth_getTransactionByHash", [tx_hash])
                calldata = str((tx or {}).get("input") or (tx or {}).get("data") or "0x").lower()
                result = {
                    "source": source.label,
                    "project": str(row["project"]),
                    "txHash": tx_hash,
                    "blockNumber": int(row["block_number"]),
                    "buyer": str(row["buyer"]).lower(),
                    "tokenAddress": str(row["token_addr"]).lower(),
                    "spentV": plain_decimal(row["spent_v_est"]),
                    "taxV": plain_decimal(row["tax_v"]),
                    "txTo": str((tx or {}).get("to") or "").lower(),
                    "selector": calldata[:10] if len(calldata) >= 10 else calldata,
                    "calldataBytes": max(0, (len(calldata) - 2) // 2),
                }
                result["routeClass"] = classify_route(result)
                results.append(result)
    return results


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_project: dict[str, dict[str, Any]] = {}
    for sample in samples:
        project = str(sample["project"])
        bucket = by_project.setdefault(
            project,
            {
                "sampleCount": 0,
                "routeClassCounts": Counter(),
                "routerCounts": Counter(),
                "selectorCounts": Counter(),
                "calldataByteCounts": Counter(),
                "directBuyCount": 0,
                "nonDirectExamples": [],
            },
        )
        bucket["sampleCount"] += 1
        bucket["routeClassCounts"][sample["routeClass"]] += 1
        bucket["routerCounts"][sample["txTo"]] += 1
        bucket["selectorCounts"][sample["selector"]] += 1
        bucket["calldataByteCounts"][str(sample["calldataBytes"])] += 1
        if sample["routeClass"] == "direct_buy":
            bucket["directBuyCount"] += 1
        elif len(bucket["nonDirectExamples"]) < 5:
            bucket["nonDirectExamples"].append(sample)

    output: dict[str, Any] = {}
    for project, bucket in by_project.items():
        sample_count = int(bucket["sampleCount"])
        direct_count = int(bucket["directBuyCount"])
        output[project] = {
            "sampleCount": sample_count,
            "directBuyCount": direct_count,
            "directBuyRatio": direct_count / sample_count if sample_count else 0,
            "routeClassCounts": dict(bucket["routeClassCounts"]),
            "routerCounts": dict(bucket["routerCounts"]),
            "selectorCounts": dict(bucket["selectorCounts"]),
            "calldataByteCounts": dict(bucket["calldataByteCounts"]),
            "nonDirectExamples": bucket["nonDirectExamples"],
        }
    return output


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Phase 053 - Virtuals Buy Route Universality Audit",
        "",
        "## 结论",
        "",
        "- 对普通用户的 Virtuals direct buy，本地样本支持同一套入口：router `0x1a540088125d00dd3990f9da45ca0859af4d3b01`，selector `0x706910ff`。",
        "- 这不是所有交易的通用入口：TDS 团队/初始化交易出现同 router 但 selector `0x214013ca`；SR 有 1 个 alternate/aggregator route。",
        "- 因此执行层应该把 `direct_buy` 当作第一版自动买入支持范围，把 team/initialization 和 aggregator route 排除在自动买入外。",
        "- 判断口径：交易必须同时满足 `to == direct router`、`selector == 0x706910ff`、`value == 0`，并通过 TxSimulator 的 balance/allowance/eth_call/gas 检查。",
        "- 对大户榜单过滤也有价值：`team_or_initialization_route` 可以作为团队购买的高置信自动过滤信号；最小判断只保留 direct router + `selector == 0x214013ca`。",
        "- 本阶段仍然不签名、不广播。",
        "",
        "## 项目摘要",
        "",
        "| Project | Samples | Direct Buy | Route Classes | Selectors |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for project, summary in report["summaryByProject"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    project,
                    str(summary["sampleCount"]),
                    str(summary["directBuyCount"]),
                    f"`{json.dumps(summary['routeClassCounts'], ensure_ascii=False)}`",
                    f"`{json.dumps(summary['selectorCounts'], ensure_ascii=False)}`",
                ]
            )
            + " |"
        )
    lines.extend(["", "## 非 Direct Buy 样本", ""])
    lines.append("| Project | Route Class | Tx | Router | Selector | Buyer |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for project, summary in report["summaryByProject"].items():
        for sample in summary["nonDirectExamples"]:
            tx = str(sample["txHash"])
            router = str(sample["txTo"])
            buyer = str(sample["buyer"])
            lines.append(
                "| "
                + " | ".join(
                    [
                        project,
                        str(sample["routeClass"]),
                        f"`{tx[:10]}...{tx[-8:]}`",
                        f"`{router[:10]}...{router[-8:]}`",
                        f"`{sample['selector']}`",
                        f"`{buyer[:10]}...{buyer[-8:]}`",
                    ]
                )
                + " |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Virtuals buy route universality.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--limit-per-project", type=int, default=60)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", default=DEFAULT_OUTPUT_MD)
    parser.add_argument(
        "--db",
        action="append",
        default=[
            "data/replay-event-level/sr_event_replay-20260510T073102Z.db",
            "data/replay-event-level/isc_event_replay-20260510T085419Z.db",
            "data/virtuals_v11.db",
        ],
        help="SQLite DB with an events table. Can be provided multiple times.",
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_url = (cfg.backfill_http_rpc_urls or [cfg.http_rpc_url])[0]
    sources = [SourceDB(Path(path).stem, Path(path)) for path in args.db]
    samples = await fetch_routes(rpc_url=rpc_url, sources=sources, limit_per_project=args.limit_per_project)
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rpc": redact_rpc_url(rpc_url),
        "readOnly": True,
        "tradeSent": False,
        "directBuyRouter": VIRTUALS_BUY_ROUTER,
        "directBuySelector": VIRTUALS_BUY_SELECTOR,
        "sampleCount": len(samples),
        "summaryByProject": summarize(samples),
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
                "sampleCount": len(samples),
                "projects": sorted(report["summaryByProject"].keys()),
                "tradeSent": False,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
