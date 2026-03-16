import { requestJson } from "@/api/client";
import type {
  AdminUserDetail,
  AdminUsersResponse,
  AppMetaResponse,
  AppNotificationsResponse,
  AuthMeResponse,
  AuthRegisterPendingResponse,
  AuthResendVerificationResponse,
  AuthSuccessResponse,
  BillingRequestsResponse,
  BillingSummaryResponse,
  CreditLedgerItem,
  DbBatchResponse,
  EventDelayRow,
  HealthResponse,
  LaunchConfig,
  LegacyApisResponse,
  LeaderboardRow,
  ManagedProjectItem,
  ManagedProjectUpsertPayload,
  ManagedProjectsResponse,
  MetaResponse,
  MinuteRow,
  OverviewActiveResponse,
  ProjectAccessResponse,
  ProjectSchedulerStatusResponse,
  ProjectUnlockResponse,
  ProjectTaxResponse,
  RuntimePauseResponse,
  ScanJobResponse,
  SignalHubResponse,
  UserProjectAccessItem,
  UserWalletItem,
  UserWalletsResponse,
  WalletConfigsResponse,
  WalletsResponse,
} from "@/types/api";

export const dashboardApi = {
  auth: {
    me() {
      return requestJson<AuthMeResponse>("/api/auth/me");
    },
    login(email: string, password: string) {
      return requestJson<AuthSuccessResponse>("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
    },
    register(nickname: string, email: string, password: string) {
      return requestJson<AuthRegisterPendingResponse>("/api/auth/register", {
        method: "POST",
        body: { nickname, email, password },
      });
    },
    resendVerification(email: string) {
      return requestJson<AuthResendVerificationResponse>("/api/auth/resend-verification", {
        method: "POST",
        body: { email },
      });
    },
    verifyEmail(token: string) {
      return requestJson<AuthSuccessResponse>("/api/auth/verify-email", {
        params: { token },
      });
    },
    logout() {
      return requestJson<{ ok: boolean }>("/api/auth/logout", {
        method: "POST",
        body: {},
      });
    },
  },

  admin: {
    getMeta() {
      return requestJson<MetaResponse>("/api/admin/meta");
    },
    getHealth() {
      return requestJson<HealthResponse>("/api/admin/health");
    },
    getSignalHubUpcoming(limit: number, withinHours: number) {
      return requestJson<SignalHubResponse>("/api/admin/signalhub", {
        params: { limit, within_hours: withinHours },
      });
    },
    getLaunchConfigs() {
      return requestJson<{ count: number; items: LaunchConfig[] }>("/api/admin/launch-configs");
    },
    getManagedProjects() {
      return requestJson<ManagedProjectsResponse>("/api/admin/projects");
    },
    upsertManagedProject(payload: ManagedProjectUpsertPayload) {
      return requestJson<{ ok: boolean; item: ManagedProjectItem; count: number; items: ManagedProjectItem[] }>(
        "/api/admin/projects",
        {
          method: "POST",
          body: payload,
        },
      );
    },
    deleteManagedProject(projectId: number) {
      return requestJson<{ ok: boolean; count: number; items: ManagedProjectItem[] }>(
        `/api/admin/projects/${projectId}`,
        {
          method: "DELETE",
        },
      );
    },
    upsertLaunchConfig(payload: {
      name: string;
      internal_pool_addr: string;
      is_enabled?: boolean;
      switch_only?: boolean;
    }) {
      return requestJson<{ ok: boolean; monitoringProjects: string[]; items: LaunchConfig[] }>(
        "/api/admin/launch-configs",
        {
          method: "POST",
          body: payload,
        },
      );
    },
    deleteLaunchConfig(name: string) {
      return requestJson<{ ok: boolean; monitoringProjects: string[]; items: LaunchConfig[] }>(
        `/api/admin/launch-configs/${encodeURIComponent(name)}`,
        {
          method: "DELETE",
        },
      );
    },
    getWalletConfigs() {
      return requestJson<WalletConfigsResponse>("/api/admin/wallets");
    },
    addWallet(wallet: string, name = "") {
      return requestJson<WalletConfigsResponse & { ok: boolean }>("/api/admin/wallets", {
        method: "POST",
        body: { wallet, name },
      });
    },
    deleteWallet(wallet: string) {
      return requestJson<WalletConfigsResponse & { ok: boolean }>(
        `/api/admin/wallets/${encodeURIComponent(wallet)}`,
        {
          method: "DELETE",
        },
      );
    },
    recalcWallet(project: string, wallet: string) {
      return requestJson<{
        ok: boolean;
        project: string;
        wallet: string;
        eventCount: number;
        tokenCount: number;
        durationMs: number;
      }>("/api/admin/wallet-recalc", {
        method: "POST",
        body: { project, wallet },
      });
    },
    getRuntimePause() {
      return requestJson<RuntimePauseResponse>("/api/admin/runtime/pause");
    },
    setRuntimePause(paused: boolean) {
      return requestJson<RuntimePauseResponse>("/api/admin/runtime/pause", {
        method: "POST",
        body: { paused },
      });
    },
    sendHeartbeat() {
      return requestJson<RuntimePauseResponse>("/api/admin/runtime/heartbeat", {
        method: "POST",
        body: {},
      });
    },
    getDbBatchSize() {
      return requestJson<DbBatchResponse>("/api/admin/runtime/db-batch-size");
    },
    setDbBatchSize(db_batch_size: number) {
      return requestJson<DbBatchResponse>("/api/admin/runtime/db-batch-size", {
        method: "POST",
        body: { db_batch_size },
      });
    },
    getProjectSchedulerStatus() {
      return requestJson<ProjectSchedulerStatusResponse>("/api/admin/project-scheduler/status");
    },
    getOverviewActive(project = "") {
      return requestJson<OverviewActiveResponse>("/api/admin/overview-active", {
        params: project ? { project } : {},
      });
    },
    getProjectOverview(projectId: number) {
      return requestJson<OverviewActiveResponse>(`/api/admin/projects/${projectId}/overview`);
    },
    createScanJob(project: string | null, startTs: number, endTs: number) {
      return requestJson<{ ok: boolean; jobId: string }>("/api/admin/scan-range", {
        method: "POST",
        body: { project, start_ts: startTs, end_ts: endTs },
      });
    },
    getScanJob(jobId: string) {
      return requestJson<ScanJobResponse>(`/api/admin/scan-jobs/${encodeURIComponent(jobId)}`);
    },
    cancelScanJob(jobId: string) {
      return requestJson<{ ok: boolean; alreadyFinal: boolean; job: ScanJobResponse }>(
        `/api/admin/scan-jobs/${encodeURIComponent(jobId)}/cancel`,
        {
          method: "POST",
          body: {},
        },
      );
    },
    getWallets(project: string) {
      return requestJson<WalletsResponse>("/api/admin/mywallets", {
        params: { project },
      });
    },
    getMinutes(project: string, from: number, to: number) {
      return requestJson<{ project: string; count: number; items: MinuteRow[] }>("/api/admin/minutes", {
        params: { project, from, to },
      });
    },
    getLeaderboard(project: string, top: number) {
      return requestJson<{ project: string; top: number; items: LeaderboardRow[] }>(
        "/api/admin/leaderboard",
        {
          params: { project, top },
        },
      );
    },
    getEventDelays(project: string, limit: number) {
      return requestJson<{ project: string; count: number; items: EventDelayRow[] }>(
        "/api/admin/event-delays",
        {
          params: { project, limit },
        },
      );
    },
    getProjectTax(project: string) {
      return requestJson<ProjectTaxResponse>("/api/admin/project-tax", {
        params: { project },
      });
    },
    getUsers(params?: { q?: string; status?: string; role?: string }) {
      return requestJson<AdminUsersResponse>("/api/admin/users", { params });
    },
    getUserDetail(userId: number) {
      return requestJson<{ ok: boolean; item: AdminUserDetail }>(`/api/admin/users/${userId}`);
    },
    getUserWallets(userId: number) {
      return requestJson<UserWalletsResponse>(`/api/admin/users/${userId}/wallets`);
    },
    getUserCreditLedger(userId: number) {
      return requestJson<{ count: number; items: CreditLedgerItem[] }>(
        `/api/admin/users/${userId}/credit-ledger`,
      );
    },
    getUserProjectAccess(userId: number) {
      return requestJson<{ count: number; items: UserProjectAccessItem[] }>(
        `/api/admin/users/${userId}/project-access`,
      );
    },
    getLegacyApis() {
      return requestJson<LegacyApisResponse>("/api/admin/legacy-apis");
    },
    getBillingRequests(params?: { status?: string; q?: string; limit?: number }) {
      return requestJson<BillingRequestsResponse>("/api/admin/billing/requests", { params });
    },
    setUserStatus(userId: number, status: "active" | "disabled") {
      return requestJson<{ ok: boolean; item: AdminUserDetail }>(`/api/admin/users/${userId}/status`, {
        method: "POST",
        body: { status },
      });
    },
    resetUserPassword(userId: number, newPassword: string) {
      return requestJson<{ ok: boolean; item: AdminUserDetail; password_updated_at: number }>(
        `/api/admin/users/${userId}/reset-password`,
        {
          method: "POST",
          body: { new_password: newPassword },
        },
      );
    },
    adjustUserCredits(userId: number, payload: { delta: number; note: string }) {
      return requestJson<{ ok: boolean; item: AdminUserDetail }>(
        `/api/admin/users/${userId}/credits/adjust`,
        {
          method: "POST",
          body: payload,
        },
      );
    },
    topupUserCredits(
      userId: number,
      payload: { credits: number; amount_paid?: string; payment_proof_ref?: string; note?: string },
    ) {
      return requestJson<{ ok: boolean; item: AdminUserDetail }>(
        `/api/admin/users/${userId}/credits/topup`,
        {
          method: "POST",
          body: payload,
        },
      );
    },
    creditBillingRequest(
      requestId: number,
      payload: { credits?: number; amount_paid?: string; admin_note?: string },
    ) {
      return requestJson<{ ok: boolean; item: BillingRequestsResponse["items"][number] }>(
        `/api/admin/billing/requests/${requestId}/credit`,
        {
          method: "POST",
          body: payload,
        },
      );
    },
    notifyBillingRequest(requestId: number, payload: { admin_note?: string }) {
      return requestJson<{ ok: boolean; item: BillingRequestsResponse["items"][number] }>(
        `/api/admin/billing/requests/${requestId}/notify`,
        {
          method: "POST",
          body: payload,
        },
      );
    },
    setUserWalletStatus(userId: number, walletId: number, isEnabled: boolean) {
      return requestJson<{ ok: boolean; item: UserWalletItem }>(
        `/api/admin/users/${userId}/wallets/${walletId}/status`,
        {
          method: "POST",
          body: { is_enabled: isEnabled },
        },
      );
    },
    deleteUserWallet(userId: number, walletId: number) {
      return requestJson<{ ok: boolean; count: number; items: UserWalletItem[] }>(
        `/api/admin/users/${userId}/wallets/${walletId}`,
        {
          method: "DELETE",
        },
      );
    },
  },

  app: {
    getMeta() {
      return requestJson<AppMetaResponse>("/api/app/meta");
    },
    getBillingSummary() {
      return requestJson<BillingSummaryResponse>("/api/app/billing/summary");
    },
    getNotifications(limit = 12) {
      return requestJson<AppNotificationsResponse>("/api/app/notifications", {
        params: { limit },
      });
    },
    markNotificationRead(notificationId: number) {
      return requestJson<{ ok: boolean; item: AppNotificationsResponse["items"][number]; unreadCount: number }>(
        `/api/app/notifications/${notificationId}/read`,
        {
          method: "POST",
          body: {},
        },
      );
    },
    markAllNotificationsRead() {
      return requestJson<{ ok: boolean; updated: number; unreadCount: number }>(
        "/api/app/notifications/read-all",
        {
          method: "POST",
          body: {},
        },
      );
    },
    getBillingRequests(limit = 50) {
      return requestJson<BillingRequestsResponse>("/api/app/billing/requests", {
        params: { limit },
      });
    },
    createBillingRequest(formData: FormData) {
      return requestJson<{ ok: boolean; item: BillingRequestsResponse["items"][number] }>(
        "/api/app/billing/requests",
        {
          method: "POST",
          body: formData,
        },
      );
    },
    getOverviewActive(project = "") {
      return requestJson<OverviewActiveResponse>("/api/app/overview-active", {
        params: project ? { project } : {},
      });
    },
    getProjects(params?: { status?: string; q?: string }) {
      return requestJson<ManagedProjectsResponse>("/api/app/projects", { params });
    },
    getProjectOverview(projectId: number) {
      return requestJson<OverviewActiveResponse>(`/api/app/projects/${projectId}/overview`);
    },
    getProjectAccess(projectId: number) {
      return requestJson<ProjectAccessResponse>(`/api/app/projects/${projectId}/access`);
    },
    unlockProject(projectId: number) {
      return requestJson<ProjectUnlockResponse>(`/api/app/projects/${projectId}/unlock`, {
        method: "POST",
        body: {},
      });
    },
    getSignalHubUpcoming(limit: number, withinHours: number) {
      return requestJson<SignalHubResponse>("/api/app/signalhub", {
        params: { limit, within_hours: withinHours },
      });
    },
    getWallets() {
      return requestJson<UserWalletsResponse>("/api/app/wallets");
    },
    addWallet(wallet: string, name = "") {
      return requestJson<UserWalletsResponse & { ok: boolean; item: UserWalletItem }>("/api/app/wallets", {
        method: "POST",
        body: { wallet, name },
      });
    },
    updateWallet(walletId: number, payload: { name?: string; is_enabled?: boolean }) {
      return requestJson<{ ok: boolean; item: UserWalletItem }>(`/api/app/wallets/${walletId}`, {
        method: "PATCH",
        body: payload,
      });
    },
    deleteWallet(walletId: number) {
      return requestJson<UserWalletsResponse & { ok: boolean }>(`/api/app/wallets/${walletId}`, {
        method: "DELETE",
      });
    },
    getWalletPositions(project: string) {
      return requestJson<WalletsResponse>("/api/app/wallets/positions", {
        params: { project },
      });
    },
  },
};
