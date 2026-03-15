import asyncio
from typing import Any, Dict, List, Optional

import aiohttp


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_address(value: Any) -> Optional[str]:
    raw = _clean_text(value).lower()
    if not raw:
        return None
    if not raw.startswith("0x") or len(raw) != 42:
        return None
    try:
        int(raw[2:], 16)
    except ValueError:
        return None
    return raw


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pick_import_name(project: Dict[str, Any]) -> str:
    symbol = _clean_text(project.get("symbol"))
    if symbol:
        return symbol.upper()
    name = _clean_text(project.get("name"))
    if name:
        return name
    display_title = _clean_text(project.get("display_title")).lstrip("$")
    if display_title:
        return display_title
    return _clean_text(project.get("project_id"))


class SignalHubClient:
    def __init__(
        self,
        base_url: str,
        timeout_sec: int = 8,
        analysis_concurrency: int = 4,
    ) -> None:
        self.base_url = str(base_url).strip().rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_sec)))
        self.analysis_concurrency = max(1, int(analysis_concurrency))
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "SignalHubClient":
        self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._session:
            raise RuntimeError("SignalHub session is not initialized")
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _normalize_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        token_address = _normalize_optional_address(project.get("token_address"))
        contract_address = _normalize_optional_address(project.get("contract_address")) or token_address
        liquidity_pool = (
            _normalize_optional_address(project.get("pool_address"))
            or _normalize_optional_address(project.get("internal_market_address"))
        )
        item = {
            "projectId": _clean_text(project.get("project_id")),
            "importName": _pick_import_name(project),
            "displayTitle": _clean_text(project.get("display_title")),
            "name": _clean_text(project.get("name")),
            "symbol": _clean_text(project.get("symbol")),
            "status": _clean_text(project.get("status")),
            "launchTime": _clean_text(project.get("launch_time")),
            "secondsToLaunch": _coerce_int(project.get("seconds_to_launch")),
            "contractAddress": contract_address,
            "contractReady": bool(project.get("contract_ready") or contract_address or token_address),
            "url": _clean_text(project.get("url")),
            "creator": _normalize_optional_address(project.get("creator")),
            "description": _clean_text(project.get("description")),
            "team": _clean_text(project.get("team")),
            "lifecycleStage": _clean_text(project.get("lifecycle_stage")),
            "projectScore": _coerce_int(project.get("project_score")),
            "scoreGrade": _clean_text(project.get("score_grade")).upper(),
            "riskLevel": _clean_text(project.get("risk_level")),
            "watchlist": bool(project.get("watchlist")),
            "links": project.get("links") or [],
            "liquidityPool": liquidity_pool,
            "treasuryAddress": None,
            "analysisError": None,
            "syncReady": bool(liquidity_pool),
        }
        return item

    async def _load_analysis_addresses(self, project_id: str) -> Dict[str, Optional[str]]:
        analysis = await self._get_json(
            f"/projects/{project_id}/analysis",
            params={"event_limit": 1, "change_limit": 1},
        )
        out: Dict[str, Optional[str]] = {
            "liquidityPool": None,
            "treasuryAddress": None,
        }
        for row in analysis.get("addresses") or []:
            address_type = _clean_text(row.get("address_type")).lower()
            address = _normalize_optional_address(row.get("address"))
            if not address:
                continue
            if address_type in {"liquidity_pool", "internal_market", "pool_address"} and not out["liquidityPool"]:
                out["liquidityPool"] = address
            elif address_type == "treasury" and not out["treasuryAddress"]:
                out["treasuryAddress"] = address
        return out

    async def fetch_upcoming(self, limit: int, within_hours: int) -> Dict[str, Any]:
        payload = await self._get_json(
            "/bot/feed/upcoming",
            params={
                "limit": max(1, int(limit)),
                "within_hours": max(1, int(within_hours)),
                "contract_ready_only": "false",
            },
        )
        projects = payload.get("projects") or []
        items = [self._normalize_project(project) for project in projects]
        semaphore = asyncio.Semaphore(self.analysis_concurrency)

        async def enrich(item: Dict[str, Any]) -> Dict[str, Any]:
            project_id = item.get("projectId") or ""
            if not project_id:
                return item
            try:
                async with semaphore:
                    addresses = await self._load_analysis_addresses(project_id)
                if addresses.get("liquidityPool") and not item.get("liquidityPool"):
                    item["liquidityPool"] = addresses["liquidityPool"]
                if addresses.get("treasuryAddress") and not item.get("treasuryAddress"):
                    item["treasuryAddress"] = addresses["treasuryAddress"]
            except Exception as exc:
                item["analysisError"] = str(exc)
            item["syncReady"] = bool(item.get("liquidityPool"))
            return item

        if items:
            items = list(await asyncio.gather(*(enrich(item) for item in items)))

        return {
            "source": _clean_text(payload.get("source")) or "signalhub",
            "generatedAt": _clean_text(payload.get("generated_at")),
            "count": len(items),
            "withinHours": max(1, int(within_hours)),
            "limit": max(1, int(limit)),
            "items": items,
        }
