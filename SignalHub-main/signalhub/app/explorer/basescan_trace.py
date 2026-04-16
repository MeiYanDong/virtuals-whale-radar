from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from signalhub.app.config import Settings


ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ZERO_TOPIC = "0x" + ("0" * 64)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
RPC_TRANSIENT_ERROR_TOKENS = (
    "timeout",
    "timed out",
    "readtimeout",
    "connecttimeout",
    "pooltimeout",
    "read timeout",
    "connect timeout",
    "temporarily unavailable",
    "connection reset",
    "connection refused",
    "server disconnected",
    "502",
    "503",
    "504",
    "gateway",
    "econnreset",
)


@dataclass(slots=True)
class RpcEndpointState:
    url: str
    label: str
    is_public: bool
    supports_basic_rpc: bool | None = None
    supports_historical_blocks: bool | None = None
    supports_logs: bool | None = None
    supports_trace: bool | None = None
    cooldown_until: float = 0.0
    last_error: str = ""
    last_probed_at: float = 0.0


class BaseLaunchTraceService:
    def __init__(self, settings: Settings) -> None:
        self.https_url = settings.chainstack_base_https_url
        self.wss_url = settings.chainstack_base_wss_url
        self.https_urls = self._build_https_pool(settings)
        self.chain_id = settings.base_chain_id
        self.timeout_seconds = settings.request_timeout_seconds
        self.log_chunk_size = max(settings.chainstack_log_chunk_size, 1)
        self.earliest_scan_window_blocks = max(
            settings.chainstack_earliest_scan_window_blocks,
            self.log_chunk_size,
        )
        self.earliest_batch_size = max(settings.chainstack_earliest_batch_size, 1)
        self.pattern_log_limit = max(settings.chainstack_pattern_log_limit, 1)
        self.prelaunch_statuses = {
            self._normalize_status_value(item)
            for item in settings.chainstack_prelaunch_statuses
            if self._normalize_status_value(item)
        }
        self.rpc_quota_cooldown_seconds = settings.chainstack_rpc_quota_cooldown_seconds
        self.rpc_transient_cooldown_seconds = settings.chainstack_rpc_transient_cooldown_seconds
        self.rpc_states = {
            state.url: state
            for state in self.https_urls
        }

    def get_rpc_pool_status(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        now = time.time()
        for state in self.https_urls:
            cooldown_until = state.cooldown_until if state.cooldown_until > now else 0.0
            items.append(
                {
                    "label": state.label,
                    "url": state.url,
                    "is_public": state.is_public,
                    "supports_basic_rpc": state.supports_basic_rpc,
                    "supports_historical_blocks": state.supports_historical_blocks,
                    "supports_logs": state.supports_logs,
                    "supports_trace": state.supports_trace,
                    "cooldown_until": datetime.fromtimestamp(cooldown_until).isoformat()
                    if cooldown_until
                    else None,
                    "last_error": state.last_error or None,
                    "last_probed_at": datetime.fromtimestamp(state.last_probed_at).isoformat()
                    if state.last_probed_at
                    else None,
                }
            )
        return items

    async def probe_rpc_pool(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            for state in self.https_urls:
                await self._probe_endpoint(client, state)
        return self.get_rpc_pool_status()

    def _build_https_pool(self, settings: Settings) -> list[RpcEndpointState]:
        urls: list[RpcEndpointState] = []
        seen: set[str] = set()

        def add(items: tuple[str, ...], *, is_public: bool, prefix: str) -> None:
            index = 0
            for raw in items:
                url = str(raw or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                index += 1
                urls.append(
                    RpcEndpointState(
                        url=url,
                        label=f"{prefix}-{index}",
                        is_public=is_public,
                    )
                )

        add(settings.chainstack_base_https_urls, is_public=False, prefix="chainstack")
        add(settings.chainstack_public_https_urls, is_public=True, prefix="public")
        return urls

    async def trace_token_launch(
        self,
        contract_address: str,
        *,
        launch_time_hint: str | None = None,
        created_time_hint: str | None = None,
        project_status: str | None = None,
    ) -> dict[str, Any]:
        token_contract = self._normalize_address(contract_address)
        if not self.https_url:
            raise RuntimeError("CHAINSTACK_BASE_HTTPS_URL is not configured")

        prefer_prelaunch = self._is_prelaunch_status(project_status)
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            earliest_batch = await self._find_earliest_transfer_batch(
                client,
                token_contract,
                launch_time_hint=launch_time_hint,
                created_time_hint=created_time_hint,
                prefer_prelaunch=prefer_prelaunch,
            )
            earliest_transfer = earliest_batch["logs"][0] if earliest_batch["logs"] else None
            pattern_context = await self._detect_pool_pattern(
                client,
                token_contract,
                earliest_batch["logs"],
            )
            batch_transactions = await self._collect_batch_transactions(
                client,
                token_contract,
                earliest_batch["logs"],
            )
            selected_record = self._select_pattern_record(batch_transactions, pattern_context)
            if selected_record is None:
                selected_record = await self._select_launch_record(
                    client,
                    token_contract,
                    batch_transactions,
                )
        launch_transaction = selected_record.get("transaction", {}) if selected_record else {}
        transaction_receipt = selected_record.get("receipt", {}) if selected_record else {}
        internal_transactions = selected_record.get("internal_transactions", []) if selected_record else []
        launch_candidate = {}
        if pattern_context.get("pattern_found"):
            launch_candidate = self._build_pattern_launch_candidate(
                selected_record=selected_record,
                pattern_context=pattern_context,
            )
        elif selected_record:
            launch_candidate = selected_record.get("launch_candidate", {}) or {}
        if earliest_transfer and not launch_candidate:
            launch_candidate = self._infer_launch_candidate(
                token_contract=token_contract,
                launch_transaction=launch_transaction,
                earliest_transfer=earliest_transfer,
                internal_transactions=internal_transactions,
            )

        notes = [
            "This result is heuristic. It infers a probable launch-market or internal-sale address from the token address's earliest ERC20 transfer block and the traced launch transaction.",
            "Only the earliest ERC20 transfer block is scanned. The service stops after the first chunk that contains token transfer activity.",
            "Within the earliest transfer block, the detector first tries the zero-address mint to intermediate-address to pool-address pattern, then falls back to generic launch-candidate inference.",
            "Within the earliest candidate pool transfers, contract addresses are preferred over EOA candidates whenever on-chain bytecode is detected.",
            "HTTPS RPC is used for historical backfill and trace analysis; WSS is prepared for real-time eth_subscribe log monitoring.",
        ]
        effective_hint = created_time_hint or launch_time_hint
        if effective_hint:
            notes.append(f"Time hint used for earliest-batch window: {effective_hint}")
        if prefer_prelaunch:
            notes.append("Project status matched Pre Launch priority, so earliest transfer scanning was executed in pre-launch priority mode.")
        if earliest_batch["search_mode"] == "transfer":
            notes.append(
                "No mint-from-zero transfer was found inside the earliest scan window, so the trace fell back to the earliest available transfer batch."
            )
        if not earliest_batch["logs"]:
            notes.append("No ERC20 transfer was found inside the configured earliest scan window.")
        if earliest_batch["logs"] and not batch_transactions:
            notes.append("An earliest ERC20 transfer batch was found, but no transaction payload could be resolved from that batch.")
        if earliest_batch["logs"] and not internal_transactions:
            notes.append("No internal call trace was returned for the selected earliest-batch transaction.")
        if not self.wss_url:
            notes.append("CHAINSTACK_BASE_WSS_URL is not configured, so live log subscriptions are not enabled yet.")

        return {
            "token_contract": token_contract,
            "chain_id": self.chain_id,
            "trace_source": "chainstack_base_rpc",
            "transport": {
                "history": "https",
                "subscription": "wss",
                "wss_configured": bool(self.wss_url),
            },
            "scan_policy": {
                "mode": "earliest_erc20_batch",
                "log_chunk_size": self.log_chunk_size,
                "scan_window_blocks": self.earliest_scan_window_blocks,
                "earliest_batch_size": self.earliest_batch_size,
                "pattern_log_limit": self.pattern_log_limit,
                "prelaunch_priority": prefer_prelaunch,
                "project_status": project_status or "",
            },
            "earliest_transfer": earliest_transfer,
            "earliest_transfer_batch": {
                "search_mode": earliest_batch["search_mode"],
                "chunk_start_block": earliest_batch["chunk_start_block"],
                "chunk_end_block": earliest_batch["chunk_end_block"],
                "first_block_number": earliest_batch["first_block_number"],
                "log_count": len(earliest_batch["logs"]),
                "transaction_count": len(batch_transactions),
                "logs": earliest_batch["logs"],
            },
            "pool_pattern": pattern_context,
            "launch_transaction": launch_transaction,
            "transaction_receipt": transaction_receipt,
            "internal_transactions": internal_transactions,
            "launch_candidate": launch_candidate,
            "subscription": self._build_subscription(token_contract),
            "notes": notes,
        }

    async def _find_earliest_transfer_batch(
        self,
        client: httpx.AsyncClient,
        contract_address: str,
        *,
        launch_time_hint: str | None = None,
        created_time_hint: str | None = None,
        prefer_prelaunch: bool,
    ) -> dict[str, Any]:
        latest_block_hex = await self._rpc(client, "eth_blockNumber", [])
        latest_block = self._to_int(latest_block_hex, base=16) or 0
        start_block = await self._estimate_start_block(
            client,
            launch_time_hint=launch_time_hint,
            created_time_hint=created_time_hint,
            latest_block=latest_block,
        )
        end_block = min(start_block + self.earliest_scan_window_blocks - 1, latest_block)

        search_modes = (("mint", True), ("transfer", False))
        if prefer_prelaunch:
            search_modes = (("mint", True), ("transfer", False))

        for search_mode, mint_only in search_modes:
            logs, chunk_start, chunk_end = await self._scan_window_for_first_batch(
                client,
                contract_address,
                start_block=start_block,
                end_block=end_block,
                mint_only=mint_only,
            )
            if logs:
                first_block_number = logs[0].get("block_number")
                if mint_only and first_block_number is not None:
                    first_block_logs = await self._fetch_logs_range(
                        client,
                        contract_address,
                        start_block=first_block_number,
                        end_block=first_block_number,
                        mint_only=False,
                    )
                    first_block_logs = sorted(
                        first_block_logs,
                        key=lambda item: (
                            item.get("block_number") or 0,
                            item.get("transaction_index") or 0,
                            item.get("log_index") or 0,
                        ),
                    )
                else:
                    first_block_logs = self._limit_to_first_block(logs)
                return {
                    "search_mode": search_mode,
                    "chunk_start_block": chunk_start,
                    "chunk_end_block": chunk_end,
                    "first_block_number": first_block_logs[0].get("block_number") if first_block_logs else None,
                    "logs": first_block_logs[: self.earliest_batch_size],
                }

        return {
            "search_mode": "none",
            "chunk_start_block": start_block,
            "chunk_end_block": end_block,
            "first_block_number": None,
            "logs": [],
        }

    async def _scan_window_for_first_batch(
        self,
        client: httpx.AsyncClient,
        contract_address: str,
        *,
        start_block: int,
        end_block: int,
        mint_only: bool,
    ) -> tuple[list[dict[str, Any]], int | None, int | None]:
        current_block = max(start_block, 0)
        while current_block <= end_block:
            current_end = min(current_block + self.log_chunk_size - 1, end_block)
            logs = await self._fetch_logs_range(
                client,
                contract_address,
                start_block=current_block,
                end_block=current_end,
                mint_only=mint_only,
            )
            if logs:
                ordered = sorted(
                    logs,
                    key=lambda item: (
                        item.get("block_number") or 0,
                        item.get("transaction_index") or 0,
                        item.get("log_index") or 0,
                    ),
                )
                return ordered, current_block, current_end
            current_block = current_end + 1
        return [], None, None

    def _limit_to_first_block(self, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not logs:
            return []
        first_block = logs[0].get("block_number")
        return [
            item
            for item in logs
            if item.get("block_number") == first_block
        ]

    async def _detect_pool_pattern(
        self,
        client: httpx.AsyncClient,
        token_contract: str,
        logs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        considered_logs = list(logs[: self.pattern_log_limit])
        if not considered_logs:
            return {
                "pattern_found": False,
                "considered_log_count": 0,
                "considered_logs": [],
            }

        code_cache: dict[tuple[str, int | None], bool] = {}
        for index, log in enumerate(considered_logs):
            middle_address = self._normalize_optional_address(log.get("to_address"))
            if self._normalize_optional_address(log.get("from_address")) != ZERO_ADDRESS:
                continue
            if not middle_address or middle_address.lower() == token_contract.lower():
                continue

            forward_candidates = [
                candidate
                for candidate in considered_logs[index + 1 :]
                if self._normalize_optional_address(candidate.get("from_address")) == middle_address
            ]
            chosen_forward = await self._select_pool_forward_log(
                client,
                token_contract,
                middle_address,
                log,
                forward_candidates,
                code_cache,
            )
            if chosen_forward is None:
                continue

            pool_address = self._normalize_optional_address(chosen_forward.get("to_address"))
            is_contract = bool(chosen_forward.get("recipient_is_contract"))
            return {
                "pattern_found": True,
                "considered_log_count": len(considered_logs),
                "first_block_number": considered_logs[0].get("block_number"),
                "considered_logs": considered_logs,
                "mint_log": log,
                "pool_transfer_log": chosen_forward,
                "intermediate_address": middle_address,
                "pool_address": pool_address,
                "pool_address_is_contract": is_contract,
                "matched_all_tokens": bool(chosen_forward.get("matched_all_tokens")),
            }

        return {
            "pattern_found": False,
            "considered_log_count": len(considered_logs),
            "first_block_number": considered_logs[0].get("block_number"),
            "considered_logs": considered_logs,
        }

    async def _select_pool_forward_log(
        self,
        client: httpx.AsyncClient,
        token_contract: str,
        middle_address: str,
        mint_log: dict[str, Any],
        forward_candidates: list[dict[str, Any]],
        code_cache: dict[tuple[str, int | None], bool],
    ) -> dict[str, Any] | None:
        if not forward_candidates:
            return None

        mint_value = int(mint_log.get("transfer_value") or 0)
        eligible: list[dict[str, Any]] = []
        for candidate in forward_candidates:
            pool_address = self._normalize_optional_address(candidate.get("to_address"))
            if not pool_address:
                continue
            if pool_address.lower() in {ZERO_ADDRESS.lower(), token_contract.lower(), middle_address.lower()}:
                continue
            candidate_value = int(candidate.get("transfer_value") or 0)
            matched_all_tokens = mint_value > 0 and candidate_value == mint_value
            recipient_is_contract = await self._is_contract_address(
                client,
                pool_address,
                candidate.get("block_number"),
                code_cache,
            )
            eligible.append(
                {
                    **candidate,
                    "matched_all_tokens": matched_all_tokens,
                    "recipient_is_contract": recipient_is_contract,
                }
            )

        if not eligible:
            return None

        eligible.sort(
            key=lambda item: (
                0 if item.get("matched_all_tokens") else 1,
                0 if item.get("recipient_is_contract") else 1,
                item.get("transaction_index") or 0,
                item.get("log_index") or 0,
            )
        )
        return eligible[0]

    async def _fetch_logs_range(
        self,
        client: httpx.AsyncClient,
        contract_address: str,
        *,
        start_block: int,
        end_block: int,
        mint_only: bool,
    ) -> list[dict[str, Any]]:
        topics: list[str | None] = [TRANSFER_TOPIC]
        if mint_only:
            topics.append(ZERO_TOPIC)

        filter_payload = {
            "address": contract_address,
            "fromBlock": hex(max(start_block, 0)),
            "toBlock": hex(max(end_block, 0)),
            "topics": topics,
        }
        result = await self._rpc(client, "eth_getLogs", [filter_payload])
        if not isinstance(result, list):
            return []
        return [self._parse_log(item) for item in result if isinstance(item, dict)]

    async def _collect_batch_transactions(
        self,
        client: httpx.AsyncClient,
        token_contract: str,
        logs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        for log in logs[: self.earliest_batch_size]:
            tx_hash = str(log.get("tx_hash") or "").strip()
            if not tx_hash:
                continue
            normalized_hash = tx_hash.lower()
            if normalized_hash in seen_hashes:
                continue
            seen_hashes.add(normalized_hash)

            transaction = await self._fetch_transaction(client, tx_hash)
            receipt = await self._fetch_transaction_receipt(client, tx_hash)
            internal_transactions = await self._fetch_internal_transactions(client, tx_hash)
            launch_candidate = self._infer_launch_candidate(
                token_contract=token_contract,
                launch_transaction=transaction,
                earliest_transfer=log,
                internal_transactions=internal_transactions,
            )
            records.append(
                {
                    "tx_hash": tx_hash,
                    "log": log,
                    "transaction": transaction,
                    "receipt": receipt,
                    "internal_transactions": internal_transactions,
                    "launch_candidate": launch_candidate,
                }
            )

        return records

    def _select_pattern_record(
        self,
        records: list[dict[str, Any]],
        pattern_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not pattern_context.get("pattern_found"):
            return None

        preferred_hashes = [
            str((pattern_context.get("pool_transfer_log") or {}).get("tx_hash") or "").strip().lower(),
            str((pattern_context.get("mint_log") or {}).get("tx_hash") or "").strip().lower(),
        ]
        for preferred_hash in preferred_hashes:
            if not preferred_hash:
                continue
            for record in records:
                if str(record.get("tx_hash") or "").strip().lower() == preferred_hash:
                    return record
        return records[0] if records else None

    def _build_pattern_launch_candidate(
        self,
        *,
        selected_record: dict[str, Any] | None,
        pattern_context: dict[str, Any],
    ) -> dict[str, Any]:
        transaction = (selected_record or {}).get("transaction") or {}
        pool_transfer_log = pattern_context.get("pool_transfer_log") or {}
        mint_log = pattern_context.get("mint_log") or {}
        pool_address = self._normalize_optional_address(pattern_context.get("pool_address"))
        intermediate_address = self._normalize_optional_address(pattern_context.get("intermediate_address"))
        candidates = []
        for address in (
            pool_address,
            intermediate_address,
            self._normalize_optional_address(transaction.get("to")),
        ):
            if not address:
                continue
            if address.lower() in {item.lower() for item in candidates}:
                continue
            candidates.append(address)

        confidence = "high"
        if not pattern_context.get("matched_all_tokens") or not pattern_context.get("pool_address_is_contract"):
            confidence = "medium"

        return {
            "address": pool_address,
            "confidence": confidence,
            "evidence": "zero_to_intermediate_then_forward",
            "launch_sender": self._normalize_optional_address(transaction.get("from")),
            "launch_target": self._normalize_optional_address(transaction.get("to")),
            "mint_recipient": intermediate_address or self._normalize_optional_address(mint_log.get("to_address")),
            "intermediate_address": intermediate_address,
            "candidates": candidates,
            "pool_transfer_tx_hash": pool_transfer_log.get("tx_hash"),
        }

    async def _select_launch_record(
        self,
        client: httpx.AsyncClient,
        token_contract: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        code_cache: dict[tuple[str, int | None], bool] = {}
        for record in records:
            contract_selected = await self._select_contract_candidate(
                client,
                token_contract,
                record,
                code_cache,
            )
            if contract_selected is not None:
                return contract_selected
        for record in records:
            candidate = record.get("launch_candidate") or {}
            if candidate.get("address"):
                return record
        return records[0] if records else None

    async def _select_contract_candidate(
        self,
        client: httpx.AsyncClient,
        token_contract: str,
        record: dict[str, Any],
        code_cache: dict[tuple[str, int | None], bool],
    ) -> dict[str, Any] | None:
        launch_candidate = dict(record.get("launch_candidate") or {})
        candidate_addresses = launch_candidate.get("candidates") or []
        transaction = record.get("transaction") or {}
        log_entry = record.get("log") or {}
        block_number = transaction.get("block_number") or log_entry.get("block_number")
        excluded = {token_contract.lower(), ZERO_ADDRESS.lower()}

        for raw_address in candidate_addresses:
            candidate_address = self._normalize_optional_address(raw_address)
            if not candidate_address:
                continue
            if candidate_address.lower() in excluded:
                continue
            if not await self._is_contract_address(
                client,
                candidate_address,
                block_number,
                code_cache,
            ):
                continue

            return {
                **record,
                "launch_candidate": {
                    **launch_candidate,
                    "address": candidate_address,
                    "confidence": self._promote_contract_confidence(launch_candidate.get("confidence")),
                    "evidence": "earliest_batch_contract_code",
                    "selected_address_is_contract": True,
                },
            }

        return None

    async def _is_contract_address(
        self,
        client: httpx.AsyncClient,
        address: str,
        block_number: int | None,
        code_cache: dict[tuple[str, int | None], bool],
    ) -> bool:
        cache_key = (address.lower(), block_number)
        if cache_key in code_cache:
            return code_cache[cache_key]

        block_ref = hex(block_number) if block_number is not None else "latest"
        try:
            code = await self._rpc(client, "eth_getCode", [address, block_ref])
        except RuntimeError:
            code = await self._rpc(client, "eth_getCode", [address, "latest"])
        is_contract = isinstance(code, str) and code not in {"", "0x", "0x0"}
        code_cache[cache_key] = is_contract
        return is_contract

    def _promote_contract_confidence(self, value: Any) -> str:
        current = str(value or "").strip().lower()
        if current == "high":
            return "high"
        return "medium"

    async def _fetch_transaction(
        self,
        client: httpx.AsyncClient,
        tx_hash: str,
    ) -> dict[str, Any]:
        result = await self._rpc(client, "eth_getTransactionByHash", [tx_hash])
        if not isinstance(result, dict):
            return {}
        return {
            "hash": str(result.get("hash") or "").strip(),
            "from": self._normalize_optional_address(result.get("from")),
            "to": self._normalize_optional_address(result.get("to")),
            "block_number": self._to_int(result.get("blockNumber"), base=16),
            "transaction_index": self._to_int(result.get("transactionIndex"), base=16),
            "value": self._hex_to_decimal(result.get("value")),
            "input": str(result.get("input") or ""),
        }

    async def _fetch_transaction_receipt(
        self,
        client: httpx.AsyncClient,
        tx_hash: str,
    ) -> dict[str, Any]:
        result = await self._rpc(client, "eth_getTransactionReceipt", [tx_hash])
        if not isinstance(result, dict):
            return {}
        return {
            "transaction_hash": str(result.get("transactionHash") or "").strip(),
            "status": self._to_int(result.get("status"), base=16),
            "from": self._normalize_optional_address(result.get("from")),
            "to": self._normalize_optional_address(result.get("to")),
            "contract_address": self._normalize_optional_address(result.get("contractAddress")),
            "gas_used": self._to_int(result.get("gasUsed"), base=16),
            "effective_gas_price": self._to_int(result.get("effectiveGasPrice"), base=16),
        }

    async def _fetch_internal_transactions(
        self,
        client: httpx.AsyncClient,
        tx_hash: str,
    ) -> list[dict[str, Any]]:
        try:
            traced = await self._rpc(
                client,
                "debug_traceTransaction",
                [tx_hash, {"tracer": "callTracer"}],
            )
            items = self._flatten_call_trace(traced)
            if items:
                return items
        except (RuntimeError, httpx.HTTPError):
            pass

        try:
            replayed = await self._rpc(
                client,
                "trace_replayTransaction",
                [tx_hash, ["trace"]],
            )
        except (RuntimeError, httpx.HTTPError):
            return []

        return self._flatten_replay_trace(replayed)

    async def _probe_endpoint(
        self,
        client: httpx.AsyncClient,
        state: RpcEndpointState,
    ) -> None:
        await self._probe_capability(client, state, "basic_rpc")
        await self._probe_capability(client, state, "historical_blocks")
        await self._probe_capability(client, state, "logs")

    async def _probe_capability(
        self,
        client: httpx.AsyncClient,
        state: RpcEndpointState,
        capability: str,
    ) -> None:
        try:
            if capability == "basic_rpc":
                await self._rpc_once(client, state.url, "eth_blockNumber", [])
                self._mark_endpoint_success(state, capability)
                return
            if capability == "historical_blocks":
                latest = await self._rpc_once(client, state.url, "eth_blockNumber", [])
                latest_block = self._to_int(latest, base=16) or 0
                historical_block = max(latest_block - 64, 0)
                await self._rpc_once(client, state.url, "eth_getBlockByNumber", [hex(historical_block), False])
                self._mark_endpoint_success(state, capability)
                return
            if capability == "logs":
                latest = await self._rpc_once(client, state.url, "eth_blockNumber", [])
                latest_block = self._to_int(latest, base=16) or 0
                await self._rpc_once(
                    client,
                    state.url,
                    "eth_getLogs",
                    [{
                        "address": ZERO_ADDRESS,
                        "fromBlock": hex(latest_block),
                        "toBlock": hex(latest_block),
                        "topics": [TRANSFER_TOPIC],
                    }],
                )
                self._mark_endpoint_success(state, capability)
                return
        except RuntimeError as exc:
            self._mark_endpoint_failure(state, capability, str(exc))

    def _required_capability(self, method: str, params: list[Any]) -> str:
        if method == "eth_getLogs":
            return "logs"
        if method in {"debug_traceTransaction", "trace_replayTransaction"}:
            return "trace"
        if method == "eth_getBlockByNumber":
            block_ref = str(params[0] if params else "latest").strip().lower()
            return "basic_rpc" if block_ref == "latest" else "historical_blocks"
        if method == "eth_getCode":
            block_ref = str(params[1] if len(params) > 1 else "latest").strip().lower()
            return "basic_rpc" if block_ref == "latest" else "historical_blocks"
        return "basic_rpc"

    def _ordered_rpc_candidates(self, capability: str) -> list[RpcEndpointState]:
        now = time.time()
        active = [
            state
            for state in self.https_urls
            if state.cooldown_until <= now
        ]
        if not active:
            active = list(self.https_urls)

        def support_rank(state: RpcEndpointState) -> int:
            value = self._capability_value(state, capability)
            if value is True:
                return 0
            if value is None:
                return 1
            return 2

        ordered = sorted(
            active,
            key=lambda state: (
                support_rank(state),
                1 if state.is_public else 0,
                state.cooldown_until,
                state.label,
            ),
        )
        if capability == "basic_rpc":
            return ordered
        supported = [
            state
            for state in ordered
            if self._capability_value(state, capability) is not False
        ]
        return supported or ordered

    def _capability_value(self, state: RpcEndpointState, capability: str) -> bool | None:
        if capability == "basic_rpc":
            return state.supports_basic_rpc
        if capability == "historical_blocks":
            return state.supports_historical_blocks
        if capability == "logs":
            return state.supports_logs
        if capability == "trace":
            return state.supports_trace
        return None

    def _mark_endpoint_success(self, state: RpcEndpointState, capability: str) -> None:
        state.last_probed_at = time.time()
        state.last_error = ""
        state.cooldown_until = 0.0
        if capability == "basic_rpc":
            state.supports_basic_rpc = True
        elif capability == "historical_blocks":
            state.supports_basic_rpc = True
            state.supports_historical_blocks = True
        elif capability == "logs":
            state.supports_basic_rpc = True
            state.supports_logs = True
        elif capability == "trace":
            state.supports_basic_rpc = True
            state.supports_trace = True

    def _mark_endpoint_failure(self, state: RpcEndpointState, capability: str, error_message: str) -> None:
        lowered = error_message.lower()
        state.last_probed_at = time.time()
        state.last_error = error_message
        if self._is_quota_error(lowered):
            state.cooldown_until = time.time() + self.rpc_quota_cooldown_seconds
        elif self._is_transient_error(lowered):
            state.cooldown_until = time.time() + self.rpc_transient_cooldown_seconds

        if self._is_capability_error(lowered):
            if capability == "historical_blocks":
                state.supports_historical_blocks = False
            elif capability == "logs":
                state.supports_logs = False
            elif capability == "trace":
                state.supports_trace = False
            elif capability == "basic_rpc":
                state.supports_basic_rpc = False

    def _is_quota_error(self, lowered: str) -> bool:
        return "quota" in lowered or "request units" in lowered or "monthly ru" in lowered

    def _is_transient_error(self, lowered: str) -> bool:
        return any(token in lowered for token in RPC_TRANSIENT_ERROR_TOKENS)

    def _is_capability_error(self, lowered: str) -> bool:
        return (
            "not available on your current plan" in lowered
            or "method not found" in lowered
            or "does not exist/is not available" in lowered
        )

    async def _rpc_once(
        self,
        client: httpx.AsyncClient,
        url: str,
        method: str,
        params: list[Any],
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        request_timeout = self.timeout_seconds
        if method in {"eth_getLogs", "debug_traceTransaction", "trace_replayTransaction"}:
            request_timeout = max(self.timeout_seconds, 45)
        try:
            response = await client.post(url, json=payload, timeout=request_timeout)
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or repr(exc)
            raise RuntimeError(f"RPC transport error: {detail}") from exc

        raw_text = response.text
        body: dict[str, Any] | None = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body = parsed
        except ValueError:
            body = None

        if response.status_code >= 400:
            if body and body.get("error"):
                detail = body["error"]
                if isinstance(detail, dict):
                    message = detail.get("message") or detail
                else:
                    message = detail
                raise RuntimeError(f"RPC error: {message}")
            raise RuntimeError(f"RPC transport error: HTTP {response.status_code}: {raw_text[:240]}")

        if body is None:
            raise RuntimeError("Unexpected RPC response payload")
        if body.get("error"):
            detail = body["error"]
            if isinstance(detail, dict):
                message = detail.get("message") or detail
            else:
                message = detail
            raise RuntimeError(f"RPC error: {message}")
        return body.get("result")

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
        if not self.https_urls:
            raise RuntimeError("No HTTPS RPC endpoint is configured")

        capability = self._required_capability(method, params)
        last_error = ""
        for state in self._ordered_rpc_candidates(capability):
            try:
                result = await self._rpc_once(client, state.url, method, params)
                self._mark_endpoint_success(state, capability)
                return result
            except RuntimeError as exc:
                last_error = f"{state.label}: {exc}"
                self._mark_endpoint_failure(state, capability, str(exc))
                continue

        if capability == "trace":
            return []
        raise RuntimeError(last_error or f"No available RPC endpoint for capability={capability}")

    def _flatten_call_trace(self, trace: Any, *, depth: int = 0) -> list[dict[str, Any]]:
        if not isinstance(trace, dict):
            return []

        items: list[dict[str, Any]] = []
        for child in trace.get("calls") or []:
            if not isinstance(child, dict):
                continue
            items.append(
                {
                    "type": str(child.get("type") or "").strip(),
                    "from": self._normalize_optional_address(child.get("from")),
                    "to": self._normalize_optional_address(child.get("to")),
                    "value": self._hex_to_decimal(child.get("value")),
                    "input": str(child.get("input") or ""),
                    "depth": depth + 1,
                }
            )
            items.extend(self._flatten_call_trace(child, depth=depth + 1))
        return items

    def _flatten_replay_trace(self, replayed: Any) -> list[dict[str, Any]]:
        if not isinstance(replayed, list):
            return []

        items: list[dict[str, Any]] = []
        for item in replayed:
            if not isinstance(item, dict):
                continue
            action = item.get("action") or {}
            if not isinstance(action, dict):
                continue
            items.append(
                {
                    "type": str(item.get("type") or "").strip(),
                    "from": self._normalize_optional_address(action.get("from")),
                    "to": self._normalize_optional_address(action.get("to")),
                    "value": self._hex_to_decimal(action.get("value")),
                    "input": str(action.get("input") or ""),
                    "depth": int(len(item.get("traceAddress") or [])),
                }
            )
        return items

    def _infer_launch_candidate(
        self,
        *,
        token_contract: str,
        launch_transaction: dict[str, Any],
        earliest_transfer: dict[str, Any] | None,
        internal_transactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        origin_from = self._normalize_optional_address(launch_transaction.get("from"))
        transaction_to = self._normalize_optional_address(launch_transaction.get("to"))
        minted_to = self._normalize_optional_address(
            earliest_transfer.get("to_address") if earliest_transfer else None
        )

        excluded = {token_contract.lower(), ZERO_ADDRESS.lower()}
        if origin_from:
            excluded.add(origin_from.lower())

        internal_targets = [
            address
            for address in (
                self._normalize_optional_address(item.get("to"))
                for item in internal_transactions
            )
            if address and address.lower() not in excluded
        ]

        launch_address = None
        evidence = ""
        confidence = "low"

        if internal_targets:
            launch_address = internal_targets[0]
            evidence = "first_traced_internal_target"
            confidence = "medium"
        elif transaction_to and transaction_to.lower() not in excluded:
            launch_address = transaction_to
            evidence = "launch_transaction_to"
            confidence = "medium"
        elif minted_to and minted_to.lower() not in excluded:
            launch_address = minted_to
            evidence = "earliest_transfer_recipient"
            confidence = "low"

        candidates: list[str] = []
        seen_candidates: set[str] = set()
        for address in [transaction_to, minted_to, *internal_targets]:
            if not address:
                continue
            lowered = address.lower()
            if lowered in seen_candidates:
                continue
            seen_candidates.add(lowered)
            candidates.append(address)

        return {
            "address": launch_address,
            "confidence": confidence,
            "evidence": evidence,
            "launch_sender": origin_from,
            "launch_target": transaction_to,
            "mint_recipient": minted_to,
            "intermediate_address": "",
            "candidates": candidates,
        }

    def _build_subscription(self, contract_address: str) -> dict[str, Any]:
        return {
            "provider": "chainstack",
            "transport": "wss",
            "endpoint_configured": bool(self.wss_url),
            "endpoint": self.wss_url or "",
            "request": {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_subscribe",
                "params": [
                    "logs",
                    {
                        "address": contract_address,
                        "topics": [TRANSFER_TOPIC],
                    },
                ],
            },
        }

    async def _estimate_start_block(
        self,
        client: httpx.AsyncClient,
        *,
        launch_time_hint: str | None,
        created_time_hint: str | None,
        latest_block: int,
    ) -> int:
        target_hint = self._pick_earliest_time_hint(created_time_hint, launch_time_hint)
        if not target_hint:
            return 0

        try:
            launch_dt = datetime.fromisoformat(target_hint.replace("Z", "+00:00"))
        except ValueError:
            return 0

        latest_block_payload = await self._rpc(client, "eth_getBlockByNumber", ["latest", False])
        if not isinstance(latest_block_payload, dict):
            return 0

        latest_timestamp = self._to_int(latest_block_payload.get("timestamp"), base=16)
        latest_block_number = self._to_int(latest_block_payload.get("number"), base=16) or latest_block
        if latest_timestamp is None:
            return 0

        target_timestamp = int(launch_dt.timestamp())
        if target_timestamp >= latest_timestamp:
            return max(latest_block_number - self.log_chunk_size, 0)

        low = 0
        high = latest_block_number
        best = latest_block_number
        while low <= high:
            middle = (low + high) // 2
            block_payload = await self._rpc(client, "eth_getBlockByNumber", [hex(middle), False])
            if not isinstance(block_payload, dict):
                break
            block_timestamp = self._to_int(block_payload.get("timestamp"), base=16)
            block_number = self._to_int(block_payload.get("number"), base=16)
            if block_timestamp is None or block_number is None:
                break
            if block_timestamp >= target_timestamp:
                best = block_number
                high = middle - 1
            else:
                low = middle + 1

        safety_margin = max(self.log_chunk_size * 2, 200)
        return max(best - safety_margin, 0)

    def _pick_earliest_time_hint(
        self,
        created_time_hint: str | None,
        launch_time_hint: str | None,
    ) -> str | None:
        candidates: list[tuple[datetime, str]] = []
        for raw_value in (created_time_hint, launch_time_hint):
            value = str(raw_value or "").strip()
            if not value:
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            candidates.append((parsed, value))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def _parse_log(self, item: dict[str, Any]) -> dict[str, Any]:
        topics = item.get("topics") or []
        return {
            "tx_hash": str(item.get("transactionHash") or "").strip(),
            "block_number": self._to_int(item.get("blockNumber"), base=16),
            "log_index": self._to_int(item.get("logIndex"), base=16),
            "transaction_index": self._to_int(item.get("transactionIndex"), base=16),
            "from_address": self._topic_address(topics[1] if len(topics) > 1 else ""),
            "to_address": self._topic_address(topics[2] if len(topics) > 2 else ""),
            "transfer_value": self._to_int(item.get("data"), base=16) or 0,
            "topics": [str(topic) for topic in topics],
        }

    def _is_prelaunch_status(self, value: Any) -> bool:
        return self._normalize_status_value(value) in self.prelaunch_statuses

    def _normalize_status_value(self, value: Any) -> str:
        text = str(value or "").strip().upper()
        for token in (" ", "-", "_"):
            text = text.replace(token, "")
        return text

    def _normalize_address(self, value: Any) -> str:
        address = str(value or "").strip()
        if not ADDRESS_RE.match(address):
            raise ValueError(f"Invalid EVM address: {value}")
        return address

    def _normalize_optional_address(self, value: Any) -> str | None:
        address = str(value or "").strip()
        if not address or not ADDRESS_RE.match(address):
            return None
        return address

    def _topic_address(self, topic: Any) -> str | None:
        raw = str(topic or "").strip().lower()
        if not raw.startswith("0x") or len(raw) < 42:
            return None
        return self._normalize_optional_address("0x" + raw[-40:])

    def _to_int(self, value: Any, *, base: int = 10) -> int | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return int(raw, base)
        except ValueError:
            return None

    def _hex_to_decimal(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "0"
        try:
            if raw.startswith("0x"):
                return str(int(raw, 16))
            return str(int(raw))
        except ValueError:
            return raw
