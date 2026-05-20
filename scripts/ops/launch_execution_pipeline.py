#!/usr/bin/env python3
"""Launch strategy execution pipeline scaffolding.

Safety boundary:
- default mode is dry-run only;
- this file never broadcasts unless a future caller wires an explicit, tested
  broadcaster with a manual allow flag;
- private keys must not be logged, stored in DB, or passed on the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from backtest_launch_strategy import fmt_decimal, parse_decimal, spot_fdv_wan  # noqa: E402
from sr_event_level_replay import StrategyRule, rules, should_buy  # noqa: E402


@dataclass(frozen=True)
class DynamicExecutionConfig:
    name: str = "dynamic_25v_dip20_after1_flat10_no_cap"
    base_buy_v: Decimal = Decimal("25")
    dip_buy_v: Decimal = Decimal("50")
    dip_from_own_cost_pct: Decimal = Decimal("20")
    flat_pause_pct: Decimal = Decimal("10")
    fdv_limit_enabled: bool = False
    fdv_limit_wan_usd: Decimal | None = None
    pause_after_buy_count: int = 1
    one_buy_per_tax_rate: bool = True


@dataclass
class StrategyState:
    active_tax_key: str | None = None
    active_tax_had_buy: bool = False
    pending_pause_buy: dict[str, Any] | None = None
    bought_tax_rates: set[str] = field(default_factory=set)
    skipped_tax_rates: set[str] = field(default_factory=set)
    total_spent_v: Decimal = Decimal("0")
    weighted_cost_numerator: Decimal = Decimal("0")

    @property
    def own_weighted_cost(self) -> Decimal | None:
        if self.total_spent_v <= 0:
            return None
        return self.weighted_cost_numerator / self.total_spent_v


@dataclass(frozen=True)
class BuyIntent:
    project: str
    index: int
    timestamp: int
    tax_rate: str
    buy_size_v: str
    entry_tax_fdv_wan_usd: str
    entry_spot_fdv_wan_usd: str
    own_weighted_cost_before_wan_usd: str | None
    own_weighted_cost_after_wan_usd: str
    board_spent_v: str
    board_cost_wan_usd: str
    cost_rows: int
    whale_rows: int
    trigger_types: list[str]
    reason: str


@dataclass(frozen=True)
class StrategyDecision:
    action: str
    reason: str
    intent: BuyIntent | None = None
    pause: dict[str, Any] | None = None


@dataclass(frozen=True)
class UnsignedTransaction:
    chain_id: int
    from_addr: str
    to: str
    value_wei: str
    data: str
    nonce: int | None = None
    gas: int | None = None
    max_fee_per_gas: str | None = None
    max_priority_fee_per_gas: str | None = None


@dataclass(frozen=True)
class PoolQuote:
    pool_addr: str
    token_addr: str
    virtual_token_addr: str
    token0: str
    token1: str
    token_decimals: int
    virtual_decimals: int
    token_index: int
    reserve_virtual_wei: str
    reserve_token_raw: str
    amount_in_wei: str
    quoted_amount_out_raw: str
    amount_out_min_wei: str
    slippage_bps: int
    effective_slippage_bps: int
    buy_tax_rate_pct: str | None
    tax_adjusted_amount_out_raw: str
    lp_fee_bps: int
    deadline: int


@dataclass(frozen=True)
class BoundBuyOrder:
    tx: UnsignedTransaction
    quote: PoolQuote


@dataclass(frozen=True)
class SignedTransaction:
    raw_tx: str
    tx_hash: str
    from_addr: str
    to: str
    chain_id: int
    nonce: int
    gas: int
    signing_allowed: bool = True
    broadcast_allowed: bool = False


VIRTUALS_BUY_ROUTER = "0x1a540088125d00dd3990f9da45ca0859af4d3b01"
VIRTUALS_BUY_SPENDER = "0x02fe8ec3d9bbf7318eb54590bcc39198a8b47ded"
VIRTUALS_BUY_SELECTOR = "0x706910ff"
WEI_PER_VIRTUAL = Decimal("1000000000000000000")
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"
ERC20_ALLOWANCE_SELECTOR = "0xdd62ed3e"
ERC20_DECIMALS_SELECTOR = "0x313ce567"
TOKEN0_SELECTOR = "0x0dfe1681"
TOKEN1_SELECTOR = "0xd21220a7"
GET_RESERVES_SELECTOR = "0x0902f1ac"
BPS_DENOMINATOR = 10_000
DEFAULT_LAUNCH_SLIPPAGE_BPS = 5_000
DEFAULT_DEADLINE_OFFSET_SEC = 180
UNISWAP_V2_FEE_BPS = 30
BURNER_PRIVATE_KEY_ENV = "VWR_BURNER_PRIVATE_KEY"


def normalize_hex_address(addr: str) -> str:
    value = str(addr).strip().lower()
    if not value.startswith("0x") or len(value) != 42:
        raise ValueError(f"invalid address: {addr}")
    int(value[2:], 16)
    return value


def uint256_word(value: int) -> str:
    if value < 0:
        raise ValueError("uint256 cannot be negative")
    if value >= 1 << 256:
        raise ValueError("uint256 overflow")
    return f"{value:064x}"


def address_word(addr: str) -> str:
    return "0" * 24 + normalize_hex_address(addr)[2:]


def hex_quantity(value: int | str) -> str:
    numeric = int(value)
    if numeric < 0:
        raise ValueError("hex quantity cannot be negative")
    return hex(numeric)


def parse_rpc_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(str(value), 16)


def parse_rpc_address(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw.startswith("0x") or len(raw) < 42:
        raise ValueError(f"invalid RPC address result: {value}")
    return normalize_hex_address("0x" + raw[-40:])


def normalize_private_key(value: str) -> str:
    key = str(value or "").strip()
    if not key:
        raise ValueError("missing private key")
    if key.startswith("0x"):
        key = key[2:]
    if len(key) != 64:
        raise ValueError("private key must be 32 bytes")
    int(key, 16)
    return "0x" + key


def decimal_v_to_wei(value: Decimal | str) -> int:
    amount = Decimal(str(value))
    raw = amount * WEI_PER_VIRTUAL
    integral = raw.to_integral_value()
    if raw != integral:
        raise ValueError(f"amount has sub-wei precision: {value}")
    return int(integral)


def encode_virtuals_buy_calldata(
    *,
    amount_in_wei: int,
    token_addr: str,
    amount_out_min_wei: int,
    deadline: int,
) -> str:
    return (
        VIRTUALS_BUY_SELECTOR
        + uint256_word(amount_in_wei)
        + address_word(token_addr)
        + uint256_word(amount_out_min_wei)
        + uint256_word(deadline)
    )


def decode_virtuals_buy_calldata(data: str) -> dict[str, Any]:
    raw = str(data).strip().lower()
    if not raw.startswith("0x"):
        raise ValueError("calldata must start with 0x")
    if raw[:10] != VIRTUALS_BUY_SELECTOR:
        raise ValueError(f"unexpected selector: {raw[:10]}")
    body = raw[10:]
    min_body_len = 64 * 4
    if len(body) < min_body_len:
        raise ValueError("calldata is shorter than Virtuals buy fixed arguments")
    words = [body[i : i + 64] for i in range(0, min_body_len, 64)]
    canonical = encode_virtuals_buy_calldata(
        amount_in_wei=int(words[0], 16),
        token_addr="0x" + words[1][-40:],
        amount_out_min_wei=int(words[2], 16),
        deadline=int(words[3], 16),
    )
    tail = body[min_body_len:]
    return {
        "selector": raw[:10],
        "amountInWei": str(int(words[0], 16)),
        "tokenAddress": "0x" + words[1][-40:],
        "amountOutMinWei": str(int(words[2], 16)),
        "deadline": int(words[3], 16),
        "canonicalCalldata": canonical,
        "canonicalBytes": (len(canonical) - 2) // 2,
        "tailHex": tail,
        "tailBytes": len(tail) // 2,
        "exactCanonical": raw == canonical,
        "canonicalPrefix": raw.startswith(canonical),
    }


def encode_erc20_balance_of(owner: str) -> str:
    return ERC20_BALANCE_OF_SELECTOR + address_word(owner)


def encode_erc20_allowance(owner: str, spender: str) -> str:
    return ERC20_ALLOWANCE_SELECTOR + address_word(owner) + address_word(spender)


def get_amount_out_uniswap_v2(
    *,
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    lp_fee_bps: int = UNISWAP_V2_FEE_BPS,
) -> int:
    if amount_in <= 0:
        raise ValueError("amount_in must be positive")
    if reserve_in <= 0 or reserve_out <= 0:
        raise ValueError("pool reserves must be positive")
    if lp_fee_bps < 0 or lp_fee_bps >= BPS_DENOMINATOR:
        raise ValueError("lp_fee_bps out of range")
    amount_in_with_fee = amount_in * (BPS_DENOMINATOR - lp_fee_bps)
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * BPS_DENOMINATOR + amount_in_with_fee
    return numerator // denominator


def apply_slippage_bps(amount_out: int, slippage_bps: int) -> int:
    if amount_out <= 0:
        raise ValueError("amount_out must be positive")
    if slippage_bps < 0 or slippage_bps >= BPS_DENOMINATOR:
        raise ValueError("slippage_bps must be between 0 and 9999")
    return amount_out * (BPS_DENOMINATOR - slippage_bps) // BPS_DENOMINATOR


def buy_tax_rate_to_bps(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        pct = Decimal(str(value))
    except Exception:
        return 0
    if pct <= 0:
        return 0
    bps = int(pct * Decimal(100))
    return max(0, min(BPS_DENOMINATOR - 1, bps))


def tax_adjusted_amount_out(amount_out: int, buy_tax_rate_pct: Any) -> tuple[int, int]:
    tax_bps = buy_tax_rate_to_bps(buy_tax_rate_pct)
    if tax_bps <= 0:
        return amount_out, 0
    keep_bps = BPS_DENOMINATOR - tax_bps
    adjusted = amount_out * keep_bps // BPS_DENOMINATOR
    return adjusted, tax_bps


def combine_tax_and_slippage_bps(slippage_bps: int, tax_bps: int) -> int:
    if tax_bps <= 0:
        return slippage_bps
    keep_after_slippage = BPS_DENOMINATOR - slippage_bps
    keep_after_tax = BPS_DENOMINATOR - tax_bps
    combined_keep = max(1, keep_after_tax * keep_after_slippage // BPS_DENOMINATOR)
    return min(BPS_DENOMINATOR - 1, BPS_DENOMINATOR - combined_keep)


class VirtualsOrderBuilder:
    """Convert a BuyIntent into an unsigned tx.

    The low-level calldata encoder is implemented and covered by historical
    transaction parity tests. The high-level BuyIntent binding remains explicit:
    callers must provide the target token, slippage-derived amountOutMin, and
    deadline before a transaction can be signed.
    """

    def build(self, intent: BuyIntent) -> UnsignedTransaction:
        raise NotImplementedError(
            "BuyIntent must be bound to token/slippage/deadline before building a real order"
        )

    def build_buy(
        self,
        *,
        chain_id: int,
        from_addr: str,
        token_addr: str,
        amount_in_v: Decimal | str,
        amount_out_min_wei: int,
        deadline: int,
        router_addr: str = VIRTUALS_BUY_ROUTER,
    ) -> UnsignedTransaction:
        data = encode_virtuals_buy_calldata(
            amount_in_wei=decimal_v_to_wei(amount_in_v),
            token_addr=token_addr,
            amount_out_min_wei=amount_out_min_wei,
            deadline=deadline,
        )
        return UnsignedTransaction(
            chain_id=int(chain_id),
            from_addr=normalize_hex_address(from_addr),
            to=normalize_hex_address(router_addr),
            value_wei="0",
            data=data,
        )


class VirtualsOrderBinder:
    """Bind a direct Virtuals buy to live pool reserves before simulation."""

    def __init__(
        self,
        rpc: Any,
        *,
        virtual_token_addr: str,
        slippage_bps: int = DEFAULT_LAUNCH_SLIPPAGE_BPS,
        deadline_offset_sec: int = DEFAULT_DEADLINE_OFFSET_SEC,
        lp_fee_bps: int = UNISWAP_V2_FEE_BPS,
        order_builder: VirtualsOrderBuilder | None = None,
    ) -> None:
        if slippage_bps < 0 or slippage_bps >= BPS_DENOMINATOR:
            raise ValueError("slippage_bps must be between 0 and 9999")
        if deadline_offset_sec <= 0:
            raise ValueError("deadline_offset_sec must be positive")
        self.rpc = rpc
        self.virtual_token_addr = normalize_hex_address(virtual_token_addr)
        self.slippage_bps = int(slippage_bps)
        self.deadline_offset_sec = int(deadline_offset_sec)
        self.lp_fee_bps = int(lp_fee_bps)
        self.order_builder = order_builder or VirtualsOrderBuilder()

    async def _call(self, method: str, params: list[Any]) -> Any:
        return await self.rpc.call(method, params)

    async def _eth_call(self, to: str, data: str) -> str:
        return await self._call("eth_call", [{"to": normalize_hex_address(to), "data": data}, "latest"])

    async def _read_decimals(self, token: str) -> int:
        return parse_rpc_int(await self._eth_call(token, ERC20_DECIMALS_SELECTOR))

    async def _read_pool_layout(self, *, token_addr: str, pool_addr: str) -> dict[str, Any]:
        token = normalize_hex_address(token_addr)
        pool = normalize_hex_address(pool_addr)
        reserves_hex, token0_result, token1_result = await asyncio.gather(
            self._eth_call(pool, GET_RESERVES_SELECTOR),
            self._eth_call(pool, TOKEN0_SELECTOR),
            self._eth_call(pool, TOKEN1_SELECTOR),
            return_exceptions=True,
        )
        if isinstance(reserves_hex, Exception):
            raise reserves_hex
        data = str(reserves_hex or "")[2:]
        if len(data) < 64 * 2:
            raise ValueError("getReserves response is too short")
        reserve0 = int(data[0:64], 16)
        reserve1 = int(data[64:128], 16)
        if reserve0 <= 0 or reserve1 <= 0:
            raise ValueError("pool reserves are empty")

        try:
            if isinstance(token0_result, Exception) or isinstance(token1_result, Exception):
                raise ValueError("pool token layout unavailable")
            token0 = parse_rpc_address(token0_result)
            token1 = parse_rpc_address(token1_result)
        except Exception:
            token0 = None
            token1 = None

        if token0 and token1 and {token0, token1} != {token, self.virtual_token_addr}:
            raise ValueError("pool token0/token1 do not match target token and VIRTUAL")

        if token0 and token1:
            token0_decimals, token1_decimals = await asyncio.gather(
                self._read_decimals(token0),
                self._read_decimals(token1),
            )
            if token0 == self.virtual_token_addr:
                return {
                    "token0": token0,
                    "token1": token1,
                    "token_index": 1,
                    "token_decimals": token1_decimals,
                    "virtual_decimals": token0_decimals,
                    "reserve_virtual": reserve0,
                    "reserve_token": reserve1,
                }
            return {
                "token0": token0,
                "token1": token1,
                "token_index": 0,
                "token_decimals": token0_decimals,
                "virtual_decimals": token1_decimals,
                "reserve_virtual": reserve1,
                "reserve_token": reserve0,
            }

        token_decimals, virtual_decimals = await asyncio.gather(
            self._read_decimals(token),
            self._read_decimals(self.virtual_token_addr),
        )
        reserve0_as_token = Decimal(reserve0) / (Decimal(10) ** token_decimals)
        reserve1_as_virtual = Decimal(reserve1) / (Decimal(10) ** virtual_decimals)
        reserve1_as_token = Decimal(reserve1) / (Decimal(10) ** token_decimals)
        reserve0_as_virtual = Decimal(reserve0) / (Decimal(10) ** virtual_decimals)

        def fallback_score(token_reserve: Decimal, virtual_reserve: Decimal) -> tuple[int, Decimal]:
            score = 0
            if token_reserve > 0 and virtual_reserve > 0:
                score += 1
            if token_reserve > virtual_reserve:
                score += 2
            if virtual_reserve <= Decimal("1000000"):
                score += 1
            ratio = token_reserve / virtual_reserve if virtual_reserve > 0 else Decimal(0)
            return score, ratio

        left_score, left_ratio = fallback_score(reserve0_as_token, reserve1_as_virtual)
        right_score, right_ratio = fallback_score(reserve1_as_token, reserve0_as_virtual)
        choose_left = left_score > right_score or (left_score == right_score and left_ratio >= right_ratio)
        if choose_left:
            return {
                "token0": token,
                "token1": self.virtual_token_addr,
                "token_index": 0,
                "token_decimals": token_decimals,
                "virtual_decimals": virtual_decimals,
                "reserve_virtual": reserve1,
                "reserve_token": reserve0,
            }
        return {
            "token0": self.virtual_token_addr,
            "token1": token,
            "token_index": 1,
            "token_decimals": token_decimals,
            "virtual_decimals": virtual_decimals,
            "reserve_virtual": reserve0,
            "reserve_token": reserve1,
        }

    async def bind_buy(
        self,
        *,
        chain_id: int,
        from_addr: str,
        token_addr: str,
        pool_addr: str,
        amount_in_v: Decimal | str,
        buy_tax_rate_pct: Any = None,
        now_ts: int | None = None,
    ) -> BoundBuyOrder:
        token = normalize_hex_address(token_addr)
        pool = normalize_hex_address(pool_addr)
        amount_in_wei = decimal_v_to_wei(amount_in_v)
        layout = await self._read_pool_layout(token_addr=token, pool_addr=pool)
        quoted_amount_out = get_amount_out_uniswap_v2(
            amount_in=amount_in_wei,
            reserve_in=int(layout["reserve_virtual"]),
            reserve_out=int(layout["reserve_token"]),
            lp_fee_bps=self.lp_fee_bps,
        )
        adjusted_amount_out, tax_bps = tax_adjusted_amount_out(quoted_amount_out, buy_tax_rate_pct)
        amount_out_min = apply_slippage_bps(adjusted_amount_out, self.slippage_bps)
        if amount_out_min <= 0:
            raise ValueError("amountOutMin resolved to zero")
        effective_slippage_bps = combine_tax_and_slippage_bps(self.slippage_bps, tax_bps)
        deadline = int(now_ts if now_ts is not None else time.time()) + self.deadline_offset_sec
        tx = self.order_builder.build_buy(
            chain_id=chain_id,
            from_addr=from_addr,
            token_addr=token,
            amount_in_v=amount_in_v,
            amount_out_min_wei=amount_out_min,
            deadline=deadline,
        )
        quote = PoolQuote(
            pool_addr=pool,
            token_addr=token,
            virtual_token_addr=self.virtual_token_addr,
            token0=str(layout["token0"]),
            token1=str(layout["token1"]),
            token_decimals=int(layout["token_decimals"]),
            virtual_decimals=int(layout["virtual_decimals"]),
            token_index=int(layout["token_index"]),
            reserve_virtual_wei=str(layout["reserve_virtual"]),
            reserve_token_raw=str(layout["reserve_token"]),
            amount_in_wei=str(amount_in_wei),
            quoted_amount_out_raw=str(quoted_amount_out),
            amount_out_min_wei=str(amount_out_min),
            slippage_bps=self.slippage_bps,
            effective_slippage_bps=effective_slippage_bps,
            buy_tax_rate_pct=str(buy_tax_rate_pct) if buy_tax_rate_pct not in (None, "") else None,
            tax_adjusted_amount_out_raw=str(adjusted_amount_out),
            lp_fee_bps=self.lp_fee_bps,
            deadline=deadline,
        )
        return BoundBuyOrder(tx=tx, quote=quote)


class TxSimulator:
    def __init__(self, rpc: Any, *, virtual_token_addr: str, spender_addr: str = VIRTUALS_BUY_SPENDER) -> None:
        self.rpc = rpc
        self.virtual_token_addr = normalize_hex_address(virtual_token_addr)
        self.spender_addr = normalize_hex_address(spender_addr)

    async def _call(self, method: str, params: list[Any]) -> Any:
        return await self.rpc.call(method, params)

    async def erc20_balance_of(self, owner: str) -> int:
        result = await self._call(
            "eth_call",
            [{"to": self.virtual_token_addr, "data": encode_erc20_balance_of(owner)}, "latest"],
        )
        return parse_rpc_int(result)

    async def erc20_allowance(self, owner: str, spender: str | None = None) -> int:
        result = await self._call(
            "eth_call",
            [
                {
                    "to": self.virtual_token_addr,
                    "data": encode_erc20_allowance(owner, spender or self.spender_addr),
                },
                "latest",
            ],
        )
        return parse_rpc_int(result)

    async def transaction_count(self, owner: str) -> int:
        return parse_rpc_int(await self._call("eth_getTransactionCount", [normalize_hex_address(owner), "pending"]))

    def tx_payload(self, tx: UnsignedTransaction) -> dict[str, Any]:
        return {
            "from": normalize_hex_address(tx.from_addr),
            "to": normalize_hex_address(tx.to),
            "value": hex_quantity(tx.value_wei),
            "data": tx.data,
        }

    async def _try_rpc(self, method: str, params: list[Any]) -> dict[str, Any]:
        try:
            result = await self._call(method, params)
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def simulate(self, tx: UnsignedTransaction, *, now_ts: int | None = None) -> dict[str, Any]:
        payload = self.tx_payload(tx)
        decoded = decode_virtuals_buy_calldata(tx.data)
        amount_in_wei = int(decoded["amountInWei"])
        amount_out_min_wei = int(decoded["amountOutMinWei"])
        deadline = int(decoded["deadline"])
        now = int(now_ts if now_ts is not None else time.time())

        balance, allowance, nonce, eth_call_result, estimate_gas_result = await asyncio.gather(
            self.erc20_balance_of(tx.from_addr),
            self.erc20_allowance(tx.from_addr, self.spender_addr),
            self.transaction_count(tx.from_addr),
            self._try_rpc("eth_call", [payload, "latest"]),
            self._try_rpc("eth_estimateGas", [payload]),
        )

        checks = {
            "deadline": {
                "ok": deadline > now,
                "deadline": deadline,
                "now": now,
                "secondsRemaining": deadline - now,
            },
            "amountOutMin": {
                "ok": amount_out_min_wei > 0,
                "amountOutMinWei": str(amount_out_min_wei),
            },
            "balance": {
                "ok": balance >= amount_in_wei,
                "balanceWei": str(balance),
                "requiredWei": str(amount_in_wei),
            },
            "allowance": {
                "ok": allowance >= amount_in_wei,
                "allowanceWei": str(allowance),
                "requiredWei": str(amount_in_wei),
                "spender": self.spender_addr,
            },
            "nonce": {
                "ok": nonce >= 0,
                "pendingNonce": nonce,
            },
            "ethCall": {
                "ok": eth_call_result["ok"],
                **({"result": eth_call_result["result"]} if eth_call_result["ok"] else {"error": eth_call_result["error"]}),
            },
            "estimateGas": {
                "ok": estimate_gas_result["ok"],
                **(
                    {"gas": str(parse_rpc_int(estimate_gas_result["result"]))}
                    if estimate_gas_result["ok"]
                    else {"error": estimate_gas_result["error"]}
                ),
            },
        }
        green = all(check["ok"] for check in checks.values())
        return {
            "green": green,
            "tradeSent": False,
            "chainId": tx.chain_id,
            "from": normalize_hex_address(tx.from_addr),
            "to": normalize_hex_address(tx.to),
            "valueWei": str(int(tx.value_wei)),
            "decodedBuy": decoded,
            "checks": checks,
            "signingAllowed": False,
            "broadcastAllowed": False,
        }


class LocalSigner:
    def __init__(self, *, private_key_env: str = BURNER_PRIVATE_KEY_ENV) -> None:
        self.private_key_env = private_key_env

    def _load_account(self) -> Any:
        try:
            from eth_account import Account
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("eth-account is required for local signing") from exc
        private_key = normalize_private_key(os.environ.get(self.private_key_env, ""))
        return Account.from_key(private_key)

    @staticmethod
    def recover_sender(raw_tx: str) -> str:
        try:
            from eth_account import Account
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("eth-account is required for local signing") from exc
        return normalize_hex_address(Account.recover_transaction(raw_tx))

    def sign(self, tx: UnsignedTransaction) -> SignedTransaction:
        decoded = decode_virtuals_buy_calldata(tx.data)
        if int(decoded["amountOutMinWei"]) <= 0:
            raise ValueError("refuse to sign transaction with amountOutMin=0")
        if tx.nonce is None:
            raise ValueError("refuse to sign transaction without nonce")
        if tx.gas is None:
            raise ValueError("refuse to sign transaction without gas")
        if tx.max_fee_per_gas is None or tx.max_priority_fee_per_gas is None:
            raise ValueError("refuse to sign transaction without EIP-1559 fee fields")

        account = self._load_account()
        account_addr = normalize_hex_address(account.address)
        expected_from = normalize_hex_address(tx.from_addr)
        if account_addr != expected_from:
            raise ValueError("burner private key does not match transaction from address")

        try:
            from eth_utils import to_checksum_address
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("eth-utils is required for local signing") from exc

        payload = {
            "type": 2,
            "chainId": int(tx.chain_id),
            "nonce": int(tx.nonce),
            "to": to_checksum_address(normalize_hex_address(tx.to)),
            "value": int(tx.value_wei),
            "data": tx.data,
            "gas": int(tx.gas),
            "maxFeePerGas": int(tx.max_fee_per_gas),
            "maxPriorityFeePerGas": int(tx.max_priority_fee_per_gas),
        }
        signed = account.sign_transaction(payload)
        raw_bytes = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        raw_tx = "0x" + bytes(raw_bytes).hex()
        tx_hash_bytes = getattr(signed, "hash")
        tx_hash = "0x" + bytes(tx_hash_bytes).hex()
        recovered = self.recover_sender(raw_tx)
        if recovered != expected_from:
            raise ValueError("signed transaction recover check failed")
        return SignedTransaction(
            raw_tx=raw_tx,
            tx_hash=tx_hash,
            from_addr=expected_from,
            to=normalize_hex_address(tx.to),
            chain_id=int(tx.chain_id),
            nonce=int(tx.nonce),
            gas=int(tx.gas),
        )


class SafeBroadcaster:
    def __init__(self, *, allow_broadcast: bool = False) -> None:
        self.allow_broadcast = allow_broadcast

    def broadcast(self, raw_tx: str) -> str:
        if not self.allow_broadcast:
            raise RuntimeError("broadcast disabled: missing explicit manual allow flag")
        raise NotImplementedError("Broadcast path is not wired in this scaffold")


def load_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def decimal_ratio_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous <= 0:
        return None
    return abs(current - previous) / previous * Decimal("100")


def tax_number(value: Any) -> Decimal | None:
    parsed = parse_decimal(value)
    return parsed if parsed is not None else None


def is_next_tax_period(previous_tax: Any, current_tax: Any) -> bool:
    previous = tax_number(previous_tax)
    current = tax_number(current_tax)
    if previous is None or current is None:
        return False
    return previous - current == Decimal("1")


def resolve_rule(name: str) -> StrategyRule:
    for rule in rules():
        if rule.name == name:
            return rule
    raise ValueError(f"unknown strategy rule: {name}")


def make_intent(
    *,
    project: str,
    index: int,
    row: dict[str, Any],
    entry: Decimal,
    buy_size: Decimal,
    own_cost_before: Decimal | None,
    own_cost_after: Decimal,
    reason: str,
) -> BuyIntent:
    return BuyIntent(
        project=project,
        index=index,
        timestamp=int(row.get("simTimestamp") or 0),
        tax_rate=str(row.get("buyTaxRate")),
        buy_size_v=fmt_decimal(buy_size, 6),
        entry_tax_fdv_wan_usd=fmt_decimal(entry, 6),
        entry_spot_fdv_wan_usd=fmt_decimal(spot_fdv_wan(row), 6),
        own_weighted_cost_before_wan_usd=fmt_decimal(own_cost_before, 6)
        if own_cost_before is not None
        else None,
        own_weighted_cost_after_wan_usd=fmt_decimal(own_cost_after, 6),
        board_spent_v=fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal("0"), 3),
        board_cost_wan_usd=fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
        cost_rows=int(row.get("costRows") or 0),
        whale_rows=int(row.get("whaleRows") or 0),
        trigger_types=list(row.get("triggerTypes") or []),
        reason=reason,
    )


class DynamicAfter1StrategyEvaluator:
    def __init__(self, *, project: str, rule: StrategyRule, config: DynamicExecutionConfig | None = None) -> None:
        self.project = project
        self.rule = rule
        self.config = config or DynamicExecutionConfig()
        self.state = StrategyState()

    def on_tax_change(self, tax_key: str) -> None:
        if tax_key == self.state.active_tax_key:
            return
        if self.state.active_tax_key is not None and not self.state.active_tax_had_buy:
            self.state.pending_pause_buy = None
        self.state.active_tax_key = tax_key
        self.state.active_tax_had_buy = False

    def evaluate(self, row: dict[str, Any], *, index: int) -> StrategyDecision:
        tax_key = str(row.get("buyTaxRate"))
        self.on_tax_change(tax_key)

        ok, reason = should_buy(row, self.rule)
        if not ok:
            return StrategyDecision("skip", reason)
        if self.config.one_buy_per_tax_rate and tax_key in self.state.bought_tax_rates:
            return StrategyDecision("skip", "same_tax_period")
        if tax_key in self.state.skipped_tax_rates:
            return StrategyDecision("skip", "flat_pause_tax_period")

        entry = parse_decimal(row.get("estimatedFdvWanUsdWithTax"))
        if entry is None or entry <= 0:
            return StrategyDecision("skip", "missing_entry_fdv")
        if self.config.fdv_limit_enabled:
            limit = self.config.fdv_limit_wan_usd
            if limit is None or limit <= 0:
                return StrategyDecision("skip", "fdv_limit_not_configured")
            if entry > limit:
                return StrategyDecision("skip", "fdv_limit_not_met")

        pending = self.state.pending_pause_buy
        if pending and is_next_tax_period(pending.get("taxRate"), tax_key):
            previous_entry = parse_decimal(pending.get("entryTaxFdvWanUsd"))
            change_pct = decimal_ratio_change(entry, previous_entry) if previous_entry is not None else None
            if change_pct is not None and change_pct <= self.config.flat_pause_pct:
                self.state.skipped_tax_rates.add(tax_key)
                self.state.pending_pause_buy = None
                self.state.active_tax_had_buy = False
                pause = {
                    "index": index,
                    "timestamp": int(row.get("simTimestamp") or 0),
                    "taxRate": tax_key,
                    "taxFdvWanUsd": fmt_decimal(entry, 6),
                    "previousBuyTaxFdvWanUsd": fmt_decimal(previous_entry, 6),
                    "fdvChangePct": fmt_decimal(change_pct, 4),
                    "boardSpentV": fmt_decimal(parse_decimal(row.get("boardSpentV")) or Decimal("0"), 3),
                    "boardCostWanUsd": fmt_decimal(parse_decimal(row.get("boardCostWanUsd")), 6),
                    "triggerTypes": list(row.get("triggerTypes") or []),
                }
                return StrategyDecision("pause", "flat_pause_tax_period", pause=pause)
        elif pending and not is_next_tax_period(pending.get("taxRate"), tax_key):
            self.state.pending_pause_buy = None

        own_cost_before = self.state.own_weighted_cost
        if (
            own_cost_before is not None
            and entry <= own_cost_before * (Decimal("1") - self.config.dip_from_own_cost_pct / Decimal("100"))
        ):
            buy_size = self.config.dip_buy_v
            size_reason = "dip20_double"
        else:
            buy_size = self.config.base_buy_v
            size_reason = "base25"

        self.state.total_spent_v += buy_size
        self.state.weighted_cost_numerator += buy_size * entry
        own_cost_after = self.state.own_weighted_cost or entry
        intent = make_intent(
            project=self.project,
            index=index,
            row=row,
            entry=entry,
            buy_size=buy_size,
            own_cost_before=own_cost_before,
            own_cost_after=own_cost_after,
            reason=size_reason,
        )
        self.state.bought_tax_rates.add(tax_key)
        self.state.active_tax_had_buy = True
        self.state.pending_pause_buy = {
            "taxRate": intent.tax_rate,
            "entryTaxFdvWanUsd": intent.entry_tax_fdv_wan_usd,
        }
        return StrategyDecision("would_buy", "signal", intent=intent)


def run_dry_run(*, project: str, samples: list[dict[str, Any]], rule: StrategyRule) -> dict[str, Any]:
    evaluator = DynamicAfter1StrategyEvaluator(project=project, rule=rule)
    decisions: list[dict[str, Any]] = []
    intents: list[dict[str, Any]] = []
    pauses: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()

    for index, row in enumerate(samples):
        decision = evaluator.evaluate(row, index=index)
        reasons[f"{decision.action}:{decision.reason}"] += 1
        if decision.intent is not None:
            payload = asdict(decision.intent)
            intents.append(payload)
            decisions.append({"action": decision.action, "reason": decision.reason, "intent": payload})
        elif decision.pause is not None:
            pauses.append(decision.pause)
            decisions.append({"action": decision.action, "reason": decision.reason, "pause": decision.pause})

    final_spot = spot_fdv_wan(samples[-1]) if samples else None
    final_value = Decimal("0")
    total_spent = Decimal("0")
    for intent in intents:
        entry = parse_decimal(intent.get("entry_tax_fdv_wan_usd"))
        size_v = parse_decimal(intent.get("buy_size_v")) or Decimal("0")
        total_spent += size_v
        if entry is not None and entry > 0 and final_spot is not None:
            final_value += size_v * final_spot / entry

    final_pnl = final_value - total_spent
    final_pnl_pct = final_pnl / total_spent * Decimal("100") if total_spent > 0 else Decimal("0")
    return {
        "project": project,
        "ruleName": rule.name,
        "strategy": DynamicExecutionConfig().name,
        "readOnly": True,
        "tradeSent": False,
        "buyIntentCount": len(intents),
        "pauseCount": len(pauses),
        "totalIntentV": fmt_decimal(total_spent, 6),
        "ownWeightedCostWanUsd": fmt_decimal(evaluator.state.own_weighted_cost, 6)
        if evaluator.state.own_weighted_cost is not None
        else None,
        "finalSpotFdvWanUsd": fmt_decimal(final_spot, 6),
        "finalValueV": fmt_decimal(final_value, 6),
        "finalPnlV": fmt_decimal(final_pnl, 6),
        "finalPnlPct": fmt_decimal(final_pnl_pct, 4),
        "intents": intents,
        "pauses": pauses,
        "decisionSample": decisions[:50],
        "reasonCounts": dict(reasons),
        "executionStages": {
            "strategyEvaluator": "implemented",
            "orderBuilder": "direct_buy_calldata_and_live_pool_amount_out_min_binding_implemented",
            "txSimulator": "implemented_read_only_requires_nonzero_amount_out_min",
            "localSigner": "blocked_until_simulation_green_and_burner_secret_config",
            "broadcaster": "disabled_until_manual_canary_gate",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch execution pipeline scaffold.")
    parser.add_argument("--samples-path", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--rule", default="gate_5k_tax89_fdv_one_per_tax")
    parser.add_argument("--output-json", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    samples = load_samples(Path(args.samples_path))
    report = run_dry_run(project=str(args.project), samples=samples, rule=resolve_rule(str(args.rule)))
    output = Path(args.output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "outputJson": str(output),
                "project": report["project"],
                "ruleName": report["ruleName"],
                "buyIntentCount": report["buyIntentCount"],
                "pauseCount": report["pauseCount"],
                "totalIntentV": report["totalIntentV"],
                "finalPnlPct": report["finalPnlPct"],
                "tradeSent": report["tradeSent"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
