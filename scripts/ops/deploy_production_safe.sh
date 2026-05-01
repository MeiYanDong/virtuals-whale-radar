#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_HOST="${REMOTE_HOST:-47.243.172.165}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/opt/virtuals-whale-radar}"
SSH_KEY="${SSH_KEY:-/Users/myandong/.ssh/id_ed25519}"
MODE="${1:---dry-run}"

if [[ "$MODE" != "--dry-run" && "$MODE" != "--apply" ]]; then
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

RSYNC_ARGS=(-azR --no-owner --no-group --itemize-changes)
if [[ "$MODE" == "--dry-run" ]]; then
  RSYNC_ARGS+=(--dry-run)
fi

FILES=(
  virtuals_bot.py
  signalhub_client.py
  SignalHub-main/signalhub/app/api/routes.py
  SignalHub-main/signalhub/app/database/db.py
  frontend/admin/src/api/dashboard-api.ts
  frontend/admin/src/api/query-keys.ts
  frontend/admin/src/components/project-overview-sections.tsx
  frontend/admin/src/pages/InboxPage.tsx
  frontend/admin/src/pages/OverviewPage.tsx
  frontend/admin/src/pages/SettingsPage.tsx
  frontend/admin/src/types/api.ts
  frontend/admin/dist/
  docs/PLAN.md
  docs/todo.md
  docs/ISC-native-replay-test-2026-04-30.md
  scripts/ops/backup_runtime.sh
  scripts/ops/native_launch_replay.py
  scripts/ops/deploy_production_safe.sh
)

cd "$ROOT_DIR"

echo "mode=$MODE"
echo "remote=$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"
echo "files=${#FILES[@]}"

rsync "${RSYNC_ARGS[@]}" \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude 'data/' \
  --exclude 'secrets/' \
  --exclude 'config.json' \
  --exclude 'SignalHub-main/.env' \
  --exclude 'SignalHub-main/signalhub.db' \
  -e "ssh -oBatchMode=yes -oConnectTimeout=10 -oIdentitiesOnly=yes -i $SSH_KEY" \
  "${FILES[@]}" \
  "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

if [[ "$MODE" == "--dry-run" ]]; then
  echo "dry-run only; rerun with --apply to sync."
fi
