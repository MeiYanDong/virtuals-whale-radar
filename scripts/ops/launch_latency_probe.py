#!/usr/bin/env python3
"""Measure launch buy execution latency without broadcasting.

This probe separates:
- cold prepare: quote binding + simulation + fee suggestion + signing;
- hot path: local signing only, assuming quote/gas/fee/nonce are already ready;
- RPC baseline: a simple eth_blockNumber round trip.

It never prints private keys or raw transactions, and never calls
eth_sendRawTransaction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import load_secret_file, suggest_fees  # noqa: E402
from execution_rpc import resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import LocalSigner, TxSimulator, VirtualsOrderBinder, normalize_hex_address  # noqa: E402
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe launch execution latency without broadcasting.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--pool-address", required=True)
    parser.add_argument("--amount-v", default="0.001")
    parser.add_argument("--iterations", type=int, default=7)
    parser.add_argument("--output-json")
    return parser.parse_args()


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return round(statistics.median(values), 1)


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    rpc_selection = resolve_execution_rpc_url(cfg)
    rpc_url = rpc_selection.rpc_url
    owner = normalize_hex_address(args.from_address)
    token = normalize_hex_address(args.token_address)
    pool = normalize_hex_address(args.pool_address)

    secret_loaded = False
    try:
        load_secret_file(Path(args.secret_file))
        secret_loaded = True
    except Exception:
        secret_loaded = False

    output: dict[str, Any] = {
        "rpc": redact_rpc_url(rpc_url),
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "owner": owner,
        "token": token,
        "pool": pool,
        "amountV": str(args.amount_v),
        "iterationsRequested": int(args.iterations),
        "secretLoaded": secret_loaded,
        "broadcasted": False,
        "tradeSent": False,
        "rows": [],
    }

    async with RPCClient(rpc_url, max_retries=1, timeout_sec=20) as rpc:
        await rpc.call("eth_blockNumber", [])
        for i in range(max(1, int(args.iterations))):
            row: dict[str, Any] = {"i": i}

            section_start = time.perf_counter()
            await rpc.call("eth_blockNumber", [])
            row["blockNumberMs"] = elapsed_ms(section_start)

            section_start = time.perf_counter()
            bound = await VirtualsOrderBinder(rpc, virtual_token_addr=cfg.virtual_token_addr).bind_buy(
                chain_id=cfg.chain_id,
                from_addr=owner,
                token_addr=token,
                pool_addr=pool,
                amount_in_v=Decimal(str(args.amount_v)),
                now_ts=int(time.time()),
            )
            row["bindBuyMs"] = elapsed_ms(section_start)

            section_start = time.perf_counter()
            simulation = await TxSimulator(rpc, virtual_token_addr=cfg.virtual_token_addr).simulate(bound.tx)
            row["simulateMs"] = elapsed_ms(section_start)
            row["simulationGreen"] = bool(simulation["green"])
            row["allowanceOk"] = bool(simulation["checks"]["allowance"]["ok"])
            row["ethCallOk"] = bool(simulation["checks"]["ethCall"]["ok"])
            row["estimateGasOk"] = bool(simulation["checks"]["estimateGas"]["ok"])

            section_start = time.perf_counter()
            fees = await suggest_fees(rpc, max_fee_gwei=None, priority_gwei=None)
            row["feeSuggestMs"] = elapsed_ms(section_start)

            gas = int(simulation["checks"]["estimateGas"].get("gas") or 420000)
            tx = replace(
                bound.tx,
                nonce=int(simulation["checks"]["nonce"]["pendingNonce"]),
                gas=gas,
                max_fee_per_gas=str(fees["maxFeePerGas"]),
                max_priority_fee_per_gas=str(fees["maxPriorityFeePerGas"]),
            )
            if secret_loaded:
                section_start = time.perf_counter()
                signed = LocalSigner().sign(tx)
                row["signMs"] = elapsed_ms(section_start)
                row["signedHashPrefix"] = signed.tx_hash[:10]
            else:
                row["signMs"] = None
                row["signSkipped"] = "secret_not_loaded"

            row["coldPrepareMs"] = round(
                row["bindBuyMs"] + row["simulateMs"] + row["feeSuggestMs"] + (row["signMs"] or 0),
                1,
            )
            row["hotPathLocalMs"] = row["signMs"] or 0
            output["rows"].append(row)

    output["medianMs"] = {
        key: median(output["rows"], key)
        for key in [
            "blockNumberMs",
            "bindBuyMs",
            "simulateMs",
            "feeSuggestMs",
            "signMs",
            "coldPrepareMs",
            "hotPathLocalMs",
        ]
    }

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
