export type RefreshMode = "normal" | "fast" | "super";

export interface AuthUser {
  id: number;
  nickname: string;
  email: string;
  role: "admin" | "user";
  status: "active" | "disabled" | "archived";
}

export interface AuthMeResponse {
  authenticated: boolean;
  user?: AuthUser;
  home_path?: string;
}

export interface AuthSuccessResponse {
  ok: boolean;
  user: AuthUser;
  home_path: string;
}

export interface AuthRegisterPendingResponse {
  ok: boolean;
  requires_verification: boolean;
  email: string;
  expires_at: number;
}

export interface AuthResendVerificationResponse {
  ok: boolean;
  email: string;
  expires_at: number;
}

export interface LaunchConfig {
  name: string;
  internal_pool_addr: string;
  fee_addr: string;
  tax_addr: string;
  token_total_supply: string;
  fee_rate: string;
  is_enabled: number;
  created_at?: number;
  updated_at?: number;
}

export interface MetaResponse {
  projects: string[];
  wallets: string[];
  topN: number;
  launchConfigs: LaunchConfig[];
  managedProjects: ManagedProjectItem[];
  monitoringProjects: string[];
  fixedDefaults: {
    fee_addr: string;
    tax_addr: string;
    token_total_supply: string;
    fee_rate: string;
  };
  runtimeTuning: {
    db_batch_size: number;
    runtime_paused: boolean;
    runtime_manual_paused: boolean;
    runtime_ui_online: boolean;
    runtime_ui_last_seen_at: number | null;
    runtime_ui_heartbeat_timeout_sec: number;
  };
  signalHub: {
    enabled: boolean;
    upcoming_limit: number;
    within_hours: number;
  };
}

export interface AppMetaResponse {
  user: AuthUser;
  wallet_count: number;
  credit_balance: number;
  credit_spent_total: number;
  credit_granted_total: number;
  unlocked_project_count: number;
  unread_notification_count: number;
  visible_project_statuses: string[];
  has_active_project: boolean;
  default_path: string;
  projects: ManagedProjectItem[];
}

export interface HealthResponse {
  ok: boolean;
  queueSize: number;
  pendingTx: number;
  stats: Record<string, number | string | boolean | null>;
  lastProcessedBlock: string | null;
  price: string | null;
  monitoringProjects: string[];
  scanJobs: number;
  backfillRpcMode: string;
  backfillRpcPool: BackfillRpcPoolItem[];
  backfillRpcUsage: BackfillRpcUsageSummary;
  role: string;
  runtimePaused: boolean;
  runtimeManualPaused: boolean;
  runtimeUiOnline: boolean;
  runtimeUiLastSeenAt: number | null;
  runtimeUiHeartbeatTimeoutSec: number;
  runtimePauseUpdatedAt: number | null;
}

export interface BackfillRpcPoolItem {
  label: string;
  url: string;
  supportsBasicRpc: boolean | null;
  supportsHistoricalBlocks: boolean | null;
  supportsLogs: boolean | null;
  cooldownUntil: number | null;
  isCoolingDown: boolean;
  lastError: string | null;
  lastCheckedAt: number | null;
  requestCount: number;
  estimatedRu: number;
  lastUsedAt: number | null;
  basicRequestCount: number;
  historicalBlockRequestCount: number;
  logsRequestCount: number;
}

export interface BackfillRpcUsageSummary {
  totalRequestCount: number;
  totalEstimatedRu: number;
  lastUsedAt: number | null;
  isEstimated: boolean;
}

export interface SignalHubItem {
  projectId: string;
  importName: string;
  displayTitle: string;
  name: string;
  symbol: string;
  status: string;
  launchTime: string;
  secondsToLaunch: number | null;
  contractAddress: string | null;
  contractReady: boolean;
  url: string;
  creator: string | null;
  description: string;
  team: string;
  lifecycleStage: string;
  projectScore: number | null;
  scoreGrade: string;
  riskLevel: string;
  watchlist: boolean;
  links: Array<{ label?: string; url?: string }>;
  liquidityPool: string | null;
  treasuryAddress: string | null;
  analysisError: string | null;
  syncReady: boolean;
  managedProjectId?: number | null;
  managedStatus?: string;
  resolvedEndAt?: number | null;
  isUnlocked?: boolean;
  unlockCost?: number;
  canUnlockNow?: boolean;
}

export interface SignalHubResponse {
  enabled: boolean;
  available: boolean;
  message: string;
  source: string;
  generatedAt: string;
  count: number;
  withinHours: number;
  limit: number;
  items: SignalHubItem[];
}

export interface MinuteRow {
  project: string;
  minute_key: number;
  minute_spent_v: string;
  minute_fee_v: string;
  minute_tax_v: string;
  minute_buy_count: number;
  minute_unique_buyers: number;
  updated_at: number;
}

export interface LeaderboardRow {
  project: string;
  buyer: string;
  sum_spent_v_est: string;
  sum_token_bought: string;
  last_tx_time: number;
  updated_at: number;
  avg_cost_v?: string;
  breakeven_fdv_v?: string;
  breakeven_fdv_usd?: string | null;
}

export interface WalletPositionRow {
  project: string;
  wallet: string;
  token_addr: string;
  sum_fee_v: string;
  sum_spent_v_est: string;
  sum_token_bought: string;
  avg_cost_v: string;
  total_supply: string;
  breakeven_fdv_v: string;
  virtual_price_usd: string | null;
  breakeven_fdv_usd: string | null;
  updated_at: number;
}

export interface EventDelayRow {
  project: string;
  tx_hash: string;
  block_timestamp: number;
  recorded_at: number;
  delay_sec: number;
}

export interface ProjectTaxResponse {
  project: string;
  sum_tax_v: string;
  updated_at: number;
}

export interface ManagedProjectItem {
  id: number;
  name: string;
  signalhub_project_id: string | null;
  detail_url: string;
  token_addr: string | null;
  internal_pool_addr: string | null;
  start_at: number;
  signalhub_end_at: number | null;
  manual_end_at: number | null;
  resolved_end_at: number;
  is_watched: number;
  collect_enabled: number;
  backfill_enabled: number;
  status: string;
  source: string;
  created_at: number;
  updated_at: number;
  is_unlocked?: boolean;
  unlock_cost?: number;
  can_unlock_now?: boolean;
  unlocked_at?: number | null;
}

export interface WalletConfigItem {
  wallet: string;
  name: string;
  created_at: number;
  updated_at: number;
}

export interface UserWalletItem {
  id: number;
  user_id: number;
  wallet: string;
  name: string;
  is_enabled: boolean;
  created_at: number;
  updated_at: number;
}

export interface WalletConfigsResponse {
  count: number;
  items: WalletConfigItem[];
}

export interface UserWalletsResponse {
  count: number;
  items: UserWalletItem[];
}

export interface WalletsResponse {
  count: number;
  items: WalletPositionRow[];
}

export interface RuntimePauseResponse {
  ok: boolean;
  runtimePaused: boolean;
  runtimeManualPaused: boolean;
  runtimeUiOnline: boolean;
  runtimeUiLastSeenAt: number | null;
  runtimeUiHeartbeatTimeoutSec: number;
  updatedAt: number | null;
}

export interface DbBatchResponse {
  ok: boolean;
  dbBatchSize: number;
}

export interface ScanJobResponse {
  id: string;
  status: string;
  project: string | null;
  startTs: number;
  endTs: number;
  createdAt: number;
  startedAt?: number;
  finishedAt?: number;
  cancelRequested?: boolean;
  progress?: Record<string, unknown>;
  error?: string;
}

export interface ProjectSchedulerItem {
  id: number;
  name: string;
  status: string;
  projectedStatus: string;
  startAt: number;
  resolvedEndAt: number;
  chartFromAt: number | null;
  chartToAt: number | null;
  lastScanJobId: string | null;
  lastScanQueuedAt: number | null;
  isWatched: boolean;
  collectEnabled: boolean;
  backfillEnabled: boolean;
  isComplete: boolean;
}

export interface ProjectSchedulerStatusResponse {
  ok: boolean;
  intervalSec: number;
  prelaunchLeadSec: number;
  runtimePaused: boolean;
  activeCount: number;
  count: number;
  lastRunAt: number | null;
  items: ProjectSchedulerItem[];
}

export interface OverviewBoardItem {
  wallet: string;
  name: string;
  spentV: string;
  tokenBought: string;
  breakevenFdvUsd?: string | null;
  updatedAt: number;
}

export interface OverviewActiveProjectOption {
  id: number;
  name: string;
  status: string;
  projectedStatus: string;
  startAt: number;
  resolvedEndAt: number;
}

export interface OverviewActiveProjectItem {
  id: number;
  name: string;
  status: string;
  projectedStatus: string;
  startAt: number;
  resolvedEndAt: number;
  detailUrl: string;
  tokenAddr: string | null;
  internalPoolAddr: string | null;
  sumTaxV: string;
  chartFromAt: number;
  chartToAt: number;
}

export interface OverviewActiveResponse {
  ok: boolean;
  viewMode?: "active" | "project";
  requestedProject: string;
  hasActiveProject: boolean;
  activeProjects: OverviewActiveProjectOption[];
  item: OverviewActiveProjectItem | null;
  minutes: MinuteRow[];
  whaleBoard: OverviewBoardItem[];
  trackedWallets: OverviewBoardItem[];
  delays: EventDelayRow[];
}

export interface ProjectAccessState {
  projectId: number;
  isUnlocked: boolean;
  unlockCost: number;
  canUnlockNow: boolean;
  creditBalance: number;
  unlockedAt: number | null;
}

export interface BillingPlan {
  id: string;
  credits: number;
  priceCny: number;
  label: string;
}

export interface BillingSummaryResponse {
  ok: boolean;
  credit_balance: number;
  credit_spent_total: number;
  credit_granted_total: number;
  unlocked_project_count: number;
  pending_request_count: number;
  unread_notification_count: number;
  plans: BillingPlan[];
  contact_qr_url: string;
  contact_hint: string;
  notice: string;
  referral_url: string;
}

export interface AppNotificationItem {
  id: number;
  title: string;
  body: string;
  kind: "success" | "warning" | "info" | "accent";
  delta: number;
  type: string;
  projectName: string | null;
  createdAt: number;
  isRead: boolean;
  readAt: number | null;
  actionUrl?: string | null;
  sourceId?: number | null;
}

export interface AppNotificationsResponse {
  ok: boolean;
  count: number;
  unreadCount: number;
  items: AppNotificationItem[];
}

export interface BillingRequestItem {
  id: number;
  user_id?: number;
  userNickname?: string | null;
  userEmail?: string | null;
  plan_id: string;
  requested_credits: number;
  payment_amount: string;
  note: string;
  proof_original_name: string;
  proof_content_type: string;
  proof_size: number;
  proof_url: string | null;
  status: "pending_review" | "credited" | "notified";
  status_label: string;
  admin_note: string;
  credited_credit_ledger_id: number | null;
  operator_user_id?: number | null;
  operatorNickname?: string | null;
  operatorEmail?: string | null;
  created_at: number;
  updated_at: number;
  reviewed_at: number | null;
  credited_at: number | null;
  notified_at: number | null;
}

export interface BillingRequestsResponse {
  ok: boolean;
  count: number;
  items: BillingRequestItem[];
}

export interface ProjectAccessResponse {
  ok: boolean;
  project: {
    id: number;
    name: string;
    status: string;
    detailUrl: string;
    startAt: number;
    resolvedEndAt: number;
  };
  access: ProjectAccessState;
}

export interface ProjectUnlockResponse {
  ok: boolean;
  alreadyUnlocked: boolean;
  credit_balance: number;
  access: ProjectAccessState;
  item?: UserProjectAccessItem;
}

export interface ProjectLockedResponse {
  error: string;
  code: "project_locked";
  requestedProject: string;
  hasActiveProject: boolean;
  activeProjects: OverviewActiveProjectOption[];
  project: OverviewActiveProjectItem;
  access: ProjectAccessState;
  billing: BillingSummaryResponse;
}

export interface ManagedProjectsResponse {
  count: number;
  items: ManagedProjectItem[];
}

export interface ManagedProjectUpsertPayload {
  id?: number;
  signalhub_project_id?: string | null;
  name: string;
  detail_url?: string;
  token_addr?: string | null;
  internal_pool_addr?: string | null;
  start_at: number;
  signalhub_end_at?: number | null;
  manual_end_at?: number | null;
  is_watched?: boolean;
  collect_enabled?: boolean;
  backfill_enabled?: boolean;
  status?: string;
  source?: string;
}

export interface DraftProject {
  projectId: string;
  importName: string;
  displayTitle: string;
  internal_pool_addr: string;
  notes: string;
  updatedAt: number;
}

export interface AdminUserSummary {
  id: number;
  nickname: string;
  email: string;
  role: "admin" | "user";
  status: "active" | "disabled" | "archived";
  source: "self_signup" | "admin_created";
  wallet_count: number;
  credit_balance: number;
  credit_spent_total: number;
  credit_granted_total: number;
  unlocked_project_count: number;
  password_set: boolean;
  password_updated_at: number;
  email_verified_at: number | null;
  last_login_at: number | null;
  created_at: number;
  updated_at: number;
}

export type AdminUserDetail = AdminUserSummary;

export interface CreditLedgerItem {
  id: number;
  user_id: number;
  delta: number;
  balance_after: number;
  type: string;
  source: string;
  project_id: number | null;
  project_name?: string | null;
  payment_amount: string;
  payment_proof_ref: string;
  note: string;
  operator_user_id: number | null;
  operator_nickname?: string | null;
  operator_email?: string | null;
  created_at: number;
}

export interface LegacyApiItem {
  path: string;
  replacement: string;
  access: "admin" | "public";
  state: "compatible";
}

export interface LegacyApisResponse {
  ok: boolean;
  count: number;
  items: LegacyApiItem[];
}

export interface UserProjectAccessItem {
  id: number;
  user_id: number;
  project_id: number;
  project_name?: string | null;
  project_detail_url?: string | null;
  project_status?: string | null;
  project_start_at?: number | null;
  project_resolved_end_at?: number | null;
  unlock_cost: number;
  source: string;
  unlocked_at: number;
  expires_at: number | null;
  created_at: number;
}

export interface AdminUsersResponse {
  count: number;
  items: AdminUserSummary[];
}
