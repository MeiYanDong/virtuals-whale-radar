#!/usr/bin/env python3
"""Audit whether a launch window has been discovered, scanned, and parsed."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from virtuals_bot import (  # noqa: E402
    DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS,
    LaunchConfig,
    RPCClient,
    TRANSFER_TOPIC0,
    load_config,
    normalize_address,
    normalize_optional_address,
    topic_address,
)


def one_or_none(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    return int(row[0] or 0)


def text_set(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> set[str]:
    rows = conn.execute(sql, params).fetchall()
    return {str(row[0]).strip().lower() for row in rows if row[0]}


def managed_project_row(conn: sqlite3.Connection, project: str) -> dict[str, Any] | None:
    return one_or_none(
        conn,
        """
        SELECT *
        FROM managed_projects
        WHERE lower(name) = lower(?)
        """,
        (project,),
    )


def launch_config_row(conn: sqlite3.Connection, project: str) -> dict[str, Any] | None:
    return one_or_none(
        conn,
        """
        SELECT *
        FROM launch_configs
        WHERE lower(name) = lower(?)
        """,
        (project,),
    )


def build_launch_config(
    project: str,
    managed: dict[str, Any] | None,
    launch_row: dict[str, Any] | None,
    cfg: Any,
) -> LaunchConfig | None:
    if managed and managed.get("internal_pool_addr"):
        template = cfg.launch_configs[0]
        return LaunchConfig(
            name=str(managed.get("name") or project).strip(),
            internal_pool_addr=normalize_address(str(managed["internal_pool_addr"])),
            fee_addr=template.fee_addr,
            tax_addr=template.tax_addr,
            token_addr=normalize_optional_address(managed.get("token_addr")),
            token_total_supply=template.token_total_supply,
            fee_rate=template.fee_rate,
        )

    if launch_row:
        return LaunchConfig(
            name=str(launch_row.get("name") or project).strip(),
            internal_pool_addr=normalize_address(str(launch_row["internal_pool_addr"])),
            fee_addr=normalize_address(str(launch_row["fee_addr"])),
            tax_addr=normalize_address(str(launch_row["tax_addr"])),
            token_addr=normalize_optional_address(launch_row.get("token_addr")),
            token_total_supply=cfg.launch_configs[0].token_total_supply,
            fee_rate=cfg.launch_configs[0].fee_rate,
        )

    return None


def db_profile(conn: sqlite3.Connection, project: str) -> dict[str, Any]:
    event_row = conn.execute(
        """
        SELECT
            COUNT(1) AS event_count,
            COUNT(DISTINCT tx_hash) AS event_tx_count,
            COUNT(DISTINCT buyer) AS buyer_count,
            MIN(block_number) AS first_block,
            MAX(block_number) AS last_block,
            MIN(block_timestamp) AS first_event_ts,
            MAX(block_timestamp) AS last_event_ts
        FROM events
        WHERE project = ?
        """,
        (project,),
    ).fetchone()
    event = dict(event_row) if event_row else {}
    return {
        "events": {k: int(v or 0) for k, v in event.items()},
        "minuteAggRows": scalar(conn, "SELECT COUNT(1) FROM minute_agg WHERE project = ?", (project,)),
        "leaderboardRows": scalar(conn, "SELECT COUNT(1) FROM leaderboard WHERE project = ?", (project,)),
        "walletPositionRows": scalar(
            conn, "SELECT COUNT(1) FROM wallet_positions WHERE project = ?", (project,)
        ),
        "projectStatsRows": scalar(
            conn, "SELECT COUNT(1) FROM project_stats WHERE project = ?", (project,)
        ),
        "scannedBackfillTxRows": scalar(
            conn, "SELECT COUNT(1) FROM scanned_backfill_txs WHERE project = ?", (project,)
        ),
    }


async def block_timestamp(
    client: RPCClient,
    block_number: int,
    cache: dict[int, int],
) -> int:
    if block_number in cache:
        return cache[block_number]
    block = await client.get_block_by_number(block_number)
    if not block:
        raise RuntimeError(f"block not found: {block_number}")
    ts = int(block["timestamp"], 16)
    cache[block_number] = ts
    return ts


async def find_block_gte_timestamp(client: RPCClient, target_ts: int, cache: dict[int, int]) -> int:
    latest = await client.get_latest_block_number()
    latest_ts = await block_timestamp(client, latest, cache)
    if target_ts >= latest_ts:
        return latest

    low = 0
    high = latest
    while low < high:
        mid = (low + high) // 2
        mid_ts = await block_timestamp(client, mid, cache)
        if mid_ts < target_ts:
            low = mid + 1
        else:
            high = mid
    return low


async def find_block_lte_timestamp(client: RPCClient, target_ts: int, cache: dict[int, int]) -> int:
    latest = await client.get_latest_block_number()
    first_ts = await block_timestamp(client, 0, cache)
    if target_ts <= first_ts:
        return 0
    latest_ts = await block_timestamp(client, latest, cache)
    if target_ts >= latest_ts:
        return latest

    low = 0
    high = latest
    while low < high:
        mid = (low + high + 1) // 2
        mid_ts = await block_timestamp(client, mid, cache)
        if mid_ts <= target_ts:
            low = mid
        else:
            high = mid - 1
    return low


async def fetch_launch_logs_once(
    *,
    client: RPCClient,
    virtual_token_addr: str,
    launch: LaunchConfig,
    from_block: int,
    to_block: int,
) -> set[str]:
    txs: set[str] = set()
    internal = topic_address(launch.internal_pool_addr)
    fee = topic_address(launch.fee_addr)
    tax = topic_address(launch.tax_addr)

    filters: list[dict[str, Any]] = [
        {
            "address": virtual_token_addr,
            "topics": [TRANSFER_TOPIC0, None, [internal, fee, tax]],
        },
        {
            "address": virtual_token_addr,
            "topics": [TRANSFER_TOPIC0, internal],
        },
    ]
    if launch.token_addr:
        filters.extend(
            [
                {
                    "address": launch.token_addr,
                    "topics": [TRANSFER_TOPIC0, internal],
                },
                {
                    "address": launch.token_addr,
                    "topics": [TRANSFER_TOPIC0, None, internal],
                },
            ]
        )

    for item in filters:
        logs = await client.get_logs(
            from_block=from_block,
            to_block=to_block,
            address=item["address"],
            topics=item["topics"],
        )
        txs.update(str(x["transactionHash"]).lower() for x in logs if x.get("transactionHash"))
    return txs


async def fetch_logs_adaptive(
    *,
    client: RPCClient,
    virtual_token_addr: str,
    launch: LaunchConfig,
    from_block: int,
    to_block: int,
    min_blocks: int,
    splits: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> set[str]:
    try:
        return await fetch_launch_logs_once(
            client=client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=from_block,
            to_block=to_block,
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
            client=client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=from_block,
            to_block=mid,
            min_blocks=min_blocks,
            splits=splits,
            errors=errors,
        )
        right = await fetch_logs_adaptive(
            client=client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=mid + 1,
            to_block=to_block,
            min_blocks=min_blocks,
            splits=splits,
            errors=errors,
        )
        return left | right


async def discover_candidate_txs(
    *,
    cfg: Any,
    launch: LaunchConfig,
    logs_rpc_url: str,
    block_rpc_url: str,
    from_block: int | None,
    to_block: int | None,
    start_ts: int | None,
    end_ts: int | None,
    log_chunk_blocks: int,
    min_log_chunk_blocks: int,
    timeout_sec: int,
    max_retries: int,
) -> dict[str, Any]:
    logs_client = RPCClient(logs_rpc_url, max_retries=max_retries, timeout_sec=timeout_sec)
    block_client = logs_client if block_rpc_url == logs_rpc_url else RPCClient(
        block_rpc_url, max_retries=max_retries, timeout_sec=timeout_sec
    )
    await logs_client.__aenter__()
    if block_client is not logs_client:
        await block_client.__aenter__()
    try:
        cache: dict[int, int] = {}
        if from_block is None or to_block is None:
            if start_ts is None or end_ts is None:
                raise ValueError("discovery needs block range or project start/end timestamps")
            from_block = await find_block_gte_timestamp(block_client, int(start_ts), cache)
            to_block = await find_block_lte_timestamp(block_client, int(end_ts), cache)
        if to_block < from_block:
            raise ValueError(f"invalid block range: {from_block} -> {to_block}")

        discovered: set[str] = set()
        splits: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        chunks: list[dict[str, Any]] = []
        current = int(from_block)
        chunk_index = 0
        while current <= int(to_block):
            end_block = min(int(to_block), current + max(1, int(log_chunk_blocks)) - 1)
            chunk_index += 1
            found = await fetch_logs_adaptive(
                client=logs_client,
                virtual_token_addr=cfg.virtual_token_addr,
                launch=launch,
                from_block=current,
                to_block=end_block,
                min_blocks=max(1, int(min_log_chunk_blocks)),
                splits=splits,
                errors=errors,
            )
            discovered.update(found)
            chunks.append(
                {
                    "index": chunk_index,
                    "fromBlock": current,
                    "toBlock": end_block,
                    "candidateTxCount": len(found),
                }
            )
            current = end_block + 1

        return {
            "enabled": True,
            "fromBlock": from_block,
            "toBlock": to_block,
            "candidateTxCount": len(discovered),
            "candidateTxs": sorted(discovered),
            "chunkBlocks": log_chunk_blocks,
            "minChunkBlocks": min_log_chunk_blocks,
            "chunks": chunks,
            "splits": splits,
            "errors": errors,
        }
    finally:
        await logs_client.__aexit__(None, None, None)
        if block_client is not logs_client:
            await block_client.__aexit__(None, None, None)


def expected_checks(args: argparse.Namespace, profile: dict[str, Any], discovery: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expectations = [
        ("event_count", args.expected_events, profile["events"]["event_count"]),
        ("event_tx_count", args.expected_event_txs, profile["events"]["event_tx_count"]),
        ("candidate_tx_count", args.expected_candidate_txs, discovery.get("candidateTxCount")),
    ]
    for name, expected, actual in expectations:
        if expected is None or actual is None:
            continue
        checks.append(
            {
                "name": name,
                "expected": int(expected),
                "actual": int(actual),
                "ok": int(expected) == int(actual),
            }
        )
    return checks


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    sqlite_path = args.sqlite_path or cfg.sqlite_path
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        managed = managed_project_row(conn, args.project)
        launch_row = launch_config_row(conn, args.project)
        launch = build_launch_config(args.project, managed, launch_row, cfg)
        profile = db_profile(conn, args.project)
        event_txs = text_set(
            conn,
            "SELECT DISTINCT tx_hash FROM events WHERE project = ?",
            (args.project,),
        )
        scanned_txs = text_set(
            conn,
            "SELECT tx_hash FROM scanned_backfill_txs WHERE project = ?",
            (args.project,),
        )
        dead_txs = text_set(conn, "SELECT DISTINCT tx_hash FROM dead_letters", ())

        start_ts = int(managed["start_at"]) if managed and managed.get("start_at") else None
        end_ts = (
            int(managed["resolved_end_at"])
            if managed and managed.get("resolved_end_at")
            else None
        )
        discovery: dict[str, Any] = {"enabled": False}
        blockers: list[str] = []
        notes: list[str] = []
        if launch is None:
            blockers.append("project has no usable launch config/internal_pool_addr")
        elif not args.skip_discovery:
            logs_rpc_url = args.logs_rpc_url or (
                cfg.backfill_http_rpc_urls
                or cfg.backfill_public_http_rpc_urls
                or DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS
            )[0]
            block_rpc_url = args.block_rpc_url or logs_rpc_url
            discovery = await discover_candidate_txs(
                cfg=cfg,
                launch=launch,
                logs_rpc_url=logs_rpc_url,
                block_rpc_url=block_rpc_url,
                from_block=args.from_block,
                to_block=args.to_block,
                start_ts=start_ts,
                end_ts=end_ts,
                log_chunk_blocks=args.log_chunk_blocks,
                min_log_chunk_blocks=args.min_log_chunk_blocks,
                timeout_sec=args.timeout_sec,
                max_retries=args.max_retries,
            )

        candidate_txs = set(discovery.get("candidateTxs") or [])
        covered_txs = candidate_txs & (event_txs | scanned_txs)
        repair_txs = candidate_txs - (event_txs | scanned_txs)
        scanned_without_event = candidate_txs & scanned_txs - event_txs
        dead_candidate_txs = candidate_txs & dead_txs
        unresolved_dead_candidate_txs = dead_candidate_txs - covered_txs

        repair_tx_file = None
        if repair_txs and (args.write_repair_tx_file or args.repair_tx_file):
            repair_tx_file = args.repair_tx_file
            if not repair_tx_file:
                safe_project = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in args.project)
                repair_tx_file = str(
                    Path("data")
                    / "audits"
                    / f"{safe_project}-missing-txs-{int(time.time())}.txt"
                )
            Path(repair_tx_file).parent.mkdir(parents=True, exist_ok=True)
            Path(repair_tx_file).write_text("\n".join(sorted(repair_txs)) + "\n", encoding="utf-8")

        checks = expected_checks(args, profile, discovery)
        failed_checks = [x for x in checks if not x["ok"]]
        if not managed and not launch_row:
            blockers.append("project is not present in managed_projects or launch_configs")
        if discovery.get("errors") and int(discovery.get("candidateTxCount") or 0) == 0:
            blockers.append("log discovery returned errors and no candidate txs")
        if repair_txs:
            blockers.append("candidate txs exist that are neither parsed nor marked scanned")
        if unresolved_dead_candidate_txs:
            blockers.append("uncovered candidate txs have dead-letter failures")
        if failed_checks:
            blockers.append("expected baseline checks failed")
        if not discovery.get("enabled"):
            notes.append("discovery was skipped; status is based on local DB only")
        if scanned_without_event:
            notes.append("some candidate txs are scanned but have no parsed event; this can be normal for non-buy candidates")
        if dead_candidate_txs and not unresolved_dead_candidate_txs:
            notes.append("historical dead-letter records exist, but all matching candidate txs are already covered by events or scanned markers")

        if blockers:
            status = "red"
        elif discovery.get("enabled"):
            status = "green"
        else:
            status = "observed"

        repair_command = None
        if repair_txs:
            tx_file = repair_tx_file or "<missing_tx_file>"
            repair_command = (
                "python scripts/ops/replay_project_txs.py "
                f"--config {args.config} "
                f"--project {args.project} "
                f"--tx-file {tx_file} "
                f"--receipt-concurrency {args.receipt_concurrency} "
                "--mark-scanned"
            )

        summary: dict[str, Any] = {
            "project": args.project,
            "status": status,
            "checkedAt": int(time.time()),
            "sqlitePath": sqlite_path,
            "managedProject": managed,
            "launchConfig": {
                "name": launch.name,
                "internalPoolAddr": launch.internal_pool_addr,
                "tokenAddr": launch.token_addr,
            }
            if launch
            else None,
            "profile": profile,
            "discovery": {k: v for k, v in discovery.items() if k != "candidateTxs"},
            "coverage": {
                "candidateTxCount": len(candidate_txs),
                "eventTxCount": len(event_txs),
                "scannedTxCount": len(scanned_txs),
                "coveredCandidateTxCount": len(covered_txs),
                "candidateWithEventCount": len(candidate_txs & event_txs),
                "scannedCandidateWithoutEventCount": len(scanned_without_event),
                "repairCandidateTxCount": len(repair_txs),
                "deadLetterCandidateTxCount": len(dead_candidate_txs),
                "unresolvedDeadLetterCandidateTxCount": len(unresolved_dead_candidate_txs),
            },
            "expectedChecks": checks,
            "blockers": blockers,
            "notes": notes,
            "repair": {
                "txFile": repair_tx_file,
                "command": repair_command,
            },
        }
        if args.include_tx_lists:
            summary["txLists"] = {
                "candidateTxs": sorted(candidate_txs),
                "eventTxs": sorted(event_txs),
                "scannedTxs": sorted(scanned_txs),
                "repairCandidateTxs": sorted(repair_txs),
                "deadLetterCandidateTxs": sorted(dead_candidate_txs),
                "unresolvedDeadLetterCandidateTxs": sorted(unresolved_dead_candidate_txs),
            }
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return summary
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit project launch-window completeness and generate a replay repair command."
    )
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--project", required=True)
    parser.add_argument("--sqlite-path")
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    parser.add_argument("--logs-rpc-url")
    parser.add_argument("--block-rpc-url")
    parser.add_argument("--log-chunk-blocks", type=int, default=1000)
    parser.add_argument("--min-log-chunk-blocks", type=int, default=10)
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--receipt-concurrency", type=int, default=16)
    parser.add_argument("--expected-events", type=int)
    parser.add_argument("--expected-event-txs", type=int)
    parser.add_argument("--expected-candidate-txs", type=int)
    parser.add_argument("--skip-discovery", action="store_true")
    parser.add_argument("--include-tx-lists", action="store_true")
    parser.add_argument("--write-repair-tx-file", action="store_true")
    parser.add_argument("--repair-tx-file")
    parser.add_argument("--output")
    args = parser.parse_args()
    if (args.from_block is None) ^ (args.to_block is None):
        parser.error("--from-block and --to-block must be provided together")
    return args


def main() -> None:
    summary = asyncio.run(run(parse_args()))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
