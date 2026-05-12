#!/usr/bin/env python3
"""No-broadcast signer probe for Phase 053.

This script may load a burner private key from a local ignored env file, but it
never prints the key, never writes raw signed transactions, and never broadcasts.
It signs only after TxSimulator is green.
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

from execution_rpc import resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    LocalSigner,
    TxSimulator,
    VirtualsOrderBinder,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sign a Virtuals buy tx locally without broadcasting.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address", required=True)
    parser.add_argument("--amount-v", default="25")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
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
    try:
        result = await rpc.call("eth_maxPriorityFeePerGas", [])
        priority = int(result, 16)
    except Exception:
        pass

    base_fee = gwei_to_wei(Decimal("0.05"))
    try:
        block = await rpc.call("eth_getBlockByNumber", ["latest", False])
        if block and block.get("baseFeePerGas"):
            base_fee = int(block["baseFeePerGas"], 16)
    except Exception:
        pass

    max_fee = gwei_to_wei(max_fee_gwei) if max_fee_gwei is not None else base_fee * 2 + priority
    if max_fee < priority:
        max_fee = priority
    return {"maxFeePerGas": max_fee, "maxPriorityFeePerGas": priority}


def compact_simulation(report: dict[str, Any]) -> dict[str, Any]:
    checks = report["checks"]
    return {
        "green": report["green"],
        "tradeSent": report["tradeSent"],
        "signingAllowed": report["signingAllowed"],
        "broadcastAllowed": report["broadcastAllowed"],
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
    cfg = load_config(args.config)
    rpc_selection = resolve_execution_rpc_url(cfg)
    rpc_url = rpc_selection.rpc_url
    output: dict[str, Any]

    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        bound = await VirtualsOrderBinder(
            rpc,
            virtual_token_addr=cfg.virtual_token_addr,
            slippage_bps=args.slippage_bps,
            deadline_offset_sec=args.deadline_offset_sec,
        ).bind_buy(
            chain_id=cfg.chain_id,
            from_addr=args.from_address,
            token_addr=args.token_address,
            pool_addr=args.pool_address,
            amount_in_v=Decimal(str(args.amount_v)),
            now_ts=int(time.time()),
        )
        simulator = TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr)
        simulation = await simulator.simulate(bound.tx)
        output = {
            "rpc": redact_rpc_url(rpc_url),
            "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
            "executionRpcSource": rpc_selection.source,
            "readOnly": True,
            "tradeSent": False,
            "signed": False,
            "broadcastAllowed": False,
            "quote": asdict(bound.quote),
            "simulation": compact_simulation(simulation),
        }
        if not simulation["green"]:
            output["reason"] = "simulation_not_green"
        else:
            load_secret_file(Path(args.secret_file))
            gas_estimate = int(simulation["checks"]["estimateGas"]["gas"])
            gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
            fees = await suggest_fees(
                rpc,
                max_fee_gwei=args.max_fee_gwei,
                priority_gwei=args.max_priority_fee_gwei,
            )
            tx = replace(
                bound.tx,
                nonce=int(simulation["checks"]["nonce"]["pendingNonce"]),
                gas=gas,
                max_fee_per_gas=str(fees["maxFeePerGas"]),
                max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
            )
            signed = LocalSigner().sign(tx)
            output.update(
                {
                    "signed": True,
                    "signingAllowed": True,
                    "broadcastAllowed": False,
                    "signedSummary": {
                        "txHash": signed.tx_hash,
                        "from": signed.from_addr,
                        "to": signed.to,
                        "chainId": signed.chain_id,
                        "nonce": signed.nonce,
                        "gas": signed.gas,
                        "maxFeePerGas": tx.max_fee_per_gas,
                        "maxPriorityFeePerGas": tx.max_priority_fee_per_gas,
                        "rawTxBytes": (len(signed.raw_tx) - 2) // 2,
                    },
                }
            )

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "green": output["simulation"]["green"],
                "signed": output["signed"],
                "tradeSent": output["tradeSent"],
                "broadcastAllowed": output.get("broadcastAllowed", False),
                "rpcSharedWithMain": output.get("rpcSharedWithMain"),
                "executionRpcSource": output.get("executionRpcSource"),
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
