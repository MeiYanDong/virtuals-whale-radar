#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/virtuals-whale-radar}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
TIMESTAMP="$(date +%F-%H%M%S)"

mkdir -p "${BACKUP_DIR}"
chmod 750 "${BACKUP_DIR}"

TMP_DIR="$(mktemp -d "${BACKUP_DIR}/.tmp-${TIMESTAMP}-XXXXXX")"
STAGE_DIR="${TMP_DIR}/virtuals-whale-radar-backup-${TIMESTAMP}"
ARCHIVE_PATH="${BACKUP_DIR}/virtuals-whale-radar-backup-${TIMESTAMP}.tgz"
mkdir -p "${STAGE_DIR}/data" "${STAGE_DIR}/config" "${STAGE_DIR}/system"

backup_sqlite() {
  local src="$1"
  local dest="$2"
  if [[ -f "${src}" ]]; then
    sqlite3 "${src}" ".backup '${dest}'"
  fi
}

copy_file_if_exists() {
  local src="$1"
  local dest="$2"
  if [[ -f "${src}" ]]; then
    if [[ ! -r "${src}" ]]; then
      printf 'skip unreadable file: %s\n' "${src}" >&2
      return
    fi
    install -m 600 "${src}" "${dest}"
  fi
}

copy_dir_if_exists() {
  local src="$1"
  local dest="$2"
  if [[ -d "${src}" ]]; then
    if [[ ! -r "${src}" ]]; then
      printf 'skip unreadable directory: %s\n' "${src}" >&2
      return
    fi
    mkdir -p "${dest}"
    cp -a "${src}/." "${dest}/"
  fi
}

backup_sqlite "${APP_DIR}/data/virtuals_v11.db" "${STAGE_DIR}/data/virtuals_v11.db"
backup_sqlite "${APP_DIR}/data/virtuals_bus.db" "${STAGE_DIR}/data/virtuals_bus.db"
backup_sqlite "${APP_DIR}/SignalHub-main/signalhub.db" "${STAGE_DIR}/data/signalhub.db"

copy_file_if_exists "${APP_DIR}/data/events.jsonl" "${STAGE_DIR}/data/events.jsonl"
copy_file_if_exists "${APP_DIR}/config.json" "${STAGE_DIR}/config/config.json"
copy_file_if_exists "${APP_DIR}/SignalHub-main/.env" "${STAGE_DIR}/config/signalhub.env"
copy_file_if_exists "/etc/nginx/sites-available/virtuals-whale-radar.conf" "${STAGE_DIR}/system/nginx-virtuals-whale-radar.conf"
copy_file_if_exists "/etc/systemd/system/vwr@.service" "${STAGE_DIR}/system/vwr@.service"
copy_file_if_exists "/etc/systemd/system/vwr-signalhub.service" "${STAGE_DIR}/system/vwr-signalhub.service"
copy_file_if_exists "/etc/systemd/system/vwr-signalhub.service.d/rpc-env.conf" "${STAGE_DIR}/system/vwr-signalhub-rpc-env.conf"
copy_file_if_exists "/etc/systemd/system/vwr-backup.service" "${STAGE_DIR}/system/vwr-backup.service"
copy_file_if_exists "/etc/systemd/system/vwr-backup.timer" "${STAGE_DIR}/system/vwr-backup.timer"
copy_file_if_exists "/etc/logrotate.d/virtuals-whale-radar" "${STAGE_DIR}/system/logrotate-virtuals-whale-radar"
copy_dir_if_exists "${APP_DIR}/data/uploads" "${STAGE_DIR}/data/uploads"
# SSL private keys are host-level secrets. Keep them out of the app runtime backup
# instead of relaxing permissions for the vwr service account.

python3 - <<PY
import json
import os
import time
from pathlib import Path

stage = Path(${STAGE_DIR@Q})
manifest = {
    "created_at": int(time.time()),
    "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "app_dir": ${APP_DIR@Q},
    "backup_dir": ${BACKUP_DIR@Q},
    "files": [],
}
for path in sorted(stage.rglob("*")):
    if path.is_file():
        manifest["files"].append(
            {
                "path": str(path.relative_to(stage)).replace("\\\\", "/"),
                "size": path.stat().st_size,
            }
        )
(stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
PY

tar -czf "${ARCHIVE_PATH}" -C "${TMP_DIR}" "$(basename "${STAGE_DIR}")"
rm -rf "${TMP_DIR}"

find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'virtuals-whale-radar-backup-*.tgz' -mtime +"${KEEP_DAYS}" -delete

printf '%s\n' "${ARCHIVE_PATH}"
