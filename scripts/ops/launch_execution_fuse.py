#!/usr/bin/env python3
"""Inspect or clear launch-execution fuses.

This is an operations helper only. It never signs or broadcasts transactions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from virtuals_bot import Storage, load_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect or clear launch execution fuses.")
    parser.add_argument("--config", default="config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List recent launch execution fuses.")
    list_parser.add_argument("--project", default="")
    list_parser.add_argument("--active-only", action="store_true")
    list_parser.add_argument("--limit", type=int, default=50)

    clear_parser = sub.add_parser("clear", help="Clear one launch execution fuse.")
    clear_parser.add_argument("--project", required=True)
    clear_parser.add_argument("--strategy", required=True)
    clear_parser.add_argument("--rule", required=True)
    clear_parser.add_argument("--reason", required=True)
    return parser.parse_args()


def compact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": row.get("project"),
        "strategy": row.get("strategy"),
        "ruleName": row.get("rule_name"),
        "scope": row.get("scope"),
        "isActive": bool(row.get("is_active")),
        "failureStage": row.get("failure_stage"),
        "failureReason": row.get("failure_reason"),
        "sourceIntentId": row.get("source_intent_id"),
        "updatedAt": row.get("updated_at"),
        "clearedAt": row.get("cleared_at"),
        "clearedReason": row.get("cleared_reason"),
    }


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    storage = Storage(cfg.sqlite_path)
    try:
        if args.command == "list":
            rows = storage.list_launch_execution_fuses(
                project=str(args.project or "").strip() or None,
                active_only=bool(args.active_only),
                limit=int(args.limit),
            )
            print(json.dumps({"fuses": [compact(dict(row)) for row in rows]}, ensure_ascii=False))
            return
        if args.command == "clear":
            row = storage.clear_launch_execution_fuse(
                project=str(args.project).strip(),
                strategy=str(args.strategy).strip(),
                rule_name=str(args.rule).strip(),
                cleared_reason=str(args.reason).strip(),
            )
            if not row:
                raise SystemExit("fuse not found")
            print(json.dumps({"fuse": compact(dict(row))}, ensure_ascii=False))
            return
        raise SystemExit(f"unknown command: {args.command}")
    finally:
        storage.close()


if __name__ == "__main__":
    main()
