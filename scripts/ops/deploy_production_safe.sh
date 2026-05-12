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
  requirements.txt
  virtuals_bot.py
  signalhub_client.py
  SignalHub-main/signalhub/app/api/routes.py
  SignalHub-main/signalhub/app/database/db.py
  frontend/admin/src/api/dashboard-api.ts
  frontend/admin/src/api/query-keys.ts
  frontend/admin/src/app/App.tsx
  frontend/admin/src/app/shell.tsx
  frontend/admin/src/components/project-overview-sections.tsx
  frontend/admin/src/pages/InboxPage.tsx
  frontend/admin/src/pages/OverviewPage.tsx
  frontend/admin/src/pages/SettingsPage.tsx
  frontend/admin/src/types/api.ts
  frontend/admin/dist/
  docs/PLAN.md
  docs/todo.md
  docs/源码导读图.md
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
  docs/phases/phase-052-dynamic-buy-recalc-2026-05-10.md
  docs/phases/phase-052-dynamic-buy-recalc-after1-flat10-2026-05-10.md
  docs/phases/phase-052-dual-sell-strategy-2026-05-11.md
  docs/phases/phase-052-final-dynamic-buy-strategy-2026-05-10.md
  docs/phases/phase-052-isc-event-level-replay-2026-05-10.md
  docs/phases/phase-052-sell-half-tax30-spot-pump10-2026-05-11.md
  docs/phases/phase-052-sell-trigger-tax30-large5ku-profit50-2026-05-11.md
  docs/phases/phase-052-sr-event-level-replay-2026-05-10.md
  docs/phases/phase-052-sr-only-latest-gates-2026-05-10.md
  docs/phases/phase-053-launch-execution-pipeline-plan.md
  docs/phases/phase-053-launch-execution-pipeline-todo.md
  docs/phases/phase-053-local-signer-no-broadcast-2026-05-10.md
  docs/phases/phase-053-virtuals-buy-calldata-research-2026-05-10.md
  docs/phases/phase-053-virtuals-buy-route-universality-audit-2026-05-10.md
  docs/phases/phase-053-virtuals-buy-spender-trace-2026-05-10.md
  docs/phases/phase-053-virtuals-order-binding-minout-2026-05-10.md
  scripts/ops/backup_runtime.sh
  scripts/ops/approve_erc20_spender.py
  scripts/ops/approve_virtual_spender.py
  scripts/ops/bench_execution_rpc.py
  scripts/ops/buy_virtual_canary.py
  scripts/ops/execution_rpc.py
  scripts/ops/launch_execution_fuse.py
  scripts/ops/launch_execution_pipeline.py
  scripts/ops/launch_latency_probe.py
  scripts/ops/launch_prewarm_executor.py
  scripts/ops/launch_readiness_check.py
  scripts/ops/launch_rpc_pressure_probe.py
  scripts/ops/launch_sell_strategy.py
  scripts/ops/launch_sell_executor.py
  scripts/ops/live_strategy_dry_run.py
  scripts/ops/local_signer_probe.py
  scripts/ops/native_launch_replay.py
  scripts/ops/backtest_launch_strategy.py
  scripts/ops/prewarmed_buy_canary.py
  scripts/ops/recalc_dual_sell_strategy.py
  scripts/ops/recalc_dynamic_buy_strategy.py
  scripts/ops/recalc_sell_half_pump_strategy.py
  scripts/ops/recalc_sell_trigger_strategy.py
  scripts/ops/sell_virtuals_token.py
  scripts/ops/sr_event_level_replay.py
  scripts/ops/sr_strategy_scenario_suite.py
  scripts/ops/sr_strategy_ablation_suite.py
  scripts/ops/sr_strategy_recalc_from_matrix.py
  scripts/ops/strategy_test_matrix_runner.py
  scripts/ops/test_execution_rpc.py
  scripts/ops/test_launch_execution_pipeline.py
  scripts/ops/test_launch_rpc_pressure_probe.py
  scripts/ops/test_launch_prewarm_executor.py
  scripts/ops/test_launch_sell_executor.py
  scripts/ops/test_launch_sell_strategy.py
  scripts/ops/tx_simulator_probe.py
  scripts/ops/virtuals_buy_calldata_research.py
  scripts/ops/virtuals_buy_route_universality_audit.py
  scripts/ops/virtuals_buy_spender_trace.py
  scripts/ops/run_chainstack_test_suite.py
  scripts/ops/deploy_production_safe.sh
  deploy/systemd/vwr-launch-autobuy@.service
  deploy/systemd/vwr-launch-autosell@.service
  deploy/systemd/vwr-launch-roo-start.service
  deploy/systemd/vwr-launch-roo-start.timer
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
