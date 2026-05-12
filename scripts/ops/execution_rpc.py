#!/usr/bin/env python3
"""Shared execution RPC routing helpers for launch transaction tools."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXEC_RPC_ENV = "VWR_EXEC_HTTP_RPC_URL"
EXEC_RPC_SOURCE_FILE_ENV = "VWR_EXEC_HTTP_RPC_URL_SOURCE_FILE"
ALLOW_PROJECT_ENV_BROADCAST_ENV = "VWR_ALLOW_PROJECT_ENV_BROADCAST"
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ExecutionRpcSelection:
    rpc_url: str
    rpc_shared_with_main: bool
    source: str
    source_detail: str
    loaded_from_project_env_file: bool
    project_env_file: str | None = None


def configured_main_rpc_urls(cfg: Any) -> list[str]:
    values = [
        getattr(cfg, "http_rpc_url", None),
        getattr(cfg, "backfill_http_rpc_url", None),
        *list(getattr(cfg, "backfill_http_rpc_urls", None) or []),
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def configured_main_rpc_pool(cfg: Any) -> set[str]:
    return set(configured_main_rpc_urls(cfg))


def env_flag_enabled(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def load_project_execution_env_if_needed() -> Path | None:
    if str(os.environ.get(EXEC_RPC_ENV) or "").strip():
        source_file = str(os.environ.get(EXEC_RPC_SOURCE_FILE_ENV) or "").strip()
        return Path(source_file) if source_file else None
    if env_flag_enabled("VWR_SKIP_PROJECT_ENV_LOAD"):
        return None
    for path in (Path.cwd() / ".env.local", ROOT / ".env.local"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != EXEC_RPC_ENV:
                continue
            secret = value.strip().strip('"').strip("'")
            if secret:
                os.environ[EXEC_RPC_ENV] = secret
                os.environ[EXEC_RPC_SOURCE_FILE_ENV] = str(path)
                return path
    return None


def resolve_execution_rpc_url(cfg: Any) -> ExecutionRpcSelection:
    project_env_file = load_project_execution_env_if_needed()
    main_urls = configured_main_rpc_urls(cfg)
    main_pool = set(main_urls)
    exec_rpc = str(os.environ.get(EXEC_RPC_ENV) or "").strip()
    if exec_rpc:
        loaded_from_project_env_file = project_env_file is not None
        return ExecutionRpcSelection(
            rpc_url=exec_rpc,
            rpc_shared_with_main=exec_rpc in main_pool,
            source=EXEC_RPC_ENV,
            source_detail="project_env_file" if loaded_from_project_env_file else "process_env",
            loaded_from_project_env_file=loaded_from_project_env_file,
            project_env_file=str(project_env_file) if project_env_file else None,
        )

    fallback = main_urls[0] if main_urls else ""
    if not fallback:
        raise ValueError("no HTTP RPC configured")
    return ExecutionRpcSelection(
        rpc_url=fallback,
        rpc_shared_with_main=True,
        source="config_main_rpc",
        source_detail="config",
        loaded_from_project_env_file=False,
        project_env_file=None,
    )


def apply_execution_rpc_to_config(cfg: Any) -> ExecutionRpcSelection:
    selection = resolve_execution_rpc_url(cfg)
    if selection.source == EXEC_RPC_ENV:
        cfg.http_rpc_url = selection.rpc_url
        cfg.backfill_http_rpc_url = selection.rpc_url
        cfg.backfill_http_rpc_urls = [selection.rpc_url]
        cfg.backfill_public_http_rpc_urls = []
    return selection


def require_isolated_execution_rpc(
    selection: ExecutionRpcSelection,
    *,
    action: str,
    allow_shared: bool = False,
    allow_project_env_broadcast: bool = False,
) -> None:
    if selection.rpc_shared_with_main and not allow_shared:
        raise SystemExit(f"{action} requires isolated {EXEC_RPC_ENV}")
    if (
        selection.loaded_from_project_env_file
        and not allow_project_env_broadcast
        and not env_flag_enabled(ALLOW_PROJECT_ENV_BROADCAST_ENV)
    ):
        raise SystemExit(
            f"{action} refuses broadcast with {EXEC_RPC_ENV} loaded from local .env.local; "
            f"set {ALLOW_PROJECT_ENV_BROADCAST_ENV}=1 only for an explicit local canary"
        )
