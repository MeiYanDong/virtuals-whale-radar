#!/usr/bin/env python3
"""Smoke tests for execution_rpc.py."""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OPS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from execution_rpc import (  # noqa: E402
    ALLOW_PROJECT_ENV_BROADCAST_ENV,
    EXEC_RPC_ENV,
    EXEC_RPC_SOURCE_FILE_ENV,
    apply_execution_rpc_to_config,
    load_project_execution_env_if_needed,
    require_isolated_execution_rpc,
    resolve_execution_rpc_url,
)


@contextmanager
def env_value(name: str, value: str | None):
    old = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def cfg() -> SimpleNamespace:
    return SimpleNamespace(
        http_rpc_url="https://main.example",
        backfill_http_rpc_url="https://backfill.example",
        backfill_http_rpc_urls=["https://backfill.example", "https://main.example"],
        backfill_public_http_rpc_urls=["https://public.example"],
    )


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_fallback_marks_main_shared() -> None:
    with env_value(EXEC_RPC_ENV, None):
        with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
            with env_value("VWR_SKIP_PROJECT_ENV_LOAD", "1"):
                selection = resolve_execution_rpc_url(cfg())
    assert_eq(selection.rpc_url, "https://main.example", "fallback rpc")
    assert_eq(selection.rpc_shared_with_main, True, "fallback shared")
    assert_eq(selection.source, "config_main_rpc", "fallback source")
    assert_eq(selection.source_detail, "config", "fallback source detail")


def test_env_execution_rpc_marks_isolated() -> None:
    with env_value(EXEC_RPC_ENV, "https://exec.example"):
        with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
            with env_value("VWR_SKIP_PROJECT_ENV_LOAD", "1"):
                selection = resolve_execution_rpc_url(cfg())
    assert_eq(selection.rpc_url, "https://exec.example", "env rpc")
    assert_eq(selection.rpc_shared_with_main, False, "env isolated")
    assert_eq(selection.source, EXEC_RPC_ENV, "env source")
    assert_eq(selection.source_detail, "process_env", "env source detail")
    assert_eq(selection.loaded_from_project_env_file, False, "env not local file")


def test_env_matching_main_marks_shared() -> None:
    with env_value(EXEC_RPC_ENV, "https://backfill.example"):
        with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
            with env_value("VWR_SKIP_PROJECT_ENV_LOAD", "1"):
                selection = resolve_execution_rpc_url(cfg())
    assert_eq(selection.rpc_shared_with_main, True, "matching env shared")


def test_apply_execution_rpc_replaces_config_pool() -> None:
    config = cfg()
    with env_value(EXEC_RPC_ENV, "https://exec.example"):
        with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
            with env_value("VWR_SKIP_PROJECT_ENV_LOAD", "1"):
                selection = apply_execution_rpc_to_config(config)
    assert_eq(selection.rpc_shared_with_main, False, "applied isolated")
    assert_eq(config.http_rpc_url, "https://exec.example", "http replaced")
    assert_eq(config.backfill_http_rpc_url, "https://exec.example", "backfill replaced")
    assert_eq(config.backfill_http_rpc_urls, ["https://exec.example"], "backfill list replaced")
    assert_eq(config.backfill_public_http_rpc_urls, [], "public list cleared")


def test_require_isolated_blocks_shared() -> None:
    with env_value(EXEC_RPC_ENV, None):
        with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
            with env_value("VWR_SKIP_PROJECT_ENV_LOAD", "1"):
                selection = resolve_execution_rpc_url(cfg())
    try:
        require_isolated_execution_rpc(selection, action="test broadcast")
    except SystemExit as exc:
        assert "requires isolated" in str(exc)
    else:
        raise AssertionError("shared RPC should block broadcast")


def test_local_env_file_loads_when_env_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp)
            Path(".env.local").write_text(f'{EXEC_RPC_ENV}="https://local-exec.example"\n', encoding="utf-8")
            with env_value(EXEC_RPC_ENV, None):
                with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
                    with env_value("VWR_SKIP_PROJECT_ENV_LOAD", None):
                        loaded = load_project_execution_env_if_needed()
                        assert_eq(os.environ.get(EXEC_RPC_ENV), "https://local-exec.example", "local env loaded")
                        assert_eq(loaded.resolve(), (Path(tmp) / ".env.local").resolve(), "local env path")
                        selection = resolve_execution_rpc_url(cfg())
                        assert_eq(selection.source_detail, "project_env_file", "local env source detail")
                        assert_eq(selection.loaded_from_project_env_file, True, "local env file marker")
        finally:
            os.chdir(old_cwd)


def test_require_isolated_blocks_local_project_env_broadcast_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp)
            Path(".env.local").write_text(f"{EXEC_RPC_ENV}=https://local-exec.example\n", encoding="utf-8")
            with env_value(EXEC_RPC_ENV, None):
                with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
                    with env_value("VWR_SKIP_PROJECT_ENV_LOAD", None):
                        with env_value(ALLOW_PROJECT_ENV_BROADCAST_ENV, None):
                            selection = resolve_execution_rpc_url(cfg())
                            try:
                                require_isolated_execution_rpc(selection, action="test broadcast")
                            except SystemExit as exc:
                                assert "loaded from local .env.local" in str(exc)
                            else:
                                raise AssertionError("local project env broadcast should block by default")
        finally:
            os.chdir(old_cwd)


def test_require_isolated_allows_explicit_local_project_env_broadcast() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        old_cwd = Path.cwd()
        try:
            os.chdir(tmp)
            Path(".env.local").write_text(f"{EXEC_RPC_ENV}=https://local-exec.example\n", encoding="utf-8")
            with env_value(EXEC_RPC_ENV, None):
                with env_value(EXEC_RPC_SOURCE_FILE_ENV, None):
                    with env_value("VWR_SKIP_PROJECT_ENV_LOAD", None):
                        with env_value(ALLOW_PROJECT_ENV_BROADCAST_ENV, "1"):
                            selection = resolve_execution_rpc_url(cfg())
                            require_isolated_execution_rpc(selection, action="test broadcast")
        finally:
            os.chdir(old_cwd)


def main() -> None:
    test_fallback_marks_main_shared()
    test_env_execution_rpc_marks_isolated()
    test_env_matching_main_marks_shared()
    test_apply_execution_rpc_replaces_config_pool()
    test_require_isolated_blocks_shared()
    test_local_env_file_loads_when_env_missing()
    test_require_isolated_blocks_local_project_env_broadcast_by_default()
    test_require_isolated_allows_explicit_local_project_env_broadcast()
    print("execution_rpc tests ok")


if __name__ == "__main__":
    main()
