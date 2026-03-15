import argparse
import json
import sqlite3
import time
from pathlib import Path


FIXTURE_PROJECT = "FIXTURE_TRACKED_WALLET"
FIXTURE_WALLET = "0x1111111111111111111111111111111111111111"
FIXTURE_TOKEN = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
FIXTURE_POOL = "0x3390759661ecaae232287fca61cee9672cb44f32"
FIXTURE_DETAIL_URL = "https://app.virtuals.io/prototypes/fixure-tracked-wallet"


def seed_fixture(db_path: Path, wallet_name: str) -> dict:
    now = int(time.time())
    start_at = now - 5 * 60
    resolved_end_at = now + 60 * 60
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                INSERT INTO managed_projects(
                    name, signalhub_project_id, detail_url, token_addr, internal_pool_addr,
                    start_at, signalhub_end_at, manual_end_at, resolved_end_at,
                    is_watched, collect_enabled, backfill_enabled, status, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    detail_url = excluded.detail_url,
                    token_addr = excluded.token_addr,
                    internal_pool_addr = excluded.internal_pool_addr,
                    start_at = excluded.start_at,
                    signalhub_end_at = excluded.signalhub_end_at,
                    manual_end_at = excluded.manual_end_at,
                    resolved_end_at = excluded.resolved_end_at,
                    is_watched = excluded.is_watched,
                    collect_enabled = excluded.collect_enabled,
                    backfill_enabled = excluded.backfill_enabled,
                    status = excluded.status,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (
                    FIXTURE_PROJECT,
                    None,
                    FIXTURE_DETAIL_URL,
                    FIXTURE_TOKEN,
                    FIXTURE_POOL,
                    start_at,
                    None,
                    resolved_end_at,
                    resolved_end_at,
                    1,
                    1,
                    1,
                    "live",
                    "fixture",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO monitored_wallets(wallet, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(wallet) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (FIXTURE_WALLET, wallet_name, now, now),
            )
            conn.execute(
                """
                INSERT INTO wallet_positions(
                    project, wallet, token_addr, sum_fee_v, sum_spent_v_est, sum_token_bought,
                    avg_cost_v, total_supply, breakeven_fdv_v, virtual_price_usd, breakeven_fdv_usd, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, wallet, token_addr) DO UPDATE SET
                    sum_fee_v = excluded.sum_fee_v,
                    sum_spent_v_est = excluded.sum_spent_v_est,
                    sum_token_bought = excluded.sum_token_bought,
                    avg_cost_v = excluded.avg_cost_v,
                    total_supply = excluded.total_supply,
                    breakeven_fdv_v = excluded.breakeven_fdv_v,
                    virtual_price_usd = excluded.virtual_price_usd,
                    breakeven_fdv_usd = excluded.breakeven_fdv_usd,
                    updated_at = excluded.updated_at
                """,
                (
                    FIXTURE_PROJECT,
                    FIXTURE_WALLET,
                    FIXTURE_TOKEN,
                    "0.500000000000000000",
                    "125.000000000000000000",
                    "2500000.000000000000000000",
                    "0.000050000000000000",
                    "1000000000.000000000000000000",
                    "50000.000000000000000000",
                    "0.125000000000000000",
                    "6250.000000000000000000",
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO project_stats(project, sum_tax_v, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project) DO UPDATE SET
                    sum_tax_v = excluded.sum_tax_v,
                    updated_at = excluded.updated_at
                """,
                (FIXTURE_PROJECT, "12.500000000000000000", now),
            )
        return {
            "ok": True,
            "db": str(db_path),
            "project": FIXTURE_PROJECT,
            "wallet": FIXTURE_WALLET,
            "wallet_name": wallet_name,
            "token_addr": FIXTURE_TOKEN,
            "internal_pool_addr": FIXTURE_POOL,
            "start_at": start_at,
            "resolved_end_at": resolved_end_at,
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed replayable wallet_positions fixture")
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--wallet-name", default="Fixture Wallet Alpha", help="Initial wallet display name")
    args = parser.parse_args()
    result = seed_fixture(Path(args.db), args.wallet_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
