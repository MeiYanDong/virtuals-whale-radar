from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from signalhub.app.database.db import Database
from signalhub.app.database.models import utc_now_iso


class TokenPoolExportService:
    def __init__(self, database: Database, export_path: str | Path) -> None:
        self.database = database
        self.export_path = Path(export_path)
        self._cached_payload: dict[str, Any] | None = None

    def build_payload(self) -> dict[str, Any]:
        items = self.database.list_token_pool_export_items(limit=1000)
        payload = {
            "generated_at": utc_now_iso(),
            "count": len(items),
            "items": items,
        }
        self._cached_payload = payload
        return payload

    def refresh(self) -> dict[str, Any]:
        payload = self.build_payload()
        self.export_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

