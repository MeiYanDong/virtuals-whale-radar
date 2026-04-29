#!/usr/bin/env python3
"""Replay project transactions with separate logs and receipt RPC paths."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from virtuals_bot import (  # noqa: E402
    DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS,
    RPCClient,
    VirtualsBot,
    load_config,
)


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def read_tx_hashes(path: str | None) -> list[str]:
    if not path:
        return []
    values: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        item = line.strip().split()[0] if line.strip() else ""
        if item:
            values.append(item.lower())
    return dedupe(values)


def project_event_count(db_path: str, project: str, tx_hash: str | None = None) -> int:
    conn = sqlite3.connect(db_path)
    try:
        if tx_hash:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE project = ? AND tx_hash = ?",
                (project, tx_hash.lower()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE project = ?",
                (project,),
            ).fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def clear_project_rows(db_path: str, project: str) -> None:
    tables = [
        "events",
        "minute_agg",
        "minute_buyers",
        "leaderboard",
        "wallet_positions",
        "project_stats",
        "scanned_backfill_txs",
    ]
    conn = sqlite3.connect(db_path)
    try:
        for table in tables:
            conn.execute(f"DELETE FROM {table} WHERE project = ?", (project,))
        conn.commit()
    finally:
        conn.close()


async def fetch_logs_adaptive(
    bot: VirtualsBot,
    launch: Any,
    logs_rpc: RPCClient,
    from_block: int,
    to_block: int,
    min_blocks: int,
    splits: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> set[str]:
    try:
        return await bot._fetch_backfill_txhashes_via_logs(  # noqa: SLF001
            from_block,
            to_block,
            [launch],
            rpc=logs_rpc,
        )
    except Exception as exc:
        if to_block - from_block + 1 <= min_blocks:
            errors.append(
                {
                    "from_block": from_block,
                    "to_block": to_block,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return set()
        mid = (from_block + to_block) // 2
        splits.append(
            {
                "from_block": from_block,
                "to_block": to_block,
                "error": f"{type(exc).__name__}: {exc}",
                "split": [[from_block, mid], [mid + 1, to_block]],
            }
        )
        left = await fetch_logs_adaptive(
            bot, launch, logs_rpc, from_block, mid, min_blocks, splits, errors
        )
        right = await fetch_logs_adaptive(
            bot, launch, logs_rpc, mid + 1, to_block, min_blocks, splits, errors
        )
        return set(left) | set(right)


async def process_tx_with_receipt_pool(
    bot: VirtualsBot,
    launch: Any,
    project: str,
    tx_hash: str,
    receipt_clients: list[tuple[str, RPCClient]],
    block_rpc: RPCClient,
    db_path: str,
) -> dict[str, Any]:
    before = project_event_count(db_path, project, tx_hash)
    attempts: list[dict[str, Any]] = []
    for label, client in receipt_clients:
        try:
            receipt = await client.get_receipt(tx_hash)
            if not receipt:
                attempts.append({"label": label, "receipt": False, "inserted": 0})
                continue
            if receipt.get("status") and int(receipt["status"], 16) == 0:
                attempts.append({"label": label, "receipt": True, "status": "failed", "inserted": 0})
                break
            block_number = int(receipt["blockNumber"], 16)
            related = bot.is_related_to_launch(receipt.get("logs", []), launch)
            if not related:
                attempts.append(
                    {
                        "label": label,
                        "receipt": True,
                        "block_number": block_number,
                        "related": False,
                        "inserted": 0,
                    }
                )
                break
            timestamp = await bot.get_block_timestamp(block_number, rpc=block_rpc)
            virtual_price_usd, is_price_stale = await bot.price_service.get_price()
            events = await bot.parse_receipt_for_launch(
                launch=launch,
                receipt=receipt,
                timestamp=timestamp,
                virtual_price_usd=virtual_price_usd,
                is_price_stale=is_price_stale,
                rpc=client,
            )
            if events:
                await bot.emit_parsed_events(events, block_number)
                await bot.flush_once(force=True)
            after = project_event_count(db_path, project, tx_hash)
            inserted = max(0, after - before)
            attempts.append(
                {
                    "label": label,
                    "receipt": True,
                    "block_number": block_number,
                    "related": True,
                    "parsed_events": len(events),
                    "inserted": inserted,
                }
            )
            if inserted > 0 or events:
                break
        except Exception as exc:
            attempts.append(
                {
                    "label": label,
                    "error": f"{type(exc).__name__}: {exc}",
                    "inserted": 0,
                }
            )
    return {
        "tx_hash": tx_hash,
        "before": before,
        "after": project_event_count(db_path, project, tx_hash),
        "attempts": attempts,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    logs_rpc_url = args.logs_rpc_url or (
        cfg.backfill_http_rpc_urls
        or cfg.backfill_public_http_rpc_urls
        or DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS
    )[0]
    block_rpc_url = args.block_rpc_url or logs_rpc_url
    receipt_urls = dedupe(
        args.receipt_rpc_url
        or [
            *cfg.backfill_http_rpc_urls,
            cfg.backfill_http_rpc_url or "",
            cfg.http_rpc_url,
            logs_rpc_url,
            *cfg.backfill_public_http_rpc_urls,
            *DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS,
        ]
    )

    sqlite_path = args.sqlite_path or cfg.sqlite_path
    event_bus_path = args.event_bus_sqlite_path or cfg.event_bus_sqlite_path
    jsonl_path = args.jsonl_path or str(Path(sqlite_path).with_name("events.replay.jsonl"))
    cfg = replace(
        cfg,
        sqlite_path=sqlite_path,
        event_bus_sqlite_path=event_bus_path,
        jsonl_path=jsonl_path,
        api_port=args.api_port,
    )
    if args.clear_project:
        clear_project_rows(sqlite_path, args.project)

    bot = VirtualsBot(cfg, role="all")
    clients: list[tuple[str, RPCClient]] = []
    logs_client = RPCClient(logs_rpc_url, max_retries=args.max_retries, timeout_sec=args.timeout_sec)
    clients.append(("logs", logs_client))
    block_client = logs_client
    if block_rpc_url != logs_rpc_url:
        block_client = RPCClient(block_rpc_url, max_retries=args.max_retries, timeout_sec=args.timeout_sec)
        clients.append(("block", block_client))
    for idx, url in enumerate(receipt_urls, start=1):
        client = bot.rpc_clients_by_url.get(url) or RPCClient(
            url, max_retries=args.max_retries, timeout_sec=args.timeout_sec
        )
        client.timeout = aiohttp.ClientTimeout(total=args.timeout_sec)
        clients.append((f"receipt-{idx}", client))

    opened: set[int] = set()
    for _, client in clients:
        if id(client) not in opened:
            opened.add(id(client))
            await client.__aenter__()

    started_at = int(time.time())
    try:
        managed = bot._find_managed_project_by_name(args.project)  # noqa: SLF001
        launch = bot.build_launch_config_from_managed_project(managed)
        if not launch:
            raise RuntimeError(f"cannot build launch config for project: {args.project}")

        tx_hashes = read_tx_hashes(args.tx_file)
        discovery: dict[str, Any] | None = None
        if args.from_block and args.to_block:
            discovered: set[str] = set()
            splits: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            current = int(args.from_block)
            chunk_index = 0
            chunks: list[dict[str, Any]] = []
            while current <= int(args.to_block):
                end_block = min(int(args.to_block), current + args.log_chunk_blocks - 1)
                chunk_index += 1
                found = await fetch_logs_adaptive(
                    bot,
                    launch,
                    logs_client,
                    current,
                    end_block,
                    args.min_log_chunk_blocks,
                    splits,
                    errors,
                )
                discovered.update(found)
                chunks.append(
                    {
                        "index": chunk_index,
                        "from_block": current,
                        "to_block": end_block,
                        "tx_count": len(found),
                    }
                )
                current = end_block + 1
            tx_hashes = dedupe([*tx_hashes, *sorted(discovered)])
            discovery = {
                "from_block": args.from_block,
                "to_block": args.to_block,
                "chunk_blocks": args.log_chunk_blocks,
                "min_chunk_blocks": args.min_log_chunk_blocks,
                "discovered_tx_count": len(discovered),
                "splits": splits,
                "errors": errors,
                "chunks": chunks,
            }

        before_count = project_event_count(sqlite_path, args.project)
        receipt_clients = [(label, client) for label, client in clients if label.startswith("receipt-")]
        results: list[dict[str, Any] | None] = [None] * len(tx_hashes)
        progress = 0
        progress_lock = asyncio.Lock()
        concurrency = max(1, int(args.receipt_concurrency))
        semaphore = asyncio.Semaphore(concurrency)

        async def process_one(idx: int, tx_hash: str) -> None:
            nonlocal progress
            async with semaphore:
                result = await process_tx_with_receipt_pool(
                    bot,
                    launch,
                    args.project,
                    tx_hash,
                    receipt_clients,
                    block_client,
                    sqlite_path,
                )
                results[idx - 1] = result
                if args.mark_scanned:
                    bot.storage.mark_backfill_scanned_txs(args.project, [tx_hash])

                async with progress_lock:
                    progress += 1
                    if args.progress_every and progress % args.progress_every == 0:
                        print(
                            json.dumps(
                                {
                                    "processed": progress,
                                    "total": len(tx_hashes),
                                    "inserted_events": project_event_count(sqlite_path, args.project),
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )

        await asyncio.gather(
            *(process_one(idx, tx_hash) for idx, tx_hash in enumerate(tx_hashes, start=1))
        )
        final_results = [item for item in results if item is not None]
        await bot.flush_once(force=True)
        after_count = project_event_count(sqlite_path, args.project)
        summary = {
            "project": args.project,
            "started_at": started_at,
            "finished_at": int(time.time()),
            "duration_sec": int(time.time()) - started_at,
            "sqlite_path": sqlite_path,
            "event_bus_sqlite_path": event_bus_path,
            "logs_rpc_label": "logs",
            "block_rpc_label": "logs" if block_client is logs_client else "block",
            "receipt_rpc_labels": [label for label, _ in receipt_clients],
            "input_tx_count": len(tx_hashes),
            "before_events": before_count,
            "after_events": after_count,
            "inserted_delta": after_count - before_count,
            "receipt_concurrency": concurrency,
            "tx_inserted_count": sum(1 for item in final_results if item["after"] > item["before"]),
            "tx_not_inserted_count": sum(1 for item in final_results if item["after"] <= item["before"]),
            "discovery": discovery,
            "results": final_results if args.include_results else None,
        }
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    finally:
        if bot.jsonl_file:
            bot.jsonl_file.close()
        bot.storage.close()
        bot.event_bus.close()
        closed: set[int] = set()
        for _, client in clients:
            if id(client) not in closed:
                closed.add(id(client))
                await client.__aexit__(None, None, None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay project transactions with separate logs and receipt RPCs."
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True)
    parser.add_argument("--tx-file")
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    parser.add_argument("--logs-rpc-url")
    parser.add_argument("--block-rpc-url")
    parser.add_argument("--receipt-rpc-url", action="append")
    parser.add_argument("--sqlite-path")
    parser.add_argument("--event-bus-sqlite-path")
    parser.add_argument("--jsonl-path")
    parser.add_argument("--output")
    parser.add_argument("--api-port", type=int, default=18080)
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--log-chunk-blocks", type=int, default=1000)
    parser.add_argument("--min-log-chunk-blocks", type=int, default=10)
    parser.add_argument("--receipt-concurrency", type=int, default=16)
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--clear-project", action="store_true")
    parser.add_argument("--mark-scanned", action="store_true")
    parser.add_argument("--include-results", action="store_true")
    args = parser.parse_args()
    if not args.tx_file and not (args.from_block and args.to_block):
        parser.error("provide --tx-file or both --from-block and --to-block")
    if bool(args.from_block) ^ bool(args.to_block):
        parser.error("--from-block and --to-block must be provided together")
    return args


def main() -> None:
    summary = asyncio.run(run(parse_args()))
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "results"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
