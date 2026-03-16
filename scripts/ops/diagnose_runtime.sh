#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/virtuals-whale-radar}"
DIAG_DIR="${DIAG_DIR:-${APP_DIR}/diagnostics}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"
SIGNALHUB_HEALTH_URL="${SIGNALHUB_HEALTH_URL:-http://127.0.0.1:8000/healthz}"
SIGNALHUB_STATUS_URL="${SIGNALHUB_STATUS_URL:-http://127.0.0.1:8000/system/status}"
TIMESTAMP="$(date +%F-%H%M%S)"
WORK_DIR="${DIAG_DIR}/virtuals-whale-radar-diagnose-${TIMESTAMP}"
ARCHIVE_PATH="${DIAG_DIR}/virtuals-whale-radar-diagnose-${TIMESTAMP}.tgz"

mkdir -p "${WORK_DIR}"
chmod 750 "${DIAG_DIR}"

capture() {
  local dest="$1"
  shift
  "$@" >"${dest}" 2>&1 || true
}

capture "${WORK_DIR}/01-date.txt" date
capture "${WORK_DIR}/02-uname.txt" uname -a
capture "${WORK_DIR}/03-df.txt" df -h
capture "${WORK_DIR}/04-free.txt" free -h
capture "${WORK_DIR}/05-systemctl-vwr-writer.txt" systemctl status vwr@writer --no-pager
capture "${WORK_DIR}/06-systemctl-vwr-realtime.txt" systemctl status vwr@realtime --no-pager
capture "${WORK_DIR}/07-systemctl-vwr-backfill.txt" systemctl status vwr@backfill --no-pager
capture "${WORK_DIR}/08-systemctl-signalhub.txt" systemctl status vwr-signalhub.service --no-pager
capture "${WORK_DIR}/09-systemctl-backup-timer.txt" systemctl status vwr-backup.timer --no-pager
capture "${WORK_DIR}/10-list-timers.txt" systemctl list-timers --all --no-pager
capture "${WORK_DIR}/11-health.json" curl -fsS "${HEALTH_URL}"
capture "${WORK_DIR}/12-signalhub-health.json" curl -fsS "${SIGNALHUB_HEALTH_URL}"
capture "${WORK_DIR}/13-signalhub-status.json" curl -fsS "${SIGNALHUB_STATUS_URL}"
capture "${WORK_DIR}/14-journal-writer.txt" journalctl -u vwr@writer -n 300 --no-pager
capture "${WORK_DIR}/15-journal-realtime.txt" journalctl -u vwr@realtime -n 300 --no-pager
capture "${WORK_DIR}/16-journal-backfill.txt" journalctl -u vwr@backfill -n 300 --no-pager
capture "${WORK_DIR}/17-journal-signalhub.txt" journalctl -u vwr-signalhub.service -n 300 --no-pager
capture "${WORK_DIR}/18-journal-backup.txt" journalctl -u vwr-backup.service -n 100 --no-pager
capture "${WORK_DIR}/19-nginx-error-tail.txt" tail -n 200 /var/log/nginx/error.log
capture "${WORK_DIR}/20-nginx-access-tail.txt" tail -n 200 /var/log/nginx/access.log
capture "${WORK_DIR}/21-journal-disk-usage.txt" journalctl --disk-usage --no-pager

capture "${WORK_DIR}/31-count-events.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select count(*) as events_count from events;"
capture "${WORK_DIR}/32-count-minute-agg.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select count(*) as minute_agg_count from minute_agg;"
capture "${WORK_DIR}/33-count-leaderboard.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select count(*) as leaderboard_count from leaderboard;"
capture "${WORK_DIR}/34-count-wallet-positions.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select count(*) as wallet_positions_count from wallet_positions;"
capture "${WORK_DIR}/35-managed-projects.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select id, name, status, start_at, resolved_end_at, updated_at from managed_projects order by updated_at desc limit 50;"
capture "${WORK_DIR}/36-events-by-project.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select project, count(*) from events group by project order by count(*) desc;"
capture "${WORK_DIR}/37-minute-agg-by-project.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select project, count(*) from minute_agg group by project order by count(*) desc;"
capture "${WORK_DIR}/38-wallets-by-project.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select project, count(*) from wallet_positions group by project order by count(*) desc;"
capture "${WORK_DIR}/39-recent-credit-ledger.txt" sqlite3 "${APP_DIR}/data/virtuals_v11.db" "select id, user_id, delta, type, source, created_at from credit_ledger order by id desc limit 50;"

capture "${WORK_DIR}/41-bus-scan-jobs.txt" sqlite3 "${APP_DIR}/data/virtuals_bus.db" "select id, status, project, block_from, block_to, created_at, updated_at from scan_jobs order by id desc limit 50;"
capture "${WORK_DIR}/42-bus-scan-jobs-by-status.txt" sqlite3 "${APP_DIR}/data/virtuals_bus.db" "select status, count(*) from scan_jobs group by status order by count(*) desc;"
capture "${WORK_DIR}/43-bus-event-queue.txt" sqlite3 "${APP_DIR}/data/virtuals_bus.db" "select count(*) from event_queue;"
capture "${WORK_DIR}/44-backups-dir.txt" ls -lah "${APP_DIR}/backups"
capture "${WORK_DIR}/45-logrotate-config.txt" cat /etc/logrotate.d/virtuals-whale-radar

tar -czf "${ARCHIVE_PATH}" -C "${DIAG_DIR}" "$(basename "${WORK_DIR}")"
printf '%s\n' "${ARCHIVE_PATH}"
