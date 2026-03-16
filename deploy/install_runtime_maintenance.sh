#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run this script as root." >&2
  exit 1
fi

APP_DIR="${APP_DIR:-/opt/virtuals-whale-radar}"
APP_USER="${APP_USER:-vwr}"
APP_GROUP="${APP_GROUP:-${APP_USER}}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
DIAG_DIR="${DIAG_DIR:-${APP_DIR}/diagnostics}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
BACKUP_ON_CALENDAR="${BACKUP_ON_CALENDAR:-*-*-* 04:15:00}"

log() {
  echo "[vwr-maintenance] $*"
}

install -d -m 750 -o "${APP_USER}" -g "${APP_GROUP}" "${BACKUP_DIR}" "${DIAG_DIR}" "${APP_DIR}/SignalHub-main/logs"

install -d /usr/local/bin
ln -sfn "${APP_DIR}/scripts/ops/backup_runtime.sh" /usr/local/bin/vwr-backup
ln -sfn "${APP_DIR}/scripts/ops/diagnose_runtime.sh" /usr/local/bin/vwr-diagnose

cat >/etc/systemd/system/vwr-backup.service <<EOF
[Unit]
Description=Virtuals Whale Radar runtime backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=APP_DIR=${APP_DIR}
Environment=BACKUP_DIR=${BACKUP_DIR}
Environment=KEEP_DAYS=${BACKUP_KEEP_DAYS}
ExecStart=/bin/bash ${APP_DIR}/scripts/ops/backup_runtime.sh
EOF

cat >/etc/systemd/system/vwr-backup.timer <<EOF
[Unit]
Description=Run Virtuals Whale Radar runtime backup daily

[Timer]
OnCalendar=${BACKUP_ON_CALENDAR}
Persistent=true
Unit=vwr-backup.service

[Install]
WantedBy=timers.target
EOF

install -m 644 "${APP_DIR}/deploy/logrotate/virtuals-whale-radar" /etc/logrotate.d/virtuals-whale-radar

systemctl daemon-reload
systemctl enable --now vwr-backup.timer

log "Installed maintenance assets"
systemctl --no-pager --full status vwr-backup.timer || true
logrotate -d /etc/logrotate.d/virtuals-whale-radar >/dev/null 2>&1 || true
