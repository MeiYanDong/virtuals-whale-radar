import argparse
import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import signal
import sqlite3
import smtplib
import ssl
import time
import urllib.parse
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, getcontext
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp
from aiohttp import web
from signalhub_client import SignalHubClient

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError as Argon2InvalidHashError
    from argon2.exceptions import VerifyMismatchError as Argon2VerifyMismatchError
except Exception:  # pragma: no cover - optional dependency
    PasswordHasher = None
    Argon2InvalidHashError = ValueError
    Argon2VerifyMismatchError = ValueError

try:
    import bcrypt
except Exception:  # pragma: no cover - optional dependency
    bcrypt = None

getcontext().prec = 60

TRANSFER_TOPIC0 = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)
DECIMALS_SELECTOR = "0x313ce567"
TOKEN0_SELECTOR = "0x0dfe1681"
TOKEN1_SELECTOR = "0xd21220a7"
GET_RESERVES_SELECTOR = "0x0902f1ac"


def normalize_address(addr: str) -> str:
    if not isinstance(addr, str):
        raise ValueError(f"address must be a string, got: {type(addr)}")
    addr = addr.strip().lower()
    if not addr.startswith("0x") or len(addr) != 42:
        raise ValueError(f"invalid address format: {addr}")
    int(addr[2:], 16)
    return addr


def normalize_optional_address(addr: Any) -> Optional[str]:
    if addr is None:
        return None
    raw = str(addr).strip()
    if not raw:
        return None
    return normalize_address(raw)


def topic_address(addr: str) -> str:
    return "0x" + ("0" * 24) + normalize_address(addr)[2:]


def parse_hex_int(value: Optional[str]) -> int:
    if value is None:
        return 0
    return int(value, 16)


def parse_bool_like(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if value is None:
        return False
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def parse_bool_request(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError("paused must be a boolean")


def parse_url_list(value: Any) -> List[str]:
    urls: List[str] = []
    if isinstance(value, str):
        candidates = [x.strip() for x in value.split(",")]
    elif isinstance(value, list):
        candidates = [str(x).strip() for x in value]
    else:
        candidates = []
    for item in candidates:
        if not item:
            continue
        if item not in urls:
            urls.append(item)
    return urls


def parse_optional_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be integer") from exc


def parse_required_int(value: Any, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} is required")
    raw = str(value).strip()
    if raw == "":
        raise ValueError(f"{field_name} is required")
    try:
        return int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be integer") from exc


def normalize_billing_request_status(value: Any) -> str:
    status = str(value or "").strip().lower() or "pending_review"
    if status not in BILLING_REQUEST_STATUSES:
        raise ValueError(f"invalid billing request status: {status}")
    return status


def normalize_notification_kind(value: Any) -> str:
    kind = str(value or "").strip().lower() or "info"
    if kind not in USER_NOTIFICATION_KINDS:
        raise ValueError(f"invalid notification kind: {kind}")
    return kind


def resolve_project_end_at(
    start_at: int,
    signalhub_end_at: Optional[int],
    manual_end_at: Optional[int],
) -> int:
    candidate = manual_end_at or signalhub_end_at or (int(start_at) + 99 * 60)
    return max(int(start_at), int(candidate))


def decode_topic_address(topic: str) -> str:
    topic = topic.lower()
    if topic.startswith("0x"):
        topic = topic[2:]
    return "0x" + topic[-40:]


def decimal_to_str(v: Optional[Decimal], places: int = 18) -> Optional[str]:
    if v is None:
        return None
    q = Decimal(10) ** -places
    return str(v.quantize(q))


def raw_to_decimal(value: int, decimals: int) -> Decimal:
    return Decimal(value) / (Decimal(10) ** decimals)


EVENT_DECIMAL_FIELDS = {
    "token_bought",
    "fee_v",
    "tax_v",
    "spent_v_est",
    "spent_v_actual",
    "cost_v",
    "total_supply",
    "virtual_price_usd",
    "breakeven_fdv_v",
    "breakeven_fdv_usd",
}
EVENT_INT_FIELDS = {"block_number", "block_timestamp"}
EVENT_BOOL_FIELDS = {"is_my_wallet", "anomaly", "is_price_stale"}
MANAGED_PROJECT_STATUSES = {"draft", "scheduled", "prelaunch", "live", "ended", "removed"}
PROJECT_PRELAUNCH_LEAD_SEC = 30 * 60
PROJECT_SCHEDULER_INTERVAL_SEC = 30
USER_STATUSES = {"active", "disabled", "archived"}
USER_ROLES = {"admin", "user"}
USER_SOURCES = {"self_signup", "admin_created"}
DEFAULT_SESSION_COOKIE_NAME = "vwr_session"
DEFAULT_SESSION_TTL_SEC = 14 * 24 * 60 * 60
DEFAULT_SESSION_SECRET = "virtuals-whale-radar-dev-session-secret"
DEFAULT_APP_PUBLIC_BASE_URL = ""
DEFAULT_EMAIL_ENABLED = False
DEFAULT_EMAIL_SMTP_PORT = 587
DEFAULT_EMAIL_SMTP_USE_TLS = True
DEFAULT_EMAIL_FROM_NAME = "Virtuals Whale Radar"
DEFAULT_EMAIL_VERIFY_TOKEN_TTL_SEC = 30 * 60
DEFAULT_SIGNUP_BONUS_CREDITS = 20
DEFAULT_PROJECT_UNLOCK_CREDITS = 10
AUTH_REGISTER_IP_SHORT_WINDOW_SEC = 15 * 60
AUTH_REGISTER_IP_SHORT_MAX_ATTEMPTS = 2
AUTH_REGISTER_IP_LONG_WINDOW_SEC = 24 * 60 * 60
AUTH_REGISTER_IP_LONG_MAX_ATTEMPTS = 5
AUTH_RESEND_IP_WINDOW_SEC = 60 * 60
AUTH_RESEND_IP_MAX_ATTEMPTS = 5
AUTH_LOGIN_FAIL_IP_WINDOW_SEC = 15 * 60
AUTH_LOGIN_FAIL_IP_MAX_ATTEMPTS = 10
DEFAULT_BILLING_CONTACT_QR_URL = "/admin/brand/contact-qr-wechat.png"
DEFAULT_BILLING_CONTACT_HINT = "扫码添加运营联系方式，付款后联系管理员手动补积分。"
DEFAULT_BILLING_REFERRAL_NOTICE = "Virtuals 新用户使用邀请码注册，后续付费一律五折"
DEFAULT_BILLING_REFERRAL_URL = "https://app.virtuals.io/referral?code=LFfW5x"
DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS = [
    "https://base-rpc.publicnode.com",
    "https://base.llamarpc.com",
    "https://mainnet.base.org",
]
RPC_RU_EXCEEDED_TOKENS = (
    "monthly quota",
    "request units",
    "ru",
    "pay-as-you-go",
)
RPC_LOG_HISTORY_UNAVAILABLE_TOKENS = (
    "archive, debug and trace requests are not available",
    "debug and trace requests are not available",
)
RPC_TRANSIENT_ERROR_TOKENS = (
    "timeout",
    "temporarily unavailable",
    "server disconnected",
    "connection reset",
    "connection aborted",
    "connection refused",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
    "too many requests",
    "429",
    "502",
    "503",
    "504",
)
CREDIT_LEDGER_TYPES = {"signup_bonus", "manual_topup", "manual_adjustment", "project_unlock"}
BILLING_REQUEST_STATUSES = {"pending_review", "credited", "notified"}
USER_NOTIFICATION_KINDS = {"success", "warning", "info", "accent"}
MAX_BILLING_PROOF_BYTES = 8 * 1024 * 1024
ALLOWED_BILLING_PROOF_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DISPOSABLE_EMAIL_DOMAINS = {
    "10minutemail.com",
    "10minutemail.net",
    "dispostable.com",
    "fakeinbox.com",
    "getairmail.com",
    "getnada.com",
    "guerrillamail.com",
    "maildrop.cc",
    "mailinator.com",
    "mailnesia.com",
    "moakt.com",
    "sharklasers.com",
    "sharebot.net",
    "temp-mail.io",
    "temp-mail.org",
    "tempail.com",
    "tempmail.com",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
    "yopmail.net",
}
BILLING_PLANS = [
    {"id": "starter", "credits": 10, "priceCny": 10, "label": "10 积分 / 10 元"},
    {"id": "value", "credits": 50, "priceCny": 40, "label": "50 积分 / 40 元"},
]
ARGON2_HASHER = (
    PasswordHasher(time_cost=2, memory_cost=102400, parallelism=8)
    if PasswordHasher is not None
    else None
)
LEGACY_API_SPECS = [
    {"path": "/meta", "replacement": "/api/admin/meta", "access": "admin", "state": "compatible"},
    {"path": "/signalhub/upcoming", "replacement": "/api/admin/signalhub", "access": "admin", "state": "compatible"},
    {"path": "/launch-configs", "replacement": "/api/admin/launch-configs", "access": "admin", "state": "compatible"},
    {"path": "/managed-projects", "replacement": "/api/admin/projects", "access": "admin", "state": "compatible"},
    {"path": "/project-scheduler/status", "replacement": "/api/admin/project-scheduler/status", "access": "admin", "state": "compatible"},
    {"path": "/overview-active", "replacement": "/api/admin/overview-active", "access": "admin", "state": "compatible"},
    {"path": "/signalhub/watchlist/add", "replacement": "/api/admin/signalhub/watchlist/add", "access": "admin", "state": "compatible"},
    {"path": "/signalhub/watchlist/remove", "replacement": "/api/admin/signalhub/watchlist/remove", "access": "admin", "state": "compatible"},
    {"path": "/signalhub/watchlist/batch-add", "replacement": "/api/admin/signalhub/watchlist/batch-add", "access": "admin", "state": "compatible"},
    {"path": "/signalhub/watchlist/batch-remove", "replacement": "/api/admin/signalhub/watchlist/batch-remove", "access": "admin", "state": "compatible"},
    {"path": "/wallet-configs", "replacement": "/api/admin/wallets", "access": "admin", "state": "compatible"},
    {"path": "/wallet-recalc", "replacement": "/api/admin/wallet-recalc", "access": "admin", "state": "compatible"},
    {"path": "/runtime/db-batch-size", "replacement": "/api/admin/runtime/db-batch-size", "access": "admin", "state": "compatible"},
    {"path": "/runtime/pause", "replacement": "/api/admin/runtime/pause", "access": "admin", "state": "compatible"},
    {"path": "/runtime/heartbeat", "replacement": "/api/admin/runtime/heartbeat", "access": "admin", "state": "compatible"},
    {"path": "/scan-range", "replacement": "/api/admin/scan-range", "access": "admin", "state": "compatible"},
    {"path": "/scan-jobs/{job_id}", "replacement": "/api/admin/scan-jobs/{job_id}", "access": "admin", "state": "compatible"},
    {"path": "/scan-jobs/{job_id}/cancel", "replacement": "/api/admin/scan-jobs/{job_id}/cancel", "access": "admin", "state": "compatible"},
    {"path": "/health", "replacement": "/api/admin/health", "access": "public", "state": "compatible"},
    {"path": "/mywallets", "replacement": "/api/admin/mywallets", "access": "admin", "state": "compatible"},
    {"path": "/mywallets/{addr}", "replacement": "/api/admin/mywallets/{addr}", "access": "admin", "state": "compatible"},
    {"path": "/minutes", "replacement": "/api/admin/minutes", "access": "admin", "state": "compatible"},
    {"path": "/leaderboard", "replacement": "/api/admin/leaderboard", "access": "admin", "state": "compatible"},
    {"path": "/event-delays", "replacement": "/api/admin/event-delays", "access": "admin", "state": "compatible"},
    {"path": "/project-tax", "replacement": "/api/admin/project-tax", "access": "admin", "state": "compatible"},
]


def serialize_event_for_bus(event: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(event)
    for key in EVENT_DECIMAL_FIELDS:
        if key in out and out[key] is not None:
            out[key] = str(out[key])
    for key in EVENT_INT_FIELDS:
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    for key in EVENT_BOOL_FIELDS:
        if key in out and out[key] is not None:
            out[key] = bool(out[key])
    return out


def normalize_email(email: Any) -> str:
    raw = str(email or "").strip().lower()
    if not raw or "@" not in raw or raw.startswith("@") or raw.endswith("@"):
        raise ValueError("invalid email")
    return raw


def extract_email_domain(email: str) -> str:
    normalized = normalize_email(email)
    return normalized.split("@", 1)[1]


def require_nonempty_text(value: Any, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field_name} is required")
    return raw


def hash_password(password: str) -> str:
    raw = require_nonempty_text(password, "password")
    if len(raw) < 8:
        raise ValueError("password must be at least 8 characters")
    if ARGON2_HASHER is not None:
        return ARGON2_HASHER.hash(raw)
    if bcrypt is not None:
        return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(raw.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    raw = str(password or "")
    stored = str(password_hash or "").strip()
    if not raw or not stored:
        return False
    if stored.startswith("$argon2") and ARGON2_HASHER is not None:
        with contextlib.suppress(Argon2VerifyMismatchError, Argon2InvalidHashError):
            return bool(ARGON2_HASHER.verify(stored, raw))
        return False
    if stored.startswith("$2") and bcrypt is not None:
        with contextlib.suppress(ValueError):
            return bool(bcrypt.checkpw(raw.encode("utf-8"), stored.encode("utf-8")))
        return False
    if stored.startswith("scrypt$"):
        parts = stored.split("$")
        if len(parts) != 3:
            return False
        try:
            salt = base64.urlsafe_b64decode(parts[1].encode("ascii"))
            expected = base64.urlsafe_b64decode(parts[2].encode("ascii"))
            actual = hashlib.scrypt(raw.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    return False


def hash_session_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def deserialize_event_from_bus(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    for key in EVENT_DECIMAL_FIELDS:
        if key in out and out[key] is not None:
            out[key] = Decimal(str(out[key]))
    for key in EVENT_INT_FIELDS:
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    for key in EVENT_BOOL_FIELDS:
        if key in out and out[key] is not None:
            out[key] = bool(out[key])
    return out


def rpc_error_text(exc: Exception) -> str:
    return str(exc or "").strip().lower()


def is_rpc_ru_exceeded_error(exc: Exception) -> bool:
    text = rpc_error_text(exc)
    return any(token in text for token in RPC_RU_EXCEEDED_TOKENS)


def is_rpc_log_history_unavailable_error(exc: Exception) -> bool:
    text = rpc_error_text(exc)
    return any(token in text for token in RPC_LOG_HISTORY_UNAVAILABLE_TOKENS)


def is_rpc_transient_error(exc: Exception) -> bool:
    text = rpc_error_text(exc)
    return any(token in text for token in RPC_TRANSIENT_ERROR_TOKENS)


@dataclass
class LaunchConfig:
    name: str
    internal_pool_addr: str
    fee_addr: str
    tax_addr: str
    token_addr: Optional[str]
    token_total_supply: Decimal
    fee_rate: Decimal


@dataclass
class RpcEndpointState:
    label: str
    url: str
    client: Optional["RPCClient"] = None
    supports_basic_rpc: Optional[bool] = None
    supports_historical_blocks: Optional[bool] = None
    supports_logs: Optional[bool] = None
    cooldown_until: int = 0
    last_error: str = ""
    last_checked_at: int = 0
    request_count: int = 0
    estimated_ru: int = 0
    last_used_at: int = 0
    basic_request_count: int = 0
    historical_block_request_count: int = 0
    logs_request_count: int = 0


@dataclass
class AppConfig:
    chain_id: int
    ws_rpc_url: str
    http_rpc_url: str
    backfill_http_rpc_url: Optional[str]
    virtual_token_addr: str
    fee_rate_default: Decimal
    total_supply_default: Decimal
    launch_configs: List[LaunchConfig]
    my_wallets: Set[str]
    top_n: int
    confirmations: int
    agg_minute_window: int
    price_mode: str
    virtual_usdc_pair_addr: Optional[str]
    price_refresh_sec: int
    db_mode: str
    sqlite_path: str
    db_batch_size: int
    db_flush_ms: int
    receipt_workers: int
    receipt_workers_realtime: int
    receipt_workers_backfill: int
    max_rpc_retries: int
    backfill_chunk_blocks: int
    backfill_interval_sec: int
    log_level: str
    jsonl_path: str
    event_bus_sqlite_path: str
    api_host: str
    api_port: int
    cors_allow_origins: List[str]
    signalhub_base_url: Optional[str]
    signalhub_timeout_sec: int
    signalhub_upcoming_limit: int
    signalhub_within_hours: int
    bootstrap_admin_nickname: Optional[str]
    bootstrap_admin_email: Optional[str]
    bootstrap_admin_password: Optional[str]
    session_cookie_name: str
    session_ttl_sec: int
    session_secret: str
    app_public_base_url: str
    email_enabled: bool
    email_smtp_host: str
    email_smtp_port: int
    email_smtp_username: str
    email_smtp_password: str
    email_smtp_use_tls: bool
    email_from_address: str
    email_from_name: str
    email_verify_token_ttl_sec: int
    billing_contact_qr_url: str
    billing_contact_hint: str
    backfill_http_rpc_urls: List[str] = field(default_factory=list)
    backfill_public_http_rpc_urls: List[str] = field(default_factory=list)
    backfill_rpc_quota_cooldown_sec: int = 3600
    backfill_rpc_transient_cooldown_sec: int = 600


class RateLimitExceeded(Exception):
    def __init__(self, message: str, *, code: str, retry_after_sec: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retry_after_sec = retry_after_sec


class DisposableEmailBlocked(Exception):
    def __init__(self, message: str = "请使用常用邮箱完成注册。") -> None:
        super().__init__(message)
        self.message = message


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    forbidden_keys = {"SUPABASE_URL", "SUPABASE_KEY"}
    found_forbidden = forbidden_keys.intersection(set(raw.keys()))
    if found_forbidden:
        bad = ", ".join(sorted(found_forbidden))
        raise ValueError(f"v1.1 does not allow Supabase hot path config keys: {bad}")

    chain_id = int(raw.get("CHAIN_ID", 8453))
    ws_rpc_url = str(raw["WS_RPC_URL"]).strip()
    http_rpc_url = str(raw["HTTP_RPC_URL"]).strip()
    backfill_http_rpc_url_raw = str(raw.get("BACKFILL_HTTP_RPC_URL", "")).strip()
    backfill_http_rpc_url = backfill_http_rpc_url_raw or None
    backfill_http_rpc_urls = parse_url_list(raw.get("BACKFILL_HTTP_RPC_URLS", []))
    if not backfill_http_rpc_urls:
        if backfill_http_rpc_url:
            backfill_http_rpc_urls.append(backfill_http_rpc_url)
        if http_rpc_url and http_rpc_url not in backfill_http_rpc_urls:
            backfill_http_rpc_urls.append(http_rpc_url)
    backfill_public_http_rpc_urls = parse_url_list(
        raw.get("BACKFILL_PUBLIC_HTTP_RPC_URLS", DEFAULT_PUBLIC_BASE_HTTP_RPC_URLS)
    )
    virtual_token_addr = normalize_address(raw["VIRTUAL_TOKEN_ADDR"])

    fee_rate_default = Decimal(str(raw.get("FEE_RATE_DEFAULT", "0.01")))
    total_supply_default = Decimal(str(raw.get("TOTAL_SUPPLY_DEFAULT", "1000000000")))
    if fee_rate_default <= 0 or fee_rate_default >= 1:
        raise ValueError("FEE_RATE_DEFAULT must be in (0,1)")

    launch_configs: List[LaunchConfig] = []
    for item in raw.get("LAUNCH_CONFIGS", []):
        fee_rate = Decimal(str(item.get("fee_rate", fee_rate_default)))
        if fee_rate <= 0 or fee_rate >= 1:
            raise ValueError(f"project {item.get('name')} fee_rate is invalid: {fee_rate}")
        launch_configs.append(
            LaunchConfig(
                name=str(item["name"]),
                internal_pool_addr=normalize_address(item["internal_pool_addr"]),
                fee_addr=normalize_address(item["fee_addr"]),
                tax_addr=normalize_address(item["tax_addr"]),
                token_addr=normalize_optional_address(item.get("token_addr")),
                token_total_supply=Decimal(
                    str(item.get("token_total_supply", total_supply_default))
                ),
                fee_rate=fee_rate,
            )
        )
    if not launch_configs:
        raise ValueError("LAUNCH_CONFIGS cannot be empty")

    my_wallets = {normalize_address(x) for x in raw.get("MY_WALLETS", [])}

    price_mode = str(raw.get("PRICE_MODE", "onchain_pool"))
    pair = raw.get("VIRTUAL_USDC_PAIR_ADDR")
    virtual_usdc_pair_addr = normalize_address(pair) if pair else None

    db_mode = str(raw.get("DB_MODE", "sqlite")).lower()
    if db_mode not in {"sqlite", "postgres"}:
        raise ValueError("DB_MODE only supports sqlite or postgres")
    if db_mode == "postgres":
        raise ValueError("current runtime only supports sqlite; set DB_MODE=sqlite")

    receipt_workers = int(raw.get("RECEIPT_WORKERS", 8))
    receipt_workers_realtime = int(
        raw.get("RECEIPT_WORKERS_REALTIME", receipt_workers)
    )
    receipt_workers_backfill = int(
        raw.get("RECEIPT_WORKERS_BACKFILL", receipt_workers)
    )
    if receipt_workers <= 0:
        raise ValueError("RECEIPT_WORKERS must be >= 1")
    if receipt_workers_realtime <= 0:
        raise ValueError("RECEIPT_WORKERS_REALTIME must be >= 1")
    if receipt_workers_backfill <= 0:
        raise ValueError("RECEIPT_WORKERS_BACKFILL must be >= 1")

    cors_allow_origins_raw = raw.get("CORS_ALLOW_ORIGINS", [])
    cors_allow_origins: List[str] = []
    if isinstance(cors_allow_origins_raw, str):
        cors_allow_origins = [
            x.strip().rstrip("/")
            for x in cors_allow_origins_raw.split(",")
            if x and x.strip()
        ]
    elif isinstance(cors_allow_origins_raw, list):
        cors_allow_origins = [
            str(x).strip().rstrip("/")
            for x in cors_allow_origins_raw
            if str(x).strip()
        ]

    signalhub_base_url_raw = str(raw.get("SIGNALHUB_BASE_URL", "")).strip().rstrip("/")
    signalhub_base_url = signalhub_base_url_raw or None
    bootstrap_admin_nickname = str(
        raw.get("BOOTSTRAP_ADMIN_NICKNAME")
        or os.getenv("BOOTSTRAP_ADMIN_NICKNAME")
        or "Administrator"
    ).strip()
    bootstrap_admin_email_raw = (
        raw.get("BOOTSTRAP_ADMIN_EMAIL")
        or os.getenv("BOOTSTRAP_ADMIN_EMAIL")
        or ""
    )
    bootstrap_admin_password_raw = (
        raw.get("BOOTSTRAP_ADMIN_PASSWORD")
        or os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
        or ""
    )
    bootstrap_admin_email = (
        normalize_email(bootstrap_admin_email_raw) if str(bootstrap_admin_email_raw).strip() else None
    )
    bootstrap_admin_password = (
        str(bootstrap_admin_password_raw) if str(bootstrap_admin_password_raw).strip() else None
    )
    session_cookie_name = str(
        raw.get("SESSION_COOKIE_NAME")
        or os.getenv("SESSION_COOKIE_NAME")
        or DEFAULT_SESSION_COOKIE_NAME
    ).strip() or DEFAULT_SESSION_COOKIE_NAME
    session_ttl_sec = max(
        3600,
        int(
            raw.get("SESSION_TTL_SEC")
            or os.getenv("SESSION_TTL_SEC")
            or DEFAULT_SESSION_TTL_SEC
        ),
    )
    session_secret = str(
        raw.get("SESSION_SECRET") or os.getenv("SESSION_SECRET") or DEFAULT_SESSION_SECRET
    ).strip()
    app_public_base_url = str(
        raw.get("APP_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_BASE_URL")
        or DEFAULT_APP_PUBLIC_BASE_URL
    ).strip().rstrip("/")
    email_enabled = parse_bool_like(
        raw.get("EMAIL_ENABLED")
        or os.getenv("EMAIL_ENABLED")
        or DEFAULT_EMAIL_ENABLED
    )
    email_smtp_host = str(
        raw.get("EMAIL_SMTP_HOST")
        or os.getenv("EMAIL_SMTP_HOST")
        or ""
    ).strip()
    email_smtp_port = int(
        raw.get("EMAIL_SMTP_PORT")
        or os.getenv("EMAIL_SMTP_PORT")
        or DEFAULT_EMAIL_SMTP_PORT
    )
    email_smtp_username = str(
        raw.get("EMAIL_SMTP_USERNAME")
        or os.getenv("EMAIL_SMTP_USERNAME")
        or ""
    ).strip()
    email_smtp_password = str(
        raw.get("EMAIL_SMTP_PASSWORD")
        or os.getenv("EMAIL_SMTP_PASSWORD")
        or ""
    )
    email_smtp_use_tls = parse_bool_like(
        raw.get("EMAIL_SMTP_USE_TLS")
        or os.getenv("EMAIL_SMTP_USE_TLS")
        or DEFAULT_EMAIL_SMTP_USE_TLS
    )
    email_from_address = str(
        raw.get("EMAIL_FROM_ADDRESS")
        or os.getenv("EMAIL_FROM_ADDRESS")
        or ""
    ).strip()
    email_from_name = str(
        raw.get("EMAIL_FROM_NAME")
        or os.getenv("EMAIL_FROM_NAME")
        or DEFAULT_EMAIL_FROM_NAME
    ).strip() or DEFAULT_EMAIL_FROM_NAME
    email_verify_token_ttl_sec = max(
        300,
        int(
            raw.get("EMAIL_VERIFY_TOKEN_TTL_SEC")
            or os.getenv("EMAIL_VERIFY_TOKEN_TTL_SEC")
            or DEFAULT_EMAIL_VERIFY_TOKEN_TTL_SEC
        ),
    )
    billing_contact_qr_url = str(
        raw.get("BILLING_CONTACT_QR_URL")
        or os.getenv("BILLING_CONTACT_QR_URL")
        or DEFAULT_BILLING_CONTACT_QR_URL
    ).strip() or DEFAULT_BILLING_CONTACT_QR_URL
    billing_contact_hint = str(
        raw.get("BILLING_CONTACT_HINT")
        or os.getenv("BILLING_CONTACT_HINT")
        or DEFAULT_BILLING_CONTACT_HINT
    ).strip() or DEFAULT_BILLING_CONTACT_HINT

    return AppConfig(
        chain_id=chain_id,
        ws_rpc_url=ws_rpc_url,
        http_rpc_url=http_rpc_url,
        backfill_http_rpc_url=backfill_http_rpc_url,
        virtual_token_addr=virtual_token_addr,
        fee_rate_default=fee_rate_default,
        total_supply_default=total_supply_default,
        launch_configs=launch_configs,
        my_wallets=my_wallets,
        top_n=int(raw.get("TOP_N", 20)),
        confirmations=int(raw.get("CONFIRMATIONS", 1)),
        agg_minute_window=int(raw.get("AGG_MINUTE_WINDOW", 0)),
        price_mode=price_mode,
        virtual_usdc_pair_addr=virtual_usdc_pair_addr,
        price_refresh_sec=int(raw.get("PRICE_REFRESH_SEC", 3)),
        db_mode=db_mode,
        sqlite_path=str(raw.get("SQLITE_PATH", "./data/virtuals_v11.db")),
        db_batch_size=int(raw.get("DB_BATCH_SIZE", 200)),
        db_flush_ms=int(raw.get("DB_FLUSH_MS", 500)),
        receipt_workers=receipt_workers,
        receipt_workers_realtime=receipt_workers_realtime,
        receipt_workers_backfill=receipt_workers_backfill,
        max_rpc_retries=int(raw.get("MAX_RPC_RETRIES", 5)),
        backfill_chunk_blocks=int(raw.get("BACKFILL_CHUNK_BLOCKS", 20)),
        backfill_interval_sec=int(raw.get("BACKFILL_INTERVAL_SEC", 8)),
        log_level=str(raw.get("LOG_LEVEL", "info")).lower(),
        jsonl_path=str(raw.get("JSONL_PATH", "./data/events.jsonl")),
        event_bus_sqlite_path=str(raw.get("EVENT_BUS_SQLITE_PATH", "./data/virtuals_bus.db")),
        api_host=str(raw.get("API_HOST", "127.0.0.1")),
        api_port=int(raw.get("API_PORT", 8080)),
        cors_allow_origins=cors_allow_origins,
        signalhub_base_url=signalhub_base_url,
        signalhub_timeout_sec=max(1, int(raw.get("SIGNALHUB_TIMEOUT_SEC", 8))),
        signalhub_upcoming_limit=max(1, int(raw.get("SIGNALHUB_UPCOMING_LIMIT", 12))),
        signalhub_within_hours=max(1, int(raw.get("SIGNALHUB_WITHIN_HOURS", 72))),
        bootstrap_admin_nickname=bootstrap_admin_nickname or None,
        bootstrap_admin_email=bootstrap_admin_email,
        bootstrap_admin_password=bootstrap_admin_password,
        session_cookie_name=session_cookie_name,
        session_ttl_sec=session_ttl_sec,
        session_secret=session_secret,
        app_public_base_url=app_public_base_url,
        email_enabled=email_enabled,
        email_smtp_host=email_smtp_host,
        email_smtp_port=email_smtp_port,
        email_smtp_username=email_smtp_username,
        email_smtp_password=email_smtp_password,
        email_smtp_use_tls=email_smtp_use_tls,
        email_from_address=email_from_address,
        email_from_name=email_from_name,
        email_verify_token_ttl_sec=email_verify_token_ttl_sec,
        billing_contact_qr_url=billing_contact_qr_url,
        billing_contact_hint=billing_contact_hint,
        backfill_http_rpc_urls=backfill_http_rpc_urls,
        backfill_public_http_rpc_urls=backfill_public_http_rpc_urls,
        backfill_rpc_quota_cooldown_sec=max(
            60, int(raw.get("BACKFILL_RPC_QUOTA_COOLDOWN_SEC", 60 * 60))
        ),
        backfill_rpc_transient_cooldown_sec=max(
            30, int(raw.get("BACKFILL_RPC_TRANSIENT_COOLDOWN_SEC", 10 * 60))
        ),
    )


class RPCClient:
    def __init__(self, url: str, max_retries: int = 5, timeout_sec: int = 12):
        self.url = url
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._session: Optional[aiohttp.ClientSession] = None
        self._id = 1

    async def __aenter__(self) -> "RPCClient":
        self._session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session:
            await self._session.close()

    async def call(self, method: str, params: List[Any]) -> Any:
        if not self._session:
            raise RuntimeError("RPC session is not initialized")
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self._id += 1

        backoff = 0.5
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._session.post(self.url, json=payload) as resp:
                    data = await resp.json(content_type=None)
                if "error" in data:
                    raise RuntimeError(f"RPC error: {data['error']}")
                return data.get("result")
            except Exception:
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2

    async def get_receipt(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        return await self.call("eth_getTransactionReceipt", [tx_hash])

    async def get_block_by_number(self, block_number: int) -> Optional[Dict[str, Any]]:
        return await self.call("eth_getBlockByNumber", [hex(block_number), False])

    async def get_latest_block_number(self) -> int:
        result = await self.call("eth_blockNumber", [])
        return int(result, 16)

    async def get_logs(
        self,
        from_block: int,
        to_block: int,
        address: Optional[str] = None,
        topics: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        f: Dict[str, Any] = {"fromBlock": hex(from_block), "toBlock": hex(to_block)}
        if address:
            f["address"] = address
        if topics:
            f["topics"] = topics
        result = await self.call("eth_getLogs", [f])
        return result or []

    async def eth_call(self, to: str, data: str) -> str:
        result = await self.call("eth_call", [{"to": to, "data": data}, "latest"])
        return result


class PriceService:
    def __init__(
        self,
        cfg: AppConfig,
        rpc: RPCClient,
        is_paused: Optional[Callable[[], bool]] = None,
    ):
        self.cfg = cfg
        self.rpc = rpc
        self._is_paused = is_paused
        self._price: Optional[Decimal] = None
        self._last_updated: float = 0.0
        self._token0: Optional[str] = None
        self._token1: Optional[str] = None
        self._token0_decimals: Optional[int] = None
        self._token1_decimals: Optional[int] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.cfg.price_mode != "onchain_pool":
            return
        if not self.cfg.virtual_usdc_pair_addr:
            return
        if not (self._is_paused and self._is_paused()):
            await self.refresh_once()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _loop(self) -> None:
        while True:
            try:
                if self._is_paused and self._is_paused():
                    await asyncio.sleep(1)
                    continue
                await self.refresh_once()
            except Exception:
                pass
            await asyncio.sleep(max(1, self.cfg.price_refresh_sec))

    async def _read_address(self, to: str, selector: str) -> str:
        out = await self.rpc.eth_call(to, selector)
        return "0x" + out[-40:].lower()

    async def _read_decimals(self, token: str) -> int:
        out = await self.rpc.eth_call(token, DECIMALS_SELECTOR)
        return int(out, 16)

    async def refresh_once(self) -> None:
        if not self.cfg.virtual_usdc_pair_addr:
            return
        pair = self.cfg.virtual_usdc_pair_addr
        async with self._lock:
            if not self._token0:
                self._token0 = normalize_address(await self._read_address(pair, TOKEN0_SELECTOR))
                self._token1 = normalize_address(await self._read_address(pair, TOKEN1_SELECTOR))
                self._token0_decimals = await self._read_decimals(self._token0)
                self._token1_decimals = await self._read_decimals(self._token1)

            reserves_hex = await self.rpc.eth_call(pair, GET_RESERVES_SELECTOR)
            if not reserves_hex or reserves_hex == "0x":
                return
            data = reserves_hex[2:]
            if len(data) < 64 * 3:
                return
            reserve0 = int(data[0:64], 16)
            reserve1 = int(data[64:128], 16)
            if reserve0 == 0 or reserve1 == 0:
                return

            vaddr = self.cfg.virtual_token_addr
            if self._token0 == vaddr:
                v = raw_to_decimal(reserve0, self._token0_decimals or 18)
                q = raw_to_decimal(reserve1, self._token1_decimals or 6)
            elif self._token1 == vaddr:
                v = raw_to_decimal(reserve1, self._token1_decimals or 18)
                q = raw_to_decimal(reserve0, self._token0_decimals or 6)
            else:
                return
            if v > 0:
                self._price = q / v
                self._last_updated = time.time()

    async def get_price(self) -> Tuple[Optional[Decimal], bool]:
        async with self._lock:
            if self._price is None:
                return None, True
            age = time.time() - self._last_updated
            return self._price, age > 120


class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                block_timestamp INTEGER NOT NULL,
                internal_pool TEXT NOT NULL,
                fee_addr TEXT NOT NULL,
                tax_addr TEXT NOT NULL,
                buyer TEXT NOT NULL,
                token_addr TEXT NOT NULL,
                token_bought TEXT NOT NULL,
                fee_v TEXT NOT NULL,
                tax_v TEXT NOT NULL,
                spent_v_est TEXT NOT NULL,
                spent_v_actual TEXT,
                cost_v TEXT NOT NULL,
                total_supply TEXT NOT NULL,
                virtual_price_usd TEXT,
                breakeven_fdv_v TEXT NOT NULL,
                breakeven_fdv_usd TEXT,
                is_my_wallet INTEGER NOT NULL,
                anomaly INTEGER NOT NULL,
                is_price_stale INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(project, tx_hash, buyer, token_addr)
            );

            CREATE INDEX IF NOT EXISTS idx_events_project_time
                ON events(project, block_timestamp);

            CREATE TABLE IF NOT EXISTS wallet_positions (
                project TEXT NOT NULL,
                wallet TEXT NOT NULL,
                token_addr TEXT NOT NULL,
                sum_fee_v TEXT NOT NULL,
                sum_spent_v_est TEXT NOT NULL,
                sum_token_bought TEXT NOT NULL,
                avg_cost_v TEXT NOT NULL,
                total_supply TEXT NOT NULL,
                breakeven_fdv_v TEXT NOT NULL,
                virtual_price_usd TEXT,
                breakeven_fdv_usd TEXT,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(project, wallet, token_addr)
            );

            CREATE TABLE IF NOT EXISTS minute_agg (
                project TEXT NOT NULL,
                minute_key INTEGER NOT NULL,
                minute_spent_v TEXT NOT NULL,
                minute_fee_v TEXT NOT NULL,
                minute_tax_v TEXT NOT NULL,
                minute_buy_count INTEGER NOT NULL,
                minute_unique_buyers INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(project, minute_key)
            );

            CREATE TABLE IF NOT EXISTS minute_buyers (
                project TEXT NOT NULL,
                minute_key INTEGER NOT NULL,
                buyer TEXT NOT NULL,
                PRIMARY KEY(project, minute_key, buyer)
            );

            CREATE TABLE IF NOT EXISTS leaderboard (
                project TEXT NOT NULL,
                buyer TEXT NOT NULL,
                sum_spent_v_est TEXT NOT NULL,
                sum_token_bought TEXT NOT NULL,
                last_tx_time INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                PRIMARY KEY(project, buyer)
            );

            CREATE TABLE IF NOT EXISTS project_stats (
                project TEXT PRIMARY KEY,
                sum_tax_v TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS launch_configs (
                name TEXT PRIMARY KEY,
                internal_pool_addr TEXT NOT NULL,
                fee_addr TEXT NOT NULL,
                tax_addr TEXT NOT NULL,
                token_addr TEXT,
                token_total_supply TEXT NOT NULL,
                fee_rate TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS managed_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                signalhub_project_id TEXT UNIQUE,
                detail_url TEXT NOT NULL DEFAULT '',
                token_addr TEXT,
                internal_pool_addr TEXT,
                start_at INTEGER NOT NULL,
                signalhub_end_at INTEGER,
                manual_end_at INTEGER,
                resolved_end_at INTEGER NOT NULL,
                is_watched INTEGER NOT NULL DEFAULT 1,
                collect_enabled INTEGER NOT NULL DEFAULT 1,
                backfill_enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_managed_projects_status_time
                ON managed_projects(status, start_at, resolved_end_at);

            CREATE TABLE IF NOT EXISTS monitored_wallets (
                wallet TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                source TEXT NOT NULL DEFAULT 'self_signup',
                credit_balance INTEGER NOT NULL DEFAULT 0,
                credit_spent_total INTEGER NOT NULL DEFAULT 0,
                credit_granted_total INTEGER NOT NULL DEFAULT 0,
                password_updated_at INTEGER NOT NULL,
                last_login_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_role_status
                ON users(role, status);

            CREATE TABLE IF NOT EXISTS pending_registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                verify_token_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                request_ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                device_fingerprint TEXT NOT NULL DEFAULT '',
                risk_level TEXT NOT NULL DEFAULT 'normal',
                expires_at INTEGER NOT NULL,
                verified_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pending_registrations_email_status
                ON pending_registrations(email, status);

            CREATE INDEX IF NOT EXISTS idx_pending_registrations_expires_at
                ON pending_registrations(expires_at);

            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                user_agent TEXT NOT NULL DEFAULT '',
                ip_addr TEXT NOT NULL DEFAULT '',
                last_seen_at INTEGER,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id
                ON user_sessions(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at
                ON user_sessions(expires_at);

            CREATE TABLE IF NOT EXISTS user_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wallet TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                is_enabled INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, wallet)
            );

            CREATE INDEX IF NOT EXISTS idx_user_wallets_user_id
                ON user_wallets(user_id);

            CREATE INDEX IF NOT EXISTS idx_user_wallets_wallet
                ON user_wallets(wallet);

            CREATE TABLE IF NOT EXISTS credit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                type TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                project_id INTEGER,
                payment_amount TEXT NOT NULL DEFAULT '',
                payment_proof_ref TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                operator_user_id INTEGER,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(operator_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_credit_ledger_user_id
                ON credit_ledger(user_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_credit_ledger_project_id
                ON credit_ledger(project_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_project_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                unlock_cost INTEGER NOT NULL DEFAULT 10,
                source TEXT NOT NULL DEFAULT 'credit_unlock',
                unlocked_at INTEGER NOT NULL,
                expires_at INTEGER,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, project_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_project_access_user_id
                ON user_project_access(user_id, unlocked_at DESC);

            CREATE INDEX IF NOT EXISTS idx_user_project_access_project_id
                ON user_project_access(project_id, unlocked_at DESC);

            CREATE TABLE IF NOT EXISTS billing_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL DEFAULT '',
                requested_credits INTEGER NOT NULL,
                payment_amount TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                proof_storage_key TEXT NOT NULL DEFAULT '',
                proof_original_name TEXT NOT NULL DEFAULT '',
                proof_content_type TEXT NOT NULL DEFAULT '',
                proof_size INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending_review',
                admin_note TEXT NOT NULL DEFAULT '',
                credited_credit_ledger_id INTEGER,
                operator_user_id INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                credited_at INTEGER,
                notified_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(operator_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_billing_requests_user_status
                ON billing_requests(user_id, status, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_billing_requests_status
                ON billing_requests(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS user_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'info',
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                action_url TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_id INTEGER,
                delta INTEGER NOT NULL DEFAULT 0,
                project_id INTEGER,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                read_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_user_notifications_user_created
                ON user_notifications(user_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_user_notifications_user_unread
                ON user_notifications(user_id, is_read, created_at DESC);

            CREATE TABLE IF NOT EXISTS auth_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup
                ON auth_attempts(event_type, subject, created_at DESC);

            CREATE TABLE IF NOT EXISTS dead_letters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_hash TEXT NOT NULL,
                reason TEXT NOT NULL,
                payload TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scanned_backfill_txs (
                project TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                scanned_at INTEGER NOT NULL,
                PRIMARY KEY(project, tx_hash)
            );
            """
        )
        self._ensure_column("monitored_wallets", "name", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("users", "credit_balance", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("users", "credit_spent_total", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("users", "credit_granted_total", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("users", "source", "TEXT NOT NULL DEFAULT 'self_signup'")
        self._ensure_column("users", "email_verified_at", "INTEGER")
        self._ensure_column("users", "signup_ip", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("users", "signup_device_fingerprint", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("users", "signup_bonus_granted_at", "INTEGER")
        self._ensure_column("credit_ledger", "payment_amount", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("credit_ledger", "payment_proof_ref", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("launch_configs", "token_addr", "TEXT")
        self._ensure_column("billing_requests", "admin_note", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("billing_requests", "credited_credit_ledger_id", "INTEGER")
        self._ensure_column("billing_requests", "operator_user_id", "INTEGER")
        self._ensure_column("billing_requests", "reviewed_at", "INTEGER")
        self._ensure_column("billing_requests", "credited_at", "INTEGER")
        self._ensure_column("billing_requests", "notified_at", "INTEGER")
        self._ensure_column("user_notifications", "delta", "INTEGER NOT NULL DEFAULT 0")
        self.conn.execute(
            """
            UPDATE users
            SET email_verified_at = COALESCE(email_verified_at, created_at)
            WHERE email_verified_at IS NULL
            """
        )
        self.conn.commit()
        self._ensure_column("user_notifications", "project_id", "INTEGER")
        self.conn.commit()

    def _ensure_column(self, table_name: str, column_name: str, ddl: str) -> None:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        known = {str(row["name"]) for row in rows}
        if column_name in known:
            return
        self.conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}")

    def get_state(self, key: str) -> Optional[str]:
        cur = self.conn.execute("SELECT value FROM system_state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO system_state(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        self.conn.commit()

    def record_auth_attempt(
        self, event_type: str, subject: str, created_at: Optional[int] = None
    ) -> None:
        event_type_value = require_nonempty_text(event_type, "event_type")
        subject_value = require_nonempty_text(subject, "subject")
        now = int(created_at or time.time())
        self.conn.execute(
            """
            INSERT INTO auth_attempts(event_type, subject, created_at)
            VALUES (?, ?, ?)
            """,
            (event_type_value, subject_value, now),
        )
        self.conn.commit()

    def count_auth_attempts(self, event_type: str, subject: str, since_ts: int) -> int:
        event_type_value = require_nonempty_text(event_type, "event_type")
        subject_value = require_nonempty_text(subject, "subject")
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM auth_attempts
            WHERE event_type = ? AND subject = ? AND created_at >= ?
            """,
            (event_type_value, subject_value, int(since_ts)),
        ).fetchone()
        return int(row["c"] or 0) if row else 0

    def prune_auth_attempts(self, before_ts: int) -> None:
        self.conn.execute(
            """
            DELETE FROM auth_attempts
            WHERE created_at < ?
            """,
            (int(before_ts),),
        )
        self.conn.commit()

    def seed_launch_configs(self, launch_configs: List[LaunchConfig]) -> None:
        now = int(time.time())
        cur = self.conn.cursor()
        for lc in launch_configs:
            cur.execute(
                """
                INSERT OR IGNORE INTO launch_configs(
                    name, internal_pool_addr, fee_addr, tax_addr, token_addr,
                    token_total_supply, fee_rate, is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    lc.name,
                    lc.internal_pool_addr,
                    lc.fee_addr,
                    lc.tax_addr,
                    lc.token_addr,
                    decimal_to_str(lc.token_total_supply, 0),
                    decimal_to_str(lc.fee_rate, 18),
                    now,
                    now,
                ),
            )
        self.conn.commit()

    def seed_monitored_wallets(self, wallets: Set[str]) -> None:
        if not wallets:
            return
        now = int(time.time())
        cur = self.conn.cursor()
        for wallet in sorted(wallets):
            cur.execute(
                """
                INSERT OR IGNORE INTO monitored_wallets(wallet, name, created_at, updated_at)
                VALUES (?, '', ?, ?)
                """,
                (normalize_address(wallet), now, now),
            )
        self.conn.commit()

    def list_launch_configs(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM launch_configs
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def list_monitored_wallet_rows(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT wallet, name, created_at, updated_at
            FROM monitored_wallets
            ORDER BY updated_at DESC, wallet ASC
            """
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            wallet = row["wallet"]
            if not wallet:
                continue
            out.append(
                {
                    "wallet": normalize_address(str(wallet)),
                    "name": str(row["name"] or "").strip(),
                    "created_at": int(row["created_at"]),
                    "updated_at": int(row["updated_at"]),
                }
            )
        return out

    def list_monitored_wallets(self) -> List[str]:
        return [str(row["wallet"]) for row in self.list_monitored_wallet_rows()]

    def list_projects(self) -> List[str]:
        rows = self.conn.execute(
            """
            SELECT name AS project FROM launch_configs
            UNION
            SELECT name AS project FROM managed_projects
            UNION
            SELECT project FROM events
            UNION
            SELECT project FROM minute_agg
            UNION
            SELECT project FROM leaderboard
            UNION
            SELECT project FROM wallet_positions
            ORDER BY project ASC
            """
        ).fetchall()
        return [str(r["project"]) for r in rows if r["project"]]

    def get_enabled_launch_configs(self) -> List[LaunchConfig]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM launch_configs
            WHERE is_enabled = 1
            ORDER BY name ASC
            """
        ).fetchall()
        result: List[LaunchConfig] = []
        for r in rows:
            result.append(
                LaunchConfig(
                    name=r["name"],
                    internal_pool_addr=normalize_address(r["internal_pool_addr"]),
                    fee_addr=normalize_address(r["fee_addr"]),
                    tax_addr=normalize_address(r["tax_addr"]),
                    token_addr=normalize_optional_address(r["token_addr"]),
                    token_total_supply=Decimal(str(r["token_total_supply"])),
                    fee_rate=Decimal(str(r["fee_rate"])),
                )
            )
        return result

    def get_launch_config_by_name(self, name: str) -> Optional[LaunchConfig]:
        row = self.conn.execute(
            """
            SELECT *
            FROM launch_configs
            WHERE name = ?
            """,
            (name,),
        ).fetchone()
        if not row:
            return None
        return LaunchConfig(
            name=row["name"],
            internal_pool_addr=normalize_address(row["internal_pool_addr"]),
            fee_addr=normalize_address(row["fee_addr"]),
            tax_addr=normalize_address(row["tax_addr"]),
            token_addr=normalize_optional_address(row["token_addr"]),
            token_total_supply=Decimal(str(row["token_total_supply"])),
            fee_rate=Decimal(str(row["fee_rate"])),
        )

    def upsert_launch_config(
        self,
        *,
        name: str,
        internal_pool_addr: str,
        fee_addr: str,
        tax_addr: str,
        token_addr: Optional[str],
        token_total_supply: Decimal,
        fee_rate: Decimal,
        is_enabled: bool = True,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
        if fee_rate <= 0 or fee_rate >= 1:
            raise ValueError("fee_rate must be in (0,1)")
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO launch_configs(
                name, internal_pool_addr, fee_addr, tax_addr, token_addr,
                token_total_supply, fee_rate, is_enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                internal_pool_addr = excluded.internal_pool_addr,
                fee_addr = excluded.fee_addr,
                tax_addr = excluded.tax_addr,
                token_addr = excluded.token_addr,
                token_total_supply = excluded.token_total_supply,
                fee_rate = excluded.fee_rate,
                is_enabled = excluded.is_enabled,
                updated_at = excluded.updated_at
            """,
            (
                name,
                normalize_address(internal_pool_addr),
                normalize_address(fee_addr),
                normalize_address(tax_addr),
                normalize_optional_address(token_addr),
                decimal_to_str(token_total_supply, 0),
                decimal_to_str(fee_rate, 18),
                1 if is_enabled else 0,
                now,
                now,
            ),
        )
        self.conn.commit()

    def delete_launch_config(self, name: str) -> bool:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
        cur = self.conn.execute(
            """
            DELETE FROM launch_configs
            WHERE name = ?
            """,
            (name,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def set_launch_config_enabled_only(self, name: str) -> None:
        self.conn.execute(
            """
            UPDATE launch_configs
            SET is_enabled = CASE WHEN name = ? THEN 1 ELSE 0 END,
                updated_at = ?
            """,
            (name, int(time.time())),
        )
        self.conn.commit()

    def add_monitored_wallet(self, wallet: str, name: str = "") -> None:
        now = int(time.time())
        normalized = normalize_address(wallet)
        display_name = str(name).strip()
        self.conn.execute(
            """
            INSERT INTO monitored_wallets(wallet, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(wallet) DO UPDATE SET
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (normalized, display_name, now, now),
        )
        self.conn.commit()

    def delete_monitored_wallet(self, wallet: str) -> bool:
        normalized = normalize_address(wallet)
        cur = self.conn.execute(
            """
            DELETE FROM monitored_wallets
            WHERE wallet = ?
            """,
            (normalized,),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (normalize_email(email),),
        ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (int(user_id),),
        ).fetchone()
        return dict(row) if row else None

    def _normalize_pending_registration_row(
        self, row: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        item = dict(row)
        status_value = str(item.get("status") or "").strip().lower()
        expires_at = int(item.get("expires_at") or 0)
        now = int(time.time())
        if status_value == "pending" and expires_at and expires_at <= now:
            self.conn.execute(
                """
                UPDATE pending_registrations
                SET status = 'expired', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, int(item["id"])),
            )
            self.conn.commit()
            item["status"] = "expired"
            item["updated_at"] = now
        return item

    def get_pending_registration_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM pending_registrations
            WHERE email = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (normalize_email(email),),
        ).fetchone()
        return self._normalize_pending_registration_row(dict(row)) if row else None

    def get_pending_registration_by_token_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM pending_registrations
            WHERE verify_token_hash = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (require_nonempty_text(token_hash, "token_hash"),),
        ).fetchone()
        return self._normalize_pending_registration_row(dict(row)) if row else None

    def upsert_pending_registration(
        self,
        *,
        nickname: str,
        email: str,
        password_hash: str,
        verify_token_hash: str,
        request_ip: str = "",
        user_agent: str = "",
        device_fingerprint: str = "",
        risk_level: str = "normal",
        expires_at: int,
    ) -> Dict[str, Any]:
        nickname_value = require_nonempty_text(nickname, "nickname")
        email_value = normalize_email(email)
        password_hash_value = require_nonempty_text(password_hash, "password_hash")
        verify_token_hash_value = require_nonempty_text(verify_token_hash, "verify_token_hash")
        risk_level_value = str(risk_level or "normal").strip().lower() or "normal"
        if risk_level_value not in {"normal", "suspicious", "blocked"}:
            raise ValueError(f"invalid risk level: {risk_level_value}")
        now = int(time.time())
        existing = self.conn.execute(
            """
            SELECT id
            FROM pending_registrations
            WHERE email = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (email_value,),
        ).fetchone()
        with self.conn:
            if existing:
                self.conn.execute(
                    """
                    UPDATE pending_registrations
                    SET nickname = ?,
                        password_hash = ?,
                        verify_token_hash = ?,
                        status = 'pending',
                        request_ip = ?,
                        user_agent = ?,
                        device_fingerprint = ?,
                        risk_level = ?,
                        expires_at = ?,
                        verified_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        nickname_value,
                        password_hash_value,
                        verify_token_hash_value,
                        str(request_ip or "").strip(),
                        str(user_agent or "").strip(),
                        str(device_fingerprint or "").strip(),
                        risk_level_value,
                        int(expires_at),
                        now,
                        int(existing["id"]),
                    ),
                )
                pending_id = int(existing["id"])
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO pending_registrations(
                        nickname, email, password_hash, verify_token_hash,
                        status, request_ip, user_agent, device_fingerprint,
                        risk_level, expires_at, verified_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        nickname_value,
                        email_value,
                        password_hash_value,
                        verify_token_hash_value,
                        str(request_ip or "").strip(),
                        str(user_agent or "").strip(),
                        str(device_fingerprint or "").strip(),
                        risk_level_value,
                        int(expires_at),
                        now,
                        now,
                    ),
                )
                pending_id = int(cur.lastrowid)
        row = self.conn.execute(
            """
            SELECT *
            FROM pending_registrations
            WHERE id = ?
            """,
            (pending_id,),
        ).fetchone()
        if not row:
            raise ValueError("failed to upsert pending registration")
        return self._normalize_pending_registration_row(dict(row)) or {}

    def update_pending_registration_status(
        self,
        pending_id: int,
        *,
        status: str,
        verified_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        status_value = str(status or "").strip().lower()
        if status_value not in {"pending", "verified", "expired", "canceled", "blocked"}:
            raise ValueError(f"invalid pending registration status: {status_value}")
        now = int(time.time())
        cur = self.conn.execute(
            """
            UPDATE pending_registrations
            SET status = ?,
                verified_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status_value,
                int(verified_at) if verified_at is not None else None,
                now,
                int(pending_id),
            ),
        )
        self.conn.commit()
        if cur.rowcount <= 0:
            raise ValueError("pending registration not found")
        row = self.conn.execute(
            """
            SELECT *
            FROM pending_registrations
            WHERE id = ?
            """,
            (int(pending_id),),
        ).fetchone()
        return self._normalize_pending_registration_row(dict(row)) if row else {}

    def _credit_spent_increment(self, entry_type: str, delta: int) -> int:
        if str(entry_type or "").strip().lower() == "project_unlock" and int(delta) < 0:
            return abs(int(delta))
        return 0

    def _credit_granted_increment(self, delta: int) -> int:
        return max(0, int(delta))

    def _apply_credit_delta_in_tx(
        self,
        executor: sqlite3.Connection,
        *,
        user_id: int,
        delta: int,
        entry_type: str,
        source: str = "",
        project_id: Optional[int] = None,
        payment_amount: str = "",
        payment_proof_ref: str = "",
        note: str = "",
        operator_user_id: Optional[int] = None,
        now_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        delta_value = int(delta)
        if delta_value == 0:
            raise ValueError("delta must not be 0")
        type_value = str(entry_type or "").strip().lower()
        if type_value not in CREDIT_LEDGER_TYPES:
            raise ValueError(f"invalid credit entry type: {type_value}")
        now = int(now_ts or time.time())
        row = executor.execute(
            """
            SELECT id, credit_balance, credit_spent_total, credit_granted_total
            FROM users
            WHERE id = ?
            """,
            (int(user_id),),
        ).fetchone()
        if not row:
            raise ValueError(f"user not found: {user_id}")
        current_balance = int(row["credit_balance"] or 0)
        current_spent = int(row["credit_spent_total"] or 0)
        current_granted = int(row["credit_granted_total"] or 0)
        next_balance = current_balance + delta_value
        if next_balance < 0:
            raise ValueError("insufficient credits")
        next_spent = current_spent + self._credit_spent_increment(type_value, delta_value)
        next_granted = current_granted + self._credit_granted_increment(delta_value)
        executor.execute(
            """
            UPDATE users
            SET credit_balance = ?,
                credit_spent_total = ?,
                credit_granted_total = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (next_balance, next_spent, next_granted, now, int(user_id)),
        )
        ledger_cur = executor.execute(
            """
            INSERT INTO credit_ledger(
                user_id, delta, balance_after, type, source,
                project_id, payment_amount, payment_proof_ref,
                note, operator_user_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                delta_value,
                next_balance,
                type_value,
                str(source or ""),
                int(project_id) if project_id is not None else None,
                str(payment_amount or "").strip(),
                str(payment_proof_ref or "").strip(),
                str(note or "").strip(),
                int(operator_user_id) if operator_user_id is not None else None,
                now,
            ),
        )
        updated_row = executor.execute(
            """
            SELECT *
            FROM users
            WHERE id = ?
            """,
            (int(user_id),),
        ).fetchone()
        if not updated_row:
            raise ValueError(f"user not found: {user_id}")
        result = dict(updated_row)
        result["credit_ledger_id"] = int(ledger_cur.lastrowid or 0)
        return result

    def create_user(
        self,
        *,
        nickname: str,
        email: str,
        password_hash: str,
        role: str = "user",
        status: str = "active",
        source: str = "self_signup",
        signup_bonus_credits: int = 0,
        email_verified_at: Optional[int] = None,
        signup_ip: str = "",
        signup_device_fingerprint: str = "",
        signup_bonus_granted_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        nickname_value = require_nonempty_text(nickname, "nickname")
        email_value = normalize_email(email)
        role_value = str(role or "user").strip().lower()
        status_value = str(status or "active").strip().lower()
        source_value = str(source or "self_signup").strip().lower()
        if role_value not in USER_ROLES:
            raise ValueError(f"invalid role: {role_value}")
        if status_value not in USER_STATUSES:
            raise ValueError(f"invalid status: {status_value}")
        if source_value not in USER_SOURCES:
            raise ValueError(f"invalid source: {source_value}")
        now = int(time.time())
        bonus_credits = max(0, int(signup_bonus_credits or 0))
        email_verified_ts = (
            int(email_verified_at)
            if email_verified_at is not None
            else (now if role_value == "admin" else None)
        )
        signup_bonus_granted_ts = (
            int(signup_bonus_granted_at)
            if signup_bonus_granted_at is not None
            else (now if bonus_credits > 0 else None)
        )
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO users(
                    nickname, email, password_hash, role, status, source,
                    credit_balance, credit_spent_total, credit_granted_total,
                    password_updated_at, last_login_at, created_at, updated_at,
                    email_verified_at, signup_ip, signup_device_fingerprint, signup_bonus_granted_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nickname_value,
                    email_value,
                    require_nonempty_text(password_hash, "password_hash"),
                    role_value,
                    status_value,
                    source_value,
                    now,
                    now,
                    now,
                    email_verified_ts,
                    str(signup_ip or "").strip(),
                    str(signup_device_fingerprint or "").strip(),
                    signup_bonus_granted_ts,
                ),
            )
            user_id = int(cur.lastrowid)
            if bonus_credits > 0:
                updated_user = self._apply_credit_delta_in_tx(
                    self.conn,
                    user_id=user_id,
                    delta=bonus_credits,
                    entry_type="signup_bonus",
                    source="auth.register",
                    note="new user signup bonus",
                    now_ts=now,
                )
                notification_content = self.build_credit_notification_content(
                    entry_type="signup_bonus",
                    delta=bonus_credits,
                    note="new user signup bonus",
                )
                self._create_user_notification_in_tx(
                    self.conn,
                    user_id=user_id,
                    kind=notification_content["kind"],
                    title=notification_content["title"],
                    body=notification_content["body"],
                    action_url=notification_content["action_url"],
                    source_type="credit:signup_bonus",
                    source_id=int(updated_user.get("credit_ledger_id") or 0) or None,
                    delta=bonus_credits,
                    created_at=now,
                )
        row = self.get_user_by_id(int(cur.lastrowid))
        if not row:
            raise ValueError("failed to create user")
        return row

    def bootstrap_admin(
        self,
        *,
        nickname: Optional[str],
        email: Optional[str],
        password_hash: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if not email or not password_hash:
            return None
        email_value = normalize_email(email)
        existing = self.get_user_by_email(email_value)
        if existing:
            updated = False
            now = int(time.time())
            updates: List[str] = []
            params: List[Any] = []
            if str(existing.get("role") or "").lower() != "admin":
                updates.append("role = ?")
                params.append("admin")
                updated = True
            if str(existing.get("status") or "").lower() != "active":
                updates.append("status = ?")
                params.append("active")
                updated = True
            if nickname and str(existing.get("nickname") or "").strip() != nickname.strip():
                updates.append("nickname = ?")
                params.append(nickname.strip())
                updated = True
            if updated:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(int(existing["id"]))
                self.conn.execute(
                    f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                self.conn.commit()
            return self.get_user_by_id(int(existing["id"]))
        return self.create_user(
            nickname=nickname or "Administrator",
            email=email_value,
            password_hash=password_hash,
            role="admin",
            status="active",
            source="admin_created",
        )

    def update_user_last_login(self, user_id: int) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE users
            SET last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(user_id)),
        )
        self.conn.commit()

    def update_user_status(self, user_id: int, status: str) -> Dict[str, Any]:
        status_value = str(status or "").strip().lower()
        if status_value not in USER_STATUSES:
            raise ValueError(f"invalid status: {status_value}")
        cur = self.conn.execute(
            """
            UPDATE users
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status_value, int(time.time()), int(user_id)),
        )
        self.conn.commit()
        if cur.rowcount <= 0:
            raise ValueError(f"user not found: {user_id}")
        row = self.get_user_by_id(int(user_id))
        if not row:
            raise ValueError(f"user not found: {user_id}")
        return row

    def update_users_status(self, user_ids: List[int], status: str) -> List[Dict[str, Any]]:
        unique_ids = sorted({int(user_id) for user_id in user_ids if int(user_id) > 0})
        if not unique_ids:
            return []
        status_value = str(status or "").strip().lower()
        if status_value not in USER_STATUSES:
            raise ValueError(f"invalid status: {status_value}")
        now = int(time.time())
        placeholders = ",".join("?" for _ in unique_ids)
        params: List[Any] = [status_value, now, *unique_ids]
        self.conn.execute(
            f"""
            UPDATE users
            SET status = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            params,
        )
        self.conn.commit()
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM users
            WHERE id IN ({placeholders})
            ORDER BY created_at DESC, id DESC
            """,
            tuple(unique_ids),
        ).fetchall()
        return [dict(row) for row in rows]

    def update_user_password(self, user_id: int, password_hash: str) -> Dict[str, Any]:
        now = int(time.time())
        cur = self.conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                password_updated_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (require_nonempty_text(password_hash, "password_hash"), now, now, int(user_id)),
        )
        self.conn.commit()
        if cur.rowcount <= 0:
            raise ValueError(f"user not found: {user_id}")
        row = self.get_user_by_id(int(user_id))
        if not row:
            raise ValueError(f"user not found: {user_id}")
        return row

    def list_users(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                users.*,
                COUNT(DISTINCT user_wallets.id) AS wallet_count,
                COUNT(DISTINCT user_project_access.id) AS unlocked_project_count
            FROM users
            LEFT JOIN user_wallets ON user_wallets.user_id = users.id
            LEFT JOIN user_project_access ON user_project_access.user_id = users.id
            GROUP BY users.id
            ORDER BY users.created_at DESC, users.id DESC
            """
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["wallet_count"] = int(item.get("wallet_count") or 0)
            item["unlocked_project_count"] = int(item.get("unlocked_project_count") or 0)
            item["password_set"] = bool(str(item.get("password_hash") or "").strip())
            items.append(item)
        return items

    def delete_user(self, user_id: int) -> Dict[str, Any]:
        row = self.get_user_by_id(int(user_id))
        if not row:
            raise ValueError(f"user not found: {user_id}")
        with self.conn:
            self.conn.execute(
                """
                DELETE FROM users
                WHERE id = ?
                """,
                (int(user_id),),
            )
        return row

    def get_user_project_access(self, user_id: int, project_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM user_project_access
            WHERE user_id = ? AND project_id = ?
            """,
            (int(user_id), int(project_id)),
        ).fetchone()
        return dict(row) if row else None

    def list_user_project_access_rows(self, user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                user_project_access.*,
                managed_projects.name AS project_name,
                managed_projects.detail_url AS project_detail_url,
                managed_projects.status AS project_status,
                managed_projects.start_at AS project_start_at,
                managed_projects.resolved_end_at AS project_resolved_end_at
            FROM user_project_access
            LEFT JOIN managed_projects ON managed_projects.id = user_project_access.project_id
            WHERE user_project_access.user_id = ?
            ORDER BY user_project_access.unlocked_at DESC, user_project_access.id DESC
            LIMIT ?
            """,
            (int(user_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_user_credit_ledger_rows(self, user_id: int, limit: int = 200) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                credit_ledger.*,
                managed_projects.name AS project_name,
                operator.nickname AS operator_nickname,
                operator.email AS operator_email
            FROM credit_ledger
            LEFT JOIN managed_projects ON managed_projects.id = credit_ledger.project_id
            LEFT JOIN users AS operator ON operator.id = credit_ledger.operator_user_id
            WHERE credit_ledger.user_id = ?
            ORDER BY credit_ledger.created_at DESC, credit_ledger.id DESC
            LIMIT ?
            """,
            (int(user_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def _create_user_notification_in_tx(
        self,
        executor: sqlite3.Connection,
        *,
        user_id: int,
        kind: str,
        title: str,
        body: str = "",
        action_url: str = "",
        source_type: str = "",
        source_id: Optional[int] = None,
        delta: int = 0,
        project_id: Optional[int] = None,
        created_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = int(created_at or time.time())
        notification_cur = executor.execute(
            """
            INSERT INTO user_notifications(
                user_id, kind, title, body, action_url,
                source_type, source_id, delta, project_id,
                is_read, created_at, read_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL)
            """,
            (
                int(user_id),
                normalize_notification_kind(kind),
                require_nonempty_text(title, "title"),
                str(body or "").strip(),
                str(action_url or "").strip(),
                str(source_type or "").strip(),
                int(source_id) if source_id is not None else None,
                int(delta or 0),
                int(project_id) if project_id is not None else None,
                now,
            ),
        )
        row = executor.execute(
            """
            SELECT *
            FROM user_notifications
            WHERE id = ?
            """,
            (int(notification_cur.lastrowid),),
        ).fetchone()
        if not row:
            raise ValueError("failed to create notification")
        return dict(row)

    def create_user_notification(
        self,
        *,
        user_id: int,
        kind: str,
        title: str,
        body: str = "",
        action_url: str = "",
        source_type: str = "",
        source_id: Optional[int] = None,
        delta: int = 0,
        project_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self.conn:
            return self._create_user_notification_in_tx(
                self.conn,
                user_id=int(user_id),
                kind=kind,
                title=title,
                body=body,
                action_url=action_url,
                source_type=source_type,
                source_id=source_id,
                delta=delta,
                project_id=project_id,
            )

    def build_credit_notification_content(
        self,
        *,
        entry_type: str,
        delta: int,
        project_name: str = "",
        payment_amount: str = "",
        note: str = "",
    ) -> Dict[str, str]:
        entry = str(entry_type or "").strip().lower()
        delta_value = int(delta or 0)
        payment_amount_value = str(payment_amount or "").strip()
        note_value = str(note or "").strip()
        project_name_value = str(project_name or "").strip()
        if entry == "signup_bonus":
            return {
                "kind": "success",
                "title": "新用户积分已到账",
                "body": f"系统已赠送 {max(delta_value, 0)} 积分。",
                "action_url": "/app/billing",
            }
        if entry == "manual_topup":
            details = [f"管理员已为你入账 {max(delta_value, 0)} 积分。"]
            if payment_amount_value:
                details.append(f"实付 {payment_amount_value}")
            if note_value:
                details.append(note_value)
            return {
                "kind": "success",
                "title": "充值积分已到账",
                "body": " ".join(details),
                "action_url": "/app/billing",
            }
        if entry == "manual_adjustment":
            return {
                "kind": "warning" if delta_value < 0 else "info",
                "title": "积分已扣减" if delta_value < 0 else "积分已调整",
                "body": note_value or f"管理员已调整 {abs(delta_value)} 积分。",
                "action_url": "/app/billing",
            }
        if entry == "project_unlock":
            return {
                "kind": "accent",
                "title": f"{project_name_value or '项目'} 已解锁",
                "body": f"已扣除 {abs(delta_value)} 积分，Overview 现已永久可读。",
                "action_url": "/app/overview",
            }
        return {
            "kind": "info",
            "title": "账户有新的动态",
            "body": note_value or f"积分变动 {delta_value:+d}",
            "action_url": "/app/billing",
        }

    def list_user_notifications_rows(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                user_notifications.*,
                managed_projects.name AS project_name
            FROM user_notifications
            LEFT JOIN managed_projects ON managed_projects.id = user_notifications.project_id
            WHERE user_notifications.user_id = ?
            ORDER BY user_notifications.created_at DESC, user_notifications.id DESC
            LIMIT ?
            """,
            (int(user_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_user_notifications(self, user_id: int, *, unread_only: bool = False) -> int:
        if unread_only:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS count_value
                FROM user_notifications
                WHERE user_id = ? AND is_read = 0
                """,
                (int(user_id),),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS count_value
                FROM user_notifications
                WHERE user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
        if not row:
            return 0
        return int(row["count_value"] or 0)

    def mark_user_notification_read(self, user_id: int, notification_id: int) -> Optional[Dict[str, Any]]:
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE user_notifications
            SET is_read = 1,
                read_at = COALESCE(read_at, ?)
            WHERE id = ? AND user_id = ?
            """,
            (now, int(notification_id), int(user_id)),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM user_notifications
            WHERE id = ? AND user_id = ?
            """,
            (int(notification_id), int(user_id)),
        ).fetchone()
        return dict(row) if row else None

    def mark_all_user_notifications_read(self, user_id: int) -> int:
        now = int(time.time())
        cur = self.conn.execute(
            """
            UPDATE user_notifications
            SET is_read = 1,
                read_at = COALESCE(read_at, ?)
            WHERE user_id = ? AND is_read = 0
            """,
            (now, int(user_id)),
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def create_billing_request(
        self,
        *,
        user_id: int,
        plan_id: str,
        requested_credits: int,
        payment_amount: str = "",
        note: str = "",
        proof_storage_key: str = "",
        proof_original_name: str = "",
        proof_content_type: str = "",
        proof_size: int = 0,
    ) -> Dict[str, Any]:
        credits = max(1, int(requested_credits or 0))
        now = int(time.time())
        cur = self.conn.execute(
            """
            INSERT INTO billing_requests(
                user_id, plan_id, requested_credits, payment_amount, note,
                proof_storage_key, proof_original_name, proof_content_type, proof_size,
                status, admin_note, credited_credit_ledger_id, operator_user_id,
                created_at, updated_at, reviewed_at, credited_at, notified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', '', NULL, NULL, ?, ?, NULL, NULL, NULL)
            """,
            (
                int(user_id),
                str(plan_id or "").strip(),
                credits,
                str(payment_amount or "").strip(),
                str(note or "").strip(),
                str(proof_storage_key or "").strip(),
                str(proof_original_name or "").strip(),
                str(proof_content_type or "").strip(),
                max(0, int(proof_size or 0)),
                now,
                now,
            ),
        )
        self.conn.commit()
        row = self.get_billing_request(int(cur.lastrowid))
        if not row:
            raise ValueError("failed to create billing request")
        return row

    def get_billing_request(self, request_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT
                billing_requests.*,
                users.nickname AS user_nickname,
                users.email AS user_email,
                operator.nickname AS operator_nickname,
                operator.email AS operator_email
            FROM billing_requests
            LEFT JOIN users ON users.id = billing_requests.user_id
            LEFT JOIN users AS operator ON operator.id = billing_requests.operator_user_id
            WHERE billing_requests.id = ?
            """,
            (int(request_id),),
        ).fetchone()
        return dict(row) if row else None

    def get_billing_request_for_user(self, user_id: int, request_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT
                billing_requests.*,
                users.nickname AS user_nickname,
                users.email AS user_email,
                operator.nickname AS operator_nickname,
                operator.email AS operator_email
            FROM billing_requests
            LEFT JOIN users ON users.id = billing_requests.user_id
            LEFT JOIN users AS operator ON operator.id = billing_requests.operator_user_id
            WHERE billing_requests.id = ? AND billing_requests.user_id = ?
            """,
            (int(request_id), int(user_id)),
        ).fetchone()
        return dict(row) if row else None

    def list_user_billing_requests(self, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                billing_requests.*,
                operator.nickname AS operator_nickname,
                operator.email AS operator_email
            FROM billing_requests
            LEFT JOIN users AS operator ON operator.id = billing_requests.operator_user_id
            WHERE billing_requests.user_id = ?
            ORDER BY billing_requests.created_at DESC, billing_requests.id DESC
            LIMIT ?
            """,
            (int(user_id), max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_billing_requests(
        self,
        *,
        status: str = "",
        query: str = "",
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT
                billing_requests.*,
                users.nickname AS user_nickname,
                users.email AS user_email,
                operator.nickname AS operator_nickname,
                operator.email AS operator_email
            FROM billing_requests
            LEFT JOIN users ON users.id = billing_requests.user_id
            LEFT JOIN users AS operator ON operator.id = billing_requests.operator_user_id
            WHERE 1 = 1
        """
        params: List[Any] = []
        if status:
            sql += " AND billing_requests.status = ?"
            params.append(normalize_billing_request_status(status))
        if query:
            pattern = f"%{str(query or '').strip().lower()}%"
            sql += """
                AND (
                    LOWER(COALESCE(users.nickname, '')) LIKE ?
                    OR LOWER(COALESCE(users.email, '')) LIKE ?
                    OR LOWER(COALESCE(billing_requests.plan_id, '')) LIKE ?
                    OR LOWER(COALESCE(billing_requests.note, '')) LIKE ?
                )
            """
            params.extend([pattern, pattern, pattern, pattern])
        sql += """
            ORDER BY
                CASE billing_requests.status
                    WHEN 'pending_review' THEN 0
                    WHEN 'credited' THEN 1
                    WHEN 'notified' THEN 2
                    ELSE 3
                END,
                billing_requests.created_at DESC,
                billing_requests.id DESC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def credit_billing_request(
        self,
        request_id: int,
        *,
        operator_user_id: int,
        credits: Optional[int] = None,
        amount_paid: Optional[str] = None,
        admin_note: str = "",
    ) -> Dict[str, Any]:
        request_row = self.get_billing_request(int(request_id))
        if not request_row:
            raise ValueError(f"billing request not found: {request_id}")
        status = normalize_billing_request_status(request_row.get("status"))
        if status not in {"pending_review", "credited", "notified"}:
            raise ValueError(f"billing request cannot be credited from status: {status}")
        if status in {"credited", "notified"}:
            return request_row
        now = int(time.time())
        credit_amount = int(credits or request_row.get("requested_credits") or 0)
        if credit_amount <= 0:
            raise ValueError("credits must be positive")
        note_parts = [str(request_row.get("note") or "").strip(), str(admin_note or "").strip()]
        topup_note = " / ".join([part for part in note_parts if part]) or "manual topup"
        with self.conn:
            updated_user = self._apply_credit_delta_in_tx(
                self.conn,
                user_id=int(request_row["user_id"]),
                delta=credit_amount,
                entry_type="manual_topup",
                source="admin.billing_request_credit",
                payment_amount=str(amount_paid or request_row.get("payment_amount") or "").strip(),
                payment_proof_ref=str(request_row.get("proof_original_name") or f"billing_request:{request_id}"),
                note=topup_note,
                operator_user_id=int(operator_user_id),
                now_ts=now,
            )
            self._create_user_notification_in_tx(
                self.conn,
                user_id=int(request_row["user_id"]),
                kind="success",
                title="充值积分已到账",
                body=f"管理员已确认你的付款，并入账 {credit_amount} 积分。",
                action_url="/app/billing",
                source_type="billing_request_credited",
                source_id=int(request_id),
                delta=credit_amount,
                created_at=now,
            )
            self.conn.execute(
                """
                UPDATE billing_requests
                SET status = 'credited',
                    payment_amount = ?,
                    admin_note = ?,
                    credited_credit_ledger_id = ?,
                    operator_user_id = ?,
                    reviewed_at = COALESCE(reviewed_at, ?),
                    credited_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(amount_paid or request_row.get("payment_amount") or "").strip(),
                    str(admin_note or "").strip(),
                    int(updated_user.get("credit_ledger_id") or 0) or None,
                    int(operator_user_id),
                    now,
                    now,
                    now,
                    int(request_id),
                ),
            )
        row = self.get_billing_request(int(request_id))
        if not row:
            raise ValueError(f"billing request not found: {request_id}")
        return row

    def mark_billing_request_notified(
        self,
        request_id: int,
        *,
        operator_user_id: int,
        admin_note: str = "",
    ) -> Dict[str, Any]:
        request_row = self.get_billing_request(int(request_id))
        if not request_row:
            raise ValueError(f"billing request not found: {request_id}")
        status = normalize_billing_request_status(request_row.get("status"))
        if status == "notified":
            return request_row
        if status != "credited":
            raise ValueError("billing request must be credited before notify")
        now = int(time.time())
        with self.conn:
            self._create_user_notification_in_tx(
                self.conn,
                user_id=int(request_row["user_id"]),
                kind="info",
                title="充值处理已完成",
                body="运营已完成充值处理，你可以在 Billing 页面查看到账与积分变化。",
                action_url="/app/billing",
                source_type="billing_request_notified",
                source_id=int(request_id),
                created_at=now,
            )
            self.conn.execute(
                """
                UPDATE billing_requests
                SET status = 'notified',
                    admin_note = CASE
                        WHEN ? = '' THEN admin_note
                        WHEN admin_note = '' THEN ?
                        ELSE admin_note || ' / ' || ?
                    END,
                    operator_user_id = ?,
                    notified_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(admin_note or "").strip(),
                    str(admin_note or "").strip(),
                    str(admin_note or "").strip(),
                    int(operator_user_id),
                    now,
                    now,
                    int(request_id),
                ),
            )
        row = self.get_billing_request(int(request_id))
        if not row:
            raise ValueError(f"billing request not found: {request_id}")
        return row

    def adjust_user_credits(
        self,
        user_id: int,
        *,
        delta: int,
        entry_type: str,
        source: str = "",
        project_id: Optional[int] = None,
        payment_amount: str = "",
        payment_proof_ref: str = "",
        note: str = "",
        operator_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        entry_type_value = str(entry_type or "").strip().lower()
        with self.conn:
            row = self._apply_credit_delta_in_tx(
                self.conn,
                user_id=int(user_id),
                delta=int(delta),
                entry_type=entry_type_value,
                source=source,
                project_id=project_id,
                payment_amount=payment_amount,
                payment_proof_ref=payment_proof_ref,
                note=note,
                operator_user_id=operator_user_id,
            )
            project_name = ""
            if project_id is not None:
                project_row = self.get_managed_project(int(project_id))
                project_name = str(project_row.get("name") or "") if project_row else ""
            notification_content = self.build_credit_notification_content(
                entry_type=entry_type_value,
                delta=int(delta),
                project_name=project_name,
                payment_amount=payment_amount,
                note=note,
            )
            self._create_user_notification_in_tx(
                self.conn,
                user_id=int(user_id),
                kind=notification_content["kind"],
                title=notification_content["title"],
                body=notification_content["body"],
                action_url=notification_content["action_url"],
                source_type=f"credit:{entry_type_value}",
                source_id=int(row.get("credit_ledger_id") or 0) or None,
                delta=int(delta),
                project_id=int(project_id) if project_id is not None else None,
            )
        return row

    def unlock_user_project_access(
        self,
        user_id: int,
        project_id: int,
        *,
        unlock_cost: int = DEFAULT_PROJECT_UNLOCK_CREDITS,
    ) -> Dict[str, Any]:
        existing = self.get_user_project_access(int(user_id), int(project_id))
        if existing:
            return existing
        project_row = self.get_managed_project(int(project_id))
        if not project_row:
            raise ValueError(f"managed project not found: {project_id}")
        note = f"unlock project {project_row.get('name') or project_id}"
        now = int(time.time())
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO user_project_access(
                    user_id, project_id, unlock_cost, source,
                    unlocked_at, expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    int(user_id),
                    int(project_id),
                    abs(int(unlock_cost)),
                    "credit_unlock",
                    now,
                    now,
                ),
            )
            if cur.rowcount <= 0:
                row = self.get_user_project_access(int(user_id), int(project_id))
                if not row:
                    raise ValueError("failed to read project access")
                return row
            self._apply_credit_delta_in_tx(
                self.conn,
                user_id=int(user_id),
                delta=-abs(int(unlock_cost)),
                entry_type="project_unlock",
                source="app.project_unlock",
                project_id=int(project_id),
                note=note,
                now_ts=now,
            )
            notification_content = self.build_credit_notification_content(
                entry_type="project_unlock",
                delta=-abs(int(unlock_cost)),
                project_name=str(project_row.get("name") or ""),
                note=note,
            )
            latest_row = self.conn.execute(
                """
                SELECT id
                FROM credit_ledger
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
            self._create_user_notification_in_tx(
                self.conn,
                user_id=int(user_id),
                kind=notification_content["kind"],
                title=notification_content["title"],
                body=notification_content["body"],
                action_url=notification_content["action_url"],
                source_type="credit:project_unlock",
                source_id=int(latest_row["id"]) if latest_row else None,
                delta=-abs(int(unlock_cost)),
                project_id=int(project_id),
                created_at=now,
            )
        row = self.get_user_project_access(int(user_id), int(project_id))
        if not row:
            raise ValueError("failed to create project access")
        return row

    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        user_agent: str,
        ip_addr: str,
        expires_at: int,
    ) -> Dict[str, Any]:
        now = int(time.time())
        cur = self.conn.execute(
            """
            INSERT INTO user_sessions(
                user_id, token_hash, user_agent, ip_addr,
                last_seen_at, expires_at, revoked_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                int(user_id),
                require_nonempty_text(token_hash, "token_hash"),
                str(user_agent or ""),
                str(ip_addr or ""),
                now,
                int(expires_at),
                now,
                now,
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM user_sessions
            WHERE id = ?
            """,
            (int(cur.lastrowid),),
        ).fetchone()
        if not row:
            raise ValueError("failed to create session")
        return dict(row)

    def get_session_with_user(self, token_hash: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT
                user_sessions.id AS session_id,
                user_sessions.user_id AS session_user_id,
                user_sessions.last_seen_at AS session_last_seen_at,
                user_sessions.expires_at AS session_expires_at,
                user_sessions.revoked_at AS session_revoked_at,
                users.*
            FROM user_sessions
            JOIN users ON users.id = user_sessions.user_id
            WHERE user_sessions.token_hash = ?
              AND user_sessions.revoked_at IS NULL
            """,
            (require_nonempty_text(token_hash, "token_hash"),),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def touch_session(self, session_id: int, expires_at: Optional[int] = None) -> None:
        now = int(time.time())
        if expires_at is None:
            self.conn.execute(
                """
                UPDATE user_sessions
                SET last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, int(session_id)),
            )
        else:
            self.conn.execute(
                """
                UPDATE user_sessions
                SET last_seen_at = ?, expires_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, int(expires_at), now, int(session_id)),
            )
        self.conn.commit()

    def revoke_session(self, token_hash: str) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE user_sessions
            SET revoked_at = ?, updated_at = ?
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (now, now, require_nonempty_text(token_hash, "token_hash")),
        )
        self.conn.commit()

    def revoke_user_sessions(self, user_id: int) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE user_sessions
            SET revoked_at = ?, updated_at = ?
            WHERE user_id = ? AND revoked_at IS NULL
            """,
            (now, now, int(user_id)),
        )
        self.conn.commit()

    def list_user_wallet_rows(self, user_id: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, user_id, wallet, name, is_enabled, created_at, updated_at
            FROM user_wallets
            WHERE user_id = ?
            ORDER BY updated_at DESC, wallet ASC
            """,
            (int(user_id),),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["wallet"] = normalize_address(str(item["wallet"]))
            item["is_enabled"] = bool(item.get("is_enabled"))
            out.append(item)
        return out

    def list_user_wallet_addresses(self, user_id: int, only_enabled: bool = True) -> List[str]:
        items = self.list_user_wallet_rows(int(user_id))
        if only_enabled:
            items = [item for item in items if bool(item.get("is_enabled"))]
        return [str(item["wallet"]) for item in items]

    def add_user_wallet(
        self,
        user_id: int,
        wallet: str,
        name: str = "",
        is_enabled: bool = True,
    ) -> Dict[str, Any]:
        now = int(time.time())
        normalized_wallet = normalize_address(wallet)
        self.conn.execute(
            """
            INSERT INTO user_wallets(user_id, wallet, name, is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, wallet) DO UPDATE SET
                name = excluded.name,
                is_enabled = excluded.is_enabled,
                updated_at = excluded.updated_at
            """,
            (
                int(user_id),
                normalized_wallet,
                str(name or "").strip(),
                1 if is_enabled else 0,
                now,
                now,
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT id, user_id, wallet, name, is_enabled, created_at, updated_at
            FROM user_wallets
            WHERE user_id = ? AND wallet = ?
            """,
            (int(user_id), normalized_wallet),
        ).fetchone()
        if not row:
            raise ValueError("failed to persist user wallet")
        item = dict(row)
        item["wallet"] = normalize_address(str(item["wallet"]))
        item["is_enabled"] = bool(item.get("is_enabled"))
        return item

    def update_user_wallet(
        self,
        user_id: int,
        wallet_id: int,
        *,
        name: Optional[str] = None,
        is_enabled: Optional[bool] = None,
    ) -> Dict[str, Any]:
        updates: List[str] = []
        params: List[Any] = []
        if name is not None:
            updates.append("name = ?")
            params.append(str(name).strip())
        if is_enabled is not None:
            updates.append("is_enabled = ?")
            params.append(1 if is_enabled else 0)
        if not updates:
            raise ValueError("no wallet changes provided")
        updates.append("updated_at = ?")
        params.append(int(time.time()))
        params.extend([int(user_id), int(wallet_id)])
        cur = self.conn.execute(
            f"""
            UPDATE user_wallets
            SET {', '.join(updates)}
            WHERE user_id = ? AND id = ?
            """,
            params,
        )
        self.conn.commit()
        if cur.rowcount <= 0:
            raise ValueError(f"user wallet not found: {wallet_id}")
        row = self.conn.execute(
            """
            SELECT id, user_id, wallet, name, is_enabled, created_at, updated_at
            FROM user_wallets
            WHERE user_id = ? AND id = ?
            """,
            (int(user_id), int(wallet_id)),
        ).fetchone()
        if not row:
            raise ValueError(f"user wallet not found: {wallet_id}")
        item = dict(row)
        item["wallet"] = normalize_address(str(item["wallet"]))
        item["is_enabled"] = bool(item.get("is_enabled"))
        return item

    def delete_user_wallet(self, user_id: int, wallet_id: int) -> bool:
        cur = self.conn.execute(
            """
            DELETE FROM user_wallets
            WHERE user_id = ? AND id = ?
            """,
            (int(user_id), int(wallet_id)),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def query_user_wallet_positions(self, user_id: int, project: Optional[str]) -> List[Dict[str, Any]]:
        wallets = self.list_user_wallet_rows(int(user_id))
        enabled_wallets = {
            normalize_address(str(item["wallet"])): str(item.get("name") or "").strip()
            for item in wallets
            if bool(item.get("is_enabled"))
        }
        if not enabled_wallets:
            return []
        placeholders = ",".join("?" for _ in enabled_wallets)
        params: List[Any] = list(enabled_wallets.keys())
        where_clause = f"wallet IN ({placeholders})"
        if project:
            where_clause = f"project = ? AND {where_clause}"
            params.insert(0, str(project).strip())
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM wallet_positions
            WHERE {where_clause}
            ORDER BY updated_at DESC
            """,
            params,
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            wallet = normalize_address(str(item.get("wallet") or ""))
            item["wallet"] = wallet
            item["name"] = enabled_wallets.get(wallet, "")
            items.append(item)
        return items

    def list_managed_projects(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM managed_projects
            ORDER BY start_at DESC, updated_at DESC, name ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_managed_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM managed_projects
            WHERE id = ?
            """,
            (int(project_id),),
        ).fetchone()
        return dict(row) if row else None

    def upsert_managed_project(
        self,
        *,
        project_id: Optional[int],
        name: str,
        signalhub_project_id: Optional[str],
        detail_url: str,
        token_addr: Optional[str],
        internal_pool_addr: Optional[str],
        start_at: int,
        signalhub_end_at: Optional[int],
        manual_end_at: Optional[int],
        resolved_end_at: int,
        is_watched: bool,
        collect_enabled: bool,
        backfill_enabled: bool,
        status: str,
        source: str,
    ) -> Dict[str, Any]:
        project_name = str(name).strip()
        if not project_name:
            raise ValueError("name cannot be empty")
        status_value = str(status).strip().lower() or "draft"
        if status_value not in MANAGED_PROJECT_STATUSES:
            raise ValueError(f"invalid status: {status_value}")
        source_value = str(source).strip().lower() or "manual"
        signalhub_id = str(signalhub_project_id).strip() if signalhub_project_id else None
        now = int(time.time())
        if project_id is None:
            self.conn.execute(
                """
                INSERT INTO managed_projects(
                    name, signalhub_project_id, detail_url, token_addr, internal_pool_addr,
                    start_at, signalhub_end_at, manual_end_at, resolved_end_at,
                    is_watched, collect_enabled, backfill_enabled, status, source,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    signalhub_project_id = excluded.signalhub_project_id,
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
                    project_name,
                    signalhub_id,
                    str(detail_url).strip(),
                    token_addr,
                    internal_pool_addr,
                    int(start_at),
                    signalhub_end_at,
                    manual_end_at,
                    int(resolved_end_at),
                    1 if is_watched else 0,
                    1 if collect_enabled else 0,
                    1 if backfill_enabled else 0,
                    status_value,
                    source_value,
                    now,
                    now,
                ),
            )
            self.conn.commit()
            row = self.conn.execute(
                """
                SELECT *
                FROM managed_projects
                WHERE name = ?
                """,
                (project_name,),
            ).fetchone()
        else:
            cur = self.conn.execute(
                """
                UPDATE managed_projects
                SET name = ?,
                    signalhub_project_id = ?,
                    detail_url = ?,
                    token_addr = ?,
                    internal_pool_addr = ?,
                    start_at = ?,
                    signalhub_end_at = ?,
                    manual_end_at = ?,
                    resolved_end_at = ?,
                    is_watched = ?,
                    collect_enabled = ?,
                    backfill_enabled = ?,
                    status = ?,
                    source = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    project_name,
                    signalhub_id,
                    str(detail_url).strip(),
                    token_addr,
                    internal_pool_addr,
                    int(start_at),
                    signalhub_end_at,
                    manual_end_at,
                    int(resolved_end_at),
                    1 if is_watched else 0,
                    1 if collect_enabled else 0,
                    1 if backfill_enabled else 0,
                    status_value,
                    source_value,
                    now,
                    int(project_id),
                ),
            )
            self.conn.commit()
            if cur.rowcount <= 0:
                raise ValueError(f"managed project not found: {project_id}")
            row = self.conn.execute(
                """
                SELECT *
                FROM managed_projects
                WHERE id = ?
                """,
                (int(project_id),),
            ).fetchone()
        if not row:
            raise ValueError("failed to persist managed project")
        return dict(row)

    def update_managed_project_status(self, project_id: int, status: str) -> Dict[str, Any]:
        status_value = str(status).strip().lower() or "draft"
        if status_value not in MANAGED_PROJECT_STATUSES:
            raise ValueError(f"invalid status: {status_value}")
        now = int(time.time())
        cur = self.conn.execute(
            """
            UPDATE managed_projects
            SET status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status_value, now, int(project_id)),
        )
        self.conn.commit()
        if cur.rowcount <= 0:
            raise ValueError(f"managed project not found: {project_id}")
        row = self.conn.execute(
            """
            SELECT *
            FROM managed_projects
            WHERE id = ?
            """,
            (int(project_id),),
        ).fetchone()
        if not row:
            raise ValueError(f"managed project not found: {project_id}")
        return dict(row)

    def delete_managed_project(self, project_id: int) -> bool:
        cur = self.conn.execute(
            """
            DELETE FROM managed_projects
            WHERE id = ?
            """,
            (int(project_id),),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def _event_tuple(self, event: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            event["project"],
            event["tx_hash"],
            event["block_number"],
            event["block_timestamp"],
            event["internal_pool"],
            event["fee_addr"],
            event["tax_addr"],
            event["buyer"],
            event["token_addr"],
            decimal_to_str(event["token_bought"], 18),
            decimal_to_str(event["fee_v"], 18),
            decimal_to_str(event["tax_v"], 18),
            decimal_to_str(event["spent_v_est"], 18),
            decimal_to_str(event["spent_v_actual"], 18)
            if event.get("spent_v_actual") is not None
            else None,
            decimal_to_str(event["cost_v"], 18),
            decimal_to_str(event["total_supply"], 0),
            decimal_to_str(event.get("virtual_price_usd"), 18)
            if event.get("virtual_price_usd") is not None
            else None,
            decimal_to_str(event["breakeven_fdv_v"], 18),
            decimal_to_str(event.get("breakeven_fdv_usd"), 18)
            if event.get("breakeven_fdv_usd") is not None
            else None,
            1 if event["is_my_wallet"] else 0,
            1 if event["anomaly"] else 0,
            1 if event["is_price_stale"] else 0,
            int(time.time()),
        )

    def save_dead_letter(self, tx_hash: str, reason: str, payload: Optional[Dict[str, Any]]) -> None:
        self.conn.execute(
            """
            INSERT INTO dead_letters(tx_hash, reason, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (tx_hash, reason, json.dumps(payload, ensure_ascii=False) if payload else None, int(time.time())),
        )
        self.conn.commit()

    def get_known_backfill_txs(self, project: str, tx_hashes: List[str]) -> Set[str]:
        project = str(project).strip()
        if not project or not tx_hashes:
            return set()
        unique_hashes = sorted({str(x).lower() for x in tx_hashes if x})
        if not unique_hashes:
            return set()

        found: Set[str] = set()
        chunk_size = 400
        for i in range(0, len(unique_hashes), chunk_size):
            chunk = unique_hashes[i : i + chunk_size]
            placeholders = ",".join("?" for _ in chunk)
            sql = f"""
                SELECT tx_hash
                FROM scanned_backfill_txs
                WHERE project = ? AND tx_hash IN ({placeholders})
                UNION
                SELECT tx_hash
                FROM events
                WHERE project = ? AND tx_hash IN ({placeholders})
            """
            params = [project, *chunk, project, *chunk]
            rows = self.conn.execute(sql, params).fetchall()
            found.update(str(r["tx_hash"]).lower() for r in rows if r["tx_hash"])
        return found

    def mark_backfill_scanned_txs(self, project: str, tx_hashes: List[str]) -> None:
        project = str(project).strip()
        if not project or not tx_hashes:
            return
        now = int(time.time())
        rows = [
            (project, str(x).lower(), now)
            for x in tx_hashes
            if x
        ]
        if not rows:
            return
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO scanned_backfill_txs(project, tx_hash, scanned_at)
            VALUES (?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()

    def flush_events(self, events: List[Dict[str, Any]], max_block: int) -> List[Dict[str, Any]]:
        if not events and max_block <= 0:
            return []

        inserted_events: List[Dict[str, Any]] = []
        wallet_deltas: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        minute_deltas: Dict[Tuple[str, int], Dict[str, Any]] = {}
        minute_buyers: Set[Tuple[str, int, str]] = set()
        leaderboard_deltas: Dict[Tuple[str, str], Dict[str, Any]] = {}
        project_tax_deltas: Dict[str, Decimal] = {}

        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            for e in events:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO events(
                        project, tx_hash, block_number, block_timestamp,
                        internal_pool, fee_addr, tax_addr, buyer, token_addr,
                        token_bought, fee_v, tax_v, spent_v_est, spent_v_actual,
                        cost_v, total_supply, virtual_price_usd, breakeven_fdv_v,
                        breakeven_fdv_usd, is_my_wallet, anomaly, is_price_stale, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._event_tuple(e),
                )
                if cur.rowcount != 1:
                    continue

                inserted_events.append(e)

                mkey = (e["project"], int(e["block_timestamp"] // 60 * 60))
                md = minute_deltas.setdefault(
                    mkey,
                    {
                        "spent": Decimal(0),
                        "fee": Decimal(0),
                        "tax": Decimal(0),
                        "buy_count": 0,
                        "unique_inc": 0,
                    },
                )
                md["spent"] += e["spent_v_est"]
                md["fee"] += e["fee_v"]
                md["tax"] += e["tax_v"]
                md["buy_count"] += 1
                minute_buyers.add((e["project"], mkey[1], e["buyer"]))

                lkey = (e["project"], e["buyer"])
                ld = leaderboard_deltas.setdefault(
                    lkey,
                    {"spent": Decimal(0), "token": Decimal(0), "last_tx_time": 0},
                )
                ld["spent"] += e["spent_v_est"]
                ld["token"] += e["token_bought"]
                ld["last_tx_time"] = max(ld["last_tx_time"], int(e["block_timestamp"]))
                project_tax_deltas[e["project"]] = (
                    project_tax_deltas.get(e["project"], Decimal(0)) + e["tax_v"]
                )

                if e["is_my_wallet"]:
                    wkey = (e["project"], e["buyer"], e["token_addr"])
                    wd = wallet_deltas.setdefault(
                        wkey,
                        {
                            "fee": Decimal(0),
                            "spent": Decimal(0),
                            "token": Decimal(0),
                            "total_supply": e["total_supply"],
                            "virtual_price_usd": e.get("virtual_price_usd"),
                        },
                    )
                    wd["fee"] += e["fee_v"]
                    wd["spent"] += e["spent_v_est"]
                    wd["token"] += e["token_bought"]
                    wd["total_supply"] = e["total_supply"]
                    if e.get("virtual_price_usd") is not None:
                        wd["virtual_price_usd"] = e["virtual_price_usd"]

            for project, minute_key, buyer in minute_buyers:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO minute_buyers(project, minute_key, buyer)
                    VALUES (?, ?, ?)
                    """,
                    (project, minute_key, buyer),
                )
                if cur.rowcount == 1:
                    minute_deltas[(project, minute_key)]["unique_inc"] += 1

            for (project, wallet, token_addr), d in wallet_deltas.items():
                row = cur.execute(
                    """
                    SELECT sum_fee_v, sum_spent_v_est, sum_token_bought, total_supply, virtual_price_usd
                    FROM wallet_positions
                    WHERE project = ? AND wallet = ? AND token_addr = ?
                    """,
                    (project, wallet, token_addr),
                ).fetchone()
                old_fee = Decimal(row["sum_fee_v"]) if row else Decimal(0)
                old_spent = Decimal(row["sum_spent_v_est"]) if row else Decimal(0)
                old_token = Decimal(row["sum_token_bought"]) if row else Decimal(0)
                old_price = Decimal(row["virtual_price_usd"]) if row and row["virtual_price_usd"] else None

                new_fee = old_fee + d["fee"]
                new_spent = old_spent + d["spent"]
                new_token = old_token + d["token"]
                avg_cost = (new_spent / new_token) if new_token > 0 else Decimal(0)
                total_supply = d["total_supply"] if d["total_supply"] else (Decimal(row["total_supply"]) if row else Decimal(0))
                fdv_v = avg_cost * total_supply if total_supply else Decimal(0)
                price = d["virtual_price_usd"] if d["virtual_price_usd"] is not None else old_price
                fdv_usd = (fdv_v * price) if price is not None else None

                cur.execute(
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
                        project,
                        wallet,
                        token_addr,
                        decimal_to_str(new_fee, 18),
                        decimal_to_str(new_spent, 18),
                        decimal_to_str(new_token, 18),
                        decimal_to_str(avg_cost, 18),
                        decimal_to_str(total_supply, 0),
                        decimal_to_str(fdv_v, 18),
                        decimal_to_str(price, 18) if price is not None else None,
                        decimal_to_str(fdv_usd, 18) if fdv_usd is not None else None,
                        int(time.time()),
                    ),
                )

            for (project, minute_key), d in minute_deltas.items():
                row = cur.execute(
                    """
                    SELECT minute_spent_v, minute_fee_v, minute_tax_v, minute_buy_count, minute_unique_buyers
                    FROM minute_agg
                    WHERE project = ? AND minute_key = ?
                    """,
                    (project, minute_key),
                ).fetchone()
                old_spent = Decimal(row["minute_spent_v"]) if row else Decimal(0)
                old_fee = Decimal(row["minute_fee_v"]) if row else Decimal(0)
                old_tax = Decimal(row["minute_tax_v"]) if row else Decimal(0)
                old_count = int(row["minute_buy_count"]) if row else 0
                old_unique = int(row["minute_unique_buyers"]) if row else 0
                cur.execute(
                    """
                    INSERT INTO minute_agg(
                        project, minute_key, minute_spent_v, minute_fee_v, minute_tax_v,
                        minute_buy_count, minute_unique_buyers, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project, minute_key) DO UPDATE SET
                        minute_spent_v = excluded.minute_spent_v,
                        minute_fee_v = excluded.minute_fee_v,
                        minute_tax_v = excluded.minute_tax_v,
                        minute_buy_count = excluded.minute_buy_count,
                        minute_unique_buyers = excluded.minute_unique_buyers,
                        updated_at = excluded.updated_at
                    """,
                    (
                        project,
                        minute_key,
                        decimal_to_str(old_spent + d["spent"], 18),
                        decimal_to_str(old_fee + d["fee"], 18),
                        decimal_to_str(old_tax + d["tax"], 18),
                        old_count + d["buy_count"],
                        old_unique + d["unique_inc"],
                        int(time.time()),
                    ),
                )

            for (project, buyer), d in leaderboard_deltas.items():
                row = cur.execute(
                    """
                    SELECT sum_spent_v_est, sum_token_bought, last_tx_time
                    FROM leaderboard
                    WHERE project = ? AND buyer = ?
                    """,
                    (project, buyer),
                ).fetchone()
                old_spent = Decimal(row["sum_spent_v_est"]) if row else Decimal(0)
                old_token = Decimal(row["sum_token_bought"]) if row else Decimal(0)
                old_last = int(row["last_tx_time"]) if row else 0
                cur.execute(
                    """
                    INSERT INTO leaderboard(
                        project, buyer, sum_spent_v_est, sum_token_bought, last_tx_time, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project, buyer) DO UPDATE SET
                        sum_spent_v_est = excluded.sum_spent_v_est,
                        sum_token_bought = excluded.sum_token_bought,
                        last_tx_time = excluded.last_tx_time,
                        updated_at = excluded.updated_at
                    """,
                    (
                        project,
                        buyer,
                        decimal_to_str(old_spent + d["spent"], 18),
                        decimal_to_str(old_token + d["token"], 18),
                        max(old_last, d["last_tx_time"]),
                        int(time.time()),
                    ),
                )

            for project, tax_delta in project_tax_deltas.items():
                row = cur.execute(
                    """
                    SELECT sum_tax_v
                    FROM project_stats
                    WHERE project = ?
                    """,
                    (project,),
                ).fetchone()
                old_tax = Decimal(row["sum_tax_v"]) if row else Decimal(0)
                cur.execute(
                    """
                    INSERT INTO project_stats(project, sum_tax_v, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(project) DO UPDATE SET
                        sum_tax_v = excluded.sum_tax_v,
                        updated_at = excluded.updated_at
                    """,
                    (
                        project,
                        decimal_to_str(old_tax + tax_delta, 18),
                        int(time.time()),
                    ),
                )

            if max_block > 0:
                old = self.get_state("last_processed_block")
                old_b = int(old) if old else 0
                if max_block > old_b:
                    self.set_state("last_processed_block", str(max_block))

            self.conn.commit()
            return inserted_events
        except Exception:
            self.conn.rollback()
            raise

    def query_wallets(
        self,
        wallet: Optional[str] = None,
        project: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if wallet and project:
            rows = self.conn.execute(
                """
                SELECT * FROM wallet_positions
                WHERE wallet = ? AND project = ?
                ORDER BY updated_at DESC
                """,
                (wallet, project),
            ).fetchall()
        elif wallet:
            rows = self.conn.execute(
                """
                SELECT * FROM wallet_positions
                WHERE wallet = ?
                ORDER BY updated_at DESC
                """,
                (wallet,),
            ).fetchall()
        elif project:
            rows = self.conn.execute(
                """
                SELECT * FROM wallet_positions
                WHERE project = ?
                ORDER BY updated_at DESC
                """,
                (project,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM wallet_positions
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def query_minutes(self, project: str, from_ts: int, to_ts: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM minute_agg
            WHERE project = ? AND minute_key >= ? AND minute_key <= ?
            ORDER BY minute_key ASC
            """,
            (project, from_ts, to_ts),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_leaderboard(self, project: str, top_n: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM leaderboard
            WHERE project = ?
            ORDER BY CAST(sum_token_bought AS REAL) DESC, CAST(sum_spent_v_est AS REAL) DESC
            LIMIT ?
            """,
            (project, top_n),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_event_delays(self, project: str, limit_n: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                project,
                tx_hash,
                MIN(block_timestamp) AS block_timestamp,
                MIN(created_at) AS recorded_at,
                CAST(MIN(created_at) - MIN(block_timestamp) AS INTEGER) AS delay_sec
            FROM events
            WHERE project = ?
            GROUP BY project, tx_hash
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (project, limit_n),
        ).fetchall()
        return [dict(r) for r in rows]

    def query_project_tax(self, project: str) -> Dict[str, Any]:
        project = str(project).strip()
        if not project:
            raise ValueError("project is required")
        row = self.conn.execute(
            """
            SELECT project, sum_tax_v, updated_at
            FROM project_stats
            WHERE project = ?
            """,
            (project,),
        ).fetchone()
        if row:
            return dict(row)

        # Backward compatibility: build initial total from historical minute_agg once.
        rows = self.conn.execute(
            """
            SELECT minute_tax_v
            FROM minute_agg
            WHERE project = ?
            """,
            (project,),
        ).fetchall()
        total_tax = Decimal(0)
        for r in rows:
            if r["minute_tax_v"] is not None:
                total_tax += Decimal(str(r["minute_tax_v"]))
        now_ts = int(time.time())
        total_tax_str = decimal_to_str(total_tax, 18)
        self.conn.execute(
            """
            INSERT INTO project_stats(project, sum_tax_v, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(project) DO UPDATE SET
                sum_tax_v = excluded.sum_tax_v,
                updated_at = excluded.updated_at
            """,
            (project, total_tax_str, now_ts),
        )
        self.conn.commit()
        return {"project": project, "sum_tax_v": total_tax_str, "updated_at": now_ts}

    def rebuild_wallet_position_for_project_wallet(self, project: str, wallet: str) -> Dict[str, Any]:
        project = str(project).strip()
        wallet = normalize_address(wallet)
        if not project:
            raise ValueError("project is required")

        rows = self.conn.execute(
            """
            SELECT
                token_addr,
                fee_v,
                spent_v_est,
                token_bought,
                total_supply,
                virtual_price_usd,
                block_timestamp,
                created_at
            FROM events
            WHERE project = ? AND buyer = ?
            ORDER BY block_timestamp ASC, created_at ASC
            """,
            (project, wallet),
        ).fetchall()

        token_deltas: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            token_addr = normalize_address(str(r["token_addr"]))
            d = token_deltas.setdefault(
                token_addr,
                {
                    "sum_fee_v": Decimal(0),
                    "sum_spent_v_est": Decimal(0),
                    "sum_token_bought": Decimal(0),
                    "total_supply": Decimal(0),
                    "virtual_price_usd": None,
                },
            )
            d["sum_fee_v"] += Decimal(str(r["fee_v"]))
            d["sum_spent_v_est"] += Decimal(str(r["spent_v_est"]))
            d["sum_token_bought"] += Decimal(str(r["token_bought"]))
            d["total_supply"] = Decimal(str(r["total_supply"]))
            if r["virtual_price_usd"] is not None:
                d["virtual_price_usd"] = Decimal(str(r["virtual_price_usd"]))

        now = int(time.time())
        cur = self.conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.execute(
                """
                DELETE FROM wallet_positions
                WHERE project = ? AND wallet = ?
                """,
                (project, wallet),
            )

            inserted = 0
            for token_addr, d in token_deltas.items():
                sum_fee_v = d["sum_fee_v"]
                sum_spent_v_est = d["sum_spent_v_est"]
                sum_token_bought = d["sum_token_bought"]
                total_supply = d["total_supply"]
                virtual_price_usd = d["virtual_price_usd"]
                avg_cost_v = (sum_spent_v_est / sum_token_bought) if sum_token_bought > 0 else Decimal(0)
                breakeven_fdv_v = avg_cost_v * total_supply if total_supply > 0 else Decimal(0)
                breakeven_fdv_usd = (
                    breakeven_fdv_v * virtual_price_usd if virtual_price_usd is not None else None
                )
                cur.execute(
                    """
                    INSERT INTO wallet_positions(
                        project, wallet, token_addr, sum_fee_v, sum_spent_v_est, sum_token_bought,
                        avg_cost_v, total_supply, breakeven_fdv_v, virtual_price_usd, breakeven_fdv_usd, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project,
                        wallet,
                        token_addr,
                        decimal_to_str(sum_fee_v, 18),
                        decimal_to_str(sum_spent_v_est, 18),
                        decimal_to_str(sum_token_bought, 18),
                        decimal_to_str(avg_cost_v, 18),
                        decimal_to_str(total_supply, 0),
                        decimal_to_str(breakeven_fdv_v, 18),
                        decimal_to_str(virtual_price_usd, 18) if virtual_price_usd is not None else None,
                        decimal_to_str(breakeven_fdv_usd, 18) if breakeven_fdv_usd is not None else None,
                        now,
                    ),
                )
                inserted += 1

            self.conn.commit()
            return {
                "project": project,
                "wallet": wallet,
                "eventCount": len(rows),
                "tokenCount": inserted,
            }
        except Exception:
            self.conn.rollback()
            raise

    def count_events(self, project: Optional[str] = None) -> int:
        if project:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM events
                WHERE project = ?
                """,
                (project,),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM events
                """
            ).fetchone()
        return int(row["c"]) if row else 0


class EventBusStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS event_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                tx_hash TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_event_queue_id ON event_queue(id);

            CREATE TABLE IF NOT EXISTS role_heartbeats (
                role TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scan_jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                project TEXT,
                start_ts INTEGER NOT NULL,
                end_ts INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                finished_at INTEGER,
                error TEXT,
                from_block INTEGER,
                to_block INTEGER,
                total_chunks INTEGER,
                processed_chunks INTEGER,
                scanned_tx INTEGER NOT NULL DEFAULT 0,
                skipped_tx INTEGER NOT NULL DEFAULT 0,
                processed_tx INTEGER NOT NULL DEFAULT 0,
                parsed_delta INTEGER NOT NULL DEFAULT 0,
                inserted_delta INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                cancel_requested_at INTEGER,
                current_block INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_scan_jobs_status_created
                ON scan_jobs(status, created_at);
            """
        )
        # Recover unfinished manual scan jobs after restart.
        cur.execute(
            """
            UPDATE scan_jobs
            SET status = 'queued',
                started_at = NULL,
                error = 'requeued after restart'
            WHERE status = 'running'
            """
        )
        self.conn.commit()

    def enqueue_events(self, source: str, events: List[Dict[str, Any]]) -> int:
        if not events:
            return 0
        now = int(time.time())
        rows = []
        for event in events:
            payload = json.dumps(serialize_event_for_bus(event), ensure_ascii=False)
            rows.append(
                (
                    source,
                    str(event.get("tx_hash", "")).lower(),
                    int(event.get("block_number", 0)),
                    payload,
                    now,
                )
            )
        self.conn.executemany(
            """
            INSERT INTO event_queue(source, tx_hash, block_number, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def fetch_events(self, limit_n: int) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, payload, block_number
            FROM event_queue
            ORDER BY id ASC
            LIMIT ?
            """,
            (max(1, int(limit_n)),),
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload"]))
            result.append(
                {
                    "id": int(row["id"]),
                    "block_number": int(row["block_number"]),
                    "event": deserialize_event_from_bus(payload),
                }
            )
        return result

    def ack_events(self, ids: List[int]) -> None:
        if not ids:
            return
        unique_ids = sorted({int(x) for x in ids})
        placeholders = ",".join("?" for _ in unique_ids)
        self.conn.execute(
            f"DELETE FROM event_queue WHERE id IN ({placeholders})",
            unique_ids,
        )
        self.conn.commit()

    def queue_size(self) -> int:
        row = self.conn.execute("SELECT COUNT(1) AS c FROM event_queue").fetchone()
        return int(row["c"]) if row else 0

    def upsert_role_heartbeat(self, role: str, payload: Dict[str, Any]) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO role_heartbeats(role, payload, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(role) DO UPDATE SET
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (role, json.dumps(payload, ensure_ascii=False), now),
        )
        self.conn.commit()

    def get_role_heartbeat(self, role: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT role, payload, updated_at
            FROM role_heartbeats
            WHERE role = ?
            """,
            (role,),
        ).fetchone()
        if not row:
            return None
        payload: Dict[str, Any]
        try:
            payload = json.loads(str(row["payload"]))
        except Exception:
            payload = {}
        return {
            "role": str(row["role"]),
            "payload": payload,
            "updated_at": int(row["updated_at"]),
        }

    def create_scan_job(self, project: Optional[str], start_ts: int, end_ts: int) -> str:
        now = int(time.time())
        job_id = uuid.uuid4().hex[:12]
        self.conn.execute(
            """
            INSERT INTO scan_jobs(
                id, status, project, start_ts, end_ts, created_at,
                cancel_requested, scanned_tx, skipped_tx, processed_tx, parsed_delta, inserted_delta
            ) VALUES (?, 'queued', ?, ?, ?, ?, 0, 0, 0, 0, 0, 0)
            """,
            (job_id, project, int(start_ts), int(end_ts), now),
        )
        self.conn.commit()
        return job_id

    def _scan_job_row_to_api(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "project": row["project"],
            "startTs": int(row["start_ts"]),
            "endTs": int(row["end_ts"]),
            "createdAt": int(row["created_at"]),
            "startedAt": int(row["started_at"]) if row["started_at"] is not None else None,
            "finishedAt": int(row["finished_at"]) if row["finished_at"] is not None else None,
            "error": row["error"],
            "fromBlock": int(row["from_block"]) if row["from_block"] is not None else None,
            "toBlock": int(row["to_block"]) if row["to_block"] is not None else None,
            "totalChunks": int(row["total_chunks"]) if row["total_chunks"] is not None else 0,
            "processedChunks": int(row["processed_chunks"]) if row["processed_chunks"] is not None else 0,
            "scannedTx": int(row["scanned_tx"]),
            "skippedTx": int(row["skipped_tx"]),
            "processedTx": int(row["processed_tx"]),
            "parsedDelta": int(row["parsed_delta"]),
            "insertedDelta": int(row["inserted_delta"]),
            "cancelRequested": bool(row["cancel_requested"]),
            "cancelRequestedAt": int(row["cancel_requested_at"]) if row["cancel_requested_at"] is not None else None,
            "currentBlock": int(row["current_block"]) if row["current_block"] is not None else None,
        }

    def get_scan_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM scan_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return self._scan_job_row_to_api(row)

    def request_scan_job_cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """
            SELECT *
            FROM scan_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            return None
        status = str(row["status"])
        now = int(time.time())
        if status in {"done", "failed", "canceled"}:
            return self._scan_job_row_to_api(row)

        if status == "queued":
            self.conn.execute(
                """
                UPDATE scan_jobs
                SET status = 'canceled',
                    cancel_requested = 1,
                    cancel_requested_at = ?,
                    finished_at = ?,
                    error = 'canceled by user'
                WHERE id = ?
                """,
                (now, now, job_id),
            )
        else:
            self.conn.execute(
                """
                UPDATE scan_jobs
                SET cancel_requested = 1,
                    cancel_requested_at = ?
                WHERE id = ?
                """,
                (now, job_id),
            )
        self.conn.commit()
        return self.get_scan_job(job_id)

    def claim_next_scan_job(self) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            """
            SELECT id
            FROM scan_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            self.conn.rollback()
            return None
        job_id = str(row["id"])
        now = int(time.time())
        cur.execute(
            """
            UPDATE scan_jobs
            SET status = 'running',
                started_at = ?,
                error = NULL
            WHERE id = ? AND status = 'queued'
            """,
            (now, job_id),
        )
        if cur.rowcount != 1:
            self.conn.rollback()
            return None
        row2 = cur.execute(
            """
            SELECT *
            FROM scan_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        self.conn.commit()
        if not row2:
            return None
        return self._scan_job_row_to_api(row2)

    def update_scan_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = []
        vals: List[Any] = []
        for key, value in fields.items():
            cols.append(f"{key} = ?")
            vals.append(value)
        vals.append(job_id)
        sql = f"UPDATE scan_jobs SET {', '.join(cols)} WHERE id = ?"
        self.conn.execute(sql, vals)
        self.conn.commit()

    def is_scan_job_cancel_requested(self, job_id: str) -> bool:
        row = self.conn.execute(
            """
            SELECT cancel_requested
            FROM scan_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            return False
        return bool(row["cancel_requested"])

    def count_scan_jobs(self, only_active: bool = False) -> int:
        if only_active:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM scan_jobs
                WHERE status IN ('queued', 'running')
                """
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM scan_jobs
                """
            ).fetchone()
        return int(row["c"]) if row else 0


class VirtualsBot:
    def __init__(self, cfg: AppConfig, role: str = "all"):
        if role not in {"all", "writer", "realtime", "backfill"}:
            raise ValueError(f"invalid role: {role}")
        self.cfg = cfg
        self.role = role
        self.is_writer_role = role in {"all", "writer"}
        self.is_realtime_role = role in {"all", "realtime"}
        self.is_backfill_role = role in {"all", "backfill"}
        self.emit_events_to_bus = role in {"realtime", "backfill"}
        self.consume_events_from_bus = role == "writer"
        self.enable_api = role in {"all", "writer"}
        self.cors_allow_origins = {
            str(x).strip().rstrip("/") for x in cfg.cors_allow_origins if str(x).strip()
        }
        template = cfg.launch_configs[0]
        self.fixed_fee_addr = template.fee_addr
        self.fixed_tax_addr = template.tax_addr
        self.fixed_token_total_supply = template.token_total_supply
        self.fixed_fee_rate = template.fee_rate
        self.base_dir = Path(__file__).resolve().parent
        self.signalhub_client = (
            SignalHubClient(
                cfg.signalhub_base_url,
                timeout_sec=cfg.signalhub_timeout_sec,
            )
            if cfg.signalhub_base_url
            else None
        )
        self.session_cookie_name = cfg.session_cookie_name
        self.session_ttl_sec = cfg.session_ttl_sec
        self.session_secret = cfg.session_secret
        self.session_cookie_secure = str(cfg.app_public_base_url or "").strip().lower().startswith(
            "https://"
        )
        self.billing_contact_qr_url = cfg.billing_contact_qr_url
        self.billing_contact_hint = cfg.billing_contact_hint
        self.billing_proof_dir = (Path(cfg.sqlite_path).resolve().parent / "uploads" / "billing-proofs")
        self.billing_proof_dir.mkdir(parents=True, exist_ok=True)
        self.storage = Storage(cfg.sqlite_path)
        runtime_db_batch_size = self.storage.get_state("runtime_db_batch_size")
        if runtime_db_batch_size:
            with contextlib.suppress(Exception):
                cfg.db_batch_size = max(1, int(runtime_db_batch_size))
        if cfg.bootstrap_admin_email and cfg.bootstrap_admin_password:
            self.storage.bootstrap_admin(
                nickname=cfg.bootstrap_admin_nickname or "Administrator",
                email=cfg.bootstrap_admin_email,
                password_hash=hash_password(cfg.bootstrap_admin_password),
            )
        self.storage.seed_launch_configs(cfg.launch_configs)
        if not self.storage.get_state("my_wallets_seeded"):
            self.storage.seed_monitored_wallets(cfg.my_wallets)
            self.storage.set_state("my_wallets_seeded", "1")
        self.event_bus = EventBusStorage(cfg.event_bus_sqlite_path)
        self.launch_configs: List[LaunchConfig] = []
        self.my_wallets: Set[str] = set()
        self.reload_launch_configs()
        self.reload_my_wallets()
        if not self.storage.get_state("launch_configs_rev"):
            self.storage.set_state("launch_configs_rev", str(int(time.time())))
        if not self.storage.get_state("my_wallets_rev"):
            self.storage.set_state("my_wallets_rev", str(int(time.time())))
        if self.storage.get_state("runtime_bootstrap_v2") != "1":
            self.storage.set_state("runtime_paused", "1")
            self.storage.set_state("runtime_bootstrap_v2", "1")
        elif self.storage.get_state("runtime_paused") is None:
            self.storage.set_state("runtime_paused", "1")
        self.ws_reconnect_event = asyncio.Event()
        self.rpc_clients_by_url: Dict[str, RPCClient] = {}
        self.http_rpc = self.get_or_create_rpc_client(cfg.http_rpc_url)
        self.backfill_http_rpc = (
            self.get_or_create_rpc_client(cfg.backfill_http_rpc_url)
            if cfg.backfill_http_rpc_url
            else self.http_rpc
        )
        self.backfill_rpc_states: Dict[str, RpcEndpointState] = {}
        self.backfill_http_rpcs: List[RPCClient] = []
        self.configure_backfill_rpc_pool()
        self.backfill_rpc_separate = any(
            client is not self.http_rpc for client in self.backfill_http_rpcs
        )
        self.ws_timeout = aiohttp.ClientTimeout(total=None)
        self.runtime_ui_heartbeat_timeout_sec = 2 * 60 * 60
        self.runtime_manual_paused = True
        self.runtime_ui_last_seen_at = 0
        self.runtime_ui_online = False
        self.runtime_paused = True
        self.runtime_pause_updated_at = int(time.time())
        self._last_runtime_pause_check_ts = 0.0
        self.refresh_runtime_pause_state(force=True)
        self.price_service = PriceService(
            cfg,
            self.http_rpc,
            is_paused=lambda: self.runtime_paused,
        )
        self.queue: asyncio.Queue[Tuple[str, int, Optional[str]]] = asyncio.Queue(maxsize=10000)
        self.pending_txs: Set[str] = set()
        self.stop_event = asyncio.Event()
        self.tasks: List[asyncio.Task] = []
        self.flush_lock = asyncio.Lock()
        self.wallet_recalc_lock = asyncio.Lock()
        self.pending_events: List[Dict[str, Any]] = []
        self.pending_max_block = 0
        self.decimals_cache: Dict[str, int] = {}
        self.block_ts_cache: Dict[int, int] = {}
        self.scan_jobs: Dict[str, Dict[str, Any]] = {}
        self.scan_lock = asyncio.Lock()
        self.stats: Dict[str, Any] = {
            "ws_connected": False,
            "enqueued_txs": 0,
            "processed_txs": 0,
            "parsed_events": 0,
            "inserted_events": 0,
            "rpc_errors": 0,
            "dead_letters": 0,
            "last_ws_block": 0,
            "last_backfill_block": 0,
            "last_flush_at": 0,
            "started_at": int(time.time()),
            "role": role,
        }
        self.last_launch_cfg_rev = self.storage.get_state("launch_configs_rev") or ""
        self.last_my_wallets_rev = self.storage.get_state("my_wallets_rev") or ""

        self.jsonl_file = None
        if self.is_writer_role:
            Path(cfg.jsonl_path).parent.mkdir(parents=True, exist_ok=True)
            self.jsonl_file = open(cfg.jsonl_path, "a", encoding="utf-8")
        self.project_scheduler_interval_sec = PROJECT_SCHEDULER_INTERVAL_SEC
        self.project_prelaunch_lead_sec = PROJECT_PRELAUNCH_LEAD_SEC
        self.stats["scheduler_last_run_at"] = 0
        self.stats["scheduler_active_projects"] = 0
        self.stats["scheduler_transitions"] = 0
        self.stats["scheduler_scan_jobs"] = 0

    def get_or_create_rpc_client(self, url: str) -> RPCClient:
        target = str(url or "").strip()
        if not target:
            raise ValueError("rpc url cannot be empty")
        client = self.rpc_clients_by_url.get(target)
        if client is None:
            client = RPCClient(target, max_retries=self.cfg.max_rpc_retries)
            self.rpc_clients_by_url[target] = client
        return client

    def configure_backfill_rpc_pool(self) -> None:
        ordered_urls: List[Tuple[str, str]] = []
        for idx, url in enumerate(self.cfg.backfill_http_rpc_urls, start=1):
            ordered_urls.append((f"backfill-{idx}", url))
        for idx, url in enumerate(self.cfg.backfill_public_http_rpc_urls, start=1):
            ordered_urls.append((f"public-{idx}", url))
        if not ordered_urls:
            ordered_urls.append(("primary-http", self.cfg.http_rpc_url))

        seen: Set[str] = set()
        self.backfill_http_rpcs = []
        self.backfill_rpc_states = {}
        for label, url in ordered_urls:
            clean = str(url or "").strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            client = self.get_or_create_rpc_client(clean)
            self.backfill_http_rpcs.append(client)
            self.backfill_rpc_states[clean] = RpcEndpointState(
                label=label,
                url=clean,
                client=client,
            )

    def backfill_rpc_ru_cost(self, operation: str) -> int:
        if operation == "logs":
            return 1
        if operation in {"historical_block", "basic"}:
            return 1
        return 1

    def record_backfill_rpc_usage(self, client: RPCClient, *, operation: str) -> None:
        state = self.backfill_rpc_states.get(client.url)
        if not state:
            return
        now = int(time.time())
        state.request_count += 1
        state.estimated_ru += self.backfill_rpc_ru_cost(operation)
        state.last_used_at = now
        if operation == "logs":
            state.logs_request_count += 1
        elif operation == "historical_block":
            state.historical_block_request_count += 1
        else:
            state.basic_request_count += 1

    def backfill_rpc_usage_summary_payload(self) -> Dict[str, Any]:
        total_requests = 0
        total_estimated_ru = 0
        last_used_at = 0
        for state in self.backfill_rpc_states.values():
            total_requests += int(state.request_count)
            total_estimated_ru += int(state.estimated_ru)
            last_used_at = max(last_used_at, int(state.last_used_at or 0))
        return {
            "totalRequestCount": total_requests,
            "totalEstimatedRu": total_estimated_ru,
            "lastUsedAt": last_used_at or None,
            "isEstimated": True,
        }

    def mark_backfill_rpc_failure(
        self,
        client: RPCClient,
        exc: Exception,
        *,
        operation: str,
    ) -> None:
        state = self.backfill_rpc_states.get(client.url)
        if not state:
            return
        now = int(time.time())
        state.last_error = rpc_error_text(exc)
        state.last_checked_at = now
        if operation in {"logs", "probe_logs"} and is_rpc_log_history_unavailable_error(exc):
            state.supports_logs = False
        if operation in {"historical_block", "probe_historical_blocks"} and (
            is_rpc_log_history_unavailable_error(exc) or "eth_getblockbynumber" in state.last_error
        ):
            state.supports_historical_blocks = False
        if is_rpc_ru_exceeded_error(exc):
            state.cooldown_until = max(
                state.cooldown_until,
                now + int(self.cfg.backfill_rpc_quota_cooldown_sec),
            )
        elif is_rpc_transient_error(exc):
            state.cooldown_until = max(
                state.cooldown_until,
                now + int(self.cfg.backfill_rpc_transient_cooldown_sec),
            )

    async def probe_backfill_rpc(self, client: RPCClient, force: bool = False) -> RpcEndpointState:
        state = self.backfill_rpc_states[client.url]
        now = int(time.time())
        if (
            (not force)
            and state.last_checked_at > 0
            and (now - state.last_checked_at) < 300
            and state.supports_basic_rpc is not None
        ):
            return state

        state.last_checked_at = now
        state.last_error = ""
        try:
            self.record_backfill_rpc_usage(client, operation="basic")
            latest = await client.get_latest_block_number()
            state.supports_basic_rpc = True
        except Exception as exc:
            state.supports_basic_rpc = False
            self.mark_backfill_rpc_failure(client, exc, operation="probe_basic")
            return state

        try:
            self.record_backfill_rpc_usage(client, operation="historical_block")
            await client.get_block_by_number(max(0, latest - 1))
            state.supports_historical_blocks = True
        except Exception as exc:
            state.supports_historical_blocks = False
            self.mark_backfill_rpc_failure(client, exc, operation="probe_historical_blocks")

        try:
            self.record_backfill_rpc_usage(client, operation="logs")
            await client.get_logs(
                from_block=max(0, latest - 1),
                to_block=latest,
                address=self.cfg.virtual_token_addr,
                topics=[TRANSFER_TOPIC0],
            )
            state.supports_logs = True
        except Exception as exc:
            state.supports_logs = False
            self.mark_backfill_rpc_failure(client, exc, operation="probe_logs")
        return state

    async def ordered_backfill_rpc_candidates(
        self,
        *,
        require_logs: bool,
        preferred: Optional[RPCClient] = None,
        exclude_urls: Optional[Set[str]] = None,
    ) -> List[RPCClient]:
        ordered: List[RPCClient] = []
        seen: Set[str] = set()
        if preferred is not None:
            ordered.append(preferred)
            seen.add(preferred.url)
        for client in self.backfill_http_rpcs:
            if client.url in seen:
                continue
            ordered.append(client)
            seen.add(client.url)

        candidates: List[RPCClient] = []
        now = int(time.time())
        excluded = exclude_urls or set()
        for client in ordered:
            if client.url in excluded:
                continue
            state = await self.probe_backfill_rpc(client)
            if state.cooldown_until > now:
                continue
            if state.supports_basic_rpc is False:
                continue
            if state.supports_historical_blocks is False:
                continue
            if require_logs and state.supports_logs is False:
                continue
            candidates.append(client)
        return candidates

    async def resolve_backfill_scan_rpc(
        self,
        *,
        require_logs: bool = False,
        preferred: Optional[RPCClient] = None,
        exclude_urls: Optional[Set[str]] = None,
    ) -> RPCClient:
        candidates = await self.ordered_backfill_rpc_candidates(
            require_logs=require_logs,
            preferred=preferred,
            exclude_urls=exclude_urls,
        )
        if candidates:
            return candidates[0]
        need = "historical blocks + logs" if require_logs else "historical blocks"
        raise RuntimeError(f"no available backfill RPC endpoints for {need}")

    async def resolve_backfill_block_range(
        self,
        start_ts: int,
        end_ts: int,
        *,
        preferred: Optional[RPCClient] = None,
    ) -> Tuple[RPCClient, int, int]:
        last_exc: Optional[Exception] = None
        for client in await self.ordered_backfill_rpc_candidates(
            require_logs=False,
            preferred=preferred,
        ):
            try:
                from_block = await self.find_block_gte_timestamp(start_ts, rpc=client)
                to_block = await self.find_block_lte_timestamp(end_ts, rpc=client)
                if to_block < from_block:
                    raise ValueError("invalid block range for time range")
                return client, from_block, to_block
            except Exception as exc:
                self.mark_backfill_rpc_failure(client, exc, operation="historical_block")
                last_exc = exc
                if not (
                    is_rpc_ru_exceeded_error(exc)
                    or is_rpc_log_history_unavailable_error(exc)
                    or is_rpc_transient_error(exc)
                ):
                    raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("no available backfill RPC endpoints for block range resolution")

    def backfill_rpc_pool_payload(self) -> List[Dict[str, Any]]:
        now = int(time.time())
        payload: List[Dict[str, Any]] = []
        for client in self.backfill_http_rpcs:
            state = self.backfill_rpc_states.get(client.url)
            if not state:
                continue
            payload.append(
                {
                    "label": state.label,
                    "url": state.url,
                    "supportsBasicRpc": state.supports_basic_rpc,
                    "supportsHistoricalBlocks": state.supports_historical_blocks,
                    "supportsLogs": state.supports_logs,
                    "cooldownUntil": state.cooldown_until or None,
                    "isCoolingDown": state.cooldown_until > now,
                    "lastError": state.last_error or None,
                    "lastCheckedAt": state.last_checked_at or None,
                    "requestCount": state.request_count,
                    "estimatedRu": state.estimated_ru,
                    "lastUsedAt": state.last_used_at or None,
                    "basicRequestCount": state.basic_request_count,
                    "historicalBlockRequestCount": state.historical_block_request_count,
                    "logsRequestCount": state.logs_request_count,
                }
            )
        return payload

    def reload_launch_configs(self) -> None:
        launch_configs = self.storage.get_enabled_launch_configs()
        self.launch_configs = launch_configs

    def get_launch_configs(self) -> List[LaunchConfig]:
        return list(self.launch_configs)

    def reload_my_wallets(self) -> None:
        self.my_wallets = set(self.storage.list_monitored_wallets())

    def get_my_wallets(self) -> Set[str]:
        return set(self.my_wallets)

    def session_expires_at(self) -> int:
        return int(time.time()) + int(self.session_ttl_sec)

    def auth_public_user(self, user_row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not user_row:
            return None
        return {
            "id": int(user_row["id"]),
            "nickname": str(user_row.get("nickname") or ""),
            "email": str(user_row.get("email") or ""),
            "role": str(user_row.get("role") or "user"),
            "status": str(user_row.get("status") or "active"),
        }

    def user_home_path(self, user_row: Dict[str, Any]) -> str:
        return "/admin" if str(user_row.get("role") or "").lower() == "admin" else "/app"

    def build_billing_plans_payload(self) -> List[Dict[str, Any]]:
        return [dict(plan) for plan in BILLING_PLANS]

    def billing_request_status_label(self, status: str) -> str:
        status_value = normalize_billing_request_status(status)
        if status_value == "pending_review":
            return "待确认付款"
        if status_value == "credited":
            return "已入账"
        if status_value == "notified":
            return "已通知用户"
        return status_value

    def resolve_billing_proof_path(self, storage_key: str) -> Path:
        candidate = (self.billing_proof_dir / str(storage_key or "").strip()).resolve()
        base = self.billing_proof_dir.resolve()
        if candidate != base and base not in candidate.parents:
            raise ValueError("invalid proof path")
        return candidate

    def store_billing_proof_attachment(
        self,
        *,
        filename: str,
        content_type: str,
        payload: bytes,
    ) -> Dict[str, Any]:
        original_name = Path(str(filename or "").strip()).name or "billing-proof"
        suffix = Path(original_name).suffix.lower()
        guessed_suffix = (mimetypes.guess_extension(str(content_type or "").strip()) or "").lower()
        if suffix not in ALLOWED_BILLING_PROOF_EXTENSIONS:
            suffix = guessed_suffix
        if suffix not in ALLOWED_BILLING_PROOF_EXTENSIONS:
            raise ValueError("proof file must be png/jpg/jpeg/webp/gif")
        if len(payload) <= 0:
            raise ValueError("proof file is empty")
        if len(payload) > MAX_BILLING_PROOF_BYTES:
            raise ValueError("proof file exceeds 8MB limit")
        storage_key = f"{int(time.time())}-{uuid.uuid4().hex}{suffix}"
        target = self.resolve_billing_proof_path(storage_key)
        target.write_bytes(payload)
        return {
            "storage_key": storage_key,
            "original_name": original_name,
            "content_type": str(content_type or "").strip()
            or mimetypes.guess_type(target.name)[0]
            or "application/octet-stream",
            "size": len(payload),
        }

    def build_notification_item_payload(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": int(row.get("id") or 0),
            "title": str(row.get("title") or ""),
            "body": str(row.get("body") or ""),
            "kind": normalize_notification_kind(row.get("kind")),
            "delta": int(row.get("delta") or 0),
            "type": str(row.get("source_type") or ""),
            "projectName": str(row.get("project_name") or "").strip() or None,
            "createdAt": int(row.get("created_at") or 0),
            "isRead": bool(row.get("is_read")),
            "readAt": int(row.get("read_at") or 0) or None,
            "actionUrl": str(row.get("action_url") or "").strip() or None,
            "sourceId": int(row.get("source_id") or 0) or None,
        }

    def is_visible_app_notification_type(self, source_type: Any) -> bool:
        value = str(source_type or "").strip().lower()
        if not value:
            return False
        return value.startswith("credit:") or value == "billing_request_credited"

    def list_visible_user_notification_rows(
        self,
        user_id: int,
        *,
        limit: int = 12,
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        rows = self.storage.list_user_notifications_rows(int(user_id), limit=max(120, int(limit) * 6))
        visible = [
            row
            for row in rows
            if self.is_visible_app_notification_type(row.get("source_type"))
            and ((not unread_only) or (not bool(row.get("is_read"))))
        ]
        return visible[: max(1, int(limit))]

    def count_visible_user_notifications(self, user_id: int, *, unread_only: bool = False) -> int:
        rows = self.storage.list_user_notifications_rows(int(user_id), limit=500)
        return sum(
            1
            for row in rows
            if self.is_visible_app_notification_type(row.get("source_type"))
            and ((not unread_only) or (not bool(row.get("is_read"))))
        )

    def build_billing_request_payload(self, row: Dict[str, Any], viewer: str) -> Dict[str, Any]:
        request_id = int(row.get("id") or 0)
        is_admin = str(viewer or "").lower() == "admin"
        proof_url = None
        if str(row.get("proof_storage_key") or "").strip():
            proof_url = (
                f"/api/admin/billing/requests/{request_id}/proof"
                if is_admin
                else f"/api/app/billing/requests/{request_id}/proof"
            )
        payload = {
            "id": request_id,
            "user_id": int(row.get("user_id") or 0),
            "userNickname": str(row.get("user_nickname") or "").strip() or None,
            "userEmail": str(row.get("user_email") or "").strip() or None,
            "plan_id": str(row.get("plan_id") or "").strip(),
            "requested_credits": int(row.get("requested_credits") or 0),
            "payment_amount": str(row.get("payment_amount") or "").strip(),
            "note": str(row.get("note") or "").strip(),
            "proof_original_name": str(row.get("proof_original_name") or "").strip(),
            "proof_content_type": str(row.get("proof_content_type") or "").strip(),
            "proof_size": int(row.get("proof_size") or 0),
            "proof_url": proof_url,
            "status": normalize_billing_request_status(row.get("status")),
            "status_label": self.billing_request_status_label(str(row.get("status") or "")),
            "admin_note": str(row.get("admin_note") or "").strip(),
            "credited_credit_ledger_id": int(row.get("credited_credit_ledger_id") or 0) or None,
            "operator_user_id": int(row.get("operator_user_id") or 0) or None,
            "operatorNickname": str(row.get("operator_nickname") or "").strip() or None,
            "operatorEmail": str(row.get("operator_email") or "").strip() or None,
            "created_at": int(row.get("created_at") or 0),
            "updated_at": int(row.get("updated_at") or 0),
            "reviewed_at": int(row.get("reviewed_at") or 0) or None,
            "credited_at": int(row.get("credited_at") or 0) or None,
            "notified_at": int(row.get("notified_at") or 0) or None,
        }
        if not is_admin:
            payload.pop("user_id", None)
            payload.pop("userNickname", None)
            payload.pop("userEmail", None)
            payload.pop("operator_user_id", None)
            payload.pop("operatorNickname", None)
            payload.pop("operatorEmail", None)
        return payload

    def build_project_access_payload(
        self,
        user_row: Optional[Dict[str, Any]],
        project_row: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        project_id = int(project_row.get("id") or 0) if project_row else 0
        unlock_cost = DEFAULT_PROJECT_UNLOCK_CREDITS
        if not user_row or str(user_row.get("role") or "").lower() == "admin":
            return {
                "projectId": project_id,
                "isUnlocked": True,
                "unlockCost": unlock_cost,
                "canUnlockNow": True,
                "creditBalance": int(user_row.get("credit_balance") or 0) if user_row else 0,
                "unlockedAt": None,
            }
        access_row = self.storage.get_user_project_access(int(user_row["id"]), project_id) if project_id > 0 else None
        credit_balance = int(user_row.get("credit_balance") or 0)
        return {
            "projectId": project_id,
            "isUnlocked": bool(access_row),
            "unlockCost": unlock_cost,
            "canUnlockNow": project_id > 0 and (bool(access_row) or credit_balance >= unlock_cost),
            "creditBalance": credit_balance,
            "unlockedAt": int(access_row.get("unlocked_at") or 0) if access_row else None,
        }

    def build_billing_summary_payload(self, user_row: Dict[str, Any]) -> Dict[str, Any]:
        user_id = int(user_row["id"])
        return {
            "ok": True,
            "credit_balance": int(user_row.get("credit_balance") or 0),
            "credit_spent_total": int(user_row.get("credit_spent_total") or 0),
            "credit_granted_total": int(user_row.get("credit_granted_total") or 0),
            "unlocked_project_count": len(self.storage.list_user_project_access_rows(user_id, limit=1000)),
            "pending_request_count": 0,
            "unread_notification_count": self.count_visible_user_notifications(user_id, unread_only=True),
            "plans": self.build_billing_plans_payload(),
            "contact_qr_url": self.billing_contact_qr_url,
            "contact_hint": self.billing_contact_hint,
            "notice": DEFAULT_BILLING_REFERRAL_NOTICE,
            "referral_url": DEFAULT_BILLING_REFERRAL_URL,
        }

    def build_user_notifications_payload(
        self,
        user_row: Dict[str, Any],
        limit: int = 12,
    ) -> Dict[str, Any]:
        user_id = int(user_row["id"])
        rows = self.list_visible_user_notification_rows(user_id, limit=max(1, int(limit)))
        items = [self.build_notification_item_payload(row) for row in rows]
        return {
            "ok": True,
            "count": len(items),
            "unreadCount": self.count_visible_user_notifications(user_id, unread_only=True),
            "items": items,
        }

    def build_legacy_api_payload(self) -> Dict[str, Any]:
        items = []
        for spec in LEGACY_API_SPECS:
            items.append(
                {
                    "path": spec["path"],
                    "replacement": spec["replacement"],
                    "access": spec["access"],
                    "state": spec["state"],
                }
            )
        return {
            "ok": True,
            "count": len(items),
            "items": items,
        }

    def apply_legacy_response_headers(
        self,
        response: web.StreamResponse,
        *,
        replacement: str,
        access: str,
    ) -> web.StreamResponse:
        response.headers["X-VWR-Legacy-Api"] = "true"
        response.headers["X-VWR-Legacy-State"] = "compatible"
        response.headers["X-VWR-Replacement"] = replacement
        response.headers["Deprecation"] = "true"
        response.headers["Warning"] = '299 - "Deprecated legacy API; use replacement endpoint"'
        response.headers["X-VWR-Legacy-Access"] = access
        return response

    def get_request_user(self, request: web.Request) -> Optional[Dict[str, Any]]:
        raw = request.get("auth_user")
        return raw if isinstance(raw, dict) else None

    def require_auth(self, request: web.Request) -> Dict[str, Any]:
        user = self.get_request_user(request)
        if not user:
            raise web.HTTPUnauthorized(text=json.dumps({"error": "authentication required"}), content_type="application/json")
        if str(user.get("status") or "").lower() != "active":
            raise web.HTTPForbidden(text=json.dumps({"error": "user is disabled"}), content_type="application/json")
        return user

    def require_admin(self, request: web.Request) -> Dict[str, Any]:
        user = self.require_auth(request)
        if str(user.get("role") or "").lower() != "admin":
            raise web.HTTPForbidden(text=json.dumps({"error": "admin required"}), content_type="application/json")
        return user

    def parse_user_ids_payload(self, payload: Any) -> List[int]:
        if not isinstance(payload, dict):
            raise ValueError("invalid json body")
        raw_ids = payload.get("user_ids")
        if not isinstance(raw_ids, list):
            raise ValueError("user_ids must be array")
        user_ids: List[int] = []
        for raw in raw_ids:
            try:
                parsed = int(raw)
            except Exception as exc:
                raise ValueError("user_ids must contain integers") from exc
            if parsed > 0:
                user_ids.append(parsed)
        unique_ids = sorted(set(user_ids))
        if not unique_ids:
            raise ValueError("user_ids must not be empty")
        return unique_ids

    def ensure_admin_user_ids_mutable(
        self,
        *,
        operator_user_id: int,
        user_ids: List[int],
        allow_admin_targets: bool = False,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for user_id in user_ids:
            row = self.storage.get_user_by_id(int(user_id))
            if not row:
                raise ValueError(f"user not found: {user_id}")
            if int(row["id"]) == int(operator_user_id):
                raise ValueError("cannot modify current admin account")
            if (not allow_admin_targets) and str(row.get("role") or "").lower() == "admin":
                raise ValueError("admin accounts cannot be modified in batch")
            rows.append(row)
        return rows

    def build_auth_session(self, user_row: Dict[str, Any], request: web.Request) -> Tuple[str, Dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        session = self.storage.create_session(
            user_id=int(user_row["id"]),
            token_hash=hash_session_token(token, self.session_secret),
            user_agent=str(request.headers.get("User-Agent") or ""),
            ip_addr=str(request.remote or ""),
            expires_at=self.session_expires_at(),
        )
        self.storage.update_user_last_login(int(user_row["id"]))
        return token, session

    def apply_session_cookie(self, response: web.StreamResponse, token: str) -> None:
        response.set_cookie(
            self.session_cookie_name,
            token,
            max_age=int(self.session_ttl_sec),
            httponly=True,
            samesite="Lax",
            secure=self.session_cookie_secure,
            path="/",
        )

    def clear_session_cookie(self, response: web.StreamResponse) -> None:
        response.del_cookie(
            self.session_cookie_name,
            path="/",
            httponly=True,
            samesite="Lax",
            secure=self.session_cookie_secure,
        )

    def public_app_base_url(self, request: web.Request) -> str:
        configured = str(self.cfg.app_public_base_url or "").strip().rstrip("/")
        if configured:
            return configured
        return f"{request.scheme}://{request.host}".rstrip("/")

    def email_verification_expires_at(self) -> int:
        return int(time.time()) + int(self.cfg.email_verify_token_ttl_sec)

    def request_device_fingerprint(self, request: web.Request, payload: Dict[str, Any]) -> str:
        body_value = str(payload.get("device_fingerprint") or "").strip()
        header_value = str(request.headers.get("X-Device-Fingerprint") or "").strip()
        return body_value or header_value

    def request_client_ip(self, request: web.Request) -> str:
        forwarded_for = str(request.headers.get("X-Forwarded-For") or "").strip()
        if forwarded_for:
            first = forwarded_for.split(",", 1)[0].strip()
            if first and first.lower() != "unknown":
                return first
        real_ip = str(request.headers.get("X-Real-IP") or "").strip()
        if real_ip and real_ip.lower() != "unknown":
            return real_ip
        return str(request.remote or "").strip()

    def maybe_prune_auth_attempts(self) -> None:
        cutoff = int(time.time()) - max(AUTH_REGISTER_IP_LONG_WINDOW_SEC, 7 * 24 * 60 * 60)
        with contextlib.suppress(Exception):
            self.storage.prune_auth_attempts(cutoff)

    def enforce_rate_limit(
        self,
        *,
        event_type: str,
        subject: str,
        window_sec: int,
        max_attempts: int,
        message: str,
        code: str,
    ) -> None:
        subject_value = str(subject or "").strip()
        if not subject_value:
            return
        since_ts = int(time.time()) - int(window_sec)
        count = self.storage.count_auth_attempts(event_type, subject_value, since_ts)
        if count >= int(max_attempts):
            raise RateLimitExceeded(message, code=code, retry_after_sec=int(window_sec))

    def record_auth_attempt(self, event_type: str, subject: str) -> None:
        subject_value = str(subject or "").strip()
        if not subject_value:
            return
        self.storage.record_auth_attempt(event_type, subject_value)
        self.maybe_prune_auth_attempts()

    def ensure_register_ip_allowed(self, client_ip: str) -> None:
        self.enforce_rate_limit(
            event_type="register_ip",
            subject=client_ip,
            window_sec=AUTH_REGISTER_IP_SHORT_WINDOW_SEC,
            max_attempts=AUTH_REGISTER_IP_SHORT_MAX_ATTEMPTS,
            message="注册过于频繁，请 15 分钟后再试。",
            code="register_rate_limited",
        )
        self.enforce_rate_limit(
            event_type="register_ip",
            subject=client_ip,
            window_sec=AUTH_REGISTER_IP_LONG_WINDOW_SEC,
            max_attempts=AUTH_REGISTER_IP_LONG_MAX_ATTEMPTS,
            message="今天的注册次数已到上限，请明天再试。",
            code="register_daily_limited",
        )

    def ensure_resend_ip_allowed(self, client_ip: str) -> None:
        self.enforce_rate_limit(
            event_type="resend_ip",
            subject=client_ip,
            window_sec=AUTH_RESEND_IP_WINDOW_SEC,
            max_attempts=AUTH_RESEND_IP_MAX_ATTEMPTS,
            message="验证邮件发送过于频繁，请稍后再试。",
            code="resend_rate_limited",
        )

    def ensure_login_fail_ip_allowed(self, client_ip: str) -> None:
        self.enforce_rate_limit(
            event_type="login_fail_ip",
            subject=client_ip,
            window_sec=AUTH_LOGIN_FAIL_IP_WINDOW_SEC,
            max_attempts=AUTH_LOGIN_FAIL_IP_MAX_ATTEMPTS,
            message="登录尝试过于频繁，请 15 分钟后再试。",
            code="login_rate_limited",
        )

    def ensure_allowed_registration_email(self, email: str) -> None:
        domain = extract_email_domain(email)
        if domain in DISPOSABLE_EMAIL_DOMAINS:
            raise DisposableEmailBlocked()

    def ensure_email_delivery_enabled(self) -> None:
        if not self.cfg.email_enabled:
            raise ValueError("email verification is unavailable")
        if not str(self.cfg.email_smtp_host or "").strip():
            raise ValueError("EMAIL_SMTP_HOST is required")
        if not str(self.cfg.email_from_address or "").strip():
            raise ValueError("EMAIL_FROM_ADDRESS is required")

    def build_email_verification_link(self, request: web.Request, token: str) -> str:
        base_url = self.public_app_base_url(request)
        return f"{base_url}/auth/verify-email?token={urllib.parse.quote(token)}"

    def send_email_message(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
    ) -> None:
        self.ensure_email_delivery_enabled()
        message = EmailMessage()
        from_address = str(self.cfg.email_from_address or "").strip()
        from_name = str(self.cfg.email_from_name or "").strip() or DEFAULT_EMAIL_FROM_NAME
        message["From"] = formataddr((from_name, from_address))
        message["To"] = normalize_email(to_email)
        message["Subject"] = require_nonempty_text(subject, "subject")
        message.set_content(require_nonempty_text(text_body, "text_body"))

        smtp_host = str(self.cfg.email_smtp_host or "").strip()
        smtp_port = int(self.cfg.email_smtp_port)
        smtp_username = str(self.cfg.email_smtp_username or "").strip()
        smtp_password = str(self.cfg.email_smtp_password or "")
        use_tls = bool(self.cfg.email_smtp_use_tls)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as client:
            client.ehlo()
            if use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if smtp_username or smtp_password:
                client.login(smtp_username, smtp_password)
            client.send_message(message)

    def send_email_verification_email(
        self,
        *,
        request: web.Request,
        email: str,
        nickname: str,
        token: str,
    ) -> None:
        verify_link = self.build_email_verification_link(request, token)
        display_name = str(nickname or "").strip() or "朋友"
        subject = "请验证你的 Virtuals Whale Radar 邮箱"
        body = (
            f"{display_name}，你好：\n\n"
            "感谢注册 Virtuals Whale Radar。\n"
            "请点击下面的链接完成邮箱验证。验证成功后，账号才会正式创建，20 积分也会到账。\n\n"
            f"{verify_link}\n\n"
            f"链接将在 {max(1, int(self.cfg.email_verify_token_ttl_sec) // 60)} 分钟后失效。\n"
            "如果这不是你的操作，可以直接忽略这封邮件。\n"
        )
        self.send_email_message(
            to_email=email,
            subject=subject,
            text_body=body,
        )

    def build_auth_success_response(
        self, user: Dict[str, Any], request: web.Request
    ) -> web.Response:
        token, _session = self.build_auth_session(user, request)
        response = web.json_response(
            {
                "ok": True,
                "user": self.auth_public_user(user),
                "home_path": self.user_home_path(user),
            }
        )
        self.apply_session_cookie(response, token)
        return response

    def build_launch_config_from_managed_project(
        self, project_row: Optional[Dict[str, Any]]
    ) -> Optional[LaunchConfig]:
        if not project_row:
            return None
        name = str(project_row.get("name") or "").strip()
        internal_pool_addr = str(project_row.get("internal_pool_addr") or "").strip()
        if not name or not internal_pool_addr:
            return None
        return LaunchConfig(
            name=name,
            internal_pool_addr=internal_pool_addr,
            fee_addr=self.fixed_fee_addr,
            tax_addr=self.fixed_tax_addr,
            token_addr=normalize_optional_address(project_row.get("token_addr")),
            token_total_supply=self.fixed_token_total_supply,
            fee_rate=self.fixed_fee_rate,
        )

    def sync_launch_config_for_managed_project(self, project_row: Dict[str, Any]) -> None:
        name = str(project_row.get("name") or "").strip()
        if not name:
            return
        internal_pool_addr = project_row.get("internal_pool_addr")
        is_watched = bool(project_row.get("is_watched"))
        collect_enabled = bool(project_row.get("collect_enabled"))
        status = str(project_row.get("status") or "").strip().lower()

        if (
            internal_pool_addr
            and is_watched
            and collect_enabled
            and status in {"prelaunch", "live"}
        ):
            self.storage.upsert_launch_config(
                name=name,
                internal_pool_addr=str(internal_pool_addr),
                fee_addr=self.fixed_fee_addr,
                tax_addr=self.fixed_tax_addr,
                token_addr=normalize_optional_address(project_row.get("token_addr")),
                token_total_supply=self.fixed_token_total_supply,
                fee_rate=self.fixed_fee_rate,
                is_enabled=collect_enabled,
            )
        else:
            self.storage.delete_launch_config(name)

    def sync_runtime_after_managed_project_change(self) -> None:
        self.reload_launch_configs()
        self.bump_launch_config_revision()
        if self.is_realtime_role:
            self.ws_reconnect_event.set()

    def managed_project_is_complete(self, project_row: Dict[str, Any]) -> bool:
        start_at = int(project_row.get("start_at") or 0)
        resolved_end_at = int(project_row.get("resolved_end_at") or 0)
        return bool(
            str(project_row.get("name") or "").strip()
            and start_at > 0
            and resolved_end_at >= start_at
            and project_row.get("token_addr")
            and project_row.get("internal_pool_addr")
        )

    def derive_managed_project_status(
        self, project_row: Dict[str, Any], now_ts: Optional[int] = None
    ) -> str:
        now = int(now_ts or time.time())
        current_status = str(project_row.get("status") or "").strip().lower()
        if current_status == "removed" or not bool(project_row.get("is_watched")):
            return "removed"
        if not self.managed_project_is_complete(project_row):
            return "draft"
        start_at = int(project_row.get("start_at") or 0)
        resolved_end_at = max(start_at, int(project_row.get("resolved_end_at") or start_at))
        if now >= resolved_end_at:
            return "ended"
        if now >= start_at:
            return "live"
        if now >= max(0, start_at - self.project_prelaunch_lead_sec):
            return "prelaunch"
        return "scheduled"

    def _managed_project_scan_state_key(self, project_row: Dict[str, Any]) -> str:
        return (
            "managed_project_scan_job:"
            f"{int(project_row.get('id') or 0)}:"
            f"{int(project_row.get('start_at') or 0)}:"
            f"{int(project_row.get('resolved_end_at') or 0)}"
        )

    def _managed_project_chart_from_key(self, project_id: int) -> str:
        return f"managed_project_chart_from:{int(project_id)}"

    def _managed_project_chart_to_key(self, project_id: int) -> str:
        return f"managed_project_chart_to:{int(project_id)}"

    def _managed_project_last_scan_job_key(self, project_id: int) -> str:
        return f"managed_project_last_scan_job:{int(project_id)}"

    def _managed_project_last_scan_at_key(self, project_id: int) -> str:
        return f"managed_project_last_scan_at:{int(project_id)}"

    def _managed_project_scan_cursor_key(self, project_id: int) -> str:
        return f"managed_project_scan_cursor:{int(project_id)}"

    def _managed_project_scan_signature_key(self, project_id: int) -> str:
        return f"managed_project_scan_signature:{int(project_id)}"

    def _ensure_managed_project_scan_state(self, project_row: Dict[str, Any]) -> None:
        project_id = int(project_row.get("id") or 0)
        if project_id <= 0:
            return
        start_at = int(project_row.get("start_at") or 0)
        resolved_end_at = int(project_row.get("resolved_end_at") or 0)
        signature = f"{start_at}:{resolved_end_at}"
        sig_key = self._managed_project_scan_signature_key(project_id)
        if (self.storage.get_state(sig_key) or "") == signature:
            return
        self.storage.set_state(sig_key, signature)
        self.storage.set_state(self._managed_project_scan_cursor_key(project_id), str(start_at))
        self.storage.set_state(self._managed_project_last_scan_job_key(project_id), "")
        self.storage.set_state(self._managed_project_last_scan_at_key(project_id), "")

    def _get_managed_project_scan_cursor(self, project_row: Dict[str, Any]) -> int:
        project_id = int(project_row.get("id") or 0)
        start_at = int(project_row.get("start_at") or 0)
        if project_id <= 0:
            return start_at
        raw = self.storage.get_state(self._managed_project_scan_cursor_key(project_id))
        try:
            cursor = int(raw) if raw not in {None, ""} else start_at
        except Exception:
            cursor = start_at
        return max(start_at, cursor)

    def _set_managed_project_scan_cursor(self, project_row: Dict[str, Any], cursor_ts: int) -> None:
        project_id = int(project_row.get("id") or 0)
        if project_id <= 0:
            return
        start_at = int(project_row.get("start_at") or 0)
        resolved_end_at = int(project_row.get("resolved_end_at") or 0)
        bounded = max(start_at, int(cursor_ts))
        if resolved_end_at >= start_at:
            bounded = min(bounded, resolved_end_at)
        self.storage.set_state(self._managed_project_scan_cursor_key(project_id), str(bounded))

    def _find_managed_project_by_name(self, name: Optional[str]) -> Optional[Dict[str, Any]]:
        project_name = str(name or "").strip()
        if not project_name:
            return None
        for row in self.storage.list_managed_projects():
            if str(row.get("name") or "").strip() == project_name:
                return dict(row)
        return None

    def _managed_project_has_active_scan_job(self, project_row: Dict[str, Any]) -> bool:
        project_id = int(project_row.get("id") or 0)
        if project_id <= 0:
            return False
        last_job_id = self.storage.get_state(self._managed_project_last_scan_job_key(project_id))
        if not last_job_id:
            return False
        job = self.event_bus.get_scan_job(last_job_id)
        if not job:
            return False
        return str(job.get("status") or "").strip().lower() in {"queued", "running"}

    def set_managed_project_chart_window(self, project_row: Dict[str, Any]) -> None:
        project_id = int(project_row.get("id") or 0)
        if project_id <= 0:
            return
        self.storage.set_state(
            self._managed_project_chart_from_key(project_id),
            str(int(project_row.get("start_at") or 0)),
        )
        self.storage.set_state(
            self._managed_project_chart_to_key(project_id),
            str(int(project_row.get("resolved_end_at") or 0)),
        )

    def queue_managed_project_scan_job(self, project_row: Dict[str, Any]) -> Optional[str]:
        if not bool(project_row.get("backfill_enabled")):
            return None
        if not self.managed_project_is_complete(project_row):
            return None
        status = str(project_row.get("status") or "").strip().lower()
        if status not in {"prelaunch", "live", "ended"}:
            return None
        start_at = int(project_row.get("start_at") or 0)
        resolved_end_at = int(project_row.get("resolved_end_at") or 0)
        if start_at <= 0 or resolved_end_at < start_at:
            return None
        self._ensure_managed_project_scan_state(project_row)
        if self._managed_project_has_active_scan_job(project_row):
            return None
        now = int(time.time())
        scan_end_ts = min(now, resolved_end_at)
        if scan_end_ts <= start_at:
            return None
        scan_cursor = self._get_managed_project_scan_cursor(project_row)
        if scan_cursor >= resolved_end_at:
            return None
        scan_start_ts = max(start_at, scan_cursor)
        if scan_end_ts <= scan_start_ts:
            return None
        project_name = str(project_row.get("name") or "").strip() or None
        job_id = self.event_bus.create_scan_job(project_name, scan_start_ts, scan_end_ts)
        project_id = int(project_row.get("id") or 0)
        if project_id > 0:
            self.storage.set_state(self._managed_project_last_scan_job_key(project_id), job_id)
            self.storage.set_state(self._managed_project_last_scan_at_key(project_id), str(now))
        return job_id

    def build_project_scheduler_status(self) -> Dict[str, Any]:
        now = int(time.time())
        items: List[Dict[str, Any]] = []
        active_count = 0
        for row in self.storage.list_managed_projects():
            project_id = int(row.get("id") or 0)
            chart_from_raw = self.storage.get_state(self._managed_project_chart_from_key(project_id))
            chart_to_raw = self.storage.get_state(self._managed_project_chart_to_key(project_id))
            last_scan_job_id = self.storage.get_state(self._managed_project_last_scan_job_key(project_id))
            last_scan_at_raw = self.storage.get_state(self._managed_project_last_scan_at_key(project_id))
            scan_cursor_raw = self.storage.get_state(self._managed_project_scan_cursor_key(project_id))
            projected_status = self.derive_managed_project_status(row, now_ts=now)
            if projected_status in {"prelaunch", "live"}:
                active_count += 1
            items.append(
                {
                    "id": project_id,
                    "name": str(row.get("name") or ""),
                    "status": str(row.get("status") or ""),
                    "projectedStatus": projected_status,
                    "startAt": int(row.get("start_at") or 0),
                    "resolvedEndAt": int(row.get("resolved_end_at") or 0),
                    "chartFromAt": int(chart_from_raw) if chart_from_raw else None,
                    "chartToAt": int(chart_to_raw) if chart_to_raw else None,
                    "lastScanJobId": last_scan_job_id,
                    "lastScanQueuedAt": int(last_scan_at_raw) if last_scan_at_raw else None,
                    "lastScanCoveredToAt": int(scan_cursor_raw) if scan_cursor_raw not in {None, ""} else None,
                    "isWatched": bool(row.get("is_watched")),
                    "collectEnabled": bool(row.get("collect_enabled")),
                    "backfillEnabled": bool(row.get("backfill_enabled")),
                    "isComplete": self.managed_project_is_complete(row),
                }
            )
        items.sort(key=lambda item: (item["startAt"], item["name"]))
        last_run_raw = self.storage.get_state("managed_project_scheduler_last_run_at")
        return {
            "ok": True,
            "intervalSec": int(self.project_scheduler_interval_sec),
            "prelaunchLeadSec": int(self.project_prelaunch_lead_sec),
            "runtimePaused": bool(self.refresh_runtime_pause_state(force=True)),
            "activeCount": active_count,
            "count": len(items),
            "lastRunAt": int(last_run_raw) if last_run_raw else None,
            "items": items,
        }

    def build_overview_empty_payload(
        self,
        *,
        requested_project: Optional[str] = None,
        has_active_project: bool = False,
        active_projects: Optional[List[Dict[str, Any]]] = None,
        view_mode: str = "active",
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "viewMode": view_mode,
            "requestedProject": str(requested_project or "").strip(),
            "hasActiveProject": bool(has_active_project),
            "activeProjects": active_projects or [],
            "item": None,
            "minutes": [],
            "whaleBoard": [],
            "trackedWallets": [],
            "delays": [],
        }

    async def enrich_overview_board_items(
        self,
        project_name: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        launch_cfg = self.storage.get_launch_config_by_name(project_name)
        total_supply = (
            launch_cfg.token_total_supply if launch_cfg is not None else self.fixed_token_total_supply
        )
        virtual_price_usd, _ = await self.price_service.get_price()

        enriched: List[Dict[str, Any]] = []
        for item in items:
            row = dict(item)
            existing_fdv_usd = row.get("breakevenFdvUsd")
            if existing_fdv_usd not in (None, ""):
                row["breakevenFdvUsd"] = str(existing_fdv_usd)
                enriched.append(row)
                continue

            spent = Decimal(str(row.get("spentV") or "0"))
            token = Decimal(str(row.get("tokenBought") or "0"))
            avg_cost_v = (spent / token) if token > 0 else Decimal(0)
            fdv_v = avg_cost_v * total_supply
            fdv_usd = (fdv_v * virtual_price_usd) if virtual_price_usd is not None else None
            row["breakevenFdvUsd"] = decimal_to_str(fdv_usd, 18) if fdv_usd is not None else None
            enriched.append(row)

        return enriched

    async def build_project_overview_payload(
        self,
        managed_row: Optional[Dict[str, Any]],
        *,
        requested_project: Optional[str] = None,
        tracked_wallet_configs: Optional[List[Dict[str, Any]]] = None,
        scheduler_status: Optional[Dict[str, Any]] = None,
        view_mode: str = "project",
    ) -> Dict[str, Any]:
        requested_name = str(requested_project or "").strip()
        scheduler_status = scheduler_status or self.build_project_scheduler_status()
        active_scheduler_items = [
            item
            for item in scheduler_status.get("items", [])
            if str(item.get("projectedStatus") or "").strip().lower() in {"prelaunch", "live"}
        ]
        active_scheduler_items.sort(key=lambda item: (int(item.get("startAt") or 0), str(item.get("name") or "")))
        active_projects = [
            {
                "id": int(item.get("id") or 0),
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
                "projectedStatus": str(item.get("projectedStatus") or ""),
                "startAt": int(item.get("startAt") or 0),
                "resolvedEndAt": int(item.get("resolvedEndAt") or 0),
            }
            for item in active_scheduler_items
        ]
        if not managed_row:
            return self.build_overview_empty_payload(
                requested_project=requested_name,
                has_active_project=bool(active_projects),
                active_projects=active_projects,
                view_mode=view_mode,
            )

        project_name = str(managed_row.get("name") or "").strip()
        project_id = int(managed_row.get("id") or 0)
        resolved_end_at = resolve_project_end_at(
            int(managed_row.get("start_at") or 0),
            parse_optional_int(managed_row.get("signalhub_end_at"), "signalhub_end_at"),
            parse_optional_int(managed_row.get("manual_end_at"), "manual_end_at"),
        )
        managed_row = dict(managed_row)
        managed_row["resolved_end_at"] = resolved_end_at
        scheduler_item = next(
            (
                item
                for item in scheduler_status.get("items", [])
                if int(item.get("id") or 0) == project_id or str(item.get("name") or "") == project_name
            ),
            None,
        )
        projected_status = (
            str(scheduler_item.get("projectedStatus") or "").strip()
            if scheduler_item
            else self.derive_managed_project_status(managed_row, now_ts=int(time.time()))
        )
        chart_from_raw = self.storage.get_state(self._managed_project_chart_from_key(project_id))
        chart_to_raw = self.storage.get_state(self._managed_project_chart_to_key(project_id))
        chart_from_at = int(chart_from_raw) if chart_from_raw else int(managed_row.get("start_at") or 0)
        chart_to_at = int(chart_to_raw) if chart_to_raw else int(managed_row.get("resolved_end_at") or 0)

        minutes = (
            self.storage.query_minutes(project_name, chart_from_at, chart_to_at)
            if chart_from_at > 0 and chart_to_at >= chart_from_at
            else []
        )
        tax = self.storage.query_project_tax(project_name)
        delays = self.storage.query_event_delays(project_name, 12)
        leaderboard_rows = self.storage.query_leaderboard(project_name, int(self.cfg.top_n))
        wallet_positions = self.storage.query_wallets(project=project_name)
        tracked_wallet_configs = (
            tracked_wallet_configs
            if tracked_wallet_configs is not None
            else self.storage.list_monitored_wallet_rows()
        )

        wallet_names = {
            normalize_address(str(row.get("wallet") or "")): str(row.get("name") or "").strip()
            for row in tracked_wallet_configs
            if row.get("wallet")
        }
        whale_board: List[Dict[str, Any]] = []
        for row in leaderboard_rows:
            wallet = normalize_address(str(row.get("buyer") or ""))
            whale_board.append(
                {
                    "wallet": wallet,
                    "name": wallet_names.get(wallet, ""),
                    "spentV": str(row.get("sum_spent_v_est") or "0"),
                    "tokenBought": str(row.get("sum_token_bought") or "0"),
                    "breakevenFdvUsd": row.get("breakeven_fdv_usd"),
                    "updatedAt": int(row.get("last_tx_time") or row.get("updated_at") or 0),
                }
            )

        positions_by_wallet = {
            normalize_address(str(row.get("wallet") or "")): row
            for row in wallet_positions
            if row.get("wallet")
        }
        tracked_wallets: List[Dict[str, Any]] = []
        for row in tracked_wallet_configs:
            wallet = normalize_address(str(row.get("wallet") or ""))
            position = positions_by_wallet.get(wallet) or {}
            tracked_wallets.append(
                {
                    "wallet": wallet,
                    "name": str(row.get("name") or "").strip(),
                    "spentV": str(position.get("sum_spent_v_est") or "0"),
                    "tokenBought": str(position.get("sum_token_bought") or "0"),
                    "breakevenFdvUsd": position.get("breakeven_fdv_usd"),
                    "updatedAt": int(position.get("updated_at") or 0),
                }
            )
        tracked_wallets.sort(
            key=lambda item: (
                Decimal(str(item.get("spentV") or "0")),
                Decimal(str(item.get("tokenBought") or "0")),
                str(item.get("wallet") or ""),
            ),
            reverse=True,
        )
        whale_board = await self.enrich_overview_board_items(project_name, whale_board)
        tracked_wallets = await self.enrich_overview_board_items(project_name, tracked_wallets)

        return {
            "ok": True,
            "viewMode": view_mode,
            "requestedProject": requested_name or project_name,
            "hasActiveProject": bool(active_projects),
            "activeProjects": active_projects,
            "item": {
                "id": project_id,
                "name": project_name,
                "status": str(managed_row.get("status") or ""),
                "projectedStatus": projected_status,
                "startAt": int(managed_row.get("start_at") or 0),
                "resolvedEndAt": int(managed_row.get("resolved_end_at") or 0),
                "detailUrl": str(managed_row.get("detail_url") or "").strip(),
                "tokenAddr": normalize_optional_address(managed_row.get("token_addr")),
                "internalPoolAddr": normalize_optional_address(managed_row.get("internal_pool_addr")),
                "sumTaxV": str(tax.get("sum_tax_v") or "0"),
                "chartFromAt": chart_from_at,
                "chartToAt": chart_to_at,
            },
            "minutes": minutes,
            "whaleBoard": whale_board,
            "trackedWallets": tracked_wallets,
            "delays": delays,
        }

    async def build_overview_active_payload(
        self,
        requested_project: Optional[str] = None,
        tracked_wallet_configs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        scheduler_status = self.build_project_scheduler_status()
        active_scheduler_items = [
            item
            for item in scheduler_status.get("items", [])
            if str(item.get("projectedStatus") or "").strip().lower() in {"prelaunch", "live"}
        ]
        active_scheduler_items.sort(key=lambda item: (int(item.get("startAt") or 0), str(item.get("name") or "")))
        requested_name = str(requested_project or "").strip()

        if not active_scheduler_items:
            return self.build_overview_empty_payload(requested_project=requested_name, view_mode="active")

        selected_scheduler = next(
            (item for item in active_scheduler_items if str(item.get("name") or "") == requested_name),
            active_scheduler_items[0],
        )
        managed_rows = self.storage.list_managed_projects()
        managed_row = next(
            (
                row
                for row in managed_rows
                if int(row.get("id") or 0) == int(selected_scheduler.get("id") or 0)
                or str(row.get("name") or "") == str(selected_scheduler.get("name") or "")
            ),
            None,
        )
        return await self.build_project_overview_payload(
            managed_row,
            requested_project=requested_name,
            tracked_wallet_configs=tracked_wallet_configs,
            scheduler_status=scheduler_status,
            view_mode="active",
        )

    def list_public_managed_projects(self, user_row: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        visible_statuses = {"scheduled", "prelaunch", "live", "ended"}
        items: List[Dict[str, Any]] = []
        for row in self.storage.list_managed_projects():
            status = str(row.get("status") or "").strip().lower()
            if status not in visible_statuses:
                continue
            item = dict(row)
            item["resolved_end_at"] = resolve_project_end_at(
                int(item.get("start_at") or 0),
                parse_optional_int(item.get("signalhub_end_at"), "signalhub_end_at"),
                parse_optional_int(item.get("manual_end_at"), "manual_end_at"),
            )
            access = self.build_project_access_payload(user_row, item)
            item["is_unlocked"] = bool(access["isUnlocked"])
            item["unlock_cost"] = int(access["unlockCost"])
            item["can_unlock_now"] = bool(access["canUnlockNow"])
            item["unlocked_at"] = access["unlockedAt"]
            items.append(item)
        return items

    def build_user_meta_payload(self, user_row: Dict[str, Any]) -> Dict[str, Any]:
        scheduler = self.build_project_scheduler_status()
        has_active_project = any(
            str(item.get("projectedStatus") or "").lower() in {"prelaunch", "live"}
            for item in scheduler.get("items", [])
        )
        public_projects = self.list_public_managed_projects(user_row)
        has_unlocked_active_project = any(
            bool(item.get("is_unlocked"))
            and str(item.get("status") or "").lower() in {"prelaunch", "live"}
            for item in public_projects
        )
        return {
            "user": self.auth_public_user(user_row),
            "wallet_count": len(self.storage.list_user_wallet_rows(int(user_row["id"]))),
            "credit_balance": int(user_row.get("credit_balance") or 0),
            "credit_spent_total": int(user_row.get("credit_spent_total") or 0),
            "credit_granted_total": int(user_row.get("credit_granted_total") or 0),
            "unlocked_project_count": len(self.storage.list_user_project_access_rows(int(user_row["id"]), limit=1000)),
            "unread_notification_count": self.count_visible_user_notifications(
                int(user_row["id"]), unread_only=True
            ),
            "visible_project_statuses": ["scheduled", "prelaunch", "live", "ended"],
            "has_active_project": has_active_project,
            "default_path": "/app/overview" if has_unlocked_active_project else "/app/projects",
            "projects": public_projects,
        }

    def reconcile_managed_projects_schedule(self, force_launch_sync: bool = False) -> Dict[str, int]:
        now = int(time.time())
        changed = 0
        queued_jobs = 0
        active = 0
        for original_row in self.storage.list_managed_projects():
            row = dict(original_row)
            target_status = self.derive_managed_project_status(row, now_ts=now)
            current_status = str(row.get("status") or "").strip().lower()
            if target_status != current_status:
                row = self.storage.update_managed_project_status(int(row["id"]), target_status)
                changed += 1
            if target_status in {"prelaunch", "live"}:
                active += 1
                self.set_managed_project_chart_window(row)
            if target_status in {"prelaunch", "live", "ended"}:
                self.set_managed_project_chart_window(row)
                if self.queue_managed_project_scan_job(row):
                    queued_jobs += 1
            if force_launch_sync or target_status != current_status:
                self.sync_launch_config_for_managed_project(row)

        if changed or force_launch_sync:
            self.sync_runtime_after_managed_project_change()

        self.storage.set_state("managed_project_scheduler_last_run_at", str(now))
        self.stats["scheduler_last_run_at"] = now
        self.stats["scheduler_active_projects"] = active
        self.stats["scheduler_transitions"] = int(self.stats.get("scheduler_transitions", 0)) + changed
        self.stats["scheduler_scan_jobs"] = int(self.stats.get("scheduler_scan_jobs", 0)) + queued_jobs
        return {"changed": changed, "queuedJobs": queued_jobs, "active": active}

    def get_runtime_db_batch_size(self) -> int:
        return max(1, int(self.cfg.db_batch_size))

    def set_runtime_db_batch_size(self, value: int) -> int:
        v = max(1, int(value))
        self.cfg.db_batch_size = v
        self.storage.set_state("runtime_db_batch_size", str(v))
        return v

    def bump_launch_config_revision(self) -> None:
        rev = str(int(time.time()))
        self.storage.set_state("launch_configs_rev", rev)
        self.last_launch_cfg_rev = rev

    def bump_my_wallet_revision(self) -> None:
        rev = str(int(time.time()))
        self.storage.set_state("my_wallets_rev", rev)
        self.last_my_wallets_rev = rev

    def _load_runtime_ui_last_seen(self) -> int:
        raw = self.storage.get_state("runtime_ui_last_seen")
        if raw is None:
            return 0
        try:
            return max(0, int(str(raw)))
        except Exception:
            return 0

    def touch_runtime_ui_heartbeat(self) -> int:
        now = int(time.time())
        self.storage.set_state("runtime_ui_last_seen", str(now))
        self.runtime_ui_last_seen_at = now
        return now

    def get_runtime_paused(self) -> bool:
        return self.refresh_runtime_pause_state(force=True)

    def refresh_runtime_pause_state(self, force: bool = False) -> bool:
        now = time.time()
        if (not force) and (now - self._last_runtime_pause_check_ts < 1.0):
            return self.runtime_paused
        self._last_runtime_pause_check_ts = now
        prev = self.runtime_paused
        manual_state = self.storage.get_state("runtime_paused")
        manual_paused = True if manual_state is None else parse_bool_like(manual_state)
        ui_last_seen_at = self._load_runtime_ui_last_seen()
        ui_online = (ui_last_seen_at > 0) and (
            int(now) - ui_last_seen_at <= self.runtime_ui_heartbeat_timeout_sec
        )
        # UI heartbeat is telemetry only. Runtime pause now follows manual control
        # so unattended deployments no longer stop when no dashboard is open.
        effective_paused = bool(manual_paused)
        self.runtime_manual_paused = manual_paused
        self.runtime_ui_last_seen_at = ui_last_seen_at
        self.runtime_ui_online = ui_online
        self.runtime_paused = effective_paused
        if self.runtime_paused != prev:
            self.runtime_pause_updated_at = int(now)
            if self.is_realtime_role:
                self.ws_reconnect_event.set()
            if self.runtime_paused:
                self.stats["ws_connected"] = False
        return self.runtime_paused

    def set_runtime_paused(self, paused: bool) -> bool:
        value = "1" if bool(paused) else "0"
        self.storage.set_state("runtime_paused", value)
        if not paused:
            self.touch_runtime_ui_heartbeat()
        return self.refresh_runtime_pause_state(force=True)

    def runtime_pause_payload(self) -> Dict[str, Any]:
        self.refresh_runtime_pause_state(force=True)
        return {
            "runtimePaused": bool(self.runtime_paused),
            "runtimeManualPaused": bool(self.runtime_manual_paused),
            "runtimeUiOnline": bool(self.runtime_ui_online),
            "runtimeUiLastSeenAt": (
                int(self.runtime_ui_last_seen_at) if self.runtime_ui_last_seen_at > 0 else None
            ),
            "runtimeUiHeartbeatTimeoutSec": int(self.runtime_ui_heartbeat_timeout_sec),
            "updatedAt": int(self.runtime_pause_updated_at),
        }

    async def wait_until_resumed(self) -> bool:
        while not self.stop_event.is_set():
            if not self.refresh_runtime_pause_state():
                return True
            await asyncio.sleep(0.5)
        return False

    async def launch_config_watch_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(2)
            latest = self.storage.get_state("launch_configs_rev") or ""
            if latest != self.last_launch_cfg_rev:
                self.last_launch_cfg_rev = latest
                self.reload_launch_configs()
                if self.is_realtime_role:
                    self.ws_reconnect_event.set()

    async def my_wallet_watch_loop(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(2)
            latest = self.storage.get_state("my_wallets_rev") or ""
            if latest != self.last_my_wallets_rev:
                self.last_my_wallets_rev = latest
                self.reload_my_wallets()

    def write_inserted_events_jsonl(self, inserted: List[Dict[str, Any]]) -> None:
        if not inserted or not self.jsonl_file:
            return
        for e in inserted:
            self.jsonl_file.write(
                json.dumps(
                    {
                        "project": e["project"],
                        "txHash": e["tx_hash"],
                        "blockNumber": e["block_number"],
                        "timestamp": e["block_timestamp"],
                        "internalPool": e["internal_pool"],
                        "feeAddr": e["fee_addr"],
                        "taxAddr": e["tax_addr"],
                        "buyer": e["buyer"],
                        "tokenAddr": e["token_addr"],
                        "tokenBought": decimal_to_str(e["token_bought"], 18),
                        "feeV": decimal_to_str(e["fee_v"], 18),
                        "taxV": decimal_to_str(e["tax_v"], 18),
                        "spentV_est": decimal_to_str(e["spent_v_est"], 18),
                        "spentV_actual": decimal_to_str(e["spent_v_actual"], 18),
                        "costV": decimal_to_str(e["cost_v"], 18),
                        "totalSupply": decimal_to_str(e["total_supply"], 0),
                        "breakevenFDV_V": decimal_to_str(e["breakeven_fdv_v"], 18),
                        "virtualPriceUSD": decimal_to_str(e["virtual_price_usd"], 18)
                        if e.get("virtual_price_usd") is not None
                        else None,
                        "breakevenFDV_USD": decimal_to_str(e["breakeven_fdv_usd"], 18)
                        if e.get("breakeven_fdv_usd") is not None
                        else None,
                        "isMyWallet": e["is_my_wallet"],
                        "anomaly": e["anomaly"],
                        "isPriceStale": e["is_price_stale"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        self.jsonl_file.flush()

    def persist_events_batch(self, events: List[Dict[str, Any]], max_block: int) -> int:
        inserted = self.storage.flush_events(events, max_block)
        self.stats["inserted_events"] += len(inserted)
        self.stats["last_flush_at"] = int(time.time())
        self.write_inserted_events_jsonl(inserted)
        return len(inserted)

    async def emit_parsed_events(self, events: List[Dict[str, Any]], block_number: int) -> None:
        if not events:
            return
        if self.emit_events_to_bus:
            self.event_bus.enqueue_events(self.role, events)
        else:
            async with self.flush_lock:
                self.pending_events.extend(events)
                self.pending_max_block = max(self.pending_max_block, block_number)
        self.stats["parsed_events"] += len(events)

    def build_heartbeat_payload(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "runtime_paused": bool(self.runtime_paused),
            "runtime_manual_paused": bool(self.runtime_manual_paused),
            "runtime_ui_online": bool(self.runtime_ui_online),
            "ws_connected": bool(self.stats.get("ws_connected", False)),
            "enqueued_txs": int(self.stats.get("enqueued_txs", 0)),
            "processed_txs": int(self.stats.get("processed_txs", 0)),
            "parsed_events": int(self.stats.get("parsed_events", 0)),
            "rpc_errors": int(self.stats.get("rpc_errors", 0)),
            "dead_letters": int(self.stats.get("dead_letters", 0)),
            "last_ws_block": int(self.stats.get("last_ws_block", 0)),
            "last_backfill_block": int(self.stats.get("last_backfill_block", 0)),
            "queue_size": int(self.queue.qsize()),
            "pending_txs": int(len(self.pending_txs)),
            "updated_at": int(time.time()),
        }

    async def role_heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.refresh_runtime_pause_state(force=True)
                self.event_bus.upsert_role_heartbeat(self.role, self.build_heartbeat_payload())
            except Exception:
                pass
            await asyncio.sleep(2)

    async def project_scheduler_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.reconcile_managed_projects_schedule(force_launch_sync=False)
            except Exception:
                pass
            await asyncio.sleep(max(5, int(self.project_scheduler_interval_sec)))

    async def bus_writer_loop(self) -> None:
        while not self.stop_event.is_set():
            batch_size = max(1, int(self.cfg.db_batch_size))
            idle_sleep = max(0.05, self.cfg.db_flush_ms / 1000.0)
            rows = self.event_bus.fetch_events(batch_size)
            if not rows:
                await asyncio.sleep(idle_sleep)
                continue
            try:
                events = [x["event"] for x in rows]
                max_block = max((int(x.get("block_number", 0)) for x in events), default=0)
                self.stats["parsed_events"] += len(events)
                self.persist_events_batch(events, max_block)
                self.event_bus.ack_events([int(x["id"]) for x in rows])
            except Exception:
                self.stats["rpc_errors"] += 1
                await asyncio.sleep(0.5)

    async def scan_job_dispatch_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.refresh_runtime_pause_state():
                await asyncio.sleep(1)
                continue
            job = self.event_bus.claim_next_scan_job()
            if not job:
                await asyncio.sleep(1)
                continue
            await self.run_scan_range_job_bus(job)

    async def __aenter__(self) -> "VirtualsBot":
        for client in self.rpc_clients_by_url.values():
            await client.__aenter__()
        for client in self.backfill_http_rpcs:
            with contextlib.suppress(Exception):
                await self.probe_backfill_rpc(client, force=True)
        if self.enable_api and self.signalhub_client:
            await self.signalhub_client.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if not self.stop_event.is_set():
            await self.shutdown()
        for client in reversed(list(self.rpc_clients_by_url.values())):
            await client.__aexit__(exc_type, exc, tb)
        if self.enable_api and self.signalhub_client:
            await self.signalhub_client.__aexit__(exc_type, exc, tb)
        self.storage.close()
        self.event_bus.close()
        if self.jsonl_file:
            self.jsonl_file.close()

    async def get_token_decimals(
        self, token_addr: str, rpc: Optional[RPCClient] = None
    ) -> int:
        token_addr = normalize_address(token_addr)
        cached = self.decimals_cache.get(token_addr)
        if cached is not None:
            return cached
        rpc_client = rpc or self.http_rpc
        out = await rpc_client.eth_call(token_addr, DECIMALS_SELECTOR)
        dec = int(out, 16)
        self.decimals_cache[token_addr] = dec
        return dec

    async def get_block_timestamp(
        self, block_number: int, rpc: Optional[RPCClient] = None
    ) -> int:
        cached = self.block_ts_cache.get(block_number)
        if cached is not None:
            return cached
        rpc_client = rpc or self.http_rpc
        self.record_backfill_rpc_usage(rpc_client, operation="historical_block")
        block = await rpc_client.get_block_by_number(block_number)
        if not block:
            return int(time.time())
        ts = int(block["timestamp"], 16)
        self.block_ts_cache[block_number] = ts
        if len(self.block_ts_cache) > 5000:
            oldest = sorted(self.block_ts_cache.keys())[:1000]
            for b in oldest:
                self.block_ts_cache.pop(b, None)
        return ts

    def is_related_to_launch(self, receipt_logs: List[Dict[str, Any]], launch: LaunchConfig) -> bool:
        vaddr = self.cfg.virtual_token_addr
        for lg in receipt_logs:
            topics = lg.get("topics") or []
            if not topics:
                continue
            if topics[0].lower() != TRANSFER_TOPIC0:
                continue
            token = normalize_address(lg["address"])
            from_addr = decode_topic_address(topics[1]) if len(topics) > 1 else ""
            to_addr = decode_topic_address(topics[2]) if len(topics) > 2 else ""
            if token == vaddr and (
                from_addr == launch.internal_pool_addr
                or to_addr == launch.internal_pool_addr
                or to_addr == launch.fee_addr
                or to_addr == launch.tax_addr
            ):
                return True
            if from_addr == launch.internal_pool_addr or to_addr == launch.internal_pool_addr:
                return True
        return False

    async def parse_receipt_for_launch(
        self,
        launch: LaunchConfig,
        receipt: Dict[str, Any],
        timestamp: int,
        virtual_price_usd: Optional[Decimal],
        is_price_stale: bool,
        rpc: Optional[RPCClient] = None,
    ) -> List[Dict[str, Any]]:
        logs = receipt.get("logs", [])
        tx_hash = receipt["transactionHash"].lower()
        block_number = int(receipt["blockNumber"], 16)

        transfer_logs = []
        for idx, lg in enumerate(logs):
            topics = lg.get("topics") or []
            if not topics or topics[0].lower() != TRANSFER_TOPIC0 or len(topics) < 3:
                continue
            try:
                token_addr = normalize_address(lg["address"])
                from_addr = decode_topic_address(topics[1])
                to_addr = decode_topic_address(topics[2])
                amount_raw = parse_hex_int(lg.get("data"))
            except Exception:
                continue
            transfer_logs.append(
                {
                    "token_addr": token_addr,
                    "from": from_addr,
                    "to": to_addr,
                    "amount_raw": amount_raw,
                    "idx": idx,
                }
            )

        candidate_buyers: Set[str] = set()
        buyer_fee_raw: Dict[str, int] = defaultdict(int)
        buyer_tax_raw: Dict[str, int] = defaultdict(int)
        buyer_virtual_out_raw: Dict[str, int] = defaultdict(int)
        buyer_virtual_in_raw: Dict[str, int] = defaultdict(int)
        token_received_raw: Dict[Tuple[str, str], int] = defaultdict(int)
        token_received_first_idx: Dict[Tuple[str, str], int] = {}
        token_outgoing_logs: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

        vaddr = self.cfg.virtual_token_addr
        for lg in transfer_logs:
            token = lg["token_addr"]
            from_addr = lg["from"]
            to_addr = lg["to"]
            amount = lg["amount_raw"]
            if amount <= 0:
                continue

            token_outgoing_logs[(from_addr, token)].append(lg)

            if token == vaddr:
                if to_addr in {launch.fee_addr, launch.tax_addr, launch.internal_pool_addr}:
                    candidate_buyers.add(from_addr)
                if to_addr == launch.fee_addr:
                    buyer_fee_raw[from_addr] += amount
                if to_addr == launch.tax_addr:
                    buyer_tax_raw[from_addr] += amount
                buyer_virtual_out_raw[from_addr] += amount
                buyer_virtual_in_raw[to_addr] += amount

            if from_addr == launch.internal_pool_addr and amount > 0:
                token_received_raw[(to_addr, token)] += amount
                key = (to_addr, token)
                if key not in token_received_first_idx:
                    token_received_first_idx[key] = int(lg["idx"])

        virtual_decimals = await self.get_token_decimals(vaddr, rpc=rpc)

        events: List[Dict[str, Any]] = []
        for (buyer, token_addr), raw_amount in token_received_raw.items():
            if buyer not in candidate_buyers:
                continue

            # Keep strict swap validation, but attribute buyer to the final
            # destination of the token flow originating from internal pool.
            effective_buyer = buyer
            effective_raw_amount = raw_amount
            cur_idx = int(token_received_first_idx.get((buyer, token_addr), -1))
            visited: Set[str] = {launch.internal_pool_addr}
            for _ in range(8):
                outs = [
                    x
                    for x in token_outgoing_logs.get((effective_buyer, token_addr), [])
                    if int(x["idx"]) > cur_idx
                    and x["to"] != launch.internal_pool_addr
                    and int(x["amount_raw"]) > 0
                ]
                if not outs:
                    break
                nxt = max(outs, key=lambda x: (int(x["amount_raw"]), int(x["idx"])))
                nxt_to = str(nxt["to"])
                if nxt_to in visited:
                    break
                visited.add(nxt_to)
                effective_buyer = nxt_to
                cur_idx = int(nxt["idx"])
                effective_raw_amount = min(effective_raw_amount, int(nxt["amount_raw"]))

            token_decimals = await self.get_token_decimals(token_addr, rpc=rpc)
            token_bought = raw_to_decimal(effective_raw_amount, token_decimals)
            if token_bought <= 0:
                continue

            virtual_out = raw_to_decimal(buyer_virtual_out_raw.get(buyer, 0), virtual_decimals)
            virtual_in = raw_to_decimal(buyer_virtual_in_raw.get(buyer, 0), virtual_decimals)
            spent_v_actual = virtual_out - virtual_in
            if spent_v_actual <= 0:
                continue

            fee_raw = buyer_fee_raw.get(buyer, 0)
            tax_raw = buyer_tax_raw.get(buyer, 0)
            fee_v = raw_to_decimal(fee_raw, virtual_decimals)
            tax_v = raw_to_decimal(tax_raw, virtual_decimals)

            launch_pattern = ""
            if launch.fee_rate > 0 and fee_v > 0:
                launch_pattern = "fee_pool"
                spent_v_est = fee_v / launch.fee_rate
            elif tax_v > 0:
                launch_pattern = "tax_pool"
                # Newer launches can route payment to pool + tax without an
                # explicit fee transfer. In that case the actual VIRTUAL
                # outflow is the best available estimate.
                spent_v_est = spent_v_actual
            else:
                launch_pattern = "pool_only"
                # Fallback for launches that only expose pool inflow + token
                # outflow. Keep this below tax_pool so known tax-bearing flows
                # still retain their stronger signal.
                spent_v_est = spent_v_actual
            if spent_v_est <= 0:
                continue

            cost_v = spent_v_est / token_bought
            total_supply = launch.token_total_supply
            breakeven_fdv_v = cost_v * total_supply
            breakeven_fdv_usd = (
                breakeven_fdv_v * virtual_price_usd if virtual_price_usd is not None else None
            )

            anomaly = False
            if launch_pattern == "fee_pool" and spent_v_est > 0:
                gap = abs(spent_v_actual - spent_v_est) / spent_v_est
                anomaly = gap > Decimal("0.02")

            events.append(
                {
                    "project": launch.name,
                    "tx_hash": tx_hash,
                    "block_number": block_number,
                    "block_timestamp": timestamp,
                    "internal_pool": launch.internal_pool_addr,
                    "fee_addr": launch.fee_addr,
                    "tax_addr": launch.tax_addr,
                    "buyer": effective_buyer,
                    "token_addr": token_addr,
                    "token_bought": token_bought,
                    "fee_v": fee_v,
                    "tax_v": tax_v,
                    "spent_v_est": spent_v_est,
                    "spent_v_actual": spent_v_actual,
                    "cost_v": cost_v,
                    "total_supply": total_supply,
                    "virtual_price_usd": virtual_price_usd,
                    "breakeven_fdv_v": breakeven_fdv_v,
                    "breakeven_fdv_usd": breakeven_fdv_usd,
                    "is_my_wallet": effective_buyer in self.my_wallets,
                    "anomaly": anomaly,
                    "is_price_stale": is_price_stale,
                }
            )
        return events

    async def enqueue_tx(
        self, tx_hash: str, block_number: int, rpc_url: Optional[str] = None
    ) -> None:
        tx_hash = tx_hash.lower()
        if tx_hash in self.pending_txs:
            return
        self.pending_txs.add(tx_hash)
        await self.queue.put((tx_hash, block_number, rpc_url))
        self.stats["enqueued_txs"] += 1

    async def process_tx(
        self,
        tx_hash: str,
        hint_block: int,
        launch_configs: Optional[List[LaunchConfig]] = None,
        rpc: Optional[RPCClient] = None,
    ) -> None:
        try:
            rpc_client = rpc or self.http_rpc
            receipt = await rpc_client.get_receipt(tx_hash)
            if not receipt:
                return
            if receipt.get("status") and int(receipt["status"], 16) == 0:
                return

            block_number = int(receipt["blockNumber"], 16)
            timestamp = await self.get_block_timestamp(block_number, rpc=rpc_client)
            virtual_price_usd, is_price_stale = await self.price_service.get_price()

            all_events: List[Dict[str, Any]] = []
            logs = receipt.get("logs", [])
            active_launch_configs = launch_configs if launch_configs is not None else self.get_launch_configs()
            for launch in active_launch_configs:
                if not self.is_related_to_launch(logs, launch):
                    continue
                events = await self.parse_receipt_for_launch(
                    launch=launch,
                    receipt=receipt,
                    timestamp=timestamp,
                    virtual_price_usd=virtual_price_usd,
                    is_price_stale=is_price_stale,
                    rpc=rpc_client,
                )
                all_events.extend(events)

            if all_events:
                await self.emit_parsed_events(all_events, block_number)

            self.stats["processed_txs"] += 1
        except Exception as e:
            self.stats["rpc_errors"] += 1
            self.storage.save_dead_letter(
                tx_hash=tx_hash,
                reason=f"process_tx_failed: {type(e).__name__}: {e}",
                payload={"hint_block": hint_block},
            )
            self.stats["dead_letters"] += 1
        finally:
            self.pending_txs.discard(tx_hash)

    async def consumer_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.refresh_runtime_pause_state():
                await asyncio.sleep(0.5)
                continue
            tx_hash, block_number, rpc_url = await self.queue.get()
            try:
                rpc_client = self.rpc_clients_by_url.get(str(rpc_url or "").strip()) or self.http_rpc
                await self.process_tx(tx_hash, block_number, rpc=rpc_client)
            finally:
                self.queue.task_done()

    async def flush_loop(self) -> None:
        interval = max(0.1, self.cfg.db_flush_ms / 1000.0)
        while not self.stop_event.is_set():
            await asyncio.sleep(interval)
            await self.flush_once(force=False)

    async def flush_once(self, force: bool) -> None:
        async with self.flush_lock:
            if not self.pending_events and not force:
                return
            if (not force) and (len(self.pending_events) < self.cfg.db_batch_size):
                return
            events = self.pending_events
            max_block = self.pending_max_block
            self.pending_events = []
            self.pending_max_block = 0

        self.persist_events_batch(events, max_block)

    async def ws_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.refresh_runtime_pause_state():
                    self.stats["ws_connected"] = False
                    await asyncio.sleep(1)
                    continue
                launch_configs = self.get_launch_configs()
                if not launch_configs:
                    await asyncio.sleep(2)
                    continue

                async with aiohttp.ClientSession(timeout=self.ws_timeout) as session:
                    async with session.ws_connect(self.cfg.ws_rpc_url, heartbeat=20) as ws:
                        self.stats["ws_connected"] = True
                        self.storage.set_state("ws_last_reconnect_time", str(int(time.time())))
                        self.ws_reconnect_event.clear()

                        sub_filters: List[Dict[str, Any]] = []
                        vaddr = self.cfg.virtual_token_addr
                        for launch in launch_configs:
                            internal = topic_address(launch.internal_pool_addr)
                            fee = topic_address(launch.fee_addr)
                            tax = topic_address(launch.tax_addr)
                            token_addr = launch.token_addr
                            sub_filters.append(
                                {
                                    "address": vaddr,
                                    "topics": [TRANSFER_TOPIC0, None, [internal, fee, tax]],
                                }
                            )
                            sub_filters.append(
                                {
                                    "address": vaddr,
                                    "topics": [TRANSFER_TOPIC0, internal],
                                }
                            )
                            if token_addr:
                                sub_filters.append(
                                    {
                                        "address": token_addr,
                                        "topics": [TRANSFER_TOPIC0, internal],
                                    }
                                )
                                sub_filters.append(
                                    {
                                        "address": token_addr,
                                        "topics": [TRANSFER_TOPIC0, None, internal],
                                    }
                                )

                        for idx, f in enumerate(sub_filters, start=1):
                            await ws.send_json(
                                {
                                    "jsonrpc": "2.0",
                                    "id": idx,
                                    "method": "eth_subscribe",
                                    "params": ["logs", f],
                                }
                            )

                        while not self.stop_event.is_set():
                            if self.ws_reconnect_event.is_set():
                                break
                            if self.refresh_runtime_pause_state():
                                self.stats["ws_connected"] = False
                                break
                            try:
                                msg = await ws.receive(timeout=5)
                            except asyncio.TimeoutError:
                                continue

                            if msg.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                break
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            data = msg.json(loads=json.loads)
                            result = data.get("params", {}).get("result")
                            if not result:
                                continue
                            tx_hash = result.get("transactionHash")
                            block_number = parse_hex_int(result.get("blockNumber"))
                            if not tx_hash:
                                continue
                            if block_number > 0:
                                self.stats["last_ws_block"] = max(self.stats["last_ws_block"], block_number)
                            await self.enqueue_tx(tx_hash, block_number)
            except Exception:
                self.stats["ws_connected"] = False
                await asyncio.sleep(2)

    async def fetch_backfill_txhashes(
        self,
        from_block: int,
        to_block: int,
        launch_configs: List[LaunchConfig],
        rpc: Optional[RPCClient] = None,
    ) -> Set[str]:
        last_exc: Optional[Exception] = None
        for rpc_client in await self.ordered_backfill_rpc_candidates(
            require_logs=True,
            preferred=rpc,
        ):
            try:
                return await self._fetch_backfill_txhashes_via_logs(
                    from_block,
                    to_block,
                    launch_configs,
                    rpc=rpc_client,
                )
            except Exception as exc:
                self.mark_backfill_rpc_failure(rpc_client, exc, operation="logs")
                last_exc = exc
                if not (
                    is_rpc_ru_exceeded_error(exc)
                    or is_rpc_log_history_unavailable_error(exc)
                    or is_rpc_transient_error(exc)
                ):
                    raise

        for rpc_client in await self.ordered_backfill_rpc_candidates(
            require_logs=False,
            preferred=rpc,
        ):
            try:
                return await self._fetch_backfill_txhashes_via_block_scan(
                    from_block,
                    to_block,
                    launch_configs,
                    rpc=rpc_client,
                )
            except Exception as exc:
                self.mark_backfill_rpc_failure(rpc_client, exc, operation="historical_block")
                last_exc = exc
                if not (
                    is_rpc_ru_exceeded_error(exc)
                    or is_rpc_log_history_unavailable_error(exc)
                    or is_rpc_transient_error(exc)
                ):
                    raise

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("no available backfill RPC endpoints")

    async def _fetch_backfill_txhashes_via_logs(
        self,
        from_block: int,
        to_block: int,
        launch_configs: List[LaunchConfig],
        rpc: Optional[RPCClient] = None,
    ) -> Set[str]:
        txs: Set[str] = set()
        rpc_client = rpc or self.http_rpc
        vaddr = self.cfg.virtual_token_addr
        for launch in launch_configs:
            internal = topic_address(launch.internal_pool_addr)
            fee = topic_address(launch.fee_addr)
            tax = topic_address(launch.tax_addr)
            token_addr = launch.token_addr

            self.record_backfill_rpc_usage(rpc_client, operation="logs")
            logs = await rpc_client.get_logs(
                from_block=from_block,
                to_block=to_block,
                address=vaddr,
                topics=[TRANSFER_TOPIC0, None, [internal, fee, tax]],
            )
            txs.update(x["transactionHash"].lower() for x in logs if x.get("transactionHash"))

            self.record_backfill_rpc_usage(rpc_client, operation="logs")
            logs = await rpc_client.get_logs(
                from_block=from_block,
                to_block=to_block,
                address=vaddr,
                topics=[TRANSFER_TOPIC0, internal],
            )
            txs.update(x["transactionHash"].lower() for x in logs if x.get("transactionHash"))

            if token_addr:
                self.record_backfill_rpc_usage(rpc_client, operation="logs")
                logs = await rpc_client.get_logs(
                    from_block=from_block,
                    to_block=to_block,
                    address=token_addr,
                    topics=[TRANSFER_TOPIC0, internal],
                )
                txs.update(x["transactionHash"].lower() for x in logs if x.get("transactionHash"))

                self.record_backfill_rpc_usage(rpc_client, operation="logs")
                logs = await rpc_client.get_logs(
                    from_block=from_block,
                    to_block=to_block,
                    address=token_addr,
                    topics=[TRANSFER_TOPIC0, None, internal],
                )
                txs.update(x["transactionHash"].lower() for x in logs if x.get("transactionHash"))
        return txs

    async def _fetch_backfill_txhashes_via_block_scan(
        self,
        from_block: int,
        to_block: int,
        launch_configs: List[LaunchConfig],
        rpc: Optional[RPCClient] = None,
    ) -> Set[str]:
        txs: Set[str] = set()
        rpc_client = rpc or self.http_rpc
        for block_number in range(max(0, from_block), max(0, to_block) + 1):
            self.record_backfill_rpc_usage(rpc_client, operation="historical_block")
            block = await rpc_client.get_block_by_number(block_number)
            if not isinstance(block, dict):
                continue
            tx_hashes = block.get("transactions") or []
            for tx_ref in tx_hashes:
                if isinstance(tx_ref, dict):
                    tx_hash = str(tx_ref.get("hash") or "").strip().lower()
                else:
                    tx_hash = str(tx_ref or "").strip().lower()
                if not tx_hash or tx_hash in txs:
                    continue
                self.record_backfill_rpc_usage(rpc_client, operation="basic")
                receipt = await rpc_client.get_receipt(tx_hash)
                if not receipt:
                    continue
                if receipt.get("status") and int(receipt["status"], 16) == 0:
                    continue
                logs = receipt.get("logs", [])
                for launch in launch_configs:
                    if self.is_related_to_launch(logs, launch):
                        txs.add(tx_hash)
                        break
        return txs

    async def find_block_gte_timestamp(
        self, target_ts: int, rpc: Optional[RPCClient] = None
    ) -> int:
        rpc_client = rpc or self.http_rpc
        self.record_backfill_rpc_usage(rpc_client, operation="basic")
        latest = await rpc_client.get_latest_block_number()
        latest_ts = await self.get_block_timestamp(latest, rpc=rpc_client)
        if target_ts >= latest_ts:
            return latest

        low = 0
        high = latest
        while low < high:
            mid = (low + high) // 2
            mid_ts = await self.get_block_timestamp(mid, rpc=rpc_client)
            if mid_ts < target_ts:
                low = mid + 1
            else:
                high = mid
        return low

    async def find_block_lte_timestamp(
        self, target_ts: int, rpc: Optional[RPCClient] = None
    ) -> int:
        rpc_client = rpc or self.http_rpc
        self.record_backfill_rpc_usage(rpc_client, operation="basic")
        latest = await rpc_client.get_latest_block_number()
        first_ts = await self.get_block_timestamp(0, rpc=rpc_client)
        if target_ts <= first_ts:
            return 0
        latest_ts = await self.get_block_timestamp(latest, rpc=rpc_client)
        if target_ts >= latest_ts:
            return latest

        low = 0
        high = latest
        while low < high:
            mid = (low + high + 1) // 2
            mid_ts = await self.get_block_timestamp(mid, rpc=rpc_client)
            if mid_ts <= target_ts:
                low = mid
            else:
                high = mid - 1
        return low

    async def run_scan_range_job(
        self,
        job_id: str,
        project: Optional[str],
        start_ts: int,
        end_ts: int,
    ) -> None:
        job = self.scan_jobs[job_id]
        async with self.scan_lock:
            try:
                if job.get("cancelRequested") or job.get("status") == "canceled":
                    job["status"] = "canceled"
                    job["finishedAt"] = int(time.time())
                    job["error"] = "canceled by user"
                    return

                job["status"] = "running"
                job["startedAt"] = int(time.time())
                if not await self.wait_until_resumed():
                    return

                if project:
                    selected = self.storage.get_launch_config_by_name(project)
                    if not selected:
                        selected = self.build_launch_config_from_managed_project(
                            self._find_managed_project_by_name(project)
                        )
                    launch_configs = [selected] if selected else []
                else:
                    launch_configs = self.get_launch_configs()
                if not launch_configs:
                    raise ValueError("no enabled launch configs to scan; please enable a project first")

                scan_rpc, from_block, to_block = await self.resolve_backfill_block_range(
                    start_ts,
                    end_ts,
                )

                chunk = max(1, self.cfg.backfill_chunk_blocks)
                total_blocks = to_block - from_block + 1
                total_chunks = (total_blocks + chunk - 1) // chunk

                job["fromBlock"] = from_block
                job["toBlock"] = to_block
                job["totalChunks"] = total_chunks
                job["processedChunks"] = 0
                job["scannedTx"] = 0
                job["skippedTx"] = 0
                job["processedTx"] = 0
                parsed_before = int(self.stats.get("parsed_events", 0))
                inserted_before = self.storage.count_events(project=project)
                canceled = False

                current = from_block
                while current <= to_block and not self.stop_event.is_set():
                    if not await self.wait_until_resumed():
                        break
                    if job.get("cancelRequested"):
                        canceled = True
                        break
                    end_block = min(to_block, current + chunk - 1)
                    txs = await self.fetch_backfill_txhashes(
                        current, end_block, launch_configs, rpc=scan_rpc
                    )
                    tx_list = sorted(list(txs))
                    job["scannedTx"] = int(job.get("scannedTx", 0)) + len(tx_list)
                    todo_list = tx_list
                    if project and tx_list:
                        known = self.storage.get_known_backfill_txs(project, tx_list)
                        if known:
                            job["skippedTx"] = int(job.get("skippedTx", 0)) + len(known)
                            todo_list = [x for x in tx_list if x not in known]

                    for tx_hash in todo_list:
                        if not await self.wait_until_resumed():
                            break
                        if job.get("cancelRequested"):
                            canceled = True
                            break
                        await self.process_tx(
                            tx_hash,
                            end_block,
                            launch_configs=launch_configs,
                            rpc=scan_rpc,
                        )
                        job["processedTx"] = int(job.get("processedTx", 0)) + 1
                    if canceled:
                        break
                    if project and todo_list:
                        self.storage.mark_backfill_scanned_txs(project, todo_list)
                    await self.flush_once(force=True)

                    job["processedChunks"] = int(job.get("processedChunks", 0)) + 1
                    job["currentBlock"] = end_block
                    current = end_block + 1

                parsed_after = int(self.stats.get("parsed_events", 0))
                inserted_after = self.storage.count_events(project=project)
                if (not canceled) and project:
                    managed_row = self._find_managed_project_by_name(project)
                    if managed_row:
                        self._set_managed_project_scan_cursor(managed_row, end_ts)
                job["parsedDelta"] = max(0, parsed_after - parsed_before)
                job["insertedDelta"] = max(0, inserted_after - inserted_before)
                if canceled:
                    job["status"] = "canceled"
                    job["error"] = "canceled by user"
                    job["canceledAt"] = int(time.time())
                else:
                    job["status"] = "done"
                job["finishedAt"] = int(time.time())
            except Exception as e:
                job["status"] = "failed"
                job["error"] = str(e)
                job["finishedAt"] = int(time.time())

    async def run_scan_range_job_bus(self, job: Dict[str, Any]) -> None:
        job_id = str(job["id"])
        project = str(job["project"]).strip() if job.get("project") else None
        start_ts = int(job.get("startTs", 0))
        end_ts = int(job.get("endTs", 0))

        async with self.scan_lock:
            try:
                if not await self.wait_until_resumed():
                    return
                if project:
                    selected = self.storage.get_launch_config_by_name(project)
                    if not selected:
                        selected = self.build_launch_config_from_managed_project(
                            self._find_managed_project_by_name(project)
                        )
                    launch_configs = [selected] if selected else []
                else:
                    launch_configs = self.get_launch_configs()
                if not launch_configs:
                    raise ValueError("no enabled launch configs to scan")

                scan_rpc, from_block, to_block = await self.resolve_backfill_block_range(
                    start_ts,
                    end_ts,
                )

                chunk = max(1, self.cfg.backfill_chunk_blocks)
                total_blocks = to_block - from_block + 1
                total_chunks = (total_blocks + chunk - 1) // chunk
                self.event_bus.update_scan_job(
                    job_id,
                    from_block=from_block,
                    to_block=to_block,
                    total_chunks=total_chunks,
                    processed_chunks=0,
                    scanned_tx=0,
                    skipped_tx=0,
                    processed_tx=0,
                    parsed_delta=0,
                    inserted_delta=0,
                    current_block=from_block,
                )

                parsed_before = int(self.stats.get("parsed_events", 0))
                inserted_before = self.storage.count_events(project=project)
                canceled = False
                processed_chunks = 0
                scanned_tx = 0
                skipped_tx = 0
                processed_tx = 0

                current = from_block
                while current <= to_block and not self.stop_event.is_set():
                    if not await self.wait_until_resumed():
                        break
                    if self.event_bus.is_scan_job_cancel_requested(job_id):
                        canceled = True
                        break
                    end_block = min(to_block, current + chunk - 1)
                    txs = await self.fetch_backfill_txhashes(
                        current, end_block, launch_configs, rpc=scan_rpc
                    )
                    tx_list = sorted(list(txs))
                    scanned_tx += len(tx_list)
                    todo_list = tx_list
                    if project and tx_list:
                        known = self.storage.get_known_backfill_txs(project, tx_list)
                        if known:
                            skipped_tx += len(known)
                            todo_list = [x for x in tx_list if x not in known]

                    for tx_hash in todo_list:
                        if not await self.wait_until_resumed():
                            break
                        if self.event_bus.is_scan_job_cancel_requested(job_id):
                            canceled = True
                            break
                        await self.process_tx(
                            tx_hash,
                            end_block,
                            launch_configs=launch_configs,
                            rpc=scan_rpc,
                        )
                        processed_tx += 1
                    if canceled:
                        break
                    if project and todo_list:
                        self.storage.mark_backfill_scanned_txs(project, todo_list)

                    processed_chunks += 1
                    current = end_block + 1
                    self.event_bus.update_scan_job(
                        job_id,
                        processed_chunks=processed_chunks,
                        current_block=end_block,
                        scanned_tx=scanned_tx,
                        skipped_tx=skipped_tx,
                        processed_tx=processed_tx,
                    )

                parsed_after = int(self.stats.get("parsed_events", 0))
                inserted_after = self.storage.count_events(project=project)
                if (not canceled) and project:
                    managed_row = self._find_managed_project_by_name(project)
                    if managed_row:
                        self._set_managed_project_scan_cursor(managed_row, end_ts)
                done_status = "canceled" if canceled else "done"
                done_error = "canceled by user" if canceled else None
                self.event_bus.update_scan_job(
                    job_id,
                    status=done_status,
                    error=done_error,
                    finished_at=int(time.time()),
                    processed_chunks=processed_chunks,
                    scanned_tx=scanned_tx,
                    skipped_tx=skipped_tx,
                    processed_tx=processed_tx,
                    parsed_delta=max(0, parsed_after - parsed_before),
                    inserted_delta=max(0, inserted_after - inserted_before),
                )
            except Exception as e:
                self.event_bus.update_scan_job(
                    job_id,
                    status="failed",
                    error=str(e),
                    finished_at=int(time.time()),
                )

    async def backfill_loop(self) -> None:
        checkpoint_raw = self.storage.get_state("last_processed_block")
        if checkpoint_raw:
            cursor = int(checkpoint_raw)
        else:
            cursor = None

        while not self.stop_event.is_set():
            try:
                scan_rpc = await self.resolve_backfill_scan_rpc()
                if self.refresh_runtime_pause_state():
                    await asyncio.sleep(1)
                    continue
                if cursor is None:
                    latest = await scan_rpc.get_latest_block_number()
                    cursor = max(0, latest - 20)
                    self.storage.set_state("last_processed_block", str(cursor))
                if self.scan_lock.locked():
                    await asyncio.sleep(1)
                    continue
                latest = await scan_rpc.get_latest_block_number()
                target = max(0, latest - self.cfg.confirmations)
                if cursor >= target:
                    await asyncio.sleep(self.cfg.backfill_interval_sec)
                    continue

                launch_configs = self.get_launch_configs()
                if not launch_configs:
                    await asyncio.sleep(self.cfg.backfill_interval_sec)
                    continue
                to_block = min(target, cursor + self.cfg.backfill_chunk_blocks)
                txs = await self.fetch_backfill_txhashes(
                    cursor + 1, to_block, launch_configs, rpc=scan_rpc
                )
                for tx_hash in txs:
                    await self.enqueue_tx(
                        tx_hash,
                        to_block,
                        rpc_url=scan_rpc.url,
                    )
                cursor = to_block
                self.storage.set_state("last_processed_block", str(cursor))
                self.stats["last_backfill_block"] = cursor
            except Exception:
                await asyncio.sleep(2)

    async def health_handler(self, request: web.Request) -> web.Response:
        runtime_paused = self.refresh_runtime_pause_state(force=True)
        p, _ = await self.price_service.get_price()
        stats = dict(self.stats)
        queue_size = int(self.queue.qsize())
        pending_tx = int(len(self.pending_txs))
        scan_jobs = int(len(self.scan_jobs))

        if self.role == "writer":
            now = int(time.time())
            queue_size = self.event_bus.queue_size()
            scan_jobs = self.event_bus.count_scan_jobs(only_active=True)

            rt_hb = self.event_bus.get_role_heartbeat("realtime")
            if rt_hb and (now - int(rt_hb["updated_at"]) <= 20):
                rp = rt_hb.get("payload", {})
                stats["ws_connected"] = bool(rp.get("ws_connected", False))
                stats["last_ws_block"] = int(rp.get("last_ws_block", 0))
                stats["enqueued_txs"] = int(rp.get("enqueued_txs", 0))
                stats["processed_txs"] = int(rp.get("processed_txs", 0))
                pending_tx = int(rp.get("pending_txs", 0))
            else:
                stats["ws_connected"] = False

            bf_hb = self.event_bus.get_role_heartbeat("backfill")
            if bf_hb and (now - int(bf_hb["updated_at"]) <= 20):
                bp = bf_hb.get("payload", {})
                stats["last_backfill_block"] = int(bp.get("last_backfill_block", 0))
        if runtime_paused:
            stats["ws_connected"] = False
        runtime_data = self.runtime_pause_payload()

        return web.json_response(
            {
                "ok": True,
                "queueSize": queue_size,
                "pendingTx": pending_tx,
                "stats": stats,
                "lastProcessedBlock": self.storage.get_state("last_processed_block"),
                "price": decimal_to_str(p, 18) if p is not None else None,
                "monitoringProjects": [x.name for x in self.get_launch_configs()],
                "scanJobs": scan_jobs,
                "backfillRpcMode": "pool" if len(self.backfill_http_rpcs) > 1 else ("separate" if self.backfill_rpc_separate else "shared"),
                "backfillRpcPool": self.backfill_rpc_pool_payload(),
                "backfillRpcUsage": self.backfill_rpc_usage_summary_payload(),
                "role": self.role,
                "runtimePaused": runtime_data["runtimePaused"],
                "runtimeManualPaused": runtime_data["runtimeManualPaused"],
                "runtimeUiOnline": runtime_data["runtimeUiOnline"],
                "runtimeUiLastSeenAt": runtime_data["runtimeUiLastSeenAt"],
                "runtimeUiHeartbeatTimeoutSec": runtime_data["runtimeUiHeartbeatTimeoutSec"],
                "runtimePauseUpdatedAt": runtime_data["updatedAt"],
            }
        )

    async def scan_range_handler(self, request: web.Request) -> web.Response:
        if self.refresh_runtime_pause_state():
            return web.json_response({"error": "runtime is paused"}, status=409)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        try:
            start_ts = int(payload.get("start_ts"))
            end_ts = int(payload.get("end_ts"))
        except Exception:
            return web.json_response({"error": "start_ts/end_ts must be integer unix seconds"}, status=400)

        if start_ts <= 0 or end_ts <= 0 or end_ts < start_ts:
            return web.json_response({"error": "invalid time range"}, status=400)

        project = payload.get("project")
        if project is not None:
            project = str(project).strip() or None

        if self.role == "writer":
            job_id = self.event_bus.create_scan_job(project, start_ts, end_ts)
            return web.json_response({"ok": True, "jobId": job_id})

        job_id = uuid.uuid4().hex[:12]
        self.scan_jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "project": project,
            "startTs": start_ts,
            "endTs": end_ts,
            "createdAt": int(time.time()),
            "cancelRequested": False,
        }
        asyncio.create_task(self.run_scan_range_job(job_id, project, start_ts, end_ts))
        return web.json_response({"ok": True, "jobId": job_id})

    async def scan_job_detail_handler(self, request: web.Request) -> web.Response:
        job_id = str(request.match_info.get("job_id", "")).strip()
        if self.role == "writer":
            job = self.event_bus.get_scan_job(job_id)
            if not job:
                return web.json_response({"error": "job not found"}, status=404)
            return web.json_response(job)

        job = self.scan_jobs.get(job_id)
        if not job:
            return web.json_response({"error": "job not found"}, status=404)
        return web.json_response(job)

    async def scan_job_cancel_handler(self, request: web.Request) -> web.Response:
        job_id = str(request.match_info.get("job_id", "")).strip()
        if self.role == "writer":
            job = self.event_bus.request_scan_job_cancel(job_id)
            if not job:
                return web.json_response({"error": "job not found"}, status=404)
            final = str(job.get("status") or "") in {"done", "failed", "canceled"}
            return web.json_response({"ok": True, "alreadyFinal": final, "job": job})

        job = self.scan_jobs.get(job_id)
        if not job:
            return web.json_response({"error": "job not found"}, status=404)

        status = str(job.get("status") or "")
        if status in {"done", "failed", "canceled"}:
            return web.json_response({"ok": True, "alreadyFinal": True, "job": job})

        job["cancelRequested"] = True
        job["cancelRequestedAt"] = int(time.time())
        if status == "queued":
            job["status"] = "canceled"
            job["error"] = "canceled by user"
            job["canceledAt"] = int(time.time())
            job["finishedAt"] = int(time.time())
        return web.json_response({"ok": True, "job": job})

    async def launch_configs_handler(self, request: web.Request) -> web.Response:
        rows = self.storage.list_launch_configs()
        return web.json_response({"count": len(rows), "items": rows})

    async def managed_projects_handler(self, request: web.Request) -> web.Response:
        rows = self.storage.list_managed_projects()
        return web.json_response({"count": len(rows), "items": rows})

    def upsert_managed_project_from_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_id = parse_optional_int(payload.get("id"), "id")
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("name cannot be empty")
        start_at = parse_optional_int(payload.get("start_at"), "start_at")
        if start_at is None or start_at <= 0:
            raise ValueError("start_at is required")
        signalhub_end_at = parse_optional_int(payload.get("signalhub_end_at"), "signalhub_end_at")
        manual_end_at = parse_optional_int(payload.get("manual_end_at"), "manual_end_at")
        row = self.storage.upsert_managed_project(
            project_id=project_id,
            name=name,
            signalhub_project_id=str(payload.get("signalhub_project_id", "")).strip() or None,
            detail_url=str(payload.get("detail_url", "")).strip(),
            token_addr=normalize_optional_address(payload.get("token_addr")),
            internal_pool_addr=normalize_optional_address(payload.get("internal_pool_addr")),
            start_at=int(start_at),
            signalhub_end_at=signalhub_end_at,
            manual_end_at=manual_end_at,
            resolved_end_at=resolve_project_end_at(start_at, signalhub_end_at, manual_end_at),
            is_watched=parse_bool_like(payload.get("is_watched", True)),
            collect_enabled=parse_bool_like(payload.get("collect_enabled", True)),
            backfill_enabled=parse_bool_like(payload.get("backfill_enabled", True)),
            status=str(payload.get("status", "draft")).strip().lower() or "draft",
            source=str(payload.get("source", "manual")).strip().lower() or "manual",
        )
        self.reconcile_managed_projects_schedule(force_launch_sync=True)
        return self.storage.get_managed_project(int(row["id"])) or row

    def remove_managed_project_by_id(self, project_id: int) -> None:
        existing = self.storage.get_managed_project(project_id)
        if not existing:
            raise ValueError(f"managed project not found: {project_id}")
        deleted = self.storage.delete_managed_project(project_id)
        if not deleted:
            raise ValueError(f"managed project not found: {project_id}")
        self.storage.delete_launch_config(str(existing.get("name") or "").strip())
        self.sync_runtime_after_managed_project_change()
        self.storage.set_state("managed_project_scheduler_last_run_at", str(int(time.time())))

    async def managed_project_detail_handler(self, request: web.Request) -> web.Response:
        raw_project_id = str(request.match_info.get("project_id", "")).strip()
        if not raw_project_id:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(raw_project_id)
            row = self.storage.get_managed_project(project_id)
            if not row:
                return web.json_response({"error": f"managed project not found: {project_id}"}, status=404)
            return web.json_response({"ok": True, "item": row})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def project_scheduler_status_handler(self, request: web.Request) -> web.Response:
        return web.json_response(self.build_project_scheduler_status())

    async def overview_active_handler(self, request: web.Request) -> web.Response:
        requested_project = str(request.query.get("project", "")).strip() or None
        try:
            return web.json_response(await self.build_overview_active_payload(requested_project))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def admin_project_overview_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        raw_project_id = str(request.match_info.get("project_id", "")).strip()
        if not raw_project_id:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(raw_project_id)
        except ValueError:
            return web.json_response({"error": "project_id must be integer"}, status=400)
        try:
            project_row = self.storage.get_managed_project(project_id)
            if not project_row:
                return web.json_response({"error": f"managed project not found: {project_id}"}, status=404)
            payload = await self.build_project_overview_payload(
                project_row,
                requested_project=str(project_row.get("name") or ""),
                tracked_wallet_configs=self.storage.list_monitored_wallet_rows(),
                view_mode="project",
            )
            return web.json_response(payload)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def auth_me_handler(self, request: web.Request) -> web.Response:
        user = self.get_request_user(request)
        if not user:
            return web.json_response({"authenticated": False})
        return web.json_response(
            {
                "authenticated": True,
                "user": self.auth_public_user(user),
                "home_path": self.user_home_path(user),
            }
        )

    async def auth_register_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        client_ip = self.request_client_ip(request)
        try:
            nickname = require_nonempty_text(payload.get("nickname"), "nickname")
            email = normalize_email(payload.get("email"))
            password = require_nonempty_text(payload.get("password"), "password")
            self.ensure_register_ip_allowed(client_ip)
            self.record_auth_attempt("register_ip", client_ip)
            self.ensure_allowed_registration_email(email)
            if self.storage.get_user_by_email(email):
                return web.json_response({"error": "email already registered"}, status=409)
            raw_token = secrets.token_urlsafe(32)
            pending = self.storage.upsert_pending_registration(
                nickname=nickname,
                email=email,
                password_hash=hash_password(password),
                verify_token_hash=hash_session_token(raw_token, self.session_secret),
                request_ip=client_ip,
                user_agent=str(request.headers.get("User-Agent") or ""),
                device_fingerprint=self.request_device_fingerprint(request, payload),
                expires_at=self.email_verification_expires_at(),
            )
            self.send_email_verification_email(
                request=request,
                email=email,
                nickname=nickname,
                token=raw_token,
            )
            return web.json_response(
                {
                    "ok": True,
                    "requires_verification": True,
                    "email": email,
                    "expires_at": int(pending.get("expires_at") or 0),
                }
            )
        except RateLimitExceeded as e:
            return web.json_response(
                {"error": e.message, "code": e.code, "retry_after_sec": e.retry_after_sec},
                status=429,
            )
        except DisposableEmailBlocked as e:
            return web.json_response(
                {"error": e.message, "code": "disposable_email_blocked"},
                status=400,
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def auth_resend_verification_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        client_ip = self.request_client_ip(request)
        try:
            email = normalize_email(payload.get("email"))
            self.ensure_resend_ip_allowed(client_ip)
            if self.storage.get_user_by_email(email):
                return web.json_response({"error": "email already verified"}, status=409)
            pending = self.storage.get_pending_registration_by_email(email)
            if not pending:
                return web.json_response({"error": "pending registration not found"}, status=404)
            if str(pending.get("status") or "").strip().lower() == "blocked":
                return web.json_response({"error": "registration is blocked"}, status=403)
            raw_token = secrets.token_urlsafe(32)
            pending = self.storage.upsert_pending_registration(
                nickname=str(pending.get("nickname") or "").strip() or "新用户",
                email=email,
                password_hash=str(pending.get("password_hash") or ""),
                verify_token_hash=hash_session_token(raw_token, self.session_secret),
                request_ip=client_ip or str(pending.get("request_ip") or ""),
                user_agent=str(request.headers.get("User-Agent") or pending.get("user_agent") or ""),
                device_fingerprint=self.request_device_fingerprint(request, payload)
                or str(pending.get("device_fingerprint") or ""),
                risk_level=str(pending.get("risk_level") or "normal"),
                expires_at=self.email_verification_expires_at(),
            )
            self.send_email_verification_email(
                request=request,
                email=email,
                nickname=str(pending.get("nickname") or ""),
                token=raw_token,
            )
            self.record_auth_attempt("resend_ip", client_ip)
            return web.json_response(
                {
                    "ok": True,
                    "email": email,
                    "expires_at": int(pending.get("expires_at") or 0),
                }
            )
        except RateLimitExceeded as e:
            return web.json_response(
                {"error": e.message, "code": e.code, "retry_after_sec": e.retry_after_sec},
                status=429,
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def auth_verify_email_handler(self, request: web.Request) -> web.Response:
        token = str(request.query.get("token", "")).strip()
        if not token:
            return web.json_response({"error": "token is required"}, status=400)
        try:
            token_hash = hash_session_token(token, self.session_secret)
            pending = self.storage.get_pending_registration_by_token_hash(token_hash)
            if not pending:
                return web.json_response({"error": "verification link is invalid or expired"}, status=400)
            pending_status = str(pending.get("status") or "").strip().lower()
            if pending_status == "blocked":
                return web.json_response({"error": "registration is blocked"}, status=403)
            if pending_status == "expired":
                return web.json_response({"error": "verification link is invalid or expired"}, status=400)
            if pending_status not in {"pending", "verified"}:
                return web.json_response({"error": "verification link is invalid"}, status=400)

            email = normalize_email(pending.get("email"))
            existing_user = self.storage.get_user_by_email(email)
            if existing_user:
                if pending_status != "verified":
                    self.storage.update_pending_registration_status(
                        int(pending["id"]),
                        status="verified",
                        verified_at=int(time.time()),
                    )
                return self.build_auth_success_response(existing_user, request)

            now = int(time.time())
            user = self.storage.create_user(
                nickname=str(pending.get("nickname") or "").strip() or "新用户",
                email=email,
                password_hash=str(pending.get("password_hash") or ""),
                role="user",
                status="active",
                signup_bonus_credits=DEFAULT_SIGNUP_BONUS_CREDITS,
                email_verified_at=now,
                signup_ip=str(pending.get("request_ip") or ""),
                signup_device_fingerprint=str(pending.get("device_fingerprint") or ""),
                signup_bonus_granted_at=now,
            )
            self.storage.update_pending_registration_status(
                int(pending["id"]),
                status="verified",
                verified_at=now,
            )
            return self.build_auth_success_response(user, request)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def auth_login_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        client_ip = self.request_client_ip(request)
        try:
            email = normalize_email(payload.get("email"))
            password = require_nonempty_text(payload.get("password"), "password")
            self.ensure_login_fail_ip_allowed(client_ip)
            user = self.storage.get_user_by_email(email)
            if user:
                if not verify_password(password, str(user.get("password_hash") or "")):
                    self.record_auth_attempt("login_fail_ip", client_ip)
                    return web.json_response({"error": "invalid email or password"}, status=401)
                if not int(user.get("email_verified_at") or 0):
                    return web.json_response(
                        {
                            "error": "email is not verified",
                            "code": "email_not_verified",
                            "email": email,
                            "can_resend": True,
                        },
                        status=403,
                    )
            else:
                pending = self.storage.get_pending_registration_by_email(email)
                if pending and verify_password(password, str(pending.get("password_hash") or "")):
                    return web.json_response(
                        {
                            "error": "email is not verified",
                            "code": "email_not_verified",
                            "email": email,
                            "can_resend": True,
                            "expired": str(pending.get("status") or "").strip().lower() == "expired",
                        },
                        status=403,
                    )
                self.record_auth_attempt("login_fail_ip", client_ip)
                return web.json_response({"error": "invalid email or password"}, status=401)
            if str(user.get("status") or "").lower() != "active":
                return web.json_response({"error": "user is disabled"}, status=403)
            return self.build_auth_success_response(user, request)
        except RateLimitExceeded as e:
            return web.json_response(
                {"error": e.message, "code": e.code, "retry_after_sec": e.retry_after_sec},
                status=429,
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def auth_logout_handler(self, request: web.Request) -> web.Response:
        cookie_token = str(request.cookies.get(self.session_cookie_name) or "").strip()
        if cookie_token:
            self.storage.revoke_session(hash_session_token(cookie_token, self.session_secret))
        response = web.json_response({"ok": True})
        self.clear_session_cookie(response)
        return response

    async def app_meta_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        return web.json_response(self.build_user_meta_payload(user))

    async def app_billing_summary_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        return web.json_response(self.build_billing_summary_payload(user))

    async def app_notifications_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        limit_raw = str(request.query.get("limit", "")).strip()
        limit = 12
        if limit_raw:
            try:
                limit = max(1, min(50, int(limit_raw)))
            except ValueError:
                return web.json_response({"error": "limit must be integer"}, status=400)
        return web.json_response(self.build_user_notifications_payload(user, limit=limit))

    async def app_notification_read_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        notification_id_raw = str(request.match_info.get("notification_id", "")).strip()
        if not notification_id_raw:
            return web.json_response({"error": "notification_id is required"}, status=400)
        try:
            row = self.storage.mark_user_notification_read(int(user["id"]), int(notification_id_raw))
        except ValueError:
            return web.json_response({"error": "notification_id must be integer"}, status=400)
        if not row:
            return web.json_response({"error": f"notification not found: {notification_id_raw}"}, status=404)
        return web.json_response(
            {
                "ok": True,
                "item": self.build_notification_item_payload(row),
                "unreadCount": self.count_visible_user_notifications(int(user["id"]), unread_only=True),
            }
        )

    async def app_notifications_read_all_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        updated = self.storage.mark_all_user_notifications_read(int(user["id"]))
        return web.json_response(
            {
                "ok": True,
                "updated": updated,
                "unreadCount": self.count_visible_user_notifications(int(user["id"]), unread_only=True),
            }
        )

    async def extract_billing_request_submission(
        self, request: web.Request
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        content_type = str(request.content_type or "").lower()
        if content_type.startswith("multipart/"):
            reader = await request.multipart()
            fields: Dict[str, Any] = {}
            proof: Optional[Dict[str, Any]] = None
            async for part in reader:
                if not part.name:
                    continue
                if part.filename:
                    payload = await part.read(decode=False)
                    proof = {
                        "filename": str(part.filename or ""),
                        "content_type": str(part.headers.get("Content-Type") or part.content_type or ""),
                        "payload": payload,
                    }
                else:
                    fields[part.name] = await part.text()
            return fields, proof
        if content_type.startswith("application/json"):
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("invalid json body")
            return payload, None
        raise ValueError("content type must be multipart/form-data or application/json")

    async def app_billing_requests_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        limit_raw = str(request.query.get("limit", "")).strip()
        limit = 50
        if limit_raw:
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                return web.json_response({"error": "limit must be integer"}, status=400)
        items = [
            self.build_billing_request_payload(row, "user")
            for row in self.storage.list_user_billing_requests(int(user["id"]), limit=limit)
        ]
        return web.json_response({"ok": True, "count": len(items), "items": items})

    async def app_billing_request_create_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        try:
            payload, proof = await self.extract_billing_request_submission(request)
            plan_id = str(payload.get("plan_id") or "").strip()
            requested_credits = parse_required_int(payload.get("requested_credits"), "requested_credits")
            if requested_credits <= 0:
                raise ValueError("requested_credits must be positive")
            if plan_id:
                matched_plan = next(
                    (plan for plan in BILLING_PLANS if str(plan.get("id") or "").strip() == plan_id),
                    None,
                )
                if matched_plan and int(matched_plan.get("credits") or 0) != requested_credits:
                    raise ValueError("requested_credits does not match selected plan")
            if not proof:
                raise ValueError("proof file is required")
            stored = self.store_billing_proof_attachment(
                filename=str(proof.get("filename") or ""),
                content_type=str(proof.get("content_type") or ""),
                payload=bytes(proof.get("payload") or b""),
            )
            item = self.storage.create_billing_request(
                user_id=int(user["id"]),
                plan_id=plan_id,
                requested_credits=requested_credits,
                payment_amount=str(payload.get("payment_amount") or "").strip(),
                note=str(payload.get("note") or "").strip(),
                proof_storage_key=stored["storage_key"],
                proof_original_name=stored["original_name"],
                proof_content_type=stored["content_type"],
                proof_size=int(stored["size"]),
            )
            self.storage.create_user_notification(
                user_id=int(user["id"]),
                kind="info",
                title="付款凭证已提交",
                body=f"你的 {requested_credits} 积分充值申请已提交，当前状态为待确认付款。",
                action_url="/app/billing",
                source_type="billing_request_submitted",
                source_id=int(item["id"]),
            )
            created = self.storage.get_billing_request(int(item["id"])) or item
            return web.json_response(
                {
                    "ok": True,
                    "item": self.build_billing_request_payload(created, "user"),
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def app_billing_request_proof_handler(self, request: web.Request) -> web.StreamResponse:
        user = self.require_auth(request)
        request_id_raw = str(request.match_info.get("request_id", "")).strip()
        if not request_id_raw:
            return web.json_response({"error": "request_id is required"}, status=400)
        try:
            row = self.storage.get_billing_request_for_user(int(user["id"]), int(request_id_raw))
        except ValueError:
            return web.json_response({"error": "request_id must be integer"}, status=400)
        if not row:
            return web.json_response({"error": f"billing request not found: {request_id_raw}"}, status=404)
        proof_key = str(row.get("proof_storage_key") or "").strip()
        if not proof_key:
            return web.json_response({"error": "proof not found"}, status=404)
        path = self.resolve_billing_proof_path(proof_key)
        if not path.is_file():
            return web.json_response({"error": "proof file missing"}, status=404)
        response = web.FileResponse(path)
        response.content_type = str(row.get("proof_content_type") or "application/octet-stream")
        response.headers["Content-Disposition"] = (
            f"inline; filename=\"{str(row.get('proof_original_name') or path.name)}\""
        )
        return response

    async def app_project_access_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        project_id_raw = str(request.match_info.get("project_id", "")).strip()
        if not project_id_raw:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(project_id_raw)
        except ValueError:
            return web.json_response({"error": "project_id must be integer"}, status=400)
        project_row = self.storage.get_managed_project(project_id)
        if not project_row or str(project_row.get("status") or "").lower() not in {"scheduled", "prelaunch", "live", "ended"}:
            return web.json_response({"error": f"managed project not found: {project_id}"}, status=404)
        access = self.build_project_access_payload(user, project_row)
        return web.json_response(
            {
                "ok": True,
                "project": {
                    "id": int(project_row.get("id") or 0),
                    "name": str(project_row.get("name") or ""),
                    "status": str(project_row.get("status") or ""),
                    "detailUrl": str(project_row.get("detail_url") or ""),
                    "startAt": int(project_row.get("start_at") or 0),
                    "resolvedEndAt": int(project_row.get("resolved_end_at") or 0),
                },
                "access": access,
            }
        )

    async def app_project_unlock_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        project_id_raw = str(request.match_info.get("project_id", "")).strip()
        if not project_id_raw:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(project_id_raw)
        except ValueError:
            return web.json_response({"error": "project_id must be integer"}, status=400)
        project_row = self.storage.get_managed_project(project_id)
        if not project_row or str(project_row.get("status") or "").lower() not in {"scheduled", "prelaunch", "live", "ended"}:
            return web.json_response({"error": f"managed project not found: {project_id}"}, status=404)
        current_access = self.build_project_access_payload(user, project_row)
        if bool(current_access.get("isUnlocked")):
            return web.json_response(
                {
                    "ok": True,
                    "alreadyUnlocked": True,
                    "credit_balance": int(user.get("credit_balance") or 0),
                    "access": current_access,
                }
            )
        try:
            access_row = self.storage.unlock_user_project_access(int(user["id"]), project_id)
            refreshed_user = self.storage.get_user_by_id(int(user["id"])) or user
            return web.json_response(
                {
                    "ok": True,
                    "alreadyUnlocked": False,
                    "credit_balance": int(refreshed_user.get("credit_balance") or 0),
                    "access": self.build_project_access_payload(refreshed_user, project_row),
                    "item": access_row,
                }
            )
        except Exception as e:
            status = 400
            if "not found" in str(e):
                status = 404
            elif "insufficient credits" in str(e):
                status = 409
            return web.json_response(
                {
                    "error": str(e),
                    "code": "insufficient_credits" if "insufficient credits" in str(e) else "project_unlock_failed",
                    "billing": self.build_billing_summary_payload(user),
                },
                status=status,
            )

    async def app_overview_active_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        requested_project = str(request.query.get("project", "")).strip() or None
        wallet_rows = [
            {
                "wallet": item["wallet"],
                "name": item.get("name") or "",
            }
            for item in self.storage.list_user_wallet_rows(int(user["id"]))
            if bool(item.get("is_enabled"))
        ]
        try:
            payload = await self.build_overview_active_payload(
                requested_project,
                tracked_wallet_configs=wallet_rows,
            )
            active_item = payload.get("item") or {}
            project_id = int(active_item.get("id") or 0)
            if payload.get("hasActiveProject") and project_id > 0:
                project_row = self.storage.get_managed_project(project_id)
                access = self.build_project_access_payload(user, project_row)
                if not bool(access.get("isUnlocked")):
                    return web.json_response(
                        {
                            "error": "project overview is locked",
                            "code": "project_locked",
                            "requestedProject": payload.get("requestedProject") or "",
                            "hasActiveProject": bool(payload.get("hasActiveProject")),
                            "activeProjects": payload.get("activeProjects") or [],
                            "project": active_item,
                            "access": access,
                            "billing": self.build_billing_summary_payload(user),
                        },
                        status=403,
                    )
            return web.json_response(payload)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def app_project_overview_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        project_id_raw = str(request.match_info.get("project_id", "")).strip()
        if not project_id_raw:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(project_id_raw)
        except ValueError:
            return web.json_response({"error": "project_id must be integer"}, status=400)
        project_row = self.storage.get_managed_project(project_id)
        if not project_row or str(project_row.get("status") or "").lower() not in {"scheduled", "prelaunch", "live", "ended"}:
            return web.json_response({"error": f"managed project not found: {project_id}"}, status=404)
        wallet_rows = [
            {
                "wallet": item["wallet"],
                "name": item.get("name") or "",
            }
            for item in self.storage.list_user_wallet_rows(int(user["id"]))
            if bool(item.get("is_enabled"))
        ]
        try:
            payload = await self.build_project_overview_payload(
                project_row,
                requested_project=str(project_row.get("name") or ""),
                tracked_wallet_configs=wallet_rows,
                view_mode="project",
            )
            access = self.build_project_access_payload(user, project_row)
            if not bool(access.get("isUnlocked")):
                return web.json_response(
                    {
                        "error": "project overview is locked",
                        "code": "project_locked",
                        "requestedProject": payload.get("requestedProject") or "",
                        "hasActiveProject": bool(payload.get("hasActiveProject")),
                        "activeProjects": payload.get("activeProjects") or [],
                        "project": payload.get("item"),
                        "access": access,
                        "billing": self.build_billing_summary_payload(user),
                    },
                    status=403,
                )
            return web.json_response(payload)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def app_projects_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        status_filter = str(request.query.get("status", "")).strip().lower()
        keyword = str(request.query.get("q", "")).strip().lower()
        items = self.list_public_managed_projects(user)
        if status_filter:
            items = [item for item in items if str(item.get("status") or "").lower() == status_filter]
        if keyword:
            items = [
                item
                for item in items
                if keyword in str(item.get("name") or "").lower()
                or keyword in str(item.get("detail_url") or "").lower()
            ]
        return web.json_response({"count": len(items), "items": items})

    async def app_signalhub_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        try:
            limit = int(request.query.get("limit", str(self.cfg.signalhub_upcoming_limit)))
            within_hours = int(
                request.query.get("within_hours", str(self.cfg.signalhub_within_hours))
            )
        except ValueError:
            return web.json_response({"error": "limit/within_hours must be integer"}, status=400)
        payload = await self.build_signalhub_upcoming_payload(limit=limit, within_hours=within_hours)
        if not payload.get("items"):
            return web.json_response(payload)
        managed_projects = self.list_public_managed_projects(user)
        by_signalhub_id = {
            str(item.get("signalhub_project_id") or "").strip(): item
            for item in managed_projects
            if str(item.get("signalhub_project_id") or "").strip()
        }
        by_name = {
            str(item.get("name") or "").strip().upper(): item
            for item in managed_projects
            if str(item.get("name") or "").strip()
        }
        enriched_items: List[Dict[str, Any]] = []
        for item in payload.get("items") or []:
            enriched = dict(item)
            managed = by_signalhub_id.get(str(item.get("projectId") or "").strip()) or by_name.get(
                str(item.get("importName") or "").strip().upper()
            )
            access = self.build_project_access_payload(user, managed)
            enriched["managedProjectId"] = int(managed.get("id") or 0) if managed else None
            enriched["managedStatus"] = str(managed.get("status") or "") if managed else ""
            enriched["resolvedEndAt"] = int(managed.get("resolved_end_at") or 0) if managed else None
            enriched["isUnlocked"] = bool(access.get("isUnlocked"))
            enriched["unlockCost"] = int(access.get("unlockCost"))
            enriched["canUnlockNow"] = bool(access.get("canUnlockNow"))
            enriched_items.append(enriched)
        payload["items"] = enriched_items
        return web.json_response(payload)

    async def app_wallets_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        items = self.storage.list_user_wallet_rows(int(user["id"]))
        return web.json_response({"count": len(items), "items": items})

    async def app_wallets_add_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            item = self.storage.add_user_wallet(
                int(user["id"]),
                wallet=require_nonempty_text(payload.get("wallet"), "wallet"),
                name=str(payload.get("name") or "").strip(),
                is_enabled=parse_bool_like(payload.get("is_enabled", True)),
            )
            items = self.storage.list_user_wallet_rows(int(user["id"]))
            return web.json_response({"ok": True, "item": item, "count": len(items), "items": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def app_wallets_update_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        wallet_id_raw = str(request.match_info.get("wallet_id", "")).strip()
        if not wallet_id_raw:
            return web.json_response({"error": "wallet_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            item = self.storage.update_user_wallet(
                int(user["id"]),
                int(wallet_id_raw),
                name=payload.get("name") if "name" in payload else None,
                is_enabled=parse_bool_like(payload.get("is_enabled")) if "is_enabled" in payload else None,
            )
            return web.json_response({"ok": True, "item": item})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def app_wallets_delete_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        wallet_id_raw = str(request.match_info.get("wallet_id", "")).strip()
        if not wallet_id_raw:
            return web.json_response({"error": "wallet_id is required"}, status=400)
        try:
            deleted = self.storage.delete_user_wallet(int(user["id"]), int(wallet_id_raw))
            if not deleted:
                return web.json_response({"error": f"user wallet not found: {wallet_id_raw}"}, status=404)
            items = self.storage.list_user_wallet_rows(int(user["id"]))
            return web.json_response({"ok": True, "count": len(items), "items": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def app_wallet_positions_handler(self, request: web.Request) -> web.Response:
        user = self.require_auth(request)
        project = str(request.query.get("project", "")).strip() or None
        items = self.storage.query_user_wallet_positions(int(user["id"]), project)
        return web.json_response({"count": len(items), "items": items})

    async def admin_meta_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        return await self.meta_handler(request)

    async def admin_users_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        query = str(request.query.get("q", "")).strip().lower()
        status_filter = str(request.query.get("status", "")).strip().lower()
        role_filter = str(request.query.get("role", "")).strip().lower()
        source_filter = str(request.query.get("source", "")).strip().lower()
        items = self.storage.list_users()
        if query:
            items = [
                item
                for item in items
                if query in str(item.get("nickname") or "").lower()
                or query in str(item.get("email") or "").lower()
            ]
        if status_filter:
            items = [item for item in items if str(item.get("status") or "").lower() == status_filter]
        if role_filter:
            items = [item for item in items if str(item.get("role") or "").lower() == role_filter]
        if source_filter:
            items = [item for item in items if str(item.get("source") or "").lower() == source_filter]
        for item in items:
            item.pop("password_hash", None)
        return web.json_response({"count": len(items), "items": items})

    async def admin_user_create_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            nickname = require_nonempty_text(payload.get("nickname"), "nickname")
            email = normalize_email(payload.get("email"))
            password = require_nonempty_text(payload.get("password"), "password")
            initial_credits = parse_optional_int(payload.get("initial_credits"), "initial_credits") or 0
            if initial_credits < 0:
                raise ValueError("initial_credits must not be negative")
            note = str(payload.get("note") or "").strip()
            if self.storage.get_user_by_email(email):
                return web.json_response({"error": "email already registered"}, status=409)
            user = self.storage.create_user(
                nickname=nickname,
                email=email,
                password_hash=hash_password(password),
                role="user",
                status="active",
                source="admin_created",
                email_verified_at=int(time.time()),
            )
            if initial_credits > 0:
                user = self.storage.adjust_user_credits(
                    int(user["id"]),
                    delta=initial_credits,
                    entry_type="manual_adjustment",
                    source="admin.user_create",
                    note=note or "admin created user initial credits",
                    operator_user_id=int(operator["id"]),
                )
            user["wallet_count"] = 0
            user["unlocked_project_count"] = 0
            user["password_set"] = bool(str(user.get("password_hash") or "").strip())
            user.pop("password_hash", None)
            items = self.storage.list_users()
            for item in items:
                item.pop("password_hash", None)
            return web.json_response({"ok": True, "item": user, "count": len(items), "items": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def admin_user_detail_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        row = self.storage.get_user_by_id(int(user_id_raw))
        if not row:
            return web.json_response({"error": f"user not found: {user_id_raw}"}, status=404)
        item = dict(row)
        item["wallet_count"] = len(self.storage.list_user_wallet_rows(int(user_id_raw)))
        item["unlocked_project_count"] = len(
            self.storage.list_user_project_access_rows(int(user_id_raw), limit=1000)
        )
        item["password_set"] = bool(str(item.get("password_hash") or "").strip())
        item.pop("password_hash", None)
        return web.json_response({"ok": True, "item": item})

    async def admin_user_wallets_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        items = self.storage.list_user_wallet_rows(int(user_id_raw))
        return web.json_response({"count": len(items), "items": items})

    async def admin_user_credit_ledger_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        items = self.storage.list_user_credit_ledger_rows(int(user_id_raw))
        return web.json_response({"count": len(items), "items": items})

    async def admin_legacy_apis_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        return web.json_response(self.build_legacy_api_payload())

    async def admin_user_project_access_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        items = self.storage.list_user_project_access_rows(int(user_id_raw))
        return web.json_response({"count": len(items), "items": items})

    async def admin_user_credit_adjust_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            delta = parse_required_int(payload.get("delta"), "delta")
            if delta == 0:
                raise ValueError("delta must not be 0")
            note = require_nonempty_text(payload.get("note"), "note")
            item = self.storage.adjust_user_credits(
                int(user_id_raw),
                delta=delta,
                entry_type="manual_adjustment",
                source="admin.credit_adjust",
                note=note,
                operator_user_id=int(operator["id"]),
            )
            item["password_set"] = bool(str(item.get("password_hash") or "").strip())
            item.pop("password_hash", None)
            return web.json_response({"ok": True, "item": item})
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_user_credit_topup_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            credits = parse_required_int(payload.get("credits"), "credits")
            if credits <= 0:
                raise ValueError("credits must be positive")
            amount_paid = str(payload.get("amount_paid") or "").strip()
            payment_proof_ref = str(payload.get("payment_proof_ref") or "").strip()
            note = str(payload.get("note") or "").strip()
            item = self.storage.adjust_user_credits(
                int(user_id_raw),
                delta=credits,
                entry_type="manual_topup",
                source="admin.credit_topup",
                payment_amount=amount_paid,
                payment_proof_ref=payment_proof_ref,
                note=note or "manual topup",
                operator_user_id=int(operator["id"]),
            )
            item["password_set"] = bool(str(item.get("password_hash") or "").strip())
            item.pop("password_hash", None)
            return web.json_response({"ok": True, "item": item})
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_billing_requests_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        status_filter = str(request.query.get("status", "")).strip().lower()
        keyword = str(request.query.get("q", "")).strip().lower()
        limit_raw = str(request.query.get("limit", "")).strip()
        limit = 200
        if limit_raw:
            try:
                limit = max(1, min(500, int(limit_raw)))
            except ValueError:
                return web.json_response({"error": "limit must be integer"}, status=400)
        try:
            items = [
                self.build_billing_request_payload(row, "admin")
                for row in self.storage.list_billing_requests(
                    status=status_filter,
                    query=keyword,
                    limit=limit,
                )
            ]
            return web.json_response({"ok": True, "count": len(items), "items": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def admin_billing_request_proof_handler(self, request: web.Request) -> web.StreamResponse:
        self.require_admin(request)
        request_id_raw = str(request.match_info.get("request_id", "")).strip()
        if not request_id_raw:
            return web.json_response({"error": "request_id is required"}, status=400)
        try:
            row = self.storage.get_billing_request(int(request_id_raw))
        except ValueError:
            return web.json_response({"error": "request_id must be integer"}, status=400)
        if not row:
            return web.json_response({"error": f"billing request not found: {request_id_raw}"}, status=404)
        proof_key = str(row.get("proof_storage_key") or "").strip()
        if not proof_key:
            return web.json_response({"error": "proof not found"}, status=404)
        path = self.resolve_billing_proof_path(proof_key)
        if not path.is_file():
            return web.json_response({"error": "proof file missing"}, status=404)
        response = web.FileResponse(path)
        response.content_type = str(row.get("proof_content_type") or "application/octet-stream")
        response.headers["Content-Disposition"] = (
            f"inline; filename=\"{str(row.get('proof_original_name') or path.name)}\""
        )
        return response

    async def admin_billing_request_credit_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        request_id_raw = str(request.match_info.get("request_id", "")).strip()
        if not request_id_raw:
            return web.json_response({"error": "request_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            credits = parse_optional_int(payload.get("credits"), "credits")
            amount_paid = str(payload.get("amount_paid") or "").strip() or None
            admin_note = str(payload.get("admin_note") or "").strip()
            item = self.storage.credit_billing_request(
                int(request_id_raw),
                operator_user_id=int(operator["id"]),
                credits=credits,
                amount_paid=amount_paid,
                admin_note=admin_note,
            )
            return web.json_response({"ok": True, "item": self.build_billing_request_payload(item, "admin")})
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_billing_request_notify_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        request_id_raw = str(request.match_info.get("request_id", "")).strip()
        if not request_id_raw:
            return web.json_response({"error": "request_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        try:
            item = self.storage.mark_billing_request_notified(
                int(request_id_raw),
                operator_user_id=int(operator["id"]),
                admin_note=str(payload.get("admin_note") or "").strip(),
            )
            return web.json_response({"ok": True, "item": self.build_billing_request_payload(item, "admin")})
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_user_status_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            item = self.storage.update_user_status(int(user_id_raw), str(payload.get("status") or ""))
            if str(item.get("status") or "").lower() != "active":
                self.storage.revoke_user_sessions(int(user_id_raw))
            item["password_set"] = bool(str(item.get("password_hash") or "").strip())
            item.pop("password_hash", None)
            return web.json_response({"ok": True, "item": item})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def admin_users_batch_status_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            user_ids = self.parse_user_ids_payload(payload)
            status_value = str(payload.get("status") or "").strip().lower()
            if status_value not in {"disabled", "archived"}:
                raise ValueError("status must be disabled or archived")
            rows = self.ensure_admin_user_ids_mutable(
                operator_user_id=int(operator["id"]),
                user_ids=user_ids,
                allow_admin_targets=False,
            )
            updated_items = self.storage.update_users_status([int(row["id"]) for row in rows], status_value)
            for row in updated_items:
                self.storage.revoke_user_sessions(int(row["id"]))
            items = self.storage.list_users()
            for item in items:
                item.pop("password_hash", None)
            return web.json_response(
                {
                    "ok": True,
                    "updatedCount": len(updated_items),
                    "updatedUserIds": [int(row["id"]) for row in updated_items],
                    "count": len(items),
                    "items": items,
                }
            )
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_users_batch_delete_handler(self, request: web.Request) -> web.Response:
        operator = self.require_admin(request)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            user_ids = self.parse_user_ids_payload(payload)
            rows = self.ensure_admin_user_ids_mutable(
                operator_user_id=int(operator["id"]),
                user_ids=user_ids,
                allow_admin_targets=False,
            )
            deleted_user_ids: List[int] = []
            for row in rows:
                self.storage.revoke_user_sessions(int(row["id"]))
                self.storage.delete_user(int(row["id"]))
                deleted_user_ids.append(int(row["id"]))
            items = self.storage.list_users()
            for item in items:
                item.pop("password_hash", None)
            return web.json_response(
                {
                    "ok": True,
                    "deletedCount": len(deleted_user_ids),
                    "deletedUserIds": deleted_user_ids,
                    "count": len(items),
                    "items": items,
                }
            )
        except Exception as e:
            status = 404 if "not found" in str(e) else 400
            return web.json_response({"error": str(e)}, status=status)

    async def admin_user_reset_password_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        if not user_id_raw:
            return web.json_response({"error": "user_id is required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            new_password = require_nonempty_text(payload.get("new_password"), "new_password")
            item = self.storage.update_user_password(int(user_id_raw), hash_password(new_password))
            self.storage.revoke_user_sessions(int(user_id_raw))
            item["password_set"] = bool(str(item.get("password_hash") or "").strip())
            item.pop("password_hash", None)
            return web.json_response({"ok": True, "item": item, "password_updated_at": item.get("password_updated_at")})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def admin_user_wallet_status_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        wallet_id_raw = str(request.match_info.get("wallet_id", "")).strip()
        if not user_id_raw or not wallet_id_raw:
            return web.json_response({"error": "user_id and wallet_id are required"}, status=400)
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            item = self.storage.update_user_wallet(
                int(user_id_raw),
                int(wallet_id_raw),
                is_enabled=parse_bool_like(payload.get("is_enabled")),
            )
            return web.json_response({"ok": True, "item": item})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def admin_user_wallet_delete_handler(self, request: web.Request) -> web.Response:
        self.require_admin(request)
        user_id_raw = str(request.match_info.get("user_id", "")).strip()
        wallet_id_raw = str(request.match_info.get("wallet_id", "")).strip()
        if not user_id_raw or not wallet_id_raw:
            return web.json_response({"error": "user_id and wallet_id are required"}, status=400)
        try:
            deleted = self.storage.delete_user_wallet(int(user_id_raw), int(wallet_id_raw))
            if not deleted:
                return web.json_response({"error": f"user wallet not found: {wallet_id_raw}"}, status=404)
            items = self.storage.list_user_wallet_rows(int(user_id_raw))
            return web.json_response({"ok": True, "count": len(items), "items": items})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def managed_project_upsert_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        try:
            row = self.upsert_managed_project_from_payload(payload)
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "item": row, "count": len(rows), "items": rows})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def managed_project_delete_handler(self, request: web.Request) -> web.Response:
        raw_project_id = str(request.match_info.get("project_id", "")).strip()
        if not raw_project_id:
            return web.json_response({"error": "project_id is required"}, status=400)
        try:
            project_id = int(raw_project_id)
            self.remove_managed_project_by_id(project_id)
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "count": len(rows), "items": rows})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def signalhub_watch_add_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            row = self.upsert_managed_project_from_payload(payload)
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "item": row, "count": len(rows), "items": rows})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def signalhub_watch_remove_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        try:
            project_id = parse_optional_int(payload.get("project_id"), "project_id")
            if project_id is None:
                raise ValueError("project_id is required")
            self.remove_managed_project_by_id(project_id)
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "count": len(rows), "items": rows})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def signalhub_watch_batch_add_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return web.json_response({"error": "items is required"}, status=400)
        try:
            saved = [self.upsert_managed_project_from_payload(dict(item)) for item in items]
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "saved": saved, "count": len(rows), "items": rows})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def signalhub_watch_batch_remove_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)
        project_ids = payload.get("project_ids")
        if not isinstance(project_ids, list) or not project_ids:
            return web.json_response({"error": "project_ids is required"}, status=400)
        try:
            for raw_id in project_ids:
                project_id = parse_optional_int(raw_id, "project_id")
                if project_id is None:
                    raise ValueError("project_id is required")
                self.remove_managed_project_by_id(project_id)
            rows = self.storage.list_managed_projects()
            return web.json_response({"ok": True, "count": len(rows), "items": rows})
        except Exception as e:
            if "not found" in str(e):
                return web.json_response({"error": str(e)}, status=404)
            return web.json_response({"error": str(e)}, status=400)

    async def monitored_wallets_handler(self, request: web.Request) -> web.Response:
        rows = self.storage.list_monitored_wallet_rows()
        return web.json_response({"count": len(rows), "items": rows})

    async def monitored_wallet_add_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        try:
            wallet = normalize_address(str(payload.get("wallet", "")).strip())
            name = str(payload.get("name", "")).strip()
            self.storage.add_monitored_wallet(wallet, name=name)
            self.reload_my_wallets()
            self.bump_my_wallet_revision()
            return web.json_response(
                {
                    "ok": True,
                    "wallets": sorted(self.get_my_wallets()),
                    "items": self.storage.list_monitored_wallet_rows(),
                    "count": len(self.get_my_wallets()),
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def monitored_wallet_delete_handler(self, request: web.Request) -> web.Response:
        wallet_raw = str(request.match_info.get("wallet", "")).strip()
        if not wallet_raw:
            return web.json_response({"error": "wallet is required"}, status=400)
        try:
            wallet = normalize_address(wallet_raw)
            deleted = self.storage.delete_monitored_wallet(wallet)
            if not deleted:
                return web.json_response({"error": f"wallet not found: {wallet}"}, status=404)
            self.reload_my_wallets()
            self.bump_my_wallet_revision()
            return web.json_response(
                {
                    "ok": True,
                    "wallets": sorted(self.get_my_wallets()),
                    "items": self.storage.list_monitored_wallet_rows(),
                    "count": len(self.get_my_wallets()),
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def wallet_recalc_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        project = str(payload.get("project", "")).strip()
        wallet_raw = str(payload.get("wallet", "")).strip()
        if not project:
            return web.json_response({"error": "project is required"}, status=400)
        if not wallet_raw:
            return web.json_response({"error": "wallet is required"}, status=400)

        try:
            wallet = normalize_address(wallet_raw)
            if wallet not in self.get_my_wallets():
                return web.json_response({"error": f"wallet not monitored: {wallet}"}, status=400)

            if self.wallet_recalc_lock.locked():
                return web.json_response({"error": "another wallet recalc is running"}, status=409)

            started = time.time()
            async with self.wallet_recalc_lock:
                result = self.storage.rebuild_wallet_position_for_project_wallet(project, wallet)
            duration_ms = int((time.time() - started) * 1000)
            return web.json_response(
                {
                    "ok": True,
                    "project": result["project"],
                    "wallet": result["wallet"],
                    "eventCount": int(result["eventCount"]),
                    "tokenCount": int(result["tokenCount"]),
                    "durationMs": duration_ms,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def runtime_db_batch_size_get_handler(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "dbBatchSize": self.get_runtime_db_batch_size(),
            }
        )

    async def runtime_db_batch_size_set_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        raw = payload.get("db_batch_size")
        try:
            value = int(raw)
        except Exception:
            return web.json_response({"error": "db_batch_size must be integer"}, status=400)
        if value < 1 or value > 100:
            return web.json_response({"error": "db_batch_size must be between 1 and 100"}, status=400)
        try:
            applied = self.set_runtime_db_batch_size(value)
            return web.json_response(
                {
                    "ok": True,
                    "dbBatchSize": applied,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def runtime_pause_get_handler(self, request: web.Request) -> web.Response:
        data = self.runtime_pause_payload()
        data["ok"] = True
        return web.json_response(data)

    async def runtime_pause_set_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        if "paused" not in payload:
            return web.json_response({"error": "paused is required"}, status=400)
        try:
            paused = parse_bool_request(payload.get("paused"))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

        self.set_runtime_paused(paused)
        data = self.runtime_pause_payload()
        data["ok"] = True
        return web.json_response(data)

    async def runtime_heartbeat_handler(self, request: web.Request) -> web.Response:
        self.touch_runtime_ui_heartbeat()
        data = self.runtime_pause_payload()
        data["ok"] = True
        return web.json_response(data)

    async def launch_config_upsert_handler(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json body"}, status=400)

        try:
            name = str(payload.get("name", "")).strip()
            if not name:
                raise ValueError("name cannot be empty")
            internal_pool_addr = normalize_address(str(payload.get("internal_pool_addr", "")).strip())
            is_enabled = bool(payload.get("is_enabled", True))
            switch_only = bool(payload.get("switch_only", False))

            self.storage.upsert_launch_config(
                name=name,
                internal_pool_addr=internal_pool_addr,
                fee_addr=self.fixed_fee_addr,
                tax_addr=self.fixed_tax_addr,
                token_addr=normalize_optional_address(payload.get("token_addr")),
                token_total_supply=self.fixed_token_total_supply,
                fee_rate=self.fixed_fee_rate,
                is_enabled=is_enabled,
            )
            if switch_only:
                self.storage.set_launch_config_enabled_only(name)

            self.reload_launch_configs()
            self.bump_launch_config_revision()
            if self.is_realtime_role:
                self.ws_reconnect_event.set()
            rows = self.storage.list_launch_configs()
            return web.json_response(
                {
                    "ok": True,
                    "monitoringProjects": [x.name for x in self.get_launch_configs()],
                    "items": rows,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def launch_config_delete_handler(self, request: web.Request) -> web.Response:
        name = str(request.match_info.get("name", "")).strip()
        if not name:
            return web.json_response({"error": "name is required"}, status=400)
        try:
            deleted = self.storage.delete_launch_config(name)
            if not deleted:
                return web.json_response({"error": f"project not found: {name}"}, status=404)
            self.reload_launch_configs()
            self.bump_launch_config_revision()
            if self.is_realtime_role:
                self.ws_reconnect_event.set()
            rows = self.storage.list_launch_configs()
            return web.json_response(
                {
                    "ok": True,
                    "monitoringProjects": [x.name for x in self.get_launch_configs()],
                    "items": rows,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def meta_handler(self, request: web.Request) -> web.Response:
        runtime_data = self.runtime_pause_payload()
        launch_configs = self.storage.list_launch_configs()
        projects = self.storage.list_projects()
        monitoring_projects = [x.name for x in self.get_launch_configs()]
        wallets = sorted(list(self.get_my_wallets()))
        return web.json_response(
            {
                "projects": projects,
                "wallets": wallets,
                "managedProjects": self.storage.list_managed_projects(),
                "topN": self.cfg.top_n,
                "launchConfigs": launch_configs,
                "monitoringProjects": monitoring_projects,
                "fixedDefaults": {
                    "fee_addr": self.fixed_fee_addr,
                    "tax_addr": self.fixed_tax_addr,
                    "token_total_supply": decimal_to_str(self.fixed_token_total_supply, 0),
                    "fee_rate": decimal_to_str(self.fixed_fee_rate, 18),
                },
                "runtimeTuning": {
                    "db_batch_size": self.get_runtime_db_batch_size(),
                    "runtime_paused": runtime_data["runtimePaused"],
                    "runtime_manual_paused": runtime_data["runtimeManualPaused"],
                    "runtime_ui_online": runtime_data["runtimeUiOnline"],
                    "runtime_ui_last_seen_at": runtime_data["runtimeUiLastSeenAt"],
                    "runtime_ui_heartbeat_timeout_sec": runtime_data["runtimeUiHeartbeatTimeoutSec"],
                },
                "signalHub": {
                    "enabled": bool(self.signalhub_client),
                    "upcoming_limit": int(self.cfg.signalhub_upcoming_limit),
                    "within_hours": int(self.cfg.signalhub_within_hours),
                },
            }
        )

    async def dashboard_handler(self, request: web.Request) -> web.Response:
        return web.FileResponse(self.base_dir / "dashboard.html")

    def admin_dist_dir(self) -> Path:
        return self.base_dir / "frontend" / "admin" / "dist"

    async def admin_handler(self, request: web.Request) -> web.Response:
        dist_dir = self.admin_dist_dir()
        index_file = dist_dir / "index.html"
        if not index_file.is_file():
            return web.Response(
                status=503,
                text=(
                    "Admin frontend is not built yet. "
                    "Run `npm install` and `npm run build` under `frontend/admin` first."
                ),
                content_type="text/plain",
            )
        return web.FileResponse(index_file)

    async def favicon_handler(self, request: web.Request) -> web.Response:
        favicon_png = self.base_dir / "favicon" / "favicon-32x32.png"
        if favicon_png.is_file():
            return web.FileResponse(favicon_png)
        return web.FileResponse(self.base_dir / "frontend" / "admin" / "dist" / "brand" / "logo-mark.png")

    async def favicon_ico_handler(self, request: web.Request) -> web.Response:
        favicon_ico = self.base_dir / "favicon" / "favicon.ico"
        if favicon_ico.is_file():
            return web.FileResponse(favicon_ico)
        fallback_png = self.base_dir / "favicon" / "favicon-32x32.png"
        if fallback_png.is_file():
            return web.FileResponse(fallback_png)
        return web.FileResponse(self.base_dir / "frontend" / "admin" / "dist" / "brand" / "logo-mark.png")

    async def wallets_handler(self, request: web.Request) -> web.Response:
        project = request.query.get("project")
        project = str(project).strip() if project else None
        data = self.storage.query_wallets(project=project)
        current_wallets = self.get_my_wallets()
        data = [x for x in data if normalize_address(str(x.get("wallet", ""))) in current_wallets]
        return web.json_response({"count": len(data), "items": data})

    async def wallet_detail_handler(self, request: web.Request) -> web.Response:
        addr = normalize_address(request.match_info["addr"])
        project = request.query.get("project")
        project = str(project).strip() if project else None
        data = self.storage.query_wallets(wallet=addr, project=project)
        return web.json_response({"wallet": addr, "count": len(data), "items": data})

    async def minutes_handler(self, request: web.Request) -> web.Response:
        project = request.query.get("project")
        if not project:
            return web.json_response({"error": "project is required"}, status=400)
        try:
            from_ts = int(request.query.get("from", "0"))
            to_ts = int(request.query.get("to", str(int(time.time()))))
        except ValueError:
            return web.json_response({"error": "from/to must be integer"}, status=400)
        data = self.storage.query_minutes(project, from_ts, to_ts)
        return web.json_response({"project": project, "count": len(data), "items": data})

    async def leaderboard_handler(self, request: web.Request) -> web.Response:
        project = request.query.get("project")
        if not project:
            return web.json_response({"error": "project is required"}, status=400)
        top = int(request.query.get("top", str(self.cfg.top_n)))
        data = self.storage.query_leaderboard(project, top)

        launch_cfg = self.storage.get_launch_config_by_name(project)
        total_supply = (
            launch_cfg.token_total_supply if launch_cfg is not None else self.fixed_token_total_supply
        )
        virtual_price_usd, _ = await self.price_service.get_price()

        enriched: List[Dict[str, Any]] = []
        for row in data:
            spent = Decimal(str(row.get("sum_spent_v_est", "0")))
            token = Decimal(str(row.get("sum_token_bought", "0")))
            avg_cost_v = (spent / token) if token > 0 else Decimal(0)
            fdv_v = avg_cost_v * total_supply
            fdv_usd = (fdv_v * virtual_price_usd) if virtual_price_usd is not None else None

            x = dict(row)
            x["avg_cost_v"] = decimal_to_str(avg_cost_v, 18)
            x["breakeven_fdv_v"] = decimal_to_str(fdv_v, 18)
            x["breakeven_fdv_usd"] = (
                decimal_to_str(fdv_usd, 18) if fdv_usd is not None else None
            )
            enriched.append(x)

        return web.json_response({"project": project, "top": top, "items": enriched})

    async def event_delays_handler(self, request: web.Request) -> web.Response:
        project = request.query.get("project")
        if not project:
            return web.json_response({"error": "project is required"}, status=400)
        try:
            limit_n = int(request.query.get("limit", "100"))
        except ValueError:
            return web.json_response({"error": "limit must be integer"}, status=400)
        limit_n = max(1, min(limit_n, 500))
        data = self.storage.query_event_delays(project, limit_n)
        return web.json_response({"project": project, "count": len(data), "items": data})

    async def project_tax_handler(self, request: web.Request) -> web.Response:
        project = request.query.get("project")
        if not project:
            return web.json_response({"error": "project is required"}, status=400)
        try:
            data = self.storage.query_project_tax(project)
            return web.json_response(data)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def build_signalhub_upcoming_payload(
        self,
        *,
        limit: int,
        within_hours: int,
    ) -> Dict[str, Any]:
        limit = max(1, min(limit, 50))
        within_hours = max(1, min(within_hours, 720))

        if not self.signalhub_client:
            return {
                "enabled": False,
                "available": False,
                "message": "未配置 SIGNALHUB_BASE_URL，当前未接入 SignalHub。",
                "source": "signalhub",
                "count": 0,
                "limit": limit,
                "withinHours": within_hours,
                "items": [],
            }

        try:
            data = await self.signalhub_client.fetch_upcoming(
                limit=limit,
                within_hours=within_hours,
            )
            return {
                "enabled": True,
                "available": True,
                "message": (
                    f"已拉取 {data['count']} 个 upcoming 项目，"
                    "有内盘地址的项目可直接导入。"
                ),
                **data,
            }
        except Exception as e:
            return {
                "enabled": True,
                "available": False,
                "message": f"SignalHub 拉取失败：{e}",
                "source": "signalhub",
                "count": 0,
                "limit": limit,
                "withinHours": within_hours,
                "items": [],
            }

    async def signalhub_upcoming_handler(self, request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit", str(self.cfg.signalhub_upcoming_limit)))
            within_hours = int(
                request.query.get("within_hours", str(self.cfg.signalhub_within_hours))
            )
        except ValueError:
            return web.json_response({"error": "limit/within_hours must be integer"}, status=400)
        payload = await self.build_signalhub_upcoming_payload(limit=limit, within_hours=within_hours)
        user = self.get_request_user(request)
        if payload.get("items") and user and str(user.get("role") or "").lower() == "admin":
            managed_projects = self.storage.list_managed_projects()
            by_signalhub_id = {
                str(item.get("signalhub_project_id") or "").strip(): item
                for item in managed_projects
                if str(item.get("signalhub_project_id") or "").strip()
            }
            by_name = {
                str(item.get("name") or "").strip().upper(): item
                for item in managed_projects
                if str(item.get("name") or "").strip()
            }
            enriched_items: List[Dict[str, Any]] = []
            for item in payload.get("items") or []:
                enriched = dict(item)
                managed = by_signalhub_id.get(str(item.get("projectId") or "").strip()) or by_name.get(
                    str(item.get("importName") or "").strip().upper()
                )
                enriched["managedProjectId"] = int(managed.get("id") or 0) if managed else None
                enriched["managedStatus"] = str(managed.get("status") or "") if managed else ""
                enriched["resolvedEndAt"] = int(managed.get("resolved_end_at") or 0) if managed else None
                enriched["watchlist"] = bool(managed)
                enriched_items.append(enriched)
            payload["items"] = enriched_items
        return web.json_response(payload)

    def resolve_cors_origin(self, request_origin: Optional[str]) -> Optional[str]:
        if not request_origin or not self.cors_allow_origins:
            return None
        origin = str(request_origin).strip().rstrip("/")
        if not origin:
            return None
        if "*" in self.cors_allow_origins:
            return "*"
        if origin in self.cors_allow_origins:
            return origin
        return None

    async def create_api_app(self) -> web.Application:
        @web.middleware
        async def cors_middleware(request: web.Request, handler):
            allow_origin = self.resolve_cors_origin(request.headers.get("Origin"))
            if request.method == "OPTIONS":
                response: web.StreamResponse = web.Response(status=204)
            else:
                try:
                    response = await handler(request)
                except web.HTTPException as ex:
                    response = ex

            if allow_origin:
                response.headers["Access-Control-Allow-Origin"] = allow_origin
                response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,DELETE,OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
                response.headers["Access-Control-Max-Age"] = "86400"
            return response

        @web.middleware
        async def auth_middleware(request: web.Request, handler):
            request["auth_user"] = None
            request["auth_session"] = None
            token = str(request.cookies.get(self.session_cookie_name) or "").strip()
            if token:
                session = self.storage.get_session_with_user(
                    hash_session_token(token, self.session_secret)
                )
                now = int(time.time())
                if session and int(session.get("session_expires_at") or 0) > now:
                    request["auth_user"] = dict(session)
                    request["auth_session"] = {
                        "id": int(session.get("session_id") or 0),
                        "expires_at": int(session.get("session_expires_at") or 0),
                    }
                    self.storage.touch_session(
                        int(session.get("session_id") or 0),
                        expires_at=self.session_expires_at(),
                    )
                elif session:
                    self.storage.revoke_session(hash_session_token(token, self.session_secret))
            return await handler(request)

        def admin_only(handler):
            async def wrapped(request: web.Request) -> web.StreamResponse:
                self.require_admin(request)
                return await handler(request)

            return wrapped

        def legacy_route(handler, *, replacement: str, access: str = "admin"):
            async def wrapped(request: web.Request) -> web.StreamResponse:
                if access == "admin":
                    self.require_admin(request)
                response = await handler(request)
                return self.apply_legacy_response_headers(
                    response,
                    replacement=replacement,
                    access=access,
                )

            return wrapped

        middlewares = [auth_middleware]
        if self.cors_allow_origins:
            middlewares.insert(0, cors_middleware)
        app = web.Application(middlewares=middlewares)
        app.router.add_get("/", self.dashboard_handler)
        app.router.add_get("/dashboard", self.dashboard_handler)
        app.router.add_get("/dashboard/", self.dashboard_handler)
        app.router.add_get("/favicon-vwr.svg", self.favicon_handler)
        app.router.add_get("/favicon-vpulse.svg", self.favicon_handler)
        app.router.add_get("/favicon.ico", self.favicon_ico_handler)
        favicon_dir = self.base_dir / "favicon"
        if favicon_dir.is_dir():
            app.router.add_static("/favicon/", path=str(favicon_dir), show_index=False)
        admin_dist_dir = self.admin_dist_dir()
        admin_assets_dir = admin_dist_dir / "assets"
        admin_brand_dir = admin_dist_dir / "brand"
        if admin_assets_dir.is_dir():
            app.router.add_static("/admin/assets/", path=str(admin_assets_dir), show_index=False)
        if admin_brand_dir.is_dir():
            app.router.add_static("/admin/brand/", path=str(admin_brand_dir), show_index=False)
        app.router.add_get("/admin", self.admin_handler)
        app.router.add_get("/admin/", self.admin_handler)
        app.router.add_get("/admin/{tail:.*}", self.admin_handler)
        app.router.add_get("/app", self.admin_handler)
        app.router.add_get("/app/", self.admin_handler)
        app.router.add_get("/app/{tail:.*}", self.admin_handler)
        app.router.add_get("/auth", self.admin_handler)
        app.router.add_get("/auth/", self.admin_handler)
        app.router.add_get("/auth/{tail:.*}", self.admin_handler)
        app.router.add_post("/api/auth/register", self.auth_register_handler)
        app.router.add_post("/api/auth/resend-verification", self.auth_resend_verification_handler)
        app.router.add_get("/api/auth/verify-email", self.auth_verify_email_handler)
        app.router.add_post("/api/auth/login", self.auth_login_handler)
        app.router.add_post("/api/auth/logout", self.auth_logout_handler)
        app.router.add_get("/api/auth/me", self.auth_me_handler)
        app.router.add_get("/api/app/meta", self.app_meta_handler)
        app.router.add_get("/api/app/billing/summary", self.app_billing_summary_handler)
        app.router.add_get("/api/app/billing/requests", self.app_billing_requests_handler)
        app.router.add_post("/api/app/billing/requests", self.app_billing_request_create_handler)
        app.router.add_get("/api/app/billing/requests/{request_id}/proof", self.app_billing_request_proof_handler)
        app.router.add_get("/api/app/notifications", self.app_notifications_handler)
        app.router.add_post("/api/app/notifications/read-all", self.app_notifications_read_all_handler)
        app.router.add_post("/api/app/notifications/{notification_id}/read", self.app_notification_read_handler)
        app.router.add_get("/api/app/overview-active", self.app_overview_active_handler)
        app.router.add_get("/api/app/projects", self.app_projects_handler)
        app.router.add_get("/api/app/projects/{project_id}/overview", self.app_project_overview_handler)
        app.router.add_get("/api/app/projects/{project_id}/access", self.app_project_access_handler)
        app.router.add_post("/api/app/projects/{project_id}/unlock", self.app_project_unlock_handler)
        app.router.add_get("/api/app/signalhub", self.app_signalhub_handler)
        app.router.add_get("/api/app/wallets", self.app_wallets_handler)
        app.router.add_post("/api/app/wallets", self.app_wallets_add_handler)
        app.router.add_patch("/api/app/wallets/{wallet_id}", self.app_wallets_update_handler)
        app.router.add_delete("/api/app/wallets/{wallet_id}", self.app_wallets_delete_handler)
        app.router.add_get("/api/app/wallets/positions", self.app_wallet_positions_handler)
        app.router.add_get("/api/admin/meta", self.admin_meta_handler)
        app.router.add_get("/api/admin/overview-active", admin_only(self.overview_active_handler))
        app.router.add_get("/api/admin/projects", admin_only(self.managed_projects_handler))
        app.router.add_get("/api/admin/projects/{project_id}/overview", admin_only(self.admin_project_overview_handler))
        app.router.add_post("/api/admin/projects", admin_only(self.managed_project_upsert_handler))
        app.router.add_delete("/api/admin/projects/{project_id}", admin_only(self.managed_project_delete_handler))
        app.router.add_get("/api/admin/signalhub", admin_only(self.signalhub_upcoming_handler))
        app.router.add_get("/api/admin/health", admin_only(self.health_handler))
        app.router.add_get("/api/admin/launch-configs", admin_only(self.launch_configs_handler))
        app.router.add_post("/api/admin/launch-configs", admin_only(self.launch_config_upsert_handler))
        app.router.add_delete("/api/admin/launch-configs/{name}", admin_only(self.launch_config_delete_handler))
        app.router.add_get("/api/admin/project-scheduler/status", admin_only(self.project_scheduler_status_handler))
        app.router.add_post("/api/admin/signalhub/watchlist/add", admin_only(self.signalhub_watch_add_handler))
        app.router.add_post("/api/admin/signalhub/watchlist/remove", admin_only(self.signalhub_watch_remove_handler))
        app.router.add_post("/api/admin/signalhub/watchlist/batch-add", admin_only(self.signalhub_watch_batch_add_handler))
        app.router.add_post("/api/admin/signalhub/watchlist/batch-remove", admin_only(self.signalhub_watch_batch_remove_handler))
        app.router.add_get("/api/admin/wallets", admin_only(self.monitored_wallets_handler))
        app.router.add_post("/api/admin/wallets", admin_only(self.monitored_wallet_add_handler))
        app.router.add_delete("/api/admin/wallets/{wallet}", admin_only(self.monitored_wallet_delete_handler))
        app.router.add_post("/api/admin/wallet-recalc", admin_only(self.wallet_recalc_handler))
        app.router.add_get("/api/admin/runtime/db-batch-size", admin_only(self.runtime_db_batch_size_get_handler))
        app.router.add_post("/api/admin/runtime/db-batch-size", admin_only(self.runtime_db_batch_size_set_handler))
        app.router.add_get("/api/admin/runtime/pause", admin_only(self.runtime_pause_get_handler))
        app.router.add_post("/api/admin/runtime/pause", admin_only(self.runtime_pause_set_handler))
        app.router.add_post("/api/admin/runtime/heartbeat", admin_only(self.runtime_heartbeat_handler))
        app.router.add_post("/api/admin/scan-range", admin_only(self.scan_range_handler))
        app.router.add_get("/api/admin/scan-jobs/{job_id}", admin_only(self.scan_job_detail_handler))
        app.router.add_post("/api/admin/scan-jobs/{job_id}/cancel", admin_only(self.scan_job_cancel_handler))
        app.router.add_get("/api/admin/mywallets", admin_only(self.wallets_handler))
        app.router.add_get("/api/admin/mywallets/{addr}", admin_only(self.wallet_detail_handler))
        app.router.add_get("/api/admin/minutes", admin_only(self.minutes_handler))
        app.router.add_get("/api/admin/leaderboard", admin_only(self.leaderboard_handler))
        app.router.add_get("/api/admin/event-delays", admin_only(self.event_delays_handler))
        app.router.add_get("/api/admin/project-tax", admin_only(self.project_tax_handler))
        app.router.add_get("/api/admin/users", self.admin_users_handler)
        app.router.add_post("/api/admin/users", self.admin_user_create_handler)
        app.router.add_post("/api/admin/users/batch-status", self.admin_users_batch_status_handler)
        app.router.add_post("/api/admin/users/batch-delete", self.admin_users_batch_delete_handler)
        app.router.add_get("/api/admin/users/{user_id}", self.admin_user_detail_handler)
        app.router.add_get("/api/admin/users/{user_id}/wallets", self.admin_user_wallets_handler)
        app.router.add_get("/api/admin/users/{user_id}/credit-ledger", self.admin_user_credit_ledger_handler)
        app.router.add_get("/api/admin/users/{user_id}/project-access", self.admin_user_project_access_handler)
        app.router.add_post("/api/admin/users/{user_id}/status", self.admin_user_status_handler)
        app.router.add_post("/api/admin/users/{user_id}/reset-password", self.admin_user_reset_password_handler)
        app.router.add_post("/api/admin/users/{user_id}/credits/adjust", self.admin_user_credit_adjust_handler)
        app.router.add_post("/api/admin/users/{user_id}/credits/topup", self.admin_user_credit_topup_handler)
        app.router.add_post("/api/admin/users/{user_id}/wallets/{wallet_id}/status", self.admin_user_wallet_status_handler)
        app.router.add_delete("/api/admin/users/{user_id}/wallets/{wallet_id}", self.admin_user_wallet_delete_handler)
        app.router.add_get("/api/admin/billing/requests", self.admin_billing_requests_handler)
        app.router.add_get("/api/admin/billing/requests/{request_id}/proof", self.admin_billing_request_proof_handler)
        app.router.add_post("/api/admin/billing/requests/{request_id}/credit", self.admin_billing_request_credit_handler)
        app.router.add_post("/api/admin/billing/requests/{request_id}/notify", self.admin_billing_request_notify_handler)
        app.router.add_get("/api/admin/legacy-apis", self.admin_legacy_apis_handler)
        app.router.add_get("/meta", legacy_route(self.meta_handler, replacement="/api/admin/meta"))
        app.router.add_get("/signalhub/upcoming", legacy_route(self.signalhub_upcoming_handler, replacement="/api/admin/signalhub"))
        app.router.add_get("/launch-configs", legacy_route(self.launch_configs_handler, replacement="/api/admin/launch-configs"))
        app.router.add_post("/launch-configs", legacy_route(self.launch_config_upsert_handler, replacement="/api/admin/launch-configs"))
        app.router.add_delete("/launch-configs/{name}", legacy_route(self.launch_config_delete_handler, replacement="/api/admin/launch-configs/{name}"))
        app.router.add_get("/managed-projects", legacy_route(self.managed_projects_handler, replacement="/api/admin/projects"))
        app.router.add_get("/managed-projects/{project_id}", legacy_route(self.managed_project_detail_handler, replacement="/api/admin/projects"))
        app.router.add_post("/managed-projects", legacy_route(self.managed_project_upsert_handler, replacement="/api/admin/projects"))
        app.router.add_delete("/managed-projects/{project_id}", legacy_route(self.managed_project_delete_handler, replacement="/api/admin/projects/{project_id}"))
        app.router.add_get("/project-scheduler/status", legacy_route(self.project_scheduler_status_handler, replacement="/api/admin/project-scheduler/status"))
        app.router.add_get("/overview-active", legacy_route(self.overview_active_handler, replacement="/api/admin/overview-active"))
        app.router.add_post("/signalhub/watchlist/add", legacy_route(self.signalhub_watch_add_handler, replacement="/api/admin/signalhub/watchlist/add"))
        app.router.add_post("/signalhub/watchlist/remove", legacy_route(self.signalhub_watch_remove_handler, replacement="/api/admin/signalhub/watchlist/remove"))
        app.router.add_post("/signalhub/watchlist/batch-add", legacy_route(self.signalhub_watch_batch_add_handler, replacement="/api/admin/signalhub/watchlist/batch-add"))
        app.router.add_post("/signalhub/watchlist/batch-remove", legacy_route(self.signalhub_watch_batch_remove_handler, replacement="/api/admin/signalhub/watchlist/batch-remove"))
        app.router.add_get("/wallet-configs", legacy_route(self.monitored_wallets_handler, replacement="/api/admin/wallets"))
        app.router.add_post("/wallet-configs", legacy_route(self.monitored_wallet_add_handler, replacement="/api/admin/wallets"))
        app.router.add_delete("/wallet-configs/{wallet}", legacy_route(self.monitored_wallet_delete_handler, replacement="/api/admin/wallets/{wallet}"))
        app.router.add_post("/wallet-recalc", legacy_route(self.wallet_recalc_handler, replacement="/api/admin/wallet-recalc"))
        app.router.add_get("/runtime/db-batch-size", legacy_route(self.runtime_db_batch_size_get_handler, replacement="/api/admin/runtime/db-batch-size"))
        app.router.add_post("/runtime/db-batch-size", legacy_route(self.runtime_db_batch_size_set_handler, replacement="/api/admin/runtime/db-batch-size"))
        app.router.add_get("/runtime/pause", legacy_route(self.runtime_pause_get_handler, replacement="/api/admin/runtime/pause"))
        app.router.add_post("/runtime/pause", legacy_route(self.runtime_pause_set_handler, replacement="/api/admin/runtime/pause"))
        app.router.add_post("/runtime/heartbeat", legacy_route(self.runtime_heartbeat_handler, replacement="/api/admin/runtime/heartbeat"))
        app.router.add_post("/scan-range", legacy_route(self.scan_range_handler, replacement="/api/admin/scan-range"))
        app.router.add_get("/scan-jobs/{job_id}", legacy_route(self.scan_job_detail_handler, replacement="/api/admin/scan-jobs/{job_id}"))
        app.router.add_post("/scan-jobs/{job_id}/cancel", legacy_route(self.scan_job_cancel_handler, replacement="/api/admin/scan-jobs/{job_id}/cancel"))
        app.router.add_get("/health", legacy_route(self.health_handler, replacement="/api/admin/health", access="public"))
        app.router.add_get("/mywallets", legacy_route(self.wallets_handler, replacement="/api/admin/mywallets"))
        app.router.add_get("/mywallets/{addr}", legacy_route(self.wallet_detail_handler, replacement="/api/admin/mywallets/{addr}"))
        app.router.add_get("/minutes", legacy_route(self.minutes_handler, replacement="/api/admin/minutes"))
        app.router.add_get("/leaderboard", legacy_route(self.leaderboard_handler, replacement="/api/admin/leaderboard"))
        app.router.add_get("/event-delays", legacy_route(self.event_delays_handler, replacement="/api/admin/event-delays"))
        app.router.add_get("/project-tax", legacy_route(self.project_tax_handler, replacement="/api/admin/project-tax"))
        return app

    async def run(self) -> None:
        await self.price_service.start()
        if self.is_writer_role:
            self.reconcile_managed_projects_schedule(force_launch_sync=True)

        if self.is_realtime_role or self.is_backfill_role:
            worker_count = self.cfg.receipt_workers
            if self.role == "realtime":
                worker_count = self.cfg.receipt_workers_realtime
            elif self.role == "backfill":
                worker_count = self.cfg.receipt_workers_backfill
            for _ in range(max(1, worker_count)):
                self.tasks.append(asyncio.create_task(self.consumer_loop()))
        if self.consume_events_from_bus:
            self.tasks.append(asyncio.create_task(self.bus_writer_loop()))
        elif self.is_writer_role:
            self.tasks.append(asyncio.create_task(self.flush_loop()))
        if self.is_writer_role:
            self.tasks.append(asyncio.create_task(self.project_scheduler_loop()))
        if self.is_realtime_role:
            self.tasks.append(asyncio.create_task(self.ws_loop()))
        if self.is_backfill_role:
            self.tasks.append(asyncio.create_task(self.backfill_loop()))
        if self.role in {"realtime", "backfill"}:
            self.tasks.append(asyncio.create_task(self.role_heartbeat_loop()))
            self.tasks.append(asyncio.create_task(self.launch_config_watch_loop()))
            self.tasks.append(asyncio.create_task(self.my_wallet_watch_loop()))
        if self.role == "backfill":
            self.tasks.append(asyncio.create_task(self.scan_job_dispatch_loop()))

        runner: Optional[web.AppRunner] = None
        if self.enable_api:
            app = await self.create_api_app()
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host=self.cfg.api_host, port=self.cfg.api_port)
            await site.start()

        while not self.stop_event.is_set():
            await asyncio.sleep(1)

        if runner is not None:
            await runner.cleanup()

    async def shutdown(self) -> None:
        self.stop_event.set()
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await self.price_service.stop()
        if self.is_writer_role and not self.consume_events_from_bus:
            await self.flush_once(force=True)


async def main_async(config_path: str, role: str) -> None:
    cfg = load_config(config_path)
    async with VirtualsBot(cfg, role=role) as bot:
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _on_stop() -> None:
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _on_stop)

        run_task = asyncio.create_task(bot.run())
        wait_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            {run_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for p in pending:
            p.cancel()
        for d in done:
            if d is run_task and d.exception():
                raise d.exception()
        await bot.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Virtuals-Launch-Hunter v1.0 split-role runtime"
    )
    parser.add_argument(
        "--config",
        default="./config.json",
        help="config file path (default: ./config.json)",
    )
    parser.add_argument(
        "--role",
        default="all",
        choices=["all", "writer", "realtime", "backfill"],
        help="run role: all | writer | realtime | backfill",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main_async(args.config, args.role))
    except KeyboardInterrupt:
        pass
    except InvalidOperation as e:
        raise SystemExit(f"Decimal calculation error: {e}") from e


if __name__ == "__main__":
    main()
