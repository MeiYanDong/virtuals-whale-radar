#!/usr/bin/env python3
"""SR deterministic event-level replay for launch strategy validation.

Read-only boundaries:
- creates an isolated replay SQLite DB under data/replay-event-level;
- fetches historical logs/receipts through configured RPC;
- writes local JSON/Markdown reports;
- does not touch production DBs and does not send trades.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from backtest_launch_strategy import fmt_decimal, parse_decimal, spot_fdv_wan  # noqa: E402
from native_launch_replay import (  # noqa: E402
    HistoricalPoolMarket,
    build_sample,
    fetch_logs_adaptive,
    fetch_virtuals_data,
    find_block_gte_timestamp,
    find_block_lte_timestamp,
    prefetch_block_times,
    project_event_count,
)
from virtuals_bot import (  # noqa: E402
    RPCClient,
    TRANSFER_TOPIC0,
    VirtualsBot,
    decode_topic_address,
    load_config,
    normalize_address,
    parse_hex_int,
    parse_virtuals_timestamp,
)


@dataclass(frozen=True)
class StrategyRule:
    name: str
    spent_threshold_v: Decimal
    max_tax_rate: Decimal
    fdv_discount: Decimal = Decimal("1")
    min_cost_rows: int = 5
    min_whale_rows: int = 20
    one_buy_per_tax_rate: bool = True
    cooldown_sec: int = 0
    burst_limit: int = 0
    burst_window_sec: int = 120
    burst_cooldown_sec: int = 600
    buy_size_v: Decimal = Decimal("50")
    max_project_spend_v: Decimal = Decimal("300")


class FixedReplayClock:
    def __init__(self, start_ts: int, end_ts: int) -> None:
        self.start_ts = int(start_ts)
        self.duration_sec = max(0, int(end_ts) - int(start_ts))
        self.real_started_at = time.monotonic()
        self.current_ts = int(start_ts)

    def now(self) -> int:
        return int(self.current_ts)

    def set(self, ts: int) -> None:
        self.current_ts = int(ts)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stage(name: str, **fields: Any) -> None:
    print(json.dumps({"stage": name, **fields}, ensure_ascii=False), flush=True)


def rules() -> list[StrategyRule]:
    return [
        StrategyRule("gate_5k_tax95_fdv_one_per_tax", Decimal("5000"), Decimal("95")),
        StrategyRule("gate_5k_tax94_fdv_one_per_tax", Decimal("5000"), Decimal("94")),
        StrategyRule("gate_5k_tax93_fdv_one_per_tax", Decimal("5000"), Decimal("93")),
        StrategyRule("gate_5k_tax92_fdv_one_per_tax", Decimal("5000"), Decimal("92")),
        StrategyRule("gate_5k_tax91_fdv_one_per_tax", Decimal("5000"), Decimal("91")),
        StrategyRule("gate_5k_tax90_fdv_one_per_tax", Decimal("5000"), Decimal("90")),
        StrategyRule("gate_5k_tax89_fdv_one_per_tax", Decimal("5000"), Decimal("89")),
    ]


def transfer_logs(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(receipt.get("logs") or []):
        topics = item.get("topics") or []
        if not topics or str(topics[0]).lower() != TRANSFER_TOPIC0 or len(topics) < 3:
            continue
        with contextlib.suppress(Exception):
            rows.append(
                {
                    "token": normalize_address(str(item.get("address") or "")),
                    "from": decode_topic_address(topics[1]),
                    "to": decode_topic_address(topics[2]),
                    "amountRaw": parse_hex_int(item.get("data")),
                    "index": index,
                }
            )
    return rows


def classify_pool_event(
    receipt: dict[str, Any],
    *,
    launch: Any,
    virtual_token_addr: str,
    parsed_buy_events: int,
) -> str:
    if parsed_buy_events > 0:
        return "buy"

    vaddr = normalize_address(virtual_token_addr)
    token_to_pool_from: set[str] = set()
    virtual_from_pool_to: set[str] = set()
    for row in transfer_logs(receipt):
        token = row["token"]
        from_addr = row["from"]
        to_addr = row["to"]
        if token != vaddr and to_addr == launch.internal_pool_addr:
            token_to_pool_from.add(from_addr)
        if token == vaddr and from_addr == launch.internal_pool_addr:
            virtual_from_pool_to.add(to_addr)

    if token_to_pool_from & virtual_from_pool_to:
        return "sell"
    return "unknown_pool_event"


async def collect_pool_events(
    *,
    bot: VirtualsBot,
    launch: Any,
    tx_hashes: list[str],
    receipt_rpc: RPCClient,
    progress_every: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed_events: list[dict[str, Any]] = []
    pool_events: list[dict[str, Any]] = []
    virtual_price_usd, is_price_stale = await bot.price_service.get_price()
    for index, tx_hash in enumerate(tx_hashes, start=1):
        receipt = await receipt_rpc.get_receipt(tx_hash)
        if not receipt:
            continue
        if receipt.get("status") and int(receipt["status"], 16) == 0:
            continue
        if not bot.is_related_to_launch(receipt.get("logs") or [], launch):
            continue
        block_number = int(receipt["blockNumber"], 16)
        timestamp = await bot.get_block_timestamp(block_number, rpc=receipt_rpc)
        events = await bot.parse_receipt_for_launch(
            launch=launch,
            receipt=receipt,
            timestamp=timestamp,
            virtual_price_usd=virtual_price_usd,
            is_price_stale=is_price_stale,
            rpc=receipt_rpc,
        )
        parsed_events.extend(events)
        event_type = classify_pool_event(
            receipt,
            launch=launch,
            virtual_token_addr=bot.cfg.virtual_token_addr,
            parsed_buy_events=len(events),
        )
        pool_events.append(
            {
                "txHash": tx_hash,
                "blockNumber": block_number,
                "blockTimestamp": timestamp,
                "eventType": event_type,
                "parsedBuyEvents": len(events),
            }
        )
        if progress_every and index % progress_every == 0:
            print(
                json.dumps(
                    {
                        "stage": "parse_receipts",
                        "processed": index,
                        "total": len(tx_hashes),
                        "poolEvents": len(pool_events),
                        "parsedBuyEvents": len(parsed_events),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    parsed_events.sort(
        key=lambda item: (
            int(item.get("block_timestamp") or 0),
            int(item.get("block_number") or 0),
            str(item.get("tx_hash") or ""),
            str(item.get("buyer") or ""),
        )
    )
    pool_events.sort(
        key=lambda item: (
            int(item.get("blockTimestamp") or 0),
            int(item.get("blockNumber") or 0),
            str(item.get("txHash") or ""),
        )
    )
    return parsed_events, pool_events


def tax_ticks(
    bot: VirtualsBot,
    *,
    virtuals_data: dict[str, Any],
    start_ts: int,
    end_ts: int,
) -> tuple[list[int], dict[str, Any]]:
    launch_info = virtuals_data.get("launchInfo") if isinstance(virtuals_data.get("launchInfo"), dict) else {}
    launch_mode = bot.classify_virtuals_launch_mode(virtuals_data, launch_info)
    schedule = bot.resolve_buy_tax_schedule(
        factory=virtuals_data.get("factory"),
        category=virtuals_data.get("category"),
        anti_sniper_tax_type=launch_info.get("antiSniperTaxType"),
        is_project_60days=launch_mode.get("is_project_60days"),
    )
    duration_value = int(schedule.get("duration_value") or 0)
    unit_seconds = int(schedule.get("unit_seconds") or 1)
    if not schedule.get("known") or duration_value <= 0:
        return [], {**schedule, **launch_mode}
    ticks = [
        int(start_ts) + step * max(1, unit_seconds)
        for step in range(duration_value + 1)
        if int(start_ts) + step * max(1, unit_seconds) <= int(end_ts)
    ]
    return ticks, {**schedule, **launch_mode}


def build_timeline(
    *,
    start_ts: int,
    end_ts: int,
    pool_events: list[dict[str, Any]],
    tax_tick_values: list[int],
    heartbeat_sec: int,
) -> list[dict[str, Any]]:
    triggers: dict[int, set[str]] = defaultdict(set)
    triggers[int(start_ts)].add("start")
    triggers[int(end_ts)].add("end")
    for item in pool_events:
        ts = int(item.get("blockTimestamp") or 0)
        if start_ts <= ts <= end_ts:
            triggers[ts].add(str(item.get("eventType") or "pool_state_change"))
    for ts in tax_tick_values:
        if start_ts <= int(ts) <= end_ts:
            triggers[int(ts)].add("tax_tick")
    if heartbeat_sec > 0:
        ts = int(start_ts)
        while ts <= int(end_ts):
            triggers[ts].add("heartbeat")
            ts += int(heartbeat_sec)
    return [
        {"timestamp": ts, "triggerTypes": sorted(values)}
        for ts, values in sorted(triggers.items())
    ]


def should_buy(row: dict[str, Any], rule: StrategyRule) -> tuple[bool, str]:
    if row.get("projectStatus") not in {None, "live"}:
        return False, "not_live"
    tax_fdv = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
    board_cost = parse_decimal(row.get("boardCostWanUsd"))
    board_spent = parse_decimal(row.get("boardSpentV")) or Decimal("0")
    tax_rate = parse_decimal(row.get("buyTaxRate"))
    cost_rows = int(row.get("costRows") or 0)
    whale_rows = int(row.get("whaleRows") or 0)

    if tax_fdv is None or tax_fdv <= 0:
        return False, "missing_tax_fdv"
    if board_cost is None or board_cost <= 0:
        return False, "missing_board_cost"
    if board_spent < rule.spent_threshold_v:
        return False, "spent_threshold"
    if tax_rate is None or tax_rate > rule.max_tax_rate:
        return False, "tax_threshold"
    if cost_rows < rule.min_cost_rows:
        return False, "min_cost_rows"
    if whale_rows < rule.min_whale_rows:
        return False, "min_whale_rows"
    if tax_fdv > board_cost * rule.fdv_discount:
        return False, "fdv_not_below_cost"
    return True, "signal"


def evaluate_end_only(samples: list[dict[str, Any]], rule: StrategyRule) -> dict[str, Any]:
    buys: list[dict[str, Any]] = []
    buy_timestamps: list[int] = []
    bought_tax_rates: set[str] = set()
    skip_reasons: Counter[str] = Counter()
    next_allowed_ts = -1
    total_spent = Decimal("0")

    for index, row in enumerate(samples):
        ts = int(row.get("simTimestamp") or 0)
        tax_key = str(row.get("buyTaxRate"))
        ok, reason = should_buy(row, rule)
        if not ok:
            skip_reasons[reason] += 1
            continue
        if rule.one_buy_per_tax_rate and tax_key in bought_tax_rates:
            skip_reasons["same_tax_period"] += 1
            continue
        if rule.cooldown_sec > 0 and ts < next_allowed_ts:
            skip_reasons["cooldown"] += 1
            continue
        if total_spent + rule.buy_size_v > rule.max_project_spend_v:
            skip_reasons["max_project_spend"] += 1
            continue

        entry = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        if entry is None or entry <= 0:
            skip_reasons["missing_entry_fdv"] += 1
            continue

        buys.append(
            {
                "index": index,
                "timestamp": ts,
                "taxRate": str(row.get("buyTaxRate")),
                "entryTaxFdvWanUsd": fmt_decimal(entry, 6),
                "entrySpotFdvWanUsd": fmt_decimal(spot_fdv_wan(row), 6),
                "boardSpentV": fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal(0), 3),
                "boardCostWanUsd": fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
                "costRows": int(row.get("costRows") or 0),
                "whaleRows": int(row.get("whaleRows") or 0),
                "costPosition": str(row.get("costPosition") or "-"),
                "vCostPosition": str(row.get("vCostPosition") or "-"),
                "triggerTypes": row.get("triggerTypes") or [],
            }
        )
        total_spent += rule.buy_size_v
        if rule.one_buy_per_tax_rate:
            bought_tax_rates.add(tax_key)
        buy_timestamps.append(ts)
        recent = [item for item in buy_timestamps if ts - item <= rule.burst_window_sec]
        if rule.burst_limit > 0 and len(recent) >= rule.burst_limit:
            next_allowed_ts = ts + rule.burst_cooldown_sec
        else:
            next_allowed_ts = ts + rule.cooldown_sec

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_value = Decimal("0")
    for buy in buys:
        entry = parse_decimal(buy.get("entryTaxFdvWanUsd"))
        if entry is not None and entry > 0 and final_spot is not None:
            final_value += rule.buy_size_v * final_spot / entry

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent > 0 else Decimal("0")
    return {
        "ruleName": rule.name,
        "rule": {
            "spentThresholdV": fmt_decimal(rule.spent_threshold_v),
            "maxTaxRate": fmt_decimal(rule.max_tax_rate),
            "fdvDiscount": fmt_decimal(rule.fdv_discount),
            "minCostRows": rule.min_cost_rows,
            "minWhaleRows": rule.min_whale_rows,
            "oneBuyPerTaxRate": rule.one_buy_per_tax_rate,
            "cooldownSec": rule.cooldown_sec,
            "burstLimit": rule.burst_limit,
            "burstCooldownSec": rule.burst_cooldown_sec,
            "buySizeV": fmt_decimal(rule.buy_size_v),
            "maxProjectSpendV": fmt_decimal(rule.max_project_spend_v),
        },
        "buyCount": len(buys),
        "totalSpentV": fmt_decimal(total_spent, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "firstBuy": buys[0] if buys else None,
        "buys": buys,
        "skipReasons": dict(skip_reasons),
    }


def signal_clusters(
    samples: list[dict[str, Any]],
    rule: StrategyRule,
    *,
    cluster_gap_sec: int | None = None,
) -> tuple[Counter[str], list[dict[str, Any]]]:
    reasons: Counter[str] = Counter()
    signal_rows: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(samples):
        ok, reason = should_buy(row, rule)
        reasons[reason] += 1
        if ok:
            signal_rows.append((index, row))

    gap = max(1, int(cluster_gap_sec or rule.cooldown_sec or 60))
    clusters: list[list[tuple[int, dict[str, Any]]]] = []
    current: list[tuple[int, dict[str, Any]]] = []
    for item in signal_rows:
        ts = int(item[1].get("simTimestamp") or 0)
        prev_ts = int(current[-1][1].get("simTimestamp") or 0) if current else None
        if not current or (prev_ts is not None and ts - prev_ts <= gap):
            current.append(item)
        else:
            clusters.append(current)
            current = [item]
    if current:
        clusters.append(current)

    def compact_row(index: int, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "index": index,
            "timestamp": int(row.get("simTimestamp") or 0),
            "taxRate": str(row.get("buyTaxRate")),
            "boardSpentV": fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal(0), 3),
            "taxFdvWanUsd": fmt_decimal(parse_decimal(row.get("estimatedFdvWanUsdWithTax")), 6),
            "boardCostWanUsd": fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
            "costPosition": str(row.get("costPosition") or "-"),
            "triggerTypes": row.get("triggerTypes") or [],
        }

    compact_clusters: list[dict[str, Any]] = []
    for cluster_index, cluster in enumerate(clusters, start=1):
        first_index, first = cluster[0]
        last_index, last = cluster[-1]
        compact_clusters.append(
            {
                "cluster": cluster_index,
                "rows": len(cluster),
                "from": compact_row(first_index, first),
                "to": compact_row(last_index, last),
            }
        )
    return reasons, compact_clusters


def execution_counterfactuals(samples: list[dict[str, Any]], rule: StrategyRule) -> dict[str, Any]:
    variants = {
        "current": rule,
        "noTaxPeriodLimitMaxSpend": replace(rule, one_buy_per_tax_rate=False),
        "legacy60sCooldownNoBurst": replace(rule, one_buy_per_tax_rate=False, cooldown_sec=60, burst_limit=0),
        "legacy30sCooldownNoBurst": replace(rule, one_buy_per_tax_rate=False, cooldown_sec=30, burst_limit=0),
    }
    output: dict[str, Any] = {}
    for name, variant in variants.items():
        result = evaluate_end_only(samples, variant)
        output[name] = {
            "buyCount": result["buyCount"],
            "totalSpentV": result["totalSpentV"],
            "finalPnlPct": result["finalPnlPct"],
            "buys": result["buys"][:6],
        }
    return output


def attach_signal_validation(
    results: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    rule_map: dict[str, StrategyRule],
) -> None:
    for result in results:
        rule = rule_map.get(str(result.get("ruleName") or ""))
        if not rule:
            continue
        reasons, clusters = signal_clusters(samples, rule)
        result["signalValidation"] = {
            "sampleCount": len(samples),
            "signalRows": reasons.get("signal", 0),
            "signalClusterCount": len(clusters),
            "signalClusters": clusters,
            "preExecutionReasonCounts": dict(reasons),
            "executionCounterfactuals": execution_counterfactuals(samples, rule),
        }


def compact_first_buy(item: dict[str, Any]) -> str:
    first = item.get("firstBuy")
    if not first:
        return "-"
    return (
        f"tax {first.get('taxRate')}, board {first.get('boardSpentV')}V, "
        f"FDV {first.get('entryTaxFdvWanUsd')}万, cost {first.get('boardCostWanUsd')}万, "
        f"costPos {first.get('costPosition')}, triggers {','.join(first.get('triggerTypes') or [])}"
    )


def md_table(row: list[Any]) -> str:
    return "| " + " | ".join(str(item) for item in row) + " |"


def rpc_label(url: str) -> str:
    lowered = str(url or "").lower()
    if "chainstack" in lowered:
        return "chainstack"
    if "mainnet.base.org" in lowered:
        return "mainnet.base.org"
    if "publicnode" in lowered:
        return "publicnode"
    if "llamarpc" in lowered:
        return "llamarpc"
    if "alchemy" in lowered:
        return "alchemy"
    if "ankr" in lowered:
        return "ankr"
    return "custom"


async def prefetch_block_times_batched(
    rpc_url: str,
    fallback_rpc: RPCClient,
    from_block: int,
    to_block: int,
    *,
    batch_size: int,
    concurrency: int,
    timeout_sec: int,
) -> dict[int, int]:
    if batch_size <= 1:
        return await prefetch_block_times(
            fallback_rpc,
            from_block,
            to_block,
            {},
            concurrency=concurrency,
        )

    blocks = list(range(int(from_block), int(to_block) + 1))
    chunks = [blocks[index : index + batch_size] for index in range(0, len(blocks), batch_size)]
    result: dict[int, int] = {}
    semaphore = asyncio.Semaphore(max(1, concurrency))
    timeout = aiohttp.ClientTimeout(total=max(5, int(timeout_sec)))

    async def fetch_chunk(chunk: list[int]) -> None:
        payload = [
            {
                "jsonrpc": "2.0",
                "id": block,
                "method": "eth_getBlockByNumber",
                "params": [hex(block), False],
            }
            for block in chunk
        ]
        async with semaphore:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(rpc_url, json=payload) as response:
                    body = await response.json(content_type=None)
        if not isinstance(body, list):
            raise RuntimeError(f"unexpected batch block response: {type(body).__name__}")
        for offset, item in enumerate(body):
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            block = int(raw_id) if raw_id is not None else int(chunk[offset])
            payload_result = item.get("result")
            if block and isinstance(payload_result, dict) and payload_result.get("timestamp"):
                result[block] = int(payload_result["timestamp"], 16)

    await asyncio.gather(*(fetch_chunk(chunk) for chunk in chunks))
    missing = [block for block in blocks if block not in result]
    for block in missing:
        block_obj = await fallback_rpc.get_block_by_number(block)
        if block_obj and block_obj.get("timestamp"):
            result[block] = int(block_obj["timestamp"], 16)
    return {block: result[block] for block in blocks if block in result}


def write_report(report: dict[str, Any], output_md: Path) -> None:
    project = str(report.get("project") or "EVENT_REPLAY")
    virtuals_id = str(report.get("virtualsId") or "-")
    lines: list[str] = []
    lines.append(f"# {project} Event-Level Replay Strategy Report")
    lines.append("")
    lines.append("本报告从链上重新拉取项目发射窗口，按 `pool_state_change + tax_tick + heartbeat` 构造本地离线时间线。")
    lines.append("它只写入隔离 replay DB，不触碰生产库，不发送交易。")
    lines.append("")
    lines.append("## 口径")
    lines.append(f"- 项目：`{project}` / Virtuals ID `{virtuals_id}`。")
    rpc_profile = report.get("rpcProfile") or {}
    lines.append("- RPC：报告只记录 provider 角色，不记录 endpoint token。")
    lines.append(f"- history/log/market RPC：`{rpc_profile.get('history')}`。")
    lines.append(f"- receipt RPC：`{rpc_profile.get('receipt')}`。")
    lines.append("- `pool_state_change` 覆盖 buy、sell、unknown pool event。")
    lines.append("- `tax_tick` 是税率变化瞬间；即使没有交易也单独采样。")
    lines.append("- 收益只看 tax 降到 `1%` 时的 end 表现，不输出默认 `1m / 3m / 5m / 10m`。")
    lines.append("")
    counts = report["counts"]
    lines.append("## 数据规模")
    lines.append(md_table(["tx", "pool events", "buy", "sell", "unknown", "tax ticks", "samples", "parsed buys", "inserted buys"]))
    lines.append(md_table(["---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"]))
    lines.append(
        md_table(
            [
                counts["txCount"],
                counts["poolEventCount"],
                counts["poolEventTypes"].get("buy", 0),
                counts["poolEventTypes"].get("sell", 0),
                counts["poolEventTypes"].get("unknown_pool_event", 0),
                counts["taxTickCount"],
                counts["sampleCount"],
                counts["parsedBuyEventCount"],
                counts["insertedBuyEventCount"],
            ]
        )
    )
    lines.append("")
    lines.append("## 候选规则")
    lines.append(md_table(["Rule", "买入", "投入", "end收益", "End PnL", "首买"]))
    lines.append(md_table(["---", "---:", "---:", "---:", "---:", "---"]))
    for item in report["results"]:
        lines.append(
            md_table(
                [
                    item["ruleName"],
                    item["buyCount"],
                    item["totalSpentV"],
                    f"{item['finalPnlPct']}%",
                    item["finalPnlV"],
                    compact_first_buy(item),
                ]
            )
        )
    lines.append("")
    best = report["results"][0] if report.get("results") else {}
    validation = best.get("signalValidation") or {}
    if validation:
        lines.append("## 最佳规则验证")
        lines.append("")
        lines.append(f"- Rule：`{best.get('ruleName')}`。")
        lines.append(f"- 样本数：`{validation.get('sampleCount')}`。")
        lines.append(f"- 满足硬条件的信号样本：`{validation.get('signalRows')}`。")
        lines.append(f"- 信号簇数量：`{validation.get('signalClusterCount')}`。")
        lines.append(f"- 执行后买入次数：`{best.get('buyCount')}`。")
        lines.append(f"- 执行层拦截：`{best.get('skipReasons')}`。")
        lines.append("- 逻辑说明：样本数增加不等于买入机会增加；买入由硬条件、每个税率档位最多买一次、项目最大投入共同决定。")
        clusters = validation.get("signalClusters") or []
        if clusters:
            lines.append("")
            lines.append("### 信号簇")
            lines.append(md_table(["簇", "行数", "开始", "结束", "开始条件", "结束条件"]))
            lines.append(md_table(["---:", "---:", "---", "---", "---", "---"]))
            for cluster in clusters[:10]:
                start = cluster.get("from") or {}
                end = cluster.get("to") or {}
                lines.append(
                    md_table(
                        [
                            cluster.get("cluster"),
                            cluster.get("rows"),
                            start.get("timestamp"),
                            end.get("timestamp"),
                            f"tax {start.get('taxRate')}, board {start.get('boardSpentV')}V, FDV {start.get('taxFdvWanUsd')}万, cost {start.get('boardCostWanUsd')}万",
                            f"tax {end.get('taxRate')}, board {end.get('boardSpentV')}V, FDV {end.get('taxFdvWanUsd')}万, cost {end.get('boardCostWanUsd')}万",
                        ]
                    )
                )
        counterfactuals = validation.get("executionCounterfactuals") or {}
        if counterfactuals:
            lines.append("")
            lines.append("### 执行限制对照")
            lines.append(md_table(["模式", "买入", "投入", "end收益"]))
            lines.append(md_table(["---", "---:", "---:", "---:"]))
            for name, item in counterfactuals.items():
                lines.append(
                    md_table(
                        [
                            name,
                            item.get("buyCount"),
                            item.get("totalSpentV"),
                            f"{item.get('finalPnlPct')}%",
                        ]
                    )
                )
        lines.append("")
    lines.append("## 执行信息")
    lines.append(f"- 区块窗口：`{report['fromBlock']} -> {report['toBlock']}`")
    lines.append(f"- 时间窗口：`{report['startAt']} -> {report['endAt']}`")
    lines.append(f"- sample JSONL：`{report['samplesPath']}`")
    lines.append(f"- isolated DB：`{report['sqlitePath']}`")
    lines.append(f"- historical eth_call：`{report['historicalEthCallSupported']}`")
    if report.get("historicalEthCallFallbackReason"):
        lines.append(f"- historical eth_call fallback：`{report['historicalEthCallFallbackReason']}`")
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(args.report_dir).mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()

    replay_name = args.replay_name
    sqlite_path = str(out_dir / f"{replay_name.lower()}-{stamp}.db")
    event_bus_path = str(out_dir / f"{replay_name.lower()}-{stamp}-bus.db")
    jsonl_path = str(out_dir / f"{replay_name.lower()}-{stamp}.jsonl")
    samples_path = out_dir / f"{replay_name.lower()}-{stamp}-samples.jsonl"
    output_json = Path(args.output_json or f"data/backtests/sr-event-level-replay-{stamp}.json")
    output_md = Path(args.output_md or f"{args.report_dir}/phase-052-sr-event-level-replay-{datetime.now().strftime('%Y-%m-%d')}.md")

    cfg = replace(
        cfg,
        sqlite_path=sqlite_path,
        event_bus_sqlite_path=event_bus_path,
        jsonl_path=jsonl_path,
        api_port=int(args.api_port),
        db_batch_size=1,
        db_flush_ms=150,
    )

    virtuals_data = await fetch_virtuals_data(str(args.virtuals_id))
    start_ts = parse_virtuals_timestamp(virtuals_data.get("launchedAt"))
    if not start_ts:
        raise RuntimeError("Virtuals launchedAt is required")
    token_addr = normalize_address(str(virtuals_data.get("preToken") or ""))
    pool_addr = normalize_address(str(virtuals_data.get("preTokenPair") or ""))

    bot = VirtualsBot(cfg, role="all")
    async with bot:
        bot.storage.set_state("runtime_paused", "0")
        bot.refresh_runtime_pause_state(force=True)
        with contextlib.suppress(Exception):
            await bot.price_service.refresh_once()

        ticks, tax_schedule = tax_ticks(bot, virtuals_data=virtuals_data, start_ts=start_ts, end_ts=start_ts + 7200)
        if args.end_mode == "tax-end" and ticks:
            end_ts = ticks[-1]
        else:
            end_ts = start_ts + int(args.duration_minutes * 60)
        ticks, tax_schedule = tax_ticks(bot, virtuals_data=virtuals_data, start_ts=start_ts, end_ts=end_ts)

        project_row = bot.storage.upsert_managed_project(
            project_id=None,
            name=replay_name,
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
            source="event-level-replay",
        )
        bot.set_managed_project_chart_window(project_row)
        bot.sync_launch_config_for_managed_project(project_row)
        bot.sync_runtime_after_managed_project_change()
        launch = bot.build_launch_config_from_managed_project(project_row)
        if not launch:
            raise RuntimeError("failed to build launch config")
        bot.virtuals_launch_info_cache[str(args.virtuals_id)] = {
            "expires_at": time.time() + 3600,
            "payload": dict(virtuals_data),
        }

        logs_url = args.logs_rpc_url or (cfg.backfill_http_rpc_urls or [cfg.http_rpc_url])[0]
        receipt_url = args.receipt_rpc_url or (cfg.backfill_http_rpc_urls or [logs_url])[0]
        stage(
            "rpc_selected",
            history=rpc_label(logs_url),
            receipt=rpc_label(receipt_url),
            endMode=args.end_mode,
            heartbeatSec=int(args.heartbeat_sec),
        )
        logs_rpc = bot.rpc_clients_by_url.get(logs_url) or RPCClient(
            logs_url,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        if logs_rpc not in bot.rpc_clients_by_url.values():
            await logs_rpc.__aenter__()
        receipt_rpc = bot.rpc_clients_by_url.get(receipt_url) or RPCClient(
            receipt_url,
            max_retries=args.max_retries,
            timeout_sec=args.timeout_sec,
        )
        if receipt_rpc not in bot.rpc_clients_by_url.values() and receipt_rpc is not logs_rpc:
            await receipt_rpc.__aenter__()

        block_cache: dict[int, int] = {}
        stage("find_block_window_start")
        from_block = await find_block_gte_timestamp(logs_rpc, start_ts, block_cache)
        to_block = await find_block_lte_timestamp(logs_rpc, end_ts, block_cache)
        stage("find_block_window_done", fromBlock=from_block, toBlock=to_block, blockCount=to_block - from_block + 1)
        stage("prefetch_block_times_start", batchSize=int(args.block_batch_size))
        block_times = await prefetch_block_times_batched(
            logs_url,
            logs_rpc,
            from_block,
            to_block,
            batch_size=int(args.block_batch_size),
            concurrency=args.block_time_concurrency,
            timeout_sec=args.timeout_sec,
        )
        stage("prefetch_block_times_done", blockTimes=len(block_times))
        splits: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        stage("fetch_logs_start")
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
        stage("fetch_logs_done", txCount=len(tx_hashes), splitCount=len(splits), errorCount=len(errors))
        stage("parse_receipts_start", txCount=len(tx_hashes))
        parsed_events, pool_events = await collect_pool_events(
            bot=bot,
            launch=launch,
            tx_hashes=tx_hashes,
            receipt_rpc=receipt_rpc,
            progress_every=args.progress_every,
        )
        stage("parse_receipts_done", poolEvents=len(pool_events), parsedBuyEvents=len(parsed_events))

        clock = FixedReplayClock(start_ts, end_ts)
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

        import types

        bot.derive_managed_project_status = types.MethodType(derive_with_replay_time, bot)
        bot.compute_buy_tax_rate = types.MethodType(compute_tax_with_replay_time, bot)
        bot.get_cached_live_pool_market_snapshot = types.MethodType(historical_snapshot, bot)

        timeline = build_timeline(
            start_ts=start_ts,
            end_ts=end_ts,
            pool_events=pool_events,
            tax_tick_values=ticks,
            heartbeat_sec=max(0, int(args.heartbeat_sec)),
        )
        stage("build_samples_start", timelineCount=len(timeline))
        parsed_cursor = 0
        max_block = 0
        samples: list[dict[str, Any]] = []
        events_by_ts: dict[int, list[str]] = defaultdict(list)
        for item in pool_events:
            ts = int(item.get("blockTimestamp") or 0)
            events_by_ts[ts].append(str(item.get("eventType") or "pool_state_change"))

        for index, item in enumerate(timeline, start=1):
            ts = int(item["timestamp"])
            clock.set(ts)
            batch: list[dict[str, Any]] = []
            while parsed_cursor < len(parsed_events) and int(parsed_events[parsed_cursor]["block_timestamp"]) <= ts:
                event = parsed_events[parsed_cursor]
                batch.append(event)
                max_block = max(max_block, int(event.get("block_number") or 0))
                parsed_cursor += 1
            if batch:
                bot.persist_events_batch(batch, max_block)
            sample = await build_sample(bot, project_row, clock)
            sample["triggerTypes"] = sorted(set(item["triggerTypes"]) | set(events_by_ts.get(ts, [])))
            samples.append(sample)
            with samples_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
            if args.progress_every and index % args.progress_every == 0:
                stage(
                    "sample",
                    processed=index,
                    total=len(timeline),
                    timestamp=ts,
                    triggerTypes=sample["triggerTypes"],
                )

        stage("build_samples_done", sampleCount=len(samples))
        strategy_rules = rules()
        rule_map = {rule.name: rule for rule in strategy_rules}
        results = [evaluate_end_only(samples, rule) for rule in strategy_rules]
        attach_signal_validation(results, samples, rule_map)
        results.sort(key=lambda item: Decimal(str(item.get("finalPnlPct") or "0")), reverse=True)

        event_type_counts = Counter(str(item.get("eventType") or "unknown_pool_event") for item in pool_events)
        report = {
            "scope": "SR event-level replay",
            "readOnly": True,
            "productionDbTouched": False,
            "tradeSent": False,
            "virtualsId": str(args.virtuals_id),
            "project": replay_name,
            "startAt": start_ts,
            "endAt": end_ts,
            "endMode": args.end_mode,
            "fromBlock": from_block,
            "toBlock": to_block,
            "taxSchedule": tax_schedule,
            "heartbeatSec": int(args.heartbeat_sec),
            "rpcProfile": {
                "history": rpc_label(logs_url),
                "receipt": rpc_label(receipt_url),
            },
            "logSplits": splits,
            "logErrors": errors,
            "historicalEthCallSupported": historical_market.historical_eth_call_supported,
            "historicalEthCallFallbackReason": historical_market.fallback_reason,
            "sqlitePath": sqlite_path,
            "samplesPath": str(samples_path),
            "jsonlPath": jsonl_path,
            "counts": {
                "txCount": len(tx_hashes),
                "poolEventCount": len(pool_events),
                "poolEventTypes": dict(event_type_counts),
                "taxTickCount": len(ticks),
                "sampleCount": len(samples),
                "parsedBuyEventCount": len(parsed_events),
                "insertedBuyEventCount": project_event_count(sqlite_path, replay_name),
            },
            "results": results,
            "firstPoolEvents": pool_events[:20],
            "finalSample": samples[-1] if samples else None,
        }
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_report(report, output_md)
        stage(
            "done",
            outputJson=str(output_json),
            outputMd=str(output_md),
            counts=report["counts"],
            bestRule=results[0]["ruleName"] if results else None,
            bestEndPnlPct=results[0]["finalPnlPct"] if results else None,
        )

        if logs_rpc not in bot.rpc_clients_by_url.values():
            await logs_rpc.__aexit__(None, None, None)
        if receipt_rpc not in bot.rpc_clients_by_url.values() and receipt_rpc is not logs_rpc:
            await receipt_rpc.__aexit__(None, None, None)
        return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SR deterministic event-level replay.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--virtuals-id", default="70972")
    parser.add_argument("--replay-name", default="SR_EVENT_REPLAY")
    parser.add_argument("--output-dir", default="data/replay-event-level")
    parser.add_argument("--report-dir", default="docs/phases")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--end-mode", choices=["tax-end", "duration"], default="tax-end")
    parser.add_argument("--duration-minutes", type=float, default=99.0)
    parser.add_argument("--heartbeat-sec", type=int, default=5)
    parser.add_argument("--logs-rpc-url")
    parser.add_argument("--receipt-rpc-url")
    parser.add_argument("--api-port", type=int, default=18081)
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--min-log-chunk-blocks", type=int, default=10)
    parser.add_argument("--block-time-concurrency", type=int, default=12)
    parser.add_argument("--block-batch-size", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
