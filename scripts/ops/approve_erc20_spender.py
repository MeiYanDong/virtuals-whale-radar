#!/usr/bin/env python3
"""Approve an ERC-20 spender with an exact raw token amount.

Safety defaults:
- exact raw amount only;
- private key only from ignored local secret file;
- no raw transaction output;
- requires --broadcast for on-chain submission.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from buy_virtual_canary import suggest_fees  # noqa: E402
from execution_rpc import require_isolated_execution_rpc, resolve_execution_rpc_url  # noqa: E402
from launch_execution_pipeline import (  # noqa: E402
    BURNER_PRIVATE_KEY_ENV,
    VIRTUALS_BUY_SPENDER,
    address_word,
    encode_erc20_allowance,
    normalize_hex_address,
)
from virtuals_bot import RPCClient, load_config, redact_rpc_url  # noqa: E402


APPROVE_SELECTOR = "0x095ea7b3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Approve ERC-20 spender with exact raw amount.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--secret-file", default="secrets/burner-wallet.env")
    parser.add_argument("--from-address", required=True)
    parser.add_argument("--token-address", required=True)
    parser.add_argument("--spender-address", default=VIRTUALS_BUY_SPENDER)
    parser.add_argument("--amount-raw", required=True)
    parser.add_argument("--gas-buffer-bps", type=int, default=2000)
    parser.add_argument("--max-fee-gwei", type=Decimal)
    parser.add_argument("--max-priority-fee-gwei", type=Decimal)
    parser.add_argument("--receipt-timeout-sec", type=int, default=90)
    parser.add_argument("--allowance-confirm-timeout-sec", type=int, default=10)
    parser.add_argument("--allowance-confirm-interval-sec", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--skip-sign", action="store_true", help="Read-only approve readiness check; do not load private key or sign.")
    parser.add_argument("--force-exact", action="store_true", help="Broadcast approval even when current allowance is already sufficient.")
    parser.add_argument("--broadcast", action="store_true")
    parser.add_argument("--allow-shared-rpc-broadcast", action="store_true")
    parser.add_argument("--output-json")
    return parser.parse_args()


def load_secret_file(path: Path) -> str:
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
                return secret
    raise ValueError(f"{BURNER_PRIVATE_KEY_ENV} is missing or empty in {path}")


def encode_approve(spender: str, amount_raw: int) -> str:
    if amount_raw < 0:
        raise ValueError("amount_raw cannot be negative")
    return APPROVE_SELECTOR + address_word(spender) + f"{amount_raw:064x}"


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


async def wait_allowance_at_least(
    rpc: RPCClient,
    *,
    token: str,
    owner: str,
    spender: str,
    amount_raw: int,
    exact: bool = False,
    timeout_sec: int,
    interval_sec: Decimal,
) -> dict[str, Any]:
    deadline = time.time() + max(0, int(timeout_sec))
    reads: list[str] = []
    last = 0
    while True:
        last = await read_allowance(rpc, token=token, owner=owner, spender=spender)
        reads.append(str(last))
        if (last == amount_raw) if exact else (last >= amount_raw):
            return {"ok": True, "allowanceRaw": str(last), "reads": reads}
        if time.time() >= deadline:
            return {"ok": False, "allowanceRaw": str(last), "reads": reads}
        await asyncio.sleep(float(interval_sec))


async def async_main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    token = normalize_hex_address(args.token_address)
    owner = normalize_hex_address(args.from_address)
    spender = normalize_hex_address(args.spender_address)
    amount_raw = int(str(args.amount_raw))
    rpc_selection = resolve_execution_rpc_url(cfg)
    rpc_url = rpc_selection.rpc_url
    if args.broadcast and args.skip_sign:
        raise ValueError("--skip-sign cannot be used with --broadcast")
    if args.broadcast:
        require_isolated_execution_rpc(
            rpc_selection,
            action="approve broadcast",
            allow_shared=bool(args.allow_shared_rpc_broadcast),
        )

    Account = None
    to_checksum_address = None
    account = None
    if not args.skip_sign:
        try:
            from eth_account import Account as EthAccount
            from eth_utils import to_checksum_address as eth_to_checksum_address
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("eth-account and eth-utils are required") from exc

        secret = load_secret_file(Path(args.secret_file))
        account = EthAccount.from_key(secret)
        if normalize_hex_address(account.address) != owner:
            raise ValueError("secret file private key does not match --from-address")
        Account = EthAccount
        to_checksum_address = eth_to_checksum_address

    output: dict[str, Any] = {
        "rpc": redact_rpc_url(rpc_url),
        "token": token,
        "owner": owner,
        "spender": spender,
        "amountRaw": str(amount_raw),
        "broadcastRequested": bool(args.broadcast),
        "broadcasted": False,
        "tradeSent": False,
        "rpcSharedWithMain": rpc_selection.rpc_shared_with_main,
        "executionRpcSource": rpc_selection.source,
        "signingSkipped": bool(args.skip_sign),
        "forceExact": bool(args.force_exact),
    }

    async with RPCClient(rpc_url, max_retries=3, timeout_sec=20) as rpc:
        before = await read_allowance(rpc, token=token, owner=owner, spender=spender)
        output["allowanceBeforeRaw"] = str(before)
        if before == amount_raw or (before >= amount_raw and not args.force_exact):
            output.update(
                {
                    "skipped": True,
                    "reason": "allowance_already_exact" if before == amount_raw else "allowance_already_sufficient",
                    "allowanceAfterRaw": str(before),
                    "allowanceConfirmed": True,
                }
            )
        else:
            data = encode_approve(spender, amount_raw)
            call_payload = {"from": owner, "to": token, "value": "0x0", "data": data}
            call_result = await rpc.call("eth_call", [call_payload, "latest"])
            gas_estimate = int(await rpc.call("eth_estimateGas", [call_payload]), 16)
            gas = gas_estimate * (10_000 + int(args.gas_buffer_bps)) // 10_000
            nonce = int(await rpc.call("eth_getTransactionCount", [owner, "pending"]), 16)
            fees = await suggest_fees(
                rpc,
                max_fee_gwei=args.max_fee_gwei,
                priority_gwei=args.max_priority_fee_gwei,
            )
            if args.skip_sign:
                output.update(
                    {
                        "skipped": False,
                        "ethCallOk": True,
                        "ethCallResult": call_result,
                        "gasEstimate": gas_estimate,
                        "gas": gas,
                        "nonce": nonce,
                        "maxFeePerGas": str(fees["maxFeePerGas"]),
                        "maxPriorityFeePerGas": str(fees["maxPriorityFeePerGas"]),
                        "signed": False,
                        "reason": "skip_sign_readiness_only",
                    }
                )
                if args.output_json:
                    path = Path(args.output_json)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "broadcasted": output["broadcasted"],
                            "skipped": output.get("skipped", False),
                            "signed": output.get("signed", False),
                            "reason": output.get("reason"),
                            "allowanceBeforeRaw": output.get("allowanceBeforeRaw"),
                            "allowanceAfterRaw": output.get("allowanceAfterRaw"),
                            "allowanceConfirmed": output.get("allowanceConfirmed"),
                            "outputJson": args.output_json,
                            "rpcSharedWithMain": output.get("rpcSharedWithMain"),
                        },
                        ensure_ascii=False,
                    )
                )
                return
            tx = {
                "type": 2,
                "chainId": int(cfg.chain_id),
                "nonce": nonce,
                "to": to_checksum_address(token),
                "value": 0,
                "data": data,
                "gas": gas,
                "maxFeePerGas": fees["maxFeePerGas"],
                "maxPriorityFeePerGas": fees["maxPriorityFeePerGas"],
            }
            signed = account.sign_transaction(tx)
            raw_bytes = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
            raw_tx = "0x" + bytes(raw_bytes).hex()
            tx_hash = "0x" + bytes(getattr(signed, "hash")).hex()
            recovered = normalize_hex_address(Account.recover_transaction(raw_tx))
            if recovered != owner:
                raise ValueError("signed approve recover check failed")
            output.update(
                {
                    "skipped": False,
                    "ethCallOk": True,
                    "ethCallResult": call_result,
                    "gasEstimate": gas_estimate,
                    "gas": gas,
                    "nonce": nonce,
                    "maxFeePerGas": str(fees["maxFeePerGas"]),
                    "maxPriorityFeePerGas": str(fees["maxPriorityFeePerGas"]),
                    "signed": True,
                    "txHash": tx_hash,
                    "rawTxBytes": (len(raw_tx) - 2) // 2,
                }
            )
            if args.broadcast:
                sent_hash = await rpc.call("eth_sendRawTransaction", [raw_tx])
                receipt = await wait_receipt(rpc, str(sent_hash), timeout_sec=int(args.receipt_timeout_sec))
                allowance_confirm = await wait_allowance_at_least(
                    rpc,
                    token=token,
                    owner=owner,
                    spender=spender,
                    amount_raw=amount_raw,
                    exact=bool(args.force_exact),
                    timeout_sec=int(args.allowance_confirm_timeout_sec),
                    interval_sec=Decimal(str(args.allowance_confirm_interval_sec)),
                )
                output.update(
                    {
                        "broadcasted": True,
                        "sentTxHash": sent_hash,
                        "receipt": {
                            "status": receipt.get("status") if receipt else None,
                            "blockNumber": receipt.get("blockNumber") if receipt else None,
                            "gasUsed": receipt.get("gasUsed") if receipt else None,
                        }
                        if receipt
                        else None,
                        "allowanceAfterRaw": allowance_confirm["allowanceRaw"],
                        "allowanceConfirmed": bool(allowance_confirm["ok"]),
                        "allowanceConfirmReads": allowance_confirm["reads"],
                    }
                )

    if args.output_json:
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "broadcasted": output["broadcasted"],
                "skipped": output.get("skipped", False),
                "txHash": output.get("sentTxHash") or output.get("txHash"),
                "receiptStatus": output.get("receipt", {}).get("status") if output.get("receipt") else None,
                "allowanceBeforeRaw": output.get("allowanceBeforeRaw"),
                "allowanceAfterRaw": output.get("allowanceAfterRaw"),
                "allowanceConfirmed": output.get("allowanceConfirmed"),
                "outputJson": args.output_json,
                "rpcSharedWithMain": output.get("rpcSharedWithMain"),
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
