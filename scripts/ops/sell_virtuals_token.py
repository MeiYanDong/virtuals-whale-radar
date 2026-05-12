#!/usr/bin/env python3
"""Sell a Virtuals launch token back to VIRTUAL through the direct router.

Safety defaults:
- exact token amount, no max approvals here;
- private key only from ignored local secret file;
- simulation must be green before signing;
- requires --broadcast for on-chain submission;
- no raw transaction output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import (  # noqa: E402
    elapsed_ms,
    load_secret_file,
    read_allowance,
    read_erc20_balance,
    suggest_fees,
    wait_receipt,
)
from execution_rpc import require_isolated_execution_rpc, resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    PoolQuote,
    UnsignedTransaction,
    VIRTUALS_BUY_ROUTER,
    VIRTUALS_BUY_SPENDER,
    address_word,
    apply_slippage_bps,
    get_amount_out_uniswap_v2,
    hex_quantity,
    normalize_hex_address,
    uint256_word,
    VirtualsOrderBinder,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


VIRTUALS_SELL_SELECTOR = "0xb233e056"
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sell a Virtuals launch token back to VIRTUAL.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address", required=True)
    parser.add_argument("--project-label", required=True)
    parser.add_argument("--amount-raw", default="max")
    parser.add_argument("--spender-address", default=VIRTUALS_BUY_SPENDER)
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--no-wait-receipt", action="store_true")
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--output-json")
    return parser.parse_args()


def encode_virtuals_sell_calldata(
    *,
    amount_in_raw: int,
    token_addr: str,
    amount_out_min_wei: int,
    deadline: int,
) -> str:
    return (
        VIRTUALS_SELL_SELECTOR
        + uint256_word(amount_in_raw)
        + address_word(token_addr)
        + uint256_word(amount_out_min_wei)
        + uint256_word(deadline)
    )


def topic_address(topic: str) -> str:
    return "0x" + str(topic)[-40:].lower()


def receipt_sell_deltas(
    receipt: dict[str, Any] | None,
    *,
    owner: str,
    virtual_token: str,
    sold_token: str,
) -> dict[str, Any]:
    owner = normalize_hex_address(owner)
    virtual_token = normalize_hex_address(virtual_token)
    sold_token = normalize_hex_address(sold_token)
    token_spent = 0
    virtual_received = 0
    transfer_logs: list[dict[str, str]] = []

    for log in (receipt or {}).get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC0:
            continue
        token = normalize_hex_address(str(log.get("address") or ""))
        from_addr = topic_address(str(topics[1]))
        to_addr = topic_address(str(topics[2]))
        amount = int(str(log.get("data") or "0x0"), 16)
        if token == sold_token and from_addr == owner:
            token_spent += amount
        if token == virtual_token and to_addr == owner:
            virtual_received += amount
        if token in {virtual_token, sold_token}:
            transfer_logs.append(
                {
                    "token": token,
                    "from": from_addr,
                    "to": to_addr,
                    "amountRaw": str(amount),
                }
            )
    return {
        "soldTokenSpentRaw": str(token_spent),
        "virtualReceivedWei": str(virtual_received),
        "transferLogs": transfer_logs,
    }


async def bind_sell(
    rpc: RPCClient,
    *,
    chain_id: int,
    from_addr: str,
    token_addr: str,
    pool_addr: str,
    virtual_token_addr: str,
    amount_raw: int,
    slippage_bps: int,
    deadline_offset_sec: int,
    now_ts: int | None = None,
) -> tuple[UnsignedTransaction, PoolQuote]:
    binder = VirtualsOrderBinder(
        rpc,
        virtual_token_addr=virtual_token_addr,
        slippage_bps=slippage_bps,
        deadline_offset_sec=deadline_offset_sec,
    )
    layout = await binder._read_pool_layout(token_addr=token_addr, pool_addr=pool_addr)
    quoted_amount_out = get_amount_out_uniswap_v2(
        amount_in=amount_raw,
        reserve_in=int(layout["reserve_token"]),
        reserve_out=int(layout["reserve_virtual"]),
    )
    amount_out_min = apply_slippage_bps(quoted_amount_out, slippage_bps)
    if amount_out_min <= 0:
        raise ValueError("amountOutMin resolved to zero")
    deadline = int(now_ts if now_ts is not None else time.time()) + int(deadline_offset_sec)
    token = normalize_hex_address(token_addr)
    tx = UnsignedTransaction(
        chain_id=int(chain_id),
        from_addr=normalize_hex_address(from_addr),
        to=normalize_hex_address(VIRTUALS_BUY_ROUTER),
        value_wei="0",
        data=encode_virtuals_sell_calldata(
            amount_in_raw=amount_raw,
            token_addr=token,
            amount_out_min_wei=amount_out_min,
            deadline=deadline,
        ),
    )
    quote = PoolQuote(
        pool_addr=normalize_hex_address(pool_addr),
        token_addr=token,
        virtual_token_addr=normalize_hex_address(virtual_token_addr),
        token0=str(layout["token0"]),
        token1=str(layout["token1"]),
        token_decimals=int(layout["token_decimals"]),
        virtual_decimals=int(layout["virtual_decimals"]),
        token_index=int(layout["token_index"]),
        reserve_virtual_wei=str(layout["reserve_virtual"]),
        reserve_token_raw=str(layout["reserve_token"]),
        amount_in_wei=str(amount_raw),
        quoted_amount_out_raw=str(quoted_amount_out),
        amount_out_min_wei=str(amount_out_min),
        slippage_bps=int(slippage_bps),
        lp_fee_bps=30,
        deadline=deadline,
    )
    return tx, quote


async def simulate_sell(
    rpc: RPCClient,
    *,
    tx: UnsignedTransaction,
    token_addr: str,
    owner: str,
    spender: str,
    amount_raw: int,
    now_ts: int | None = None,
) -> dict[str, Any]:
    payload = {
        "from": normalize_hex_address(tx.from_addr),
        "to": normalize_hex_address(tx.to),
        "value": hex_quantity(tx.value_wei),
        "data": tx.data,
    }
    now = int(now_ts if now_ts is not None else time.time())
    deadline = int(tx.data[-64:], 16)
    balance_task = read_erc20_balance(rpc, token=token_addr, owner=owner)
    allowance_task = read_allowance(rpc, token=token_addr, owner=owner, spender=spender)
    nonce_task = rpc.call("eth_getTransactionCount", [normalize_hex_address(owner), "pending"])

    async def try_rpc(method: str, params: list[Any]) -> dict[str, Any]:
        try:
            return {"ok": True, "result": await rpc.call(method, params)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    balance, allowance, nonce_hex, eth_call_result, estimate_gas_result = await asyncio.gather(
        balance_task,
        allowance_task,
        nonce_task,
        try_rpc("eth_call", [payload, "latest"]),
        try_rpc("eth_estimateGas", [payload]),
    )
    nonce = int(str(nonce_hex), 16)
    checks = {
        "deadline": {"ok": deadline > now, "deadline": deadline, "now": now, "secondsRemaining": deadline - now},
        "balance": {"ok": balance >= amount_raw, "balanceRaw": str(balance), "requiredRaw": str(amount_raw)},
        "allowance": {
            "ok": allowance >= amount_raw,
            "allowanceRaw": str(allowance),
            "requiredRaw": str(amount_raw),
            "spender": normalize_hex_address(spender),
        },
        "nonce": {"ok": nonce >= 0, "pendingNonce": nonce},
        "ethCall": {
            "ok": eth_call_result["ok"],
            **({"result": eth_call_result["result"]} if eth_call_result["ok"] else {"error": eth_call_result["error"]}),
        },
        "estimateGas": {
            "ok": estimate_gas_result["ok"],
            **(
                {"gas": str(int(str(estimate_gas_result["result"]), 16))}
                if estimate_gas_result["ok"]
                else {"error": estimate_gas_result["error"]}
            ),
        },
    }
    return {"green": all(item["ok"] for item in checks.values()), "checks": checks, "tradeSent": False}


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    owner = normalize_hex_address(args.from_address)
    token = normalize_hex_address(args.token_address)
    pool = normalize_hex_address(args.pool_address)
    spender = normalize_hex_address(args.spender_address)
    rpc_selection = resolve_execution_rpc_url(cfg)
    rpc_url = rpc_selection.rpc_url
    if args.broadcast:
        require_isolated_execution_rpc(
            rpc_selection,
            action="sell broadcast",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )

    load_secret_file(Path(args.secret_file))

    try:
        from eth_account import Account
        from eth_utils import to_checksum_address
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("eth-account and eth-utils are required") from exc

    account = Account.from_key(os.environ["VWR_BURNER_PRIVATE_KEY"])
    if normalize_hex_address(account.address) != owner:
        raise ValueError("secret file private key does not match --from-address")

    output: dict[str, Any] = {
        "rpc": redact_rpc_url(rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "projectLabel": args.project_label,
        "owner": owner,
        "token": token,
        "pool": pool,
        "spender": spender,
        "broadcastRequested": bool(args.broadcast),
        "broadcasted": False,
        "tradeSent": False,
    }
    timings: dict[str, float] = {}
    total_start = time.perf_counter()

    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        section_start = time.perf_counter()
        token_before, virtual_before = await asyncio.gather(
            read_erc20_balance(rpc, token=token, owner=owner),
            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
        )
        timings["readBeforeMs"] = elapsed_ms(section_start)
        amount_raw = token_before if str(args.amount_raw).lower() == "max" else int(str(args.amount_raw))
        if amount_raw <= 0:
            output["reason"] = "zero_balance_or_amount"
        else:
            section_start = time.perf_counter()
            tx, quote = await bind_sell(
                rpc,
                chain_id=cfg.chain_id,
                from_addr=owner,
                token_addr=token,
                pool_addr=pool,
                virtual_token_addr=cfg.virtual_token_addr,
                amount_raw=amount_raw,
                slippage_bps=int(args.slippage_bps),
                deadline_offset_sec=int(args.deadline_offset_sec),
                now_ts=int(time.time()),
            )
            timings["bindSellMs"] = elapsed_ms(section_start)
            section_start = time.perf_counter()
            simulation = await simulate_sell(
                rpc,
                tx=tx,
                token_addr=token,
                owner=owner,
                spender=spender,
                amount_raw=amount_raw,
            )
            timings["simulateMs"] = elapsed_ms(section_start)
            output.update(
                {
                    "amountRaw": str(amount_raw),
                    "quote": asdict(quote),
                    "balancesBefore": {
                        "soldTokenRaw": str(token_before),
                        "virtualWei": str(virtual_before),
                    },
                    "simulation": simulation,
                }
            )
            if not simulation["green"]:
                output["reason"] = "simulation_not_green"
            else:
                gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
                gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
                section_start = time.perf_counter()
                fees = await suggest_fees(
                    rpc,
                    max_fee_gwei=args.max_fee_gwei,
                    priority_gwei=args.max_priority_fee_gwei,
                )
                timings["feeSuggestMs"] = elapsed_ms(section_start)
                tx_payload = {
                    "type": 2,
                    "chainId": int(tx.chain_id),
                    "nonce": int(simulation["checks"]["nonce"]["pendingNonce"]),
                    "to": to_checksum_address(normalize_hex_address(tx.to)),
                    "value": int(tx.value_wei),
                    "data": tx.data,
                    "gas": gas,
                    "maxFeePerGas": fees["maxFeePerGas"],
                    "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"],
                }
                section_start = time.perf_counter()
                signed = account.sign_transaction(tx_payload)
                raw_bytes = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
                raw_tx = "0x" + bytes(raw_bytes).hex()
                tx_hash = "0x" + bytes(getattr(signed, "hash")).hex()
                recovered = normalize_hex_address(Account.recover_transaction(raw_tx))
                if recovered != owner:
                    raise ValueError("signed sell recover check failed")
                timings["signMs"] = elapsed_ms(section_start)
                output.update(
                    {
                        "signed": True,
                        "signedTxHash": tx_hash,
                        "broadcasted": False,
                        "tradeSent": False,
                        "broadcastAllowed": bool(args.broadcast),
                    }
                )
                if args.broadcast:
                    section_start = time.perf_counter()
                    sent_hash = await rpc.call("eth_sendRawTransaction", [raw_tx])
                    timings["sendRawMs"] = elapsed_ms(section_start)
                    timings["totalToSendAckMs"] = elapsed_ms(total_start)
                    receipt = None
                    receipt_deltas = None
                    token_after = None
                    virtual_after = None
                    if not args.no_wait_receipt:
                        section_start = time.perf_counter()
                        receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
                        timings["waitReceiptMs"] = elapsed_ms(section_start)
                        receipt_deltas = receipt_sell_deltas(
                            receipt,
                            owner=owner,
                            virtual_token=cfg.virtual_token_addr,
                            sold_token=token,
                        )
                        token_after, virtual_after = await asyncio.gather(
                            read_erc20_balance(rpc, token=token, owner=owner),
                            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
                        )
                    receipt_status = str((receipt or {}).get("status") or "")
                    receipt_ok = args.no_wait_receipt or receipt_status in {"0x1", "1"}
                    output.update(
                        {
                            "broadcasted": True,
                            "tradeSent": True,
                            "txHash": str(sent_hash),
                            "receiptOk": receipt_ok,
                            "receiptSkipped": bool(args.no_wait_receipt),
                            "receipt": {
                                "status": receipt.get("status") if receipt else None,
                                "blockNumber": receipt.get("blockNumber") if receipt else None,
                                "gasUsed": receipt.get("gasUsed") if receipt else None,
                            }
                            if receipt
                            else None,
                            "receiptTransferDeltas": receipt_deltas,
                            "balancesAfter": {
                                "soldTokenRaw": str(token_after),
                                "virtualWei": str(virtual_after),
                            }
                            if token_after is not None and virtual_after is not None
                            else None,
                            "reason": "receipt_observed"
                            if receipt_ok and not args.no_wait_receipt
                            else ("receipt_wait_skipped" if args.no_wait_receipt else "receipt_failed"),
                        }
                    )

    timings.setdefault("totalMs", elapsed_ms(total_start))
    output["timingsMs"] = timings
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "projectLabel": output["projectLabel"],
                "broadcasted": output["broadcasted"],
                "tradeSent": output["tradeSent"],
                "rpcSharedWithMain": output.get("rpcSharedWithMain"),
                "executionRpcSource": output.get("executionRpcSource"),
                "txHash": output.get("txHash"),
                "receiptStatus": output.get("receipt", {}).get("status") if output.get("receipt") else None,
                "soldTokenSpentRaw": (output.get("receiptTransferDeltas") or {}).get("soldTokenSpentRaw"),
                "virtualReceivedWei": (output.get("receiptTransferDeltas") or {}).get("virtualReceivedWei"),
                "reason": output.get("reason"),
                "timingsMs": output.get("timingsMs"),
                "outputJson": args.output_json,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
