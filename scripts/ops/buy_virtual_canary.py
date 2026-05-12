#!/usr/bin/env python3
"""Broadcast a small Virtuals direct-buy canary.

This is intentionally narrow:
- direct Virtuals buy route only;
- private key only from ignored local secret file;
- simulation must be green before signing;
- requires --broadcast;
- no raw transaction output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from execution_rpc import require_isolated_execution_rpc, resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    LocalSigner,
    TxSimulator,
    VirtualsOrderBinder,
    VIRTUALS_BUY_SPENDER,
    encode_erc20_allowance,
    encode_erc20_balance_of,
    normalize_hex_address,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Broadcast one small Virtuals direct-buy canary.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address", required=True)
    parser.add_argument("--project-label", required=True)
    parser.add_argument("--amount-v", default="1")
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


def load_secret_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"secret file not found: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == BURNER_PRIVATE_KEY_ENV:
            secret = value.strip().strip('"').strip("'")
            if secret:
                os.environ[BURNER_PRIVATE_KEY_ENV] = secret
                return
    raise ValueError(f"{BURNER_PRIVATE_KEY_ENV} is missing or empty in {path}")


def gwei_to_wei(value: Decimal) -> int:
    return int((value * Decimal(10**9)).to_integral_value())


async def suggest_fees(rpc: RPCClient, *, max_fee_gwei: Decimal | None, priority_gwei: Decimal | None) -> dict[str, int]:
    if max_fee_gwei is not None and priority_gwei is not None:
        return {
            "maxFeePerGas": gwei_to_wei(max_fee_gwei),
            "maxPriorityFeePerGas": gwei_to_wei(priority_gwei),
        }

    priority = gwei_to_wei(priority_gwei or Decimal("0.01"))
    priority_task = None
    block_task = None
    try:
        if priority_gwei is None:
            priority_task = rpc.call("eth_maxPriorityFeePerGas", [])
    except Exception:
        priority_task = None

    base_fee = gwei_to_wei(Decimal("0.05"))
    try:
        if max_fee_gwei is None:
            block_task = rpc.call("eth_getBlockByNumber", ["latest", False])
    except Exception:
        block_task = None

    tasks = [task for task in (priority_task, block_task) if task is not None]
    results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
    result_iter = iter(results)
    if priority_task is not None:
        result = next(result_iter)
        if not isinstance(result, Exception):
            priority = int(result, 16)
    if block_task is not None:
        block = next(result_iter)
        if block and block.get("baseFeePerGas"):
            base_fee = int(block["baseFeePerGas"], 16)

    max_fee = gwei_to_wei(max_fee_gwei) if max_fee_gwei is not None else base_fee * 2 + priority
    if max_fee < priority:
        max_fee = priority
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority}


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


async def read_erc20_balance(rpc: RPCClient, *, token: str, owner: str) -> int:
    result = await rpc.call(
        "eth_call",
        [{"to": normalize_hex_address(token), "data": encode_erc20_balance_of(owner)}, "latest"],
    )
    return int(str(result), 16)


async def read_allowance(rpc: RPCClient, *, token: str, owner: str, spender: str) -> int:
    result = await rpc.call(
        "eth_call",
        [{"to": normalize_hex_address(token), "data": encode_erc20_allowance(owner, spender)}, "latest"],
    )
    return int(str(result), 16)


async def wait_receipt(rpc: RPCClient, tx_hash: str, *, timeout_sec: int) -> dict[str, Any] | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        receipt = await rpc.call("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            return receipt
        await asyncio.sleep(2)
    return None


def topic_address(topic: str) -> str:
    return "0x" + str(topic)[-40:].lower()


def receipt_transfer_deltas(
    receipt: dict[str, Any] | None,
    *,
    owner: str,
    virtual_token: str,
    target_token: str,
) -> dict[str, Any]:
    owner = normalize_hex_address(owner)
    virtual_token = normalize_hex_address(virtual_token)
    target_token = normalize_hex_address(target_token)
    virtual_spent = 0
    target_received = 0
    transfer_logs: list[dict[str, str]] = []

    for log in (receipt or {}).get("logs") or []:
        topics = log.get("topics") or []
        if len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC0:
            continue
        token = normalize_hex_address(str(log.get("address") or ""))
        from_addr = topic_address(str(topics[1]))
        to_addr = topic_address(str(topics[2]))
        amount = int(str(log.get("data") or "0x0"), 16)
        if token == virtual_token and from_addr == owner:
            virtual_spent += amount
        if token == target_token and to_addr == owner:
            target_received += amount
        if token in {virtual_token, target_token}:
            transfer_logs.append(
                {
                    "token": token,
                    "from": from_addr,
                    "to": to_addr,
                    "amountRaw": str(amount),
                }
            )

    return {
        "virtualSpentWei": str(virtual_spent),
        "targetReceivedRaw": str(target_received),
        "transferLogs": transfer_logs,
    }


def compact_simulation(report: dict[str, Any]) -> dict[str, Any]:
    checks = report["checks"]
    return {
        "green": report["green"],
        "tradeSent": report["tradeSent"],
        "from": report["from"],
        "to": report["to"],
        "amountInWei": report["decodedBuy"]["amountInWei"],
        "amountOutMinWei": report["decodedBuy"]["amountOutMinWei"],
        "checks": {
            "deadline": checks["deadline"],
            "amountOutMin": checks["amountOutMin"],
            "balance": checks["balance"],
            "allowance": checks["allowance"],
            "nonce": checks["nonce"],
            "ethCall": checks["ethCall"],
            "estimateGas": checks["estimateGas"],
        },
    }


async def async_main() -> None:
    args = parse_args()
    if not args.broadcast:
        raise RuntimeError("refuse to broadcast without --broadcast")

    cfg = load_config(args.config)
    rpc_selection = resolve_execution_rpc_url(cfg)
    require_isolated_execution_rpc(
        rpc_selection,
        action="buy canary broadcast",
        allow_shared=bool(args.allow_shared_rpc_broadcast),
    )
    load_secret_file(Path(args.secret_file))
    owner = normalize_hex_address(args.from_address)
    token = normalize_hex_address(args.token_address)
    pool = normalize_hex_address(args.pool_address)
    rpc_url = rpc_selection.rpc_url

    output: dict[str, Any] = {
        "rpc": redact_rpc_url(rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "projectLabel": args.project_label,
        "owner": owner,
        "token": token,
        "pool": pool,
        "amountV": str(args.amount_v),
        "broadcastRequested": True,
        "broadcasted": False,
        "tradeSent": False,
    }
    timings: dict[str, float] = {}
    total_start = time.perf_counter()

    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        section_start = time.perf_counter()
        virtual_before, token_before, allowance_before = await asyncio.gather(
            read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
            read_erc20_balance(rpc, token=token, owner=owner),
            read_allowance(
                rpc,
                token=cfg.virtual_token_addr,
                owner=owner,
                spender=VIRTUALS_BUY_SPENDER,
            ),
        )
        timings["readBeforeMs"] = elapsed_ms(section_start)
        section_start = time.perf_counter()
        bound = await VirtualsOrderBinder(
            rpc,
            virtual_token_addr=cfg.virtual_token_addr,
            slippage_bps=args.slippage_bps,
            deadline_offset_sec=args.deadline_offset_sec,
        ).bind_buy(
            chain_id=cfg.chain_id,
            from_addr=owner,
            token_addr=token,
            pool_addr=pool,
            amount_in_v=Decimal(str(args.amount_v)),
            now_ts=int(time.time()),
        )
        timings["bindBuyMs"] = elapsed_ms(section_start)
        section_start = time.perf_counter()
        simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
        timings["simulateMs"] = elapsed_ms(section_start)
        output.update(
            {
                "quote": asdict(bound.quote),
                "balancesBefore": {
                    "virtualWei": str(virtual_before),
                    "targetTokenRaw": str(token_before),
                    "allowanceWei": str(allowance_before),
                },
                "simulation": compact_simulation(simulation),
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
            tx = replace(
                bound.tx,
                nonce=int(simulation["checks"]["nonce"]["pendingNonce"]),
                gas=gas,
                max_fee_per_gas=str(fees["maxFeePerGas"]),
                max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
            )
            section_start = time.perf_counter()
            signed = LocalSigner().sign(tx)
            timings["signMs"] = elapsed_ms(section_start)
            section_start = time.perf_counter()
            sent_hash = await rpc.call("eth_sendRawTransaction", [signed.raw_tx])
            timings["sendRawMs"] = elapsed_ms(section_start)
            timings["totalToSendAckMs"] = elapsed_ms(total_start)
            receipt = None
            receipt_deltas = None
            virtual_after = None
            token_after = None
            allowance_after = None
            if not args.no_wait_receipt:
                section_start = time.perf_counter()
                receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
                timings["waitReceiptMs"] = elapsed_ms(section_start)
                timings["totalToReceiptMs"] = elapsed_ms(total_start)
                receipt_deltas = receipt_transfer_deltas(
                    receipt,
                    owner=owner,
                    virtual_token=cfg.virtual_token_addr,
                    target_token=token,
                )
                section_start = time.perf_counter()
                virtual_after, token_after, allowance_after = await asyncio.gather(
                    read_erc20_balance(rpc, token=cfg.virtual_token_addr, owner=owner),
                    read_erc20_balance(rpc, token=token, owner=owner),
                    read_allowance(
                        rpc,
                        token=cfg.virtual_token_addr,
                        owner=owner,
                        spender=VIRTUALS_BUY_SPENDER,
                    ),
                )
                timings["readAfterMs"] = elapsed_ms(section_start)
            output.update(
                {
                    "signed": True,
                    "broadcasted": True,
                    "tradeSent": True,
                    "txHash": str(sent_hash),
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
                        "virtualWei": str(virtual_after),
                        "targetTokenRaw": str(token_after),
                        "allowanceWei": str(allowance_after),
                    }
                    if virtual_after is not None and token_after is not None and allowance_after is not None
                    else None,
                    "balanceDelta": {
                        "virtualWei": str(virtual_after - virtual_before),
                        "targetTokenRaw": str(token_after - token_before),
                        "allowanceWei": str(allowance_after - allowance_before),
                    }
                    if virtual_after is not None and token_after is not None and allowance_after is not None
                    else None,
                    "signedSummary": {
                        "from": signed.from_addr,
                        "to": signed.to,
                        "chainId": signed.chain_id,
                        "nonce": signed.nonce,
                        "gas": signed.gas,
                        "maxFeePerGas": tx.max_fee_per_gas,
                        "maxPriorityFeePerGas": tx.max_priority_fee_per_gas,
                    },
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
                "receiptSkipped": output.get("receiptSkipped"),
                "virtualDeltaWei": (output.get("balanceDelta") or {}).get("virtualWei"),
                "targetDeltaRaw": (output.get("balanceDelta") or {}).get("targetTokenRaw"),
                "receiptVirtualSpentWei": (output.get("receiptTransferDeltas") or {}).get("virtualSpentWei"),
                "receiptTargetReceivedRaw": (output.get("receiptTransferDeltas") or {}).get("targetReceivedRaw"),
                "timingsMs": output.get("timingsMs"),
                "reason": output.get("reason"),
                "outputJson": args.output_json,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
