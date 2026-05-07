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
  config.example.json
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
  docs/requirements-outline.md
  docs/plan-index.md
  docs/todo-index.md
  docs/rpc-provider-benchmark-2026-04-29.md
  docs/ISC-native-replay-test-2026-04-30.md
  docs/ISC-chainstack-native-replay-test-2026-05-07.md
  docs/chainstack-test-runbook.md
  docs/chainstack-full-window-test-2026-05-07.md
  docs/launch-strategy-backtest-2026-05-07.md
  docs/sr-strategy-scenario-suite-2026-05-07.md
  docs/sr-strategy-ablation-suite-2026-05-07.md
  docs/phases/phase-052-strategy-test-matrix-plan.md
  docs/phases/phase-052-strategy-test-matrix-todo.md
  docs/phases/phase-052-strategy-test-matrix-report.md
  scripts/ops/backup_runtime.sh
  scripts/ops/native_launch_replay.py
  scripts/ops/backtest_launch_strategy.py
  scripts/ops/sr_strategy_scenario_suite.py
  scripts/ops/sr_strategy_ablation_suite.py
  scripts/ops/strategy_test_matrix_runner.py
  scripts/ops/run_chainstack_test_suite.py
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
