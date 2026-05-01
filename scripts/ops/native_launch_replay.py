#!/usr/bin/env python3
"""Run a local native-style launch replay against a temporary SQLite DB."""

from __future__ import annotations

import argparse
import asyncio
import bisect
import contextlib
import json
import os
import sys
import time
import types
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from virtuals_bot import (  # noqa: E402
    DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS,
    GET_RESERVES_SELECTOR,
    RPCClient,
    TOKEN0_SELECTOR,
    TOKEN1_SELECTOR,
    TRANSFER_TOPIC0,
    VirtualsBot,
    decimal_to_str,
    load_config,
    normalize_address,
    normalize_optional_address,
    parse_virtuals_timestamp,
    raw_to_decimal,
    topic_address,
)


class ReplayClock:
    def __init__(self, start_ts: int, duration_sec: int, speed: float, *, auto_start: bool = True) -> None:
        self.start_ts = int(start_ts)
        self.duration_sec = int(duration_sec)
        self.speed = float(speed)
        self.real_started_at = time.monotonic()
        self._offset_sec = 0.0
        self._running = bool(auto_start)
        self._last_real = self.real_started_at if auto_start else None

    def now(self) -> int:
        return self.start_ts + int(self.offset_sec())

    def finished(self) -> bool:
        return self.offset_sec() >= self.duration_sec

    def offset_sec(self) -> float:
        offset = self._offset_sec
        if self._running and self._last_real is not None:
            offset += (time.monotonic() - self._last_real) * self.speed
        return max(0.0, min(float(self.duration_sec), offset))

    def state(self) -> str:
        if self.finished():
            return "ended"
        if self._running:
            return "running"
        return "paused"

    def set_speed(self, speed: float) -> None:
        parsed = float(speed)
        if parsed <= 0:
            raise ValueError("speed must be greater than 0")
        self._offset_sec = self.offset_sec()
        self.speed = parsed
        if self._running:
            self._last_real = time.monotonic()

    def start(self, *, speed: float | None = None) -> None:
        if speed is not None:
            self.set_speed(speed)
        if self.finished():
            return
        self._offset_sec = self.offset_sec()
        self._last_real = time.monotonic()
        self._running = True

    def pause(self) -> None:
        self._offset_sec = self.offset_sec()
        self._last_real = None
        self._running = False

    def reset(self) -> None:
        self._offset_sec = 0.0
        self._last_real = None
        self._running = False


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def project_event_count(db_path: str, project: str) -> int:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(1) FROM events WHERE project = ?", (project,)).fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def clear_project_replay_data(db_path: str, project: str) -> None:
    import sqlite3

    tables = [
        "events",
        "wallet_positions",
        "minute_agg",
        "minute_buyers",
        "leaderboard",
        "project_stats",
    ]
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for table in tables:
            cur.execute(f"DELETE FROM {table} WHERE project = ?", (project,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def fetch_virtuals_data(project_id: str) -> dict[str, Any]:
    url = f"https://api2.virtuals.io/api/virtuals/{project_id}"
    headers = {"User-Agent": "Mozilla/5.0 VirtualsWhaleRadarReplay/1.0"}
    timeout = aiohttp.ClientTimeout(total=12)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, params={"populate": "*"}) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Virtuals API returned {resp.status}: {text[:200]}")
            body = await resp.json(content_type=None)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("Virtuals API response does not contain data")
    return data


async def block_timestamp(client: RPCClient, block_number: int, cache: dict[int, int]) -> int:
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


async def prefetch_block_times(
    client: RPCClient,
    from_block: int,
    to_block: int,
    cache: dict[int, int],
    *,
    concurrency: int = 12,
) -> dict[int, int]:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def fetch_one(block_number: int) -> None:
        async with semaphore:
            await block_timestamp(client, block_number, cache)

    await asyncio.gather(*(fetch_one(block_number) for block_number in range(from_block, to_block + 1)))
    return {block: cache[block] for block in range(from_block, to_block + 1) if block in cache}


async def fetch_logs_once(
    client: RPCClient,
    *,
    virtual_token_addr: str,
    launch: Any,
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
        txs.update(str(row["transactionHash"]).lower() for row in logs if row.get("transactionHash"))
    return txs


async def fetch_logs_adaptive(
    client: RPCClient,
    *,
    virtual_token_addr: str,
    launch: Any,
    from_block: int,
    to_block: int,
    min_blocks: int,
    splits: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> set[str]:
    try:
        return await fetch_logs_once(
            client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=from_block,
            to_block=to_block,
        )
    except Exception as exc:
        if to_block - from_block + 1 <= min_blocks:
            errors.append(
                {
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return set()
        mid = (from_block + to_block) // 2
        splits.append(
            {
                "fromBlock": from_block,
                "toBlock": to_block,
                "error": f"{type(exc).__name__}: {exc}",
                "split": [[from_block, mid], [mid + 1, to_block]],
            }
        )
        left = await fetch_logs_adaptive(
            client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=from_block,
            to_block=mid,
            min_blocks=min_blocks,
            splits=splits,
            errors=errors,
        )
        right = await fetch_logs_adaptive(
            client,
            virtual_token_addr=virtual_token_addr,
            launch=launch,
            from_block=mid + 1,
            to_block=to_block,
            min_blocks=min_blocks,
            splits=splits,
            errors=errors,
        )
        return left | right


async def eth_call_at(client: RPCClient, to: str, data: str, block_number: int) -> str:
    return await client.call("eth_call", [{"to": to, "data": data}, hex(block_number)])


class HistoricalPoolMarket:
    def __init__(
        self,
        *,
        bot: VirtualsBot,
        clock: ReplayClock,
        block_times: dict[int, int],
        rpc: RPCClient,
    ) -> None:
        self.bot = bot
        self.clock = clock
        self.rpc = rpc
        self.block_numbers = sorted(block_times)
        self.block_timestamps = [block_times[block] for block in self.block_numbers]
        self.reserves_cache: dict[tuple[str, int], str] = {}
        self.historical_eth_call_supported: bool | None = None
        self.fallback_reason: str | None = None

    def block_for_sim_time(self, sim_ts: int) -> int:
        idx = bisect.bisect_right(self.block_timestamps, sim_ts) - 1
        if idx < 0:
            return self.block_numbers[0]
        if idx >= len(self.block_numbers):
            return self.block_numbers[-1]
        return self.block_numbers[idx]

    async def get_reserves_at(self, pool: str, block_number: int) -> str:
        key = (pool, int(block_number))
        cached = self.reserves_cache.get(key)
        if cached is not None:
            return cached
        try:
            out = await eth_call_at(self.rpc, pool, GET_RESERVES_SELECTOR, int(block_number))
            self.historical_eth_call_supported = True
        except Exception as exc:
            self.historical_eth_call_supported = False
            self.fallback_reason = f"{type(exc).__name__}: {exc}"
            out = await self.rpc.eth_call(pool, GET_RESERVES_SELECTOR)
        self.reserves_cache[key] = out
        return out

    async def snapshot(
        self,
        project_name: str,
        token_addr: str | None,
        internal_pool_addr: str | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        token = normalize_optional_address(token_addr)
        pool = normalize_optional_address(internal_pool_addr)
        virtual_price_usd, virtual_price_stale = await self.bot.price_service.get_price()
        if virtual_price_usd is None:
            with contextlib.suppress(Exception):
                await self.bot.price_service.refresh_once()
                virtual_price_usd, virtual_price_stale = await self.bot.price_service.get_price()

        sim_ts = self.clock.now()
        block_number = self.block_for_sim_time(sim_ts)
        out: dict[str, Any] = {
            "token_price_v": None,
            "token_price_usd": None,
            "live_fdv_usd": None,
            "virtual_price_usd": virtual_price_usd,
            "market_price_source": "historical_pool_reserves",
            "market_price_stale": virtual_price_stale,
            "price_updated_at": sim_ts,
            "price_latency_ms": 0,
            "price_block_number": block_number,
            "market_cache_hit": False,
        }

        def finish() -> dict[str, Any]:
            out["price_latency_ms"] = int(round((time.perf_counter() - started) * 1000))
            if self.historical_eth_call_supported is False:
                out["market_price_source"] = "latest_pool_reserves_fallback"
                out["market_price_stale"] = True
                out["historicalMarketFallbackReason"] = self.fallback_reason
            return out

        if not token or not pool:
            return finish()

        reserves_hex = await self.get_reserves_at(pool, block_number)
        if not reserves_hex or reserves_hex == "0x":
            return finish()
        data = reserves_hex[2:]
        if len(data) < 64 * 2:
            return finish()
        reserve0 = int(data[0:64], 16)
        reserve1 = int(data[64:128], 16)
        if reserve0 <= 0 or reserve1 <= 0:
            return finish()

        launch_cfg = self.bot.storage.get_launch_config_by_name(project_name)
        total_supply = (
            launch_cfg.token_total_supply
            if launch_cfg is not None
            else self.bot.fixed_token_total_supply
        )
        layout = await self.bot.resolve_live_pool_market_layout(
            token=token,
            pool=pool,
            reserve0=reserve0,
            reserve1=reserve1,
            total_supply=total_supply,
        )
        if not layout.get("supported"):
            return finish()

        token_decimals = int(layout["token_decimals"])
        virtual_decimals = int(layout["virtual_decimals"])
        if int(layout["token_index"]) == 0:
            token_reserve = raw_to_decimal(reserve0, token_decimals)
            virtual_reserve = raw_to_decimal(reserve1, virtual_decimals)
        else:
            token_reserve = raw_to_decimal(reserve1, token_decimals)
            virtual_reserve = raw_to_decimal(reserve0, virtual_decimals)
        if token_reserve <= 0 or virtual_reserve <= 0:
            return finish()

        token_price_v = virtual_reserve / token_reserve
        token_price_usd = token_price_v * virtual_price_usd if virtual_price_usd is not None else None
        live_fdv_usd = (
            token_price_usd * total_supply
            if token_price_usd is not None and total_supply > 0
            else None
        )
        out["token_price_v"] = token_price_v
        out["token_price_usd"] = token_price_usd
        out["live_fdv_usd"] = live_fdv_usd
        return finish()


def to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def compute_cost_metrics(overview: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    rows = list(overview.get("whaleBoard") or [])
    virtual_price_usd = to_decimal(market.get("virtualPriceUsd"))
    estimated_fdv_usd = to_decimal(market.get("estimatedFdvUsdWithTax"))
    live_fdv_usd = to_decimal(market.get("liveFdvUsd"))
    comparison_usd = estimated_fdv_usd or live_fdv_usd
    comparison_v = (
        comparison_usd / virtual_price_usd
        if comparison_usd is not None and virtual_price_usd is not None and virtual_price_usd > 0
        else None
    )

    comparable = []
    for row in rows:
        spent = to_decimal(row.get("spentV")) or Decimal(0)
        token = to_decimal(row.get("tokenBought")) or Decimal(0)
        fdv_v = to_decimal(row.get("breakevenFdvV"))
        if spent > 0 and token > 0 and fdv_v is not None and fdv_v > 0:
            comparable.append((row, spent, token, fdv_v))
    included = [item for item in comparable if not bool(item[0].get("costExcluded"))]
    excluded = [item for item in comparable if bool(item[0].get("costExcluded"))]
    total_spent = sum((item[1] for item in included), Decimal(0))
    total_token = sum((item[2] for item in included), Decimal(0))
    weighted_cost_v = (
        sum((item[3] * item[2] for item in included), Decimal(0)) / total_token
        if total_token > 0
        else None
    )
    weighted_cost_wan_usd = (
        weighted_cost_v * virtual_price_usd / Decimal(10000)
        if weighted_cost_v is not None and virtual_price_usd is not None
        else None
    )
    below = [
        item
        for item in included
        if comparison_v is not None and item[3] < comparison_v
    ]
    position = (
        f"{min(len(below) + 1, len(included))}/{len(included)}"
        if comparison_v is not None and included
        else "-"
    )
    below_spent = sum((item[1] for item in below), Decimal(0))
    return {
        "whaleRows": len(rows),
        "costRows": len(included),
        "excludedRows": len(excluded),
        "boardSpentV": decimal_to_str(total_spent, 6),
        "boardCostWanUsd": decimal_to_str(weighted_cost_wan_usd, 6)
        if weighted_cost_wan_usd is not None
        else None,
        "costPosition": position,
        "belowCostRows": len(below),
        "vCostPosition": (
            f"{decimal_to_str(below_spent, 0)}/{decimal_to_str(total_spent, 0)}"
            if comparison_v is not None and total_spent > 0
            else "-"
        ),
    }


async def build_sample(
    bot: VirtualsBot,
    project_row: dict[str, Any],
    clock: ReplayClock,
) -> dict[str, Any]:
    project_status = bot.derive_managed_project_status(project_row)
    policy = bot.project_market_policy(project_status)
    live_market = await bot.get_cached_live_pool_market_snapshot(
        str(project_row.get("name") or ""),
        project_row.get("token_addr"),
        project_row.get("internal_pool_addr"),
        cache_ttl_sec=policy["cache_ttl_sec"],
    )
    live_market.update(
        await bot.get_project_tax_market_snapshot(
            project_row,
            token_price_usd=live_market.get("token_price_usd"),
        )
    )
    market = bot.build_project_market_payload(live_market, project_status=project_status)
    overview = await bot.build_project_overview_payload(
        project_row,
        requested_project=str(project_row.get("name") or ""),
        tracked_wallet_configs=bot.storage.list_monitored_wallet_rows(),
        view_mode="project",
    )
    cost_metrics = compute_cost_metrics(overview, market)
    item = overview.get("item") or {}
    return {
        "realElapsedSec": round(time.monotonic() - clock.real_started_at, 3),
        "simTimestamp": clock.now(),
        "projectStatus": project_status,
        "events": project_event_count(bot.cfg.sqlite_path, str(project_row.get("name") or "")),
        "priceBlockNumber": market.get("priceBlockNumber"),
        "priceLatencyMs": market.get("priceLatencyMs"),
        "marketPriceSource": market.get("marketPriceSource"),
        "tokenPriceUsd": market.get("tokenPriceUsd"),
        "liveFdvUsd": market.get("liveFdvUsd"),
        "buyTaxRate": market.get("buyTaxRate"),
        "estimatedFdvWanUsdWithTax": market.get("estimatedFdvWanUsdWithTax"),
        "sumTaxV": item.get("sumTaxV"),
        **cost_metrics,
    }


async def parse_project_events(
    *,
    bot: VirtualsBot,
    launch: Any,
    tx_hashes: list[str],
    receipt_rpc: RPCClient,
    progress_every: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    virtual_price_usd, is_price_stale = await bot.price_service.get_price()
    for index, tx_hash in enumerate(tx_hashes, start=1):
        receipt = await receipt_rpc.get_receipt(tx_hash)
        if not receipt:
            continue
        if receipt.get("status") and int(receipt["status"], 16) == 0:
            continue
        logs = receipt.get("logs") or []
        if not bot.is_related_to_launch(logs, launch):
            continue
        block_number = int(receipt["blockNumber"], 16)
        timestamp = await bot.get_block_timestamp(block_number, rpc=receipt_rpc)
        parsed = await bot.parse_receipt_for_launch(
            launch=launch,
            receipt=receipt,
            timestamp=timestamp,
            virtual_price_usd=virtual_price_usd,
            is_price_stale=is_price_stale,
            rpc=receipt_rpc,
        )
        events.extend(parsed)
        if progress_every and index % progress_every == 0:
            print(
                json.dumps(
                    {"stage": "parse_receipts", "processed": index, "total": len(tx_hashes), "events": len(events)},
                    ensure_ascii=False,
                ),
                flush=True,
            )
    events.sort(
        key=lambda item: (
            int(item.get("block_timestamp") or 0),
            int(item.get("block_number") or 0),
            str(item.get("tx_hash") or ""),
            str(item.get("buyer") or ""),
        )
    )
    return events


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.manual and not args.serve:
        raise RuntimeError("--manual requires --serve so the replay can be started from the frontend")

    cfg = load_config(args.config)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    sqlite_path = str(out_dir / f"{args.replay_name.lower()}-{stamp}.db")
    event_bus_path = str(out_dir / f"{args.replay_name.lower()}-{stamp}-bus.db")
    jsonl_path = str(out_dir / f"{args.replay_name.lower()}-{stamp}.jsonl")
    samples_path = out_dir / f"{args.replay_name.lower()}-{stamp}-samples.jsonl"
    summary_path = out_dir / f"{args.replay_name.lower()}-{stamp}-summary.json"

    cfg = replace(
        cfg,
        sqlite_path=sqlite_path,
        event_bus_sqlite_path=event_bus_path,
        jsonl_path=jsonl_path,
        api_port=int(args.api_port),
        db_batch_size=1,
        db_flush_ms=150,
        cors_allow_origins=[f"http://127.0.0.1:{args.api_port}", f"http://localhost:{args.api_port}"],
    )
    virtuals_data = await fetch_virtuals_data(str(args.virtuals_id))
    launch_info = virtuals_data.get("launchInfo") if isinstance(virtuals_data.get("launchInfo"), dict) else {}
    start_ts = parse_virtuals_timestamp(virtuals_data.get("launchedAt"))
    if not start_ts:
        raise RuntimeError("Virtuals launchedAt is required for native replay")
    duration_sec = int(args.duration_minutes * 60)
    end_ts = start_ts + duration_sec
    token_addr = normalize_address(str(virtuals_data.get("preToken") or ""))
    pool_addr = normalize_address(str(virtuals_data.get("preTokenPair") or ""))

    bot = VirtualsBot(cfg, role="all")
    async with bot:
        bot.storage.set_state("runtime_paused", "0")
        bot.refresh_runtime_pause_state(force=True)
        with contextlib.suppress(Exception):
            await bot.price_service.refresh_once()

        project_row = bot.storage.upsert_managed_project(
            project_id=None,
            name=args.replay_name,
            signalhub_project_id=str(args.virtuals_id),
            detail_url=f"https://app.virtuals.io/virtuals/{args.virtuals_id}",
            token_addr=token_addr,
            internal_pool_addr=pool_addr,
            start_at=start_ts,
            signalhub_end_at=None,
            manual_end_at=end_ts,
            resolved_end_at=end_ts,
            is_watched=True,
            collect_enabled=True,
            backfill_enabled=False,
            status="live",
            source="replay",
        )
        bot.set_managed_project_chart_window(project_row)
        bot.sync_launch_config_for_managed_project(project_row)
        bot.sync_runtime_after_managed_project_change()
        launch = bot.build_launch_config_from_managed_project(project_row)
        if not launch:
            raise RuntimeError("failed to build replay launch config")

        bot.virtuals_launch_info_cache[str(args.virtuals_id)] = {
            "expires_at": time.time() + 3600,
            "payload": dict(virtuals_data),
        }

        preferred_replay_rpc_url = os.getenv("ANKR_BASE_HTTP_RPC_URL", "").strip()
        logs_url = args.logs_rpc_url or preferred_replay_rpc_url or (
            cfg.backfill_http_rpc_urls
            or cfg.backfill_public_http_rpc_urls
            or DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS
        )[0]
        logs_rpc = bot.rpc_clients_by_url.get(logs_url) or RPCClient(
            logs_url,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        if logs_rpc not in bot.rpc_clients_by_url.values():
            await logs_rpc.__aenter__()
        receipt_url = args.receipt_rpc_url or preferred_replay_rpc_url or logs_url
        receipt_rpc = bot.rpc_clients_by_url.get(receipt_url) or RPCClient(
            receipt_url,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        if receipt_rpc not in bot.rpc_clients_by_url.values() and receipt_rpc is not logs_rpc:
            await receipt_rpc.__aenter__()

        block_cache: dict[int, int] = {}
        from_block = await find_block_gte_timestamp(logs_rpc, start_ts, block_cache)
        to_block = await find_block_lte_timestamp(logs_rpc, end_ts, block_cache)
        block_times = await prefetch_block_times(
            logs_rpc,
            from_block,
            to_block,
            block_cache,
            concurrency=args.block_time_concurrency,
        )

        splits: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        txs = await fetch_logs_adaptive(
            logs_rpc,
            virtual_token_addr=cfg.virtual_token_addr,
            launch=launch,
            from_block=from_block,
            to_block=to_block,
            min_blocks=args.min_log_chunk_blocks,
            splits=splits,
            errors=errors,
        )
        tx_hashes = sorted(txs)
        events = await parse_project_events(
            bot=bot,
            launch=launch,
            tx_hashes=tx_hashes,
            receipt_rpc=receipt_rpc,
            progress_every=args.progress_every,
        )

        clock = ReplayClock(
            start_ts=start_ts,
            duration_sec=duration_sec,
            speed=float(args.speed),
            auto_start=not bool(args.manual),
        )
        historical_market = HistoricalPoolMarket(
            bot=bot,
            clock=clock,
            block_times=block_times,
            rpc=logs_rpc,
        )
        original_derive = bot.derive_managed_project_status
        original_compute_tax = bot.compute_buy_tax_rate

        def derive_with_replay_time(self: VirtualsBot, row: dict[str, Any], now_ts: int | None = None) -> str:
            return original_derive(row, now_ts=clock.now())

        def compute_tax_with_replay_time(self: VirtualsBot, **kwargs: Any) -> int | None:
            kwargs["now_ts"] = clock.now()
            return original_compute_tax(**kwargs)

        async def historical_snapshot(
            self: VirtualsBot,
            project_name: str,
            token: str | None,
            pool: str | None,
            cache_ttl_sec: float | None = None,
        ) -> dict[str, Any]:
            return await historical_market.snapshot(project_name, token, pool)

        bot.derive_managed_project_status = types.MethodType(derive_with_replay_time, bot)
        bot.compute_buy_tax_rate = types.MethodType(compute_tax_with_replay_time, bot)
        bot.get_cached_live_pool_market_snapshot = types.MethodType(historical_snapshot, bot)

        replay_runtime: dict[str, Any] = {
            "inserted_cursor": 0,
            "max_block": 0,
            "last_sample": None,
            "reset_count": 0,
            "last_action": "auto-start" if not args.manual else "waiting",
        }

        def replay_status_payload(project_id: int) -> dict[str, Any]:
            offset = clock.offset_sec()
            progress = offset / clock.duration_sec if clock.duration_sec > 0 else 0
            return {
                "ok": True,
                "manual": bool(args.manual),
                "project": args.replay_name,
                "projectId": project_id,
                "virtualsId": str(args.virtuals_id),
                "state": clock.state(),
                "speed": clock.speed,
                "startAt": clock.start_ts,
                "endAt": clock.start_ts + clock.duration_sec,
                "now": clock.now(),
                "durationSec": clock.duration_sec,
                "elapsedSec": int(offset),
                "progress": max(0, min(1, progress)),
                "insertedEvents": int(replay_runtime["inserted_cursor"]),
                "totalEvents": len(events),
                "lastAction": replay_runtime["last_action"],
                "resetCount": int(replay_runtime["reset_count"]),
                "apiProjectUrl": (
                    f"/admin/projects/{project_row['id']}?project={args.replay_name}&replayControl=1"
                ),
                "lastSample": replay_runtime["last_sample"],
            }

        async def replay_status_handler(request: web.Request) -> web.Response:
            return web.json_response(replay_status_payload(int(project_row["id"])))

        async def replay_control_handler(request: web.Request) -> web.Response:
            action = request.match_info.get("action", "")
            try:
                payload = await request.json()
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            speed = payload.get("speed")
            try:
                if action == "start":
                    clock.start(speed=float(speed) if speed is not None else None)
                elif action == "pause":
                    clock.pause()
                elif action == "resume":
                    clock.start(speed=float(speed) if speed is not None else None)
                elif action == "speed":
                    if speed is None:
                        raise ValueError("speed is required")
                    clock.set_speed(float(speed))
                elif action == "reset":
                    clock.reset()
                    clear_project_replay_data(cfg.sqlite_path, args.replay_name)
                    replay_runtime["inserted_cursor"] = 0
                    replay_runtime["max_block"] = 0
                    replay_runtime["last_sample"] = None
                    replay_runtime["reset_count"] = int(replay_runtime["reset_count"]) + 1
                else:
                    return web.json_response({"ok": False, "error": f"unknown replay action: {action}"}, status=400)
            except Exception as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            replay_runtime["last_action"] = action
            return web.json_response(replay_status_payload(int(project_row["id"])))

        runner: web.AppRunner | None = None
        if args.serve:
            app = await bot.create_api_app()
            app.router.add_get("/api/replay/status", replay_status_handler)
            app.router.add_post("/api/replay/{action}", replay_control_handler)
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host=cfg.api_host, port=cfg.api_port).start()

        samples: list[dict[str, Any]] = []
        started_real = time.monotonic()
        next_sample_at = started_real
        print(
            json.dumps(
                {
                    "stage": "replay_start",
                    "project": args.replay_name,
                    "virtualsId": str(args.virtuals_id),
                    "db": sqlite_path,
                    "api": (
                        f"http://127.0.0.1:{cfg.api_port}/admin/projects/{project_row['id']}"
                        f"?project={args.replay_name}&replayControl=1"
                    )
                    if args.serve
                    else None,
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "txCount": len(tx_hashes),
                    "eventCount": len(events),
                    "durationSec": duration_sec,
                    "speed": float(args.speed),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        while not clock.finished():
            sim_now = clock.now()
            batch: list[dict[str, Any]] = []
            inserted_cursor = int(replay_runtime["inserted_cursor"])
            while inserted_cursor < len(events) and int(events[inserted_cursor]["block_timestamp"]) <= sim_now:
                event = events[inserted_cursor]
                batch.append(event)
                replay_runtime["max_block"] = max(
                    int(replay_runtime["max_block"]),
                    int(event.get("block_number") or 0),
                )
                inserted_cursor += 1
            replay_runtime["inserted_cursor"] = inserted_cursor
            if batch:
                bot.persist_events_batch(batch, int(replay_runtime["max_block"]))

            now = time.monotonic()
            if now >= next_sample_at:
                sample = await build_sample(bot, project_row, clock)
                replay_runtime["last_sample"] = sample
                samples.append(sample)
                with samples_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                print(json.dumps({"stage": "sample", **sample}, ensure_ascii=False), flush=True)
                next_sample_at = now + float(args.sample_interval_sec)
            await asyncio.sleep(max(0.05, float(args.tick_sec)))

        inserted_cursor = int(replay_runtime["inserted_cursor"])
        if inserted_cursor < len(events):
            remaining = events[inserted_cursor:]
            if remaining:
                replay_runtime["max_block"] = max(
                    int(replay_runtime["max_block"]),
                    *(int(event.get("block_number") or 0) for event in remaining),
                )
                bot.persist_events_batch(remaining, int(replay_runtime["max_block"]))
                inserted_cursor = len(events)
                replay_runtime["inserted_cursor"] = inserted_cursor

        final_sample = await build_sample(bot, project_row, clock)
        replay_runtime["last_sample"] = final_sample
        samples.append(final_sample)
        with samples_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(final_sample, ensure_ascii=False) + "\n")

        if args.hold_open_sec and runner is not None:
            await asyncio.sleep(max(0, int(args.hold_open_sec)))
        if runner is not None:
            await runner.cleanup()

        summary = {
            "project": args.replay_name,
            "virtualsId": str(args.virtuals_id),
            "virtualsName": virtuals_data.get("name"),
            "virtualsSymbol": virtuals_data.get("symbol"),
            "factory": virtuals_data.get("factory"),
            "category": virtuals_data.get("category"),
            "launchInfo": launch_info,
            "startAt": start_ts,
            "endAt": end_ts,
            "fromBlock": from_block,
            "toBlock": to_block,
            "txCount": len(tx_hashes),
            "parsedEventCount": len(events),
            "insertedEventCount": project_event_count(sqlite_path, args.replay_name),
            "samples": len(samples),
            "sqlitePath": sqlite_path,
            "samplesPath": str(samples_path),
            "jsonlPath": jsonl_path,
            "historicalEthCallSupported": historical_market.historical_eth_call_supported,
            "historicalEthCallFallbackReason": historical_market.fallback_reason,
            "logSplits": splits,
            "logErrors": errors,
            "finalSample": final_sample,
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"stage": "replay_done", "summaryPath": str(summary_path), **summary}, ensure_ascii=False), flush=True)

        if logs_rpc not in bot.rpc_clients_by_url.values():
            await logs_rpc.__aexit__(None, None, None)
        if receipt_rpc not in bot.rpc_clients_by_url.values() and receipt_rpc is not logs_rpc:
            await receipt_rpc.__aexit__(None, None, None)
        return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Native local launch replay for a Virtuals project.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--virtuals-id", default="72752")
    parser.add_argument("--replay-name", default="ISC_REPLAY")
    parser.add_argument("--duration-minutes", type=float, default=10.0)
    parser.add_argument("--speed", type=float, default=5.0)
    parser.add_argument("--output-dir", default="data/replay")
    parser.add_argument("--api-port", type=int, default=18080)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Start paused and expose /api/replay controls so the frontend can trigger the replay.",
    )
    parser.add_argument("--hold-open-sec", type=int, default=0)
    parser.add_argument("--logs-rpc-url")
    parser.add_argument("--receipt-rpc-url")
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--min-log-chunk-blocks", type=int, default=10)
    parser.add_argument("--block-time-concurrency", type=int, default=12)
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--sample-interval-sec", type=float, default=1.0)
    parser.add_argument("--tick-sec", type=float, default=0.2)
    return parser.parse_args()


def main() -> None:
    summary = asyncio.run(run(parse_args()))
    print(
        json.dumps(
            {
                "project": summary["project"],
                "virtualsId": summary["virtualsId"],
                "insertedEventCount": summary["insertedEventCount"],
                "samplesPath": summary["samplesPath"],
                "historicalEthCallSupported": summary["historicalEthCallSupported"],
                "finalSample": summary["finalSample"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
