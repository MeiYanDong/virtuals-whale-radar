#!/usr/bin/env python3
"""Collect historical Virtuals buy calldata fixtures.

This script is read-only. It fetches public transaction/receipt data through
the configured RPC and writes a redacted local research report. It does not
sign, simulate, or broadcast transactions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
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

from launch_execution_pipeline import (  # noqa: E402
    VIRTUALS_BUY_ROUTER,
    VIRTUALS_BUY_SELECTOR,
    decode_virtuals_buy_calldata,
)
from virtuals_bot import (  # noqa: E402
    RPCClient,
    TRANSFER_TOPIC0,
    decode_topic_address,
    load_config,
    parse_hex_int,
    redact_rpc_url,
)


TEAM_SEED_ADDRESS = "0x81f7ca6af86d1ca6335e44a2c28bc88807491415"
DEFAULT_OUTPUT_JSON = "data/backtests/virtuals-buy-calldata-research-20260510.json"
DEFAULT_OUTPUT_MD = "docs/phases/phase-053-virtuals-buy-calldata-research-2026-05-10.md"


@dataclass(frozen=True)
class ReplaySource:
    project: str
    sqlite_path: Path


def d(value: Any) -> Decimal:
    return Decimal(str(value or "0"))


def plain_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def wei_to_v(wei: int) -> str:
    return plain_decimal(Decimal(wei) / Decimal("1000000000000000000"))


def sample_rows(path: Path, *, limit: int) -> list[dict[str, Any]]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        first_rows = conn.execute(
            """
            select project, tx_hash, block_number, block_timestamp, buyer, token_addr,
                   spent_v_est, tax_v, cost_v
            from events
            where cast(spent_v_est as real) > 0
              and cast(tax_v as real) > 0
              and lower(buyer) != ?
            order by block_number, id
            limit ?
            """,
            (TEAM_SEED_ADDRESS, limit),
        ).fetchall()
        large_rows = conn.execute(
            """
            select project, tx_hash, block_number, block_timestamp, buyer, token_addr,
                   spent_v_est, tax_v, cost_v
            from events
            where cast(spent_v_est as real) > 0
              and cast(tax_v as real) > 0
              and lower(buyer) != ?
            order by cast(spent_v_est as real) desc, block_number
            limit ?
            """,
            (TEAM_SEED_ADDRESS, max(2, limit // 3)),
        ).fetchall()
    finally:
        conn.close()

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in [*first_rows, *large_rows]:
        tx_hash = str(row["tx_hash"]).lower()
        if tx_hash in seen:
            continue
        seen.add(tx_hash)
        rows.append(dict(row))
    return rows


def transfer_summary(receipt: dict[str, Any], *, virtual_token_addr: str, token_addr: str) -> dict[str, Any]:
    virtual = virtual_token_addr.lower()
    target = token_addr.lower()
    virtual_transfers: list[dict[str, str]] = []
    target_transfers: list[dict[str, str]] = []
    for log in receipt.get("logs") or []:
        topics = log.get("topics") or []
        if not topics or str(topics[0]).lower() != TRANSFER_TOPIC0 or len(topics) < 3:
            continue
        contract = str(log.get("address") or "").lower()
        row = {
            "from": decode_topic_address(str(topics[1])),
            "to": decode_topic_address(str(topics[2])),
            "amountRaw": str(parse_hex_int(str(log.get("data") or "0x0"))),
        }
        if contract == virtual:
            row["amountV"] = wei_to_v(int(row["amountRaw"]))
            virtual_transfers.append(row)
        elif contract == target:
            target_transfers.append(row)
    return {
        "virtualTransferCount": len(virtual_transfers),
        "targetTokenTransferCount": len(target_transfers),
        "virtualTransfers": virtual_transfers[:8],
        "targetTokenTransfers": target_transfers[:8],
    }


async def fetch_samples(
    *,
    rpc_url: str,
    virtual_token_addr: str,
    sources: list[ReplaySource],
    limit_per_project: int,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    async with RPCClient(rpc_url, max_retries=4, timeout_sec=20) as rpc:
        for source in sources:
            for row in sample_rows(source.sqlite_path, limit=limit_per_project):
                tx_hash = str(row["tx_hash"])
                tx = await rpc.call("eth_getTransactionByHash", [tx_hash])
                receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
                if not tx or not receipt:
                    samples.append({"project": source.project, "txHash": tx_hash, "error": "missing_rpc_result"})
                    continue

                calldata = str(tx.get("input") or tx.get("data") or "0x").lower()
                tx_to = str(tx.get("to") or "").lower()
                selector = calldata[:10] if len(calldata) >= 10 else calldata
                try:
                    decoded = decode_virtuals_buy_calldata(calldata)
                except ValueError as exc:
                    samples.append(
                        {
                            "project": source.project,
                            "txHash": tx_hash,
                            "blockNumber": int(row["block_number"]),
                            "blockTimestamp": int(row["block_timestamp"]),
                            "buyer": str(row["buyer"]).lower(),
                            "replaySpentV": plain_decimal(d(row["spent_v_est"])),
                            "replayTaxV": plain_decimal(d(row["tax_v"])),
                            "txFrom": str(tx.get("from") or "").lower(),
                            "txTo": tx_to,
                            "txValueWei": str(parse_hex_int(tx.get("value"))),
                            "gasLimit": str(parse_hex_int(tx.get("gas"))),
                            "status": str(receipt.get("status")),
                            "logCount": len(receipt.get("logs") or []),
                            "selector": selector,
                            "inputBytes": max(0, (len(calldata) - 2) // 2),
                            "decodedBuy": False,
                            "routeType": "alternate_or_aggregator_route",
                            "decodeError": str(exc),
                            "transferSummary": transfer_summary(
                                receipt,
                                virtual_token_addr=virtual_token_addr,
                                token_addr=str(row["token_addr"]),
                            ),
                        }
                    )
                    continue
                replay_amount = d(row["spent_v_est"])
                decoded_amount = Decimal(decoded["amountInWei"]) / Decimal("1000000000000000000")
                samples.append(
                    {
                        "project": source.project,
                        "txHash": tx_hash,
                        "blockNumber": int(row["block_number"]),
                        "blockTimestamp": int(row["block_timestamp"]),
                        "buyer": str(row["buyer"]).lower(),
                        "replaySpentV": plain_decimal(replay_amount),
                        "replayTaxV": plain_decimal(d(row["tax_v"])),
                        "txFrom": str(tx.get("from") or "").lower(),
                        "txTo": tx_to,
                        "txValueWei": str(parse_hex_int(tx.get("value"))),
                        "gasLimit": str(parse_hex_int(tx.get("gas"))),
                        "status": str(receipt.get("status")),
                        "logCount": len(receipt.get("logs") or []),
                        "decodedBuy": True,
                        "routeType": "direct_virtuals_buy",
                        "selector": decoded["selector"],
                        "tokenAddress": decoded["tokenAddress"],
                        "amountInWei": decoded["amountInWei"],
                        "amountInV": plain_decimal(decoded_amount),
                        "amountOutMinWei": decoded["amountOutMinWei"],
                        "deadline": decoded["deadline"],
                        "canonicalBytes": decoded["canonicalBytes"],
                        "tailBytes": decoded["tailBytes"],
                        "exactCanonical": decoded["exactCanonical"],
                        "canonicalPrefix": decoded["canonicalPrefix"],
                        "amountMatchesReplay": decoded_amount == replay_amount,
                        "tokenMatchesReplay": decoded["tokenAddress"].lower() == str(row["token_addr"]).lower(),
                        "toMatchesVirtualsRouter": str(tx.get("to") or "").lower() == VIRTUALS_BUY_ROUTER,
                        "selectorMatchesVirtualsBuy": decoded["selector"] == VIRTUALS_BUY_SELECTOR,
                        "transferSummary": transfer_summary(
                            receipt,
                            virtual_token_addr=virtual_token_addr,
                            token_addr=decoded["tokenAddress"],
                        ),
                    }
                )
    return samples


def selector_counts(samples: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        value = "" if sample.get(field) is None else str(sample.get(field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def write_markdown(report: dict[str, Any], path: Path) -> None:
    direct_samples = [sample for sample in report["samples"] if sample.get("decodedBuy")]
    alternate_samples = [sample for sample in report["samples"] if not sample.get("decodedBuy")]
    lines = [
        "# Phase 053 - Virtuals Buy Calldata Research",
        "",
        "## 结论",
        "",
        "- 历史成功买入交易使用固定路由 `0x1a540088125d00dd3990f9da45ca0859af4d3b01`。",
        "- selector 为 `0x706910ff`，BaseScan 将其解码为 `buy(uint256 amountIn_, address tokenAddress_, uint256 amountOutMin_, uint256 deadline_)`。",
        "- `value` 为 `0`，VIRTUAL 通过 ERC-20 transfer/allowance 进入路由，不是原生 ETH value。",
        "- 标准 calldata 长度为 132 bytes；部分交易会在 4 个 ABI 参数后追加 29 bytes 尾部标签，链上执行成功，合约实际使用前 4 个参数。",
        "- OrderBuilder 当前只允许生成标准 4 参数 canonical calldata；尾部标签不参与构造。",
        "- 本阶段仍然不签名、不广播。",
        "- BaseScan 参考样本：https://basescan.org/tx/0x7bdf8e9d0e3359eb20b79b92ce8b9659357dfef3dda5f8eaf74cb77370fd357f",
        "",
        "## 样本摘要",
        "",
        f"- generatedAt: `{report['generatedAt']}`",
        f"- rpc: `{report['rpc']}`",
        f"- samples: `{len(report['samples'])}`",
        f"- directBuySamples: `{len(direct_samples)}`",
        f"- alternateRouteSamples: `{len(alternate_samples)}`",
        f"- selectorCounts: `{json.dumps(report['selectorCounts'], ensure_ascii=False)}`",
        f"- routerCounts: `{json.dumps(report['routerCounts'], ensure_ascii=False)}`",
        f"- tailByteCounts: `{json.dumps(report['tailByteCounts'], ensure_ascii=False)}`",
        "",
        "## Direct Buy 样本表",
        "",
        "| Project | Tx | Amount V | Token | Min Out | Deadline | Canonical | Tail | Status |",
        "| --- | --- | ---: | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for sample in direct_samples:
        tx = str(sample["txHash"])
        short_tx = f"{tx[:10]}...{tx[-8:]}"
        token = str(sample["tokenAddress"])
        short_token = f"{token[:10]}...{token[-8:]}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(sample["project"]),
                    f"`{short_tx}`",
                    str(sample["amountInV"]),
                    f"`{short_token}`",
                    str(sample["amountOutMinWei"]),
                    str(sample["deadline"]),
                    "yes" if sample["exactCanonical"] else "prefix",
                    str(sample["tailBytes"]),
                    str(sample["status"]),
                ]
            )
            + " |"
        )
    if alternate_samples:
        lines.extend(
            [
                "",
                "## Alternate Route 样本",
                "",
                "这些交易也触发了目标池买入事件，但交易入口不是 Virtuals 直接 buy 路由。它们更像聚合器/钱包路由成交，不作为第一版 OrderBuilder 的构造目标。",
                "",
                "| Project | Tx | Router | Selector | Input Bytes | Amount V | Status |",
                "| --- | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for sample in alternate_samples:
            tx = str(sample["txHash"])
            short_tx = f"{tx[:10]}...{tx[-8:]}"
            router = str(sample.get("txTo") or "")
            short_router = f"{router[:10]}...{router[-8:]}" if router else "-"
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(sample["project"]),
                        f"`{short_tx}`",
                        f"`{short_router}`",
                        f"`{sample.get('selector')}`",
                        str(sample.get("inputBytes")),
                        str(sample.get("replaySpentV")),
                        str(sample.get("status")),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## OrderBuilder 边界",
            "",
            "- 已完成：低层 calldata encoder 可以重建标准 4 参数买入 calldata，并对历史 canonical 样本 exact parity。",
            "- 已完成：带尾部标签的历史交易可以做到 canonical prefix parity，尾部不进入 OrderBuilder。",
            "- 未完成：把 `BuyIntent` 绑定到具体 token、slippage、deadline、allowance、nonce、gas。",
            "- 未完成：`eth_call` / allowance / balance / gas estimate / receipt verifier。",
            "- 未完成：burner wallet 签名和手动 canary 广播。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research Virtuals buy calldata from replay DB samples.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--sr-db", default="data/replay-event-level/sr_event_replay-20260510T073102Z.db")
    parser.add_argument("--isc-db", default="data/replay-event-level/isc_event_replay-20260510T085419Z.db")
    parser.add_argument("--limit-per-project", type=int, default=8)
    parser.add_argument("--output-json", default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_url = (cfg.backfill_http_rpc_urls or [cfg.http_rpc_url])[0]
    sources = [
        ReplaySource("SR_EVENT_REPLAY", Path(args.sr_db)),
        ReplaySource("ISC_EVENT_REPLAY", Path(args.isc_db)),
    ]
    samples = await fetch_samples(
        rpc_url=rpc_url,
        virtual_token_addr=cfg.virtual_token_addr,
        sources=sources,
        limit_per_project=args.limit_per_project,
    )
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rpc": redact_rpc_url(rpc_url),
        "virtualsBuyRouter": VIRTUALS_BUY_ROUTER,
        "virtualsBuySelector": VIRTUALS_BUY_SELECTOR,
        "functionSignature": "buy(uint256 amountIn_, address tokenAddress_, uint256 amountOutMin_, uint256 deadline_)",
        "readOnly": True,
        "tradeSent": False,
        "samples": samples,
        "selectorCounts": selector_counts(samples, "selector"),
        "routerCounts": selector_counts(samples, "txTo"),
        "tailByteCounts": selector_counts(
            [
                {**sample, "tailBytes": sample.get("tailBytes") if sample.get("decodedBuy") else "unsupported"}
                for sample in samples
            ],
            "tailBytes",
        ),
        "directBuySamples": sum(1 for sample in samples if sample.get("decodedBuy")),
        "alternateRouteSamples": sum(1 for sample in samples if not sample.get("decodedBuy")),
        "allDirectSamplesMatchRouterSelectorTokenAmount": all(
            sample.get("toMatchesVirtualsRouter")
            and sample.get("selectorMatchesVirtualsBuy")
            and sample.get("tokenMatchesReplay")
            and sample.get("amountMatchesReplay")
            for sample in samples
            if sample.get("decodedBuy")
        ),
    }
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report, Path(args.output_md))
    print(
        json.dumps(
            {
                "outputJson": str(output_json),
                "outputMd": str(args.output_md),
                "samples": len(samples),
                "selectorCounts": report["selectorCounts"],
                "routerCounts": report["routerCounts"],
                "tailByteCounts": report["tailByteCounts"],
                "directBuySamples": report["directBuySamples"],
                "alternateRouteSamples": report["alternateRouteSamples"],
                "allDirectCoreFieldsMatch": report["allDirectSamplesMatchRouterSelectorTokenAmount"],
                "tradeSent": False,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
