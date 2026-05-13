#!/usr/bin/env python3
"""Create a reusable launch backtest archive from production runtime data.

The script is read-only against the source runtime database. It exports one
project into a frozen directory that can be used by backtest scripts without
touching production state.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from virtuals_bot import load_config  # noqa: E402


PROJECT_TABLES = [
    "events",
    "launch_execution_ledger",
    "launch_execution_fuses",
    "leaderboard",
    "wallet_positions",
    "minute_agg",
    "minute_buyers",
    "team_address_overrides",
    "project_stats",
]


JSON_COLUMNS = {
    "launch_execution_ledger": {
        "trigger_types_json": "triggerTypes",
        "snapshot_json": "snapshot",
        "intent_json": "intent",
        "simulation_json": "simulation",
        "receipt_json": "receipt",
    },
    "launch_execution_fuses": {
        "details_json": "details",
    },
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cst_date(ts: int | None) -> str:
    if ts and ts > 0:
        return datetime.fromtimestamp(ts, timezone.utc).astimezone().strftime("%Y-%m-%d")
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "project"


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"source sqlite not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def parse_json_field(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return value


def enrich_json_columns(table: str, row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    for column, target in JSON_COLUMNS.get(table, {}).items():
        if column in row:
            output[target] = parse_json_field(row.get(column))
    return output


def resolve_project(conn: sqlite3.Connection, project: str) -> dict[str, Any] | None:
    if not table_exists(conn, "managed_projects"):
        return None
    if project.isdigit():
        row = conn.execute(
            "SELECT * FROM managed_projects WHERE id = ? OR signalhub_project_id = ? LIMIT 1",
            (int(project), project),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM managed_projects
            WHERE lower(name) = lower(?) OR signalhub_project_id = ?
            LIMIT 1
            """,
            (project, project),
        ).fetchone()
    return dict(row) if row else None


def normalized_event(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output.update(
        {
            "txHash": row.get("tx_hash"),
            "blockNumber": row.get("block_number"),
            "timestamp": row.get("block_timestamp"),
            "internalPool": row.get("internal_pool"),
            "feeAddr": row.get("fee_addr"),
            "taxAddr": row.get("tax_addr"),
            "tokenAddr": row.get("token_addr"),
            "tokenBought": row.get("token_bought"),
            "feeV": row.get("fee_v"),
            "taxV": row.get("tax_v"),
            "spentV_est": row.get("spent_v_est"),
            "spentV_actual": row.get("spent_v_actual"),
            "costV": row.get("cost_v"),
            "totalSupply": row.get("total_supply"),
            "virtualPriceUsd": row.get("virtual_price_usd"),
            "breakevenFdvV": row.get("breakeven_fdv_v"),
            "breakevenFdvUsd": row.get("breakeven_fdv_usd"),
            "isMyWallet": row.get("is_my_wallet"),
            "isPriceStale": row.get("is_price_stale"),
        }
    )
    return output


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, items: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def default_sample_paths(project: str) -> list[Path]:
    symbol = safe_slug(project.upper())
    canonical = Path(f"data/execution/launch-samples-{symbol}.jsonl")
    if canonical.exists():
        return [canonical]
    return [
        Path(f"data/execution/live-strategy-dry-run-{symbol}.jsonl"),
        Path(f"data/execution/launch-autobuy-{symbol}.jsonl"),
        Path(f"data/execution/launch-autosell-{symbol}.jsonl"),
        Path(f"data/execution/launch-prewarm-executor-{symbol}.jsonl"),
    ]


def extract_samples(paths: list[Path], project: str) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    samples: list[dict[str, Any]] = []
    canonical_mode = any(path.name.startswith("launch-samples-") for path in paths)
    seen: set[tuple[Any, ...]] = set()

    for path in paths:
        if not path.exists():
            warnings.append(f"sample source missing: {path}")
            continue
        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception as exc:
                    warnings.append(f"invalid json in {path}:{line_no}: {exc}")
                    continue

                sample: dict[str, Any] | None = None
                if isinstance(row.get("sample"), dict):
                    sample = dict(row["sample"])
                    sample.setdefault("_sourceEvent", row.get("event"))
                    sample.setdefault("_recordedAt", row.get("at"))
                    sample.setdefault("_recordedAtCst", row.get("atCst"))
                    sample.setdefault("_sampleIndex", row.get("sampleIndex"))
                    sample.setdefault("_sourcePath", str(path))
                elif row.get("_recordType") == "launch_sample" or "simTimestamp" in row:
                    sample = dict(row)
                    sample.setdefault("_sourcePath", str(path))

                if not sample or "simTimestamp" not in sample:
                    continue
                sample.setdefault("_project", project)

                if not canonical_mode:
                    key = (
                        sample.get("simTimestamp"),
                        sample.get("projectStatus"),
                        sample.get("events"),
                        sample.get("buyTaxRate"),
                        sample.get("priceBlockNumber"),
                        sample.get("estimatedFdvWanUsdWithTax"),
                        sample.get("boardSpentV"),
                        sample.get("boardCostWanUsd"),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                samples.append(sample)

    samples.sort(
        key=lambda item: (
            int(item.get("simTimestamp") or 0),
            int(item.get("_sampleIndex") or item.get("sampleIndex") or 0),
            str(item.get("_sourcePath") or ""),
        )
    )
    return samples, warnings


def export_archive_db(
    *,
    source_db: Path,
    archive_db: Path,
    project_name: str,
) -> list[str]:
    warnings: list[str] = []
    if archive_db.exists():
        archive_db.unlink()
    out = sqlite3.connect(archive_db)
    try:
        out.row_factory = sqlite3.Row
        out.execute("ATTACH DATABASE ? AS src", (str(source_db),))
        for table in ["managed_projects", "launch_configs", *PROJECT_TABLES]:
            exists = out.execute(
                "SELECT name FROM src.sqlite_master WHERE type='table' AND name = ?",
                (table,),
            ).fetchone()
            if not exists:
                warnings.append(f"source table missing: {table}")
                continue
            columns = {str(row["name"]) for row in out.execute(f"PRAGMA src.table_info({table})").fetchall()}
            if table == "managed_projects":
                out.execute(
                    f"CREATE TABLE {table} AS SELECT * FROM src.{table} WHERE name = ?",
                    (project_name,),
                )
            elif table == "launch_configs":
                out.execute(
                    f"CREATE TABLE {table} AS SELECT * FROM src.{table} WHERE name = ?",
                    (project_name,),
                )
            elif "project" in columns:
                out.execute(
                    f"CREATE TABLE {table} AS SELECT * FROM src.{table} WHERE project = ?",
                    (project_name,),
                )
            else:
                warnings.append(f"source table has no project column: {table}")
        out.commit()
    finally:
        out.close()
    return warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive one launch project into reusable backtest files.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--sqlite-path", default="")
    parser.add_argument("--project", required=True, help="Managed project name/id or SignalHub id.")
    parser.add_argument("--output-dir", default="data/launch-archives")
    parser.add_argument("--archive-name", default="")
    parser.add_argument("--samples-jsonl", action="append", default=[])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-archive-db", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    source_db = Path(args.sqlite_path or cfg.sqlite_path).expanduser()
    if not source_db.is_absolute():
        source_db = (Path.cwd() / source_db).resolve()

    conn = connect_readonly(source_db)
    try:
        project_row = resolve_project(conn, str(args.project).strip())
        project_name = str((project_row or {}).get("name") or args.project).strip()
        project_slug = safe_slug(project_name.upper())
        start_at = int((project_row or {}).get("start_at") or 0)
        stamp = utc_stamp()
        archive_name = args.archive_name or f"{cst_date(start_at)}-{project_slug}-{stamp}"
        archive_dir = Path(args.output_dir) / archive_name
        if archive_dir.exists():
            if not args.overwrite:
                raise FileExistsError(f"archive exists, use --overwrite: {archive_dir}")
            shutil.rmtree(archive_dir)
        archive_dir.mkdir(parents=True, exist_ok=True)

        event_rows: list[dict[str, Any]] = []
        if table_exists(conn, "events"):
            event_rows = [
                normalized_event(item)
                for item in rows(
                    conn,
                    """
                    SELECT * FROM events
                    WHERE project = ?
                    ORDER BY block_timestamp, block_number, id
                    """,
                    (project_name,),
                )
            ]

        ledger_rows: list[dict[str, Any]] = []
        if table_exists(conn, "launch_execution_ledger"):
            ledger_rows = [
                enrich_json_columns("launch_execution_ledger", item)
                for item in rows(
                    conn,
                    """
                    SELECT * FROM launch_execution_ledger
                    WHERE project = ?
                    ORDER BY created_at, id
                    """,
                    (project_name,),
                )
            ]

        fuse_rows: list[dict[str, Any]] = []
        if table_exists(conn, "launch_execution_fuses"):
            fuse_rows = [
                enrich_json_columns("launch_execution_fuses", item)
                for item in rows(
                    conn,
                    """
                    SELECT * FROM launch_execution_fuses
                    WHERE project = ?
                    ORDER BY created_at, id
                    """,
                    (project_name,),
                )
            ]

        launch_config = None
        if table_exists(conn, "launch_configs"):
            row = conn.execute("SELECT * FROM launch_configs WHERE name = ? LIMIT 1", (project_name,)).fetchone()
            launch_config = dict(row) if row else None

        sample_paths = [Path(item) for item in args.samples_jsonl] if args.samples_jsonl else default_sample_paths(project_name)
        samples, sample_warnings = extract_samples(sample_paths, project_name)

        project_payload = {
            "project": project_name,
            "sourceProjectArg": args.project,
            "managedProject": project_row,
            "launchConfig": launch_config,
        }
        write_json(archive_dir / "project.json", project_payload)
        event_count = write_jsonl(archive_dir / "events.jsonl", event_rows)
        ledger_count = write_jsonl(archive_dir / "execution-ledger.jsonl", ledger_rows)
        fuse_count = write_jsonl(archive_dir / "fuses.jsonl", fuse_rows)
        sample_count = write_jsonl(archive_dir / "samples.jsonl", samples)

        archive_db_path = archive_dir / "archive.db"
        db_warnings: list[str] = []
        if not args.no_archive_db:
            db_warnings = export_archive_db(
                source_db=source_db,
                archive_db=archive_db_path,
                project_name=project_name,
            )

        warnings = sample_warnings + db_warnings
        summary = {
            "scope": "launch archive",
            "readOnly": True,
            "productionDbTouched": False,
            "tradeSent": False,
            "project": project_name,
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sourceSqlitePath": str(source_db),
            "startAt": int((project_row or {}).get("start_at") or 0),
            "endAt": int((project_row or {}).get("resolved_end_at") or 0),
            "samplesPath": str(archive_dir / "samples.jsonl"),
            "jsonlPath": str(archive_dir / "events.jsonl"),
            "ledgerPath": str(archive_dir / "execution-ledger.jsonl"),
            "fusesPath": str(archive_dir / "fuses.jsonl"),
            "sqlitePath": str(archive_db_path) if archive_db_path.exists() else "",
            "counts": {
                "sampleCount": sample_count,
                "eventCount": event_count,
                "ledgerCount": ledger_count,
                "fuseCount": fuse_count,
            },
            "sampleSources": [str(path) for path in sample_paths],
            "warnings": warnings,
            "finalSample": samples[-1] if samples else None,
        }
        write_json(archive_dir / "summary.json", summary)
        manifest = {
            "archiveVersion": 1,
            "createdAtUnix": int(time.time()),
            "project": project_name,
            "files": {
                "project": "project.json",
                "samples": "samples.jsonl",
                "events": "events.jsonl",
                "executionLedger": "execution-ledger.jsonl",
                "fuses": "fuses.jsonl",
                "summary": "summary.json",
                "archiveDb": "archive.db" if archive_db_path.exists() else "",
            },
            "counts": summary["counts"],
            "warnings": warnings,
        }
        write_json(archive_dir / "manifest.json", manifest)
        print(json.dumps({"archiveDir": str(archive_dir), **summary}, ensure_ascii=False), flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
