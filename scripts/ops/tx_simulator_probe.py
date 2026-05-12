#!/usr/bin/env python3
"""Read-only probe for Phase 053 unsigned buy transaction simulation.

This script never signs or broadcasts. It builds an unsigned Virtuals direct
buy transaction from explicit parameters, then checks balance, allowance,
deadline, nonce, eth_call, and estimateGas through the configured RPC.
"""

from __future__ import annotations

import argparse
import asyncio
import json
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

from execution_rpc import resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    DEFAULT_DEADLINE_OFFSET_SEC,
    DEFAULT_LAUNCH_SLIPPAGE_BPS,
    TxSimulator,
    VirtualsOrderBinder,
    VirtualsOrderBuilder,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe unsigned Virtuals buy tx simulation.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address")
    parser.add_argument("--amount-v", default="25")
    parser.add_argument("--amount-out-min-wei")
    parser.add_argument("--slippage-bps", type=int, default=DEFAULT_LAUNCH_SLIPPAGE_BPS)
    parser.add_argument("--deadline-ts", type=int)
    parser.add_argument("--deadline-offset-sec", type=int, default=DEFAULT_DEADLINE_OFFSET_SEC)
    parser.add_argument("--output-json")
    return parser.parse_args()


def compact_report(report: dict[str, Any], *, rpc_url: str, quote: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = report["checks"]
    return {
        "rpc": redact_rpc_url(rpc_url),
        "quote": quote,
        "green": report["green"],
        "tradeSent": report["tradeSent"],
        "signingAllowed": report["signingAllowed"],
        "broadcastAllowed": report["broadcastAllowed"],
        "from": report["from"],
        "to": report["to"],
        "valueWei": report["valueWei"],
        "amountInWei": report["decodedBuy"]["amountInWei"],
        "tokenAddress": report["decodedBuy"]["tokenAddress"],
        "amountOutMinWei": report["decodedBuy"]["amountOutMinWei"],
        "deadline": report["decodedBuy"]["deadline"],
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
    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        quote = None
        if args.pool_address:
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
                now_ts=int(args.deadline_ts - args.deadline_offset_sec) if args.deadline_ts else None,
            )
            tx = bound.tx
            quote = asdict(bound.quote)
        else:
            deadline = int(args.deadline_ts or (time.time() + args.deadline_offset_sec))
            tx = VirtualsOrderBuilder().build_buy(
                chain_id=cfg.chain_id,
                from_addr=args.from_address,
                token_addr=args.token_address,
                amount_in_v=Decimal(str(args.amount_v)),
                amount_out_min_wei=int(args.amount_out_min_wei or 0),
                deadline=deadline,
            )
        simulator = TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr)
        report = await simulator.simulate(tx)
    output = compact_report(report, rpc_url=rpc_url, quote=quote)
    output["rpcSharedWithMain"] = rpc_selection.rpc_shared_with_main
    output["executionRpcSource"] = rpc_selection.source
    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "green": output["green"],
                "tradeSent": output["tradeSent"],
                "deadlineOk": output["checks"]["deadline"]["ok"],
                "amountOutMinOk": output["checks"]["amountOutMin"]["ok"],
                "amountOutMinWei": output["amountOutMinWei"],
                "balanceOk": output["checks"]["balance"]["ok"],
                "allowanceOk": output["checks"]["allowance"]["ok"],
                "ethCallOk": output["checks"]["ethCall"]["ok"],
                "estimateGasOk": output["checks"]["estimateGas"]["ok"],
                "outputJson": args.output_json,
                "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
                "executionRpcSource": rpc_selection.source,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
