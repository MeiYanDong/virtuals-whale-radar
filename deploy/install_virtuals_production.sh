#!/usr/bin/env bash
set -euo pipefail

# Production installer for the current Virtuals Whale Radar stack.
# This installs:
# - main aiohttp app on 127.0.0.1:8080
# - SignalHub on 127.0.0.1:8000
# - React frontend build under frontend/admin/dist
# - nginx reverse proxy for the public domain
#
# Required env vars:
#   WS_RPC_URL
#   HTTP_RPC_URL
#
# Optional env vars:
#   BACKFILL_HTTP_RPC_URL
#   CHAINSTACK_BASE_HTTPS_URL
#   CHAINSTACK_BASE_WSS_URL
#   DOMAIN
#   REPO_URL
#   BRANCH
#   APP_DIR
#   APP_USER
#   BOOTSTRAP_ADMIN_EMAIL
#   BOOTSTRAP_ADMIN_PASSWORD
#   BOOTSTRAP_ADMIN_NICKNAME
#   SESSION_SECRET
#   BILLING_CONTACT_QR_URL
#   BILLING_CONTACT_HINT
#   LETSENCRYPT_EMAIL

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this script as root." >&2
  exit 1
fi

REPO_URL="${REPO_URL:-https://github.com/MeiYanDong/virtuals-whale-radar.git}"
BRANCH="${BRANCH:-main}"
DOMAIN="${DOMAIN:-virtuals.club}"
APP_DIR="${APP_DIR:-/opt/virtuals-whale-radar}"
APP_USER="${APP_USER:-vwr}"
APP_GROUP="${APP_GROUP:-$APP_USER}"
APP_PORT="${APP_PORT:-8080}"
SIGNALHUB_PORT="${SIGNALHUB_PORT:-8000}"

BOOTSTRAP_ADMIN_NICKNAME="${BOOTSTRAP_ADMIN_NICKNAME:-Administrator}"
BOOTSTRAP_ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-admin@example.com}"
BOOTSTRAP_ADMIN_PASSWORD="${BOOTSTRAP_ADMIN_PASSWORD:-ChangeMe123!}"
BILLING_CONTACT_QR_URL="${BILLING_CONTACT_QR_URL:-/admin/brand/contact-qr-wechat.png}"
BILLING_CONTACT_HINT="${BILLING_CONTACT_HINT:-扫码添加运营联系方式，付款后联系管理员手动补积分。}"

WS_RPC_URL="${WS_RPC_URL:?WS_RPC_URL is required}"
HTTP_RPC_URL="${HTTP_RPC_URL:?HTTP_RPC_URL is required}"
BACKFILL_HTTP_RPC_URL="${BACKFILL_HTTP_RPC_URL:-$HTTP_RPC_URL}"
CHAINSTACK_BASE_HTTPS_URL="${CHAINSTACK_BASE_HTTPS_URL:-$HTTP_RPC_URL}"
CHAINSTACK_BASE_WSS_URL="${CHAINSTACK_BASE_WSS_URL:-$WS_RPC_URL}"
SESSION_SECRET="${SESSION_SECRET:-$(openssl rand -hex 32)}"

log() {
  echo "[virtuals-prod] $*"
}

as_app_user() {
  runuser -u "${APP_USER}" -- "$@"
}

install_packages() {
  log "Installing apt packages"
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git curl ca-certificates gnupg nginx certbot python3-certbot-nginx \
    python3 python3-venv python3-pip sqlite3 openssl
}

install_node() {
  local need_install="1"
  if command -v node >/dev/null 2>&1; then
    local major
    major="$(node -p 'process.versions.node.split(".")[0]')"
    if [[ "${major}" =~ ^[0-9]+$ ]] && [[ "${major}" -ge 20 ]]; then
      need_install="0"
    fi
  fi

  if [[ "${need_install}" == "0" ]]; then
    log "Node.js already satisfies build requirement"
    return 0
  fi

  log "Installing Node.js 22.x"
  mkdir -p /etc/apt/keyrings
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
    | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
  cat >/etc/apt/sources.list.d/nodesource.list <<EOF
deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main
EOF
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
}

ensure_user() {
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    log "Creating service user ${APP_USER}"
    useradd --system --create-home --shell /bin/bash "${APP_USER}"
  fi
}

sync_repo() {
  if [[ -d "${APP_DIR}/.git" ]]; then
    log "Updating existing repo in ${APP_DIR}"
    git -C "${APP_DIR}" fetch origin
    git -C "${APP_DIR}" checkout "${BRANCH}"
    git -C "${APP_DIR}" pull --ff-only origin "${BRANCH}"
  else
    log "Cloning repo into ${APP_DIR}"
    rm -rf "${APP_DIR}"
    git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
  fi
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
}

setup_python() {
  log "Installing Python dependencies for main app"
  as_app_user python3 -m venv "${APP_DIR}/.venv"
  as_app_user "${APP_DIR}/.venv/bin/pip" install --upgrade pip
  as_app_user "${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

  log "Installing Python dependencies for SignalHub"
  as_app_user python3 -m venv "${APP_DIR}/SignalHub-main/.venv"
  as_app_user "${APP_DIR}/SignalHub-main/.venv/bin/pip" install --upgrade pip
  as_app_user "${APP_DIR}/SignalHub-main/.venv/bin/pip" install -r "${APP_DIR}/SignalHub-main/requirements.txt"
}

build_frontend() {
  log "Building frontend"
  pushd "${APP_DIR}/frontend/admin" >/dev/null
  as_app_user npm ci
  as_app_user npm run build
  popd >/dev/null
}

write_signalhub_env() {
  log "Writing SignalHub .env"
  cat >"${APP_DIR}/SignalHub-main/.env" <<EOF
CHAINSTACK_BASE_WSS_URL=${CHAINSTACK_BASE_WSS_URL}
CHAINSTACK_BASE_HTTPS_URL=${CHAINSTACK_BASE_HTTPS_URL}
EOF
  chown "${APP_USER}:${APP_GROUP}" "${APP_DIR}/SignalHub-main/.env"
}

write_main_config() {
  log "Writing config.json"
  if [[ ! -f "${APP_DIR}/config.example.json" ]]; then
    echo "config.example.json not found in ${APP_DIR}" >&2
    exit 1
  fi
  cp "${APP_DIR}/config.example.json" "${APP_DIR}/config.json"
  python3 - <<PY
import json
from pathlib import Path

path = Path("${APP_DIR}/config.json")
data = json.loads(path.read_text(encoding="utf-8"))
data.update({
    "WS_RPC_URL": "${WS_RPC_URL}",
    "HTTP_RPC_URL": "${HTTP_RPC_URL}",
    "BACKFILL_HTTP_RPC_URL": "${BACKFILL_HTTP_RPC_URL}",
    "API_HOST": "127.0.0.1",
    "API_PORT": ${APP_PORT},
    "SIGNALHUB_BASE_URL": "http://127.0.0.1:${SIGNALHUB_PORT}",
    "BOOTSTRAP_ADMIN_NICKNAME": "${BOOTSTRAP_ADMIN_NICKNAME}",
    "BOOTSTRAP_ADMIN_EMAIL": "${BOOTSTRAP_ADMIN_EMAIL}",
    "BOOTSTRAP_ADMIN_PASSWORD": "${BOOTSTRAP_ADMIN_PASSWORD}",
    "SESSION_SECRET": "${SESSION_SECRET}",
    "BILLING_CONTACT_QR_URL": "${BILLING_CONTACT_QR_URL}",
    "BILLING_CONTACT_HINT": "${BILLING_CONTACT_HINT}",
    "CORS_ALLOW_ORIGINS": [],
})
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
PY
  mkdir -p "${APP_DIR}/data"
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}/data" "${APP_DIR}/config.json"
}

install_services() {
  log "Installing systemd services"

  cat >/etc/systemd/system/vwr@.service <<EOF
[Unit]
Description=Virtuals Whale Radar role %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/virtuals_bot.py --config ${APP_DIR}/config.json --role %i
Restart=always
RestartSec=3
TimeoutStopSec=30
KillSignal=SIGINT
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/etc/virtuals-whale-radar/rpc.env

[Install]
WantedBy=multi-user.target
EOF

  cat >/etc/systemd/system/vwr-signalhub.service <<EOF
[Unit]
Description=SignalHub service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}/SignalHub-main
ExecStart=${APP_DIR}/SignalHub-main/.venv/bin/python run_local.py
Restart=always
RestartSec=3
Environment=HOST=127.0.0.1
Environment=PORT=${SIGNALHUB_PORT}
Environment=RELOAD=false
Environment=AUTO_OPEN_DASHBOARD=false
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now vwr-signalhub.service
  systemctl enable --now vwr@writer vwr@realtime vwr@backfill
}

install_nginx() {
  log "Installing nginx site"
  cat >/etc/nginx/sites-available/virtuals-whale-radar.conf <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN} www.${DOMAIN} _;

    client_max_body_size 20m;

    location = / {
        return 302 /auth/login;
    }

    location / {
        proxy_pass http://127.0.0.1:${APP_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
EOF
  rm -f /etc/nginx/sites-enabled/default
  ln -sfn /etc/nginx/sites-available/virtuals-whale-radar.conf /etc/nginx/sites-enabled/virtuals-whale-radar.conf
  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

install_runtime_maintenance() {
  log "Installing runtime maintenance"
  BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}" \
  BACKUP_ON_CALENDAR="${BACKUP_ON_CALENDAR:-*-*-* 04:15:00}" \
  APP_DIR="${APP_DIR}" \
  APP_USER="${APP_USER}" \
  APP_GROUP="${APP_GROUP}" \
  bash "${APP_DIR}/deploy/install_runtime_maintenance.sh"
}

maybe_issue_cert() {
  if [[ -z "${LETSENCRYPT_EMAIL:-}" ]]; then
    log "Skipping HTTPS certificate because LETSENCRYPT_EMAIL is empty"
    return 0
  fi

  log "Attempting HTTPS certificate for ${DOMAIN}"
  certbot --nginx --non-interactive --agree-tos --redirect \
    -m "${LETSENCRYPT_EMAIL}" -d "${DOMAIN}" -d "www.${DOMAIN}" || true
}

show_status() {
  log "Service status"
  systemctl --no-pager --full status vwr-signalhub.service || true
  systemctl --no-pager --full status vwr@writer || true
  systemctl --no-pager --full status vwr@realtime || true
  systemctl --no-pager --full status vwr@backfill || true

  log "Local health checks"
  curl -fsS "http://127.0.0.1:${SIGNALHUB_PORT}/healthz" || true
  echo
  curl -fsS "http://127.0.0.1:${APP_PORT}/health" || true
  echo
}

main() {
  install_packages
  install_node
  ensure_user
  sync_repo
  setup_python
  build_frontend
  write_signalhub_env
  write_main_config
  install_services
  install_nginx
  install_runtime_maintenance
  maybe_issue_cert
  show_status
  log "Done. If DNS already points to this server, open: http://${DOMAIN}/"
}

main "$@"
