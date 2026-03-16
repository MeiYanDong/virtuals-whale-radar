import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BellDot,
  Coins,
  Gauge,
  LogOut,
  Menu,
  MoonStar,
  RefreshCcw,
  Settings2,
  ShieldUser,
  SunMedium,
  Users,
  Wallet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation, useSearchParams } from "react-router-dom";

import { resolveProjectCandidates, resolveSelectedProject } from "@/adapters/dashboard";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { ShellContext, type ShellContextValue, type WorkspaceViewer, useShell } from "@/app/shell-context";
import { useTheme } from "@/app/use-theme";
import { useAuth } from "@/auth/use-auth";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  AppMetaResponse,
  AppNotificationsResponse,
  MetaResponse,
  RefreshMode,
  SignalHubResponse,
} from "@/types/api";

const PROJECT_STORAGE_PREFIX: Record<WorkspaceViewer, string> = {
  admin: "vwr_admin_project",
  user: "vwr_user_project",
};

const REFRESH_MODE_STORAGE_PREFIX: Record<WorkspaceViewer, string> = {
  admin: "vwr_admin_refresh_mode",
  user: "vwr_user_refresh_mode",
};

const SIDEBAR_MODE_STORAGE_PREFIX: Record<WorkspaceViewer, string> = {
  admin: "vwr_admin_sidebar_mode",
  user: "vwr_user_sidebar_mode",
};

type SidebarMode = "expanded" | "rail" | "hidden";

type WorkspaceNavItem = {
  to: string;
  label: string;
  icon: typeof Gauge;
};

const REFRESH_INTERVAL: Record<RefreshMode, number> = {
  normal: 15000,
  fast: 5000,
  super: 2500,
};

function loadRefreshMode(viewer: WorkspaceViewer): RefreshMode {
  try {
    const raw = window.localStorage.getItem(REFRESH_MODE_STORAGE_PREFIX[viewer]);
    if (raw === "fast" || raw === "super" || raw === "normal") return raw;
  } catch {
    return "normal";
  }
  return "normal";
}

function loadSavedProject(viewer: WorkspaceViewer) {
  try {
    return window.localStorage.getItem(PROJECT_STORAGE_PREFIX[viewer]) || "";
  } catch {
    return "";
  }
}

function loadSidebarMode(viewer: WorkspaceViewer): SidebarMode {
  try {
    const raw = window.localStorage.getItem(SIDEBAR_MODE_STORAGE_PREFIX[viewer]);
    if (raw === "expanded" || raw === "rail" || raw === "hidden") return raw;
  } catch {
    return "expanded";
  }
  return "expanded";
}

function nextSidebarMode(mode: SidebarMode): SidebarMode {
  if (mode === "expanded") return "rail";
  if (mode === "rail") return "hidden";
  return "expanded";
}

function useWorkspaceShellContextValue(viewer: WorkspaceViewer) {
  const queryClient = useQueryClient();
  const { user, logout } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [refreshMode, setRefreshModeState] = useState<RefreshMode>(() => loadRefreshMode(viewer));
  const [lastRefreshAt, setLastRefreshAt] = useState(() => Date.now());
  const refreshInterval = REFRESH_INTERVAL[refreshMode];

  const metaQuery = useQuery<MetaResponse | AppMetaResponse>({
    queryKey: viewer === "admin" ? queryKeys.meta : queryKeys.appMeta,
    queryFn: async () =>
      viewer === "admin" ? dashboardApi.admin.getMeta() : dashboardApi.app.getMeta(),
    refetchInterval: refreshInterval,
    refetchOnWindowFocus: false,
  });
  const adminMeta = viewer === "admin" ? (metaQuery.data as MetaResponse | undefined) : undefined;

  const healthQuery = useQuery({
    queryKey: queryKeys.health,
    queryFn: dashboardApi.admin.getHealth,
    enabled: viewer === "admin",
    refetchInterval: viewer === "admin" ? refreshInterval : false,
    refetchOnWindowFocus: false,
  });

  const signalHubPreviewQuery = useQuery<SignalHubResponse>({
    queryKey:
      viewer === "admin"
        ? queryKeys.signalHub(1, 72)
        : queryKeys.appSignalHub(1, 72),
    queryFn: () =>
      viewer === "admin"
        ? dashboardApi.admin.getSignalHubUpcoming(1, 72)
        : dashboardApi.app.getSignalHubUpcoming(1, 72),
    refetchInterval: refreshInterval,
    refetchOnWindowFocus: false,
  });

  const schedulerQuery = useQuery({
    queryKey: queryKeys.projectScheduler,
    queryFn: dashboardApi.admin.getProjectSchedulerStatus,
    enabled: viewer === "admin",
    refetchInterval: viewer === "admin" ? refreshInterval : false,
    refetchOnWindowFocus: false,
  });

  const selectedProject = resolveSelectedProject(
    metaQuery.data,
    searchParams.get("project") || loadSavedProject(viewer),
  );
  const projectOptions = resolveProjectCandidates(metaQuery.data);

  useEffect(() => {
    if (!selectedProject) return;
    const current = searchParams.get("project");
    if (current === selectedProject) return;
    const next = new URLSearchParams(searchParams);
    next.set("project", selectedProject);
    setSearchParams(next, { replace: true });
  }, [searchParams, selectedProject, setSearchParams]);

  useEffect(() => {
    try {
      window.localStorage.setItem(REFRESH_MODE_STORAGE_PREFIX[viewer], refreshMode);
    } catch {
      // ignore
    }
  }, [refreshMode, viewer]);

  useEffect(() => {
    if (!selectedProject) return;
    try {
      window.localStorage.setItem(PROJECT_STORAGE_PREFIX[viewer], selectedProject);
    } catch {
      // ignore
    }
  }, [selectedProject, viewer]);

  useEffect(() => {
    if (viewer !== "admin") return undefined;
    const heartbeat = window.setInterval(() => {
      dashboardApi.admin.sendHeartbeat().catch(() => undefined);
    }, 15000);
    return () => window.clearInterval(heartbeat);
  }, [viewer]);

  const setSelectedProject = useCallback(
    (project: string) => {
      const next = new URLSearchParams(searchParams);
      if (project) next.set("project", project);
      else next.delete("project");
      setSearchParams(next);
      setMobileOpen(false);
    },
    [searchParams, setSearchParams],
  );

  const refreshAll = useCallback(async () => {
    if (viewer === "admin") {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.authMe }),
        metaQuery.refetch(),
        healthQuery.refetch(),
        signalHubPreviewQuery.refetch(),
        schedulerQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.walletConfigs }),
        queryClient.invalidateQueries({ queryKey: queryKeys.overviewActive(selectedProject) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.projectScheduler }),
        queryClient.invalidateQueries({ queryKey: ["minutes"] }),
        queryClient.invalidateQueries({ queryKey: ["leaderboard"] }),
        queryClient.invalidateQueries({ queryKey: ["event-delays"] }),
        queryClient.invalidateQueries({ queryKey: ["project-tax"] }),
      ]);
    } else {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.authMe }),
        metaQuery.refetch(),
        signalHubPreviewQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.userWalletConfigs }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appOverviewActive(selectedProject) }),
        queryClient.invalidateQueries({ queryKey: ["app-project-access"] }),
        queryClient.invalidateQueries({ queryKey: ["user-wallets"] }),
      ]);
    }
    setLastRefreshAt(Date.now());
  }, [
    healthQuery,
    metaQuery,
    queryClient,
    schedulerQuery,
    selectedProject,
    signalHubPreviewQuery,
    viewer,
  ]);

  const runtimeMutation = useMutation({
    mutationFn: async () => {
      const paused = Boolean(
        healthQuery.data?.runtimePaused ?? adminMeta?.runtimeTuning.runtime_paused ?? false,
      );
      return dashboardApi.admin.setRuntimePause(!paused);
    },
    onSuccess: async () => {
      await Promise.all([
        healthQuery.refetch(),
        metaQuery.refetch(),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimePause }),
      ]);
      setLastRefreshAt(Date.now());
    },
  });

  const value = useMemo<ShellContextValue>(
    () => ({
      viewer,
      authUser: user,
      meta: metaQuery.data,
      health: healthQuery.data,
      signalHubPreview: signalHubPreviewQuery.data,
      projectOptions,
      selectedProject,
      setSelectedProject,
      refreshMode,
      setRefreshMode: setRefreshModeState,
      refreshAll,
      lastRefreshAt,
      isRefreshing:
        metaQuery.isFetching ||
        healthQuery.isFetching ||
        signalHubPreviewQuery.isFetching ||
        schedulerQuery.isFetching,
      toggleRuntimePause:
        viewer === "admin"
          ? async () => {
              await runtimeMutation.mutateAsync();
            }
          : async () => undefined,
      isRuntimeMutating: viewer === "admin" ? runtimeMutation.isPending : false,
      logout,
    }),
    [
      healthQuery.data,
      healthQuery.isFetching,
      lastRefreshAt,
      logout,
      metaQuery.data,
      metaQuery.isFetching,
      projectOptions,
      refreshAll,
      refreshMode,
      runtimeMutation,
      schedulerQuery.isFetching,
      selectedProject,
      setSelectedProject,
      signalHubPreviewQuery.data,
      signalHubPreviewQuery.isFetching,
      user,
      viewer,
    ],
  );

  return {
    value,
    mobileOpen,
    setMobileOpen,
    metaQuery,
    healthQuery,
    schedulerQuery,
  };
}

function BrandBlock({
  mode = "expanded",
  title,
}: {
  mode?: Exclude<SidebarMode, "hidden">;
  title: string;
}) {
  const compact = mode === "rail";

  return (
    <div className={cn("flex items-center gap-4", compact && "justify-center")}>
      <div className="theme-brand-badge flex size-14 shrink-0 items-center justify-center rounded-[20px]">
        <img src="/admin/brand/logo-mark.png" alt="Virtuals Whale Radar" className="size-10 rounded-[12px] object-cover" />
      </div>
      {compact ? null : (
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary/80">
            Virtuals Whale Radar
          </div>
          <div className="text-xl font-semibold tracking-[-0.04em]">{title}</div>
        </div>
      )}
    </div>
  );
}

function NavList({
  items,
  mode,
  onNavigate,
}: {
  items: WorkspaceNavItem[];
  mode: Exclude<SidebarMode, "hidden">;
  onNavigate?: () => void;
}) {
  const compact = mode === "rail";
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            title={item.label}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "group flex items-center rounded-[22px] text-sm font-medium transition",
                compact ? "justify-center px-3 py-3" : "justify-between px-4 py-3",
                isActive
                  ? "bg-[color:var(--surface-soft-strong)] text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-[color:var(--surface-soft)] hover:text-foreground",
              )
            }
          >
            <span className={cn("flex items-center gap-3", compact && "justify-center")}>
              <Icon className="size-4 shrink-0" />
              {compact ? null : item.label}
            </span>
          </NavLink>
        );
      })}
    </div>
  );
}

function SidebarPanel({
  title,
  items,
  mode,
}: {
  title: string;
  items: WorkspaceNavItem[];
  mode: Exclude<SidebarMode, "hidden">;
}) {
  return (
    <aside
      className={cn(
        "flex h-full flex-col gap-6 rounded-[30px] border border-white/50 bg-sidebar/80 shadow-[0_28px_60px_rgba(108,140,126,0.12)]",
        "surface-panel shadow-[var(--shadow-strong)]",
        mode === "expanded" ? "p-5" : "items-center p-3",
      )}
    >
      <BrandBlock mode={mode} title={title} />
      <div className="w-full">
        <NavList items={items} mode={mode} />
      </div>
    </aside>
  );
}

function TopBar({
  title,
  sidebarMode,
  onCycleSidebar,
  onOpenMobileNav,
}: {
  title: string;
  sidebarMode: SidebarMode;
  onCycleSidebar: () => void;
  onOpenMobileNav: () => void;
}) {
  const {
    viewer,
    authUser,
    meta,
    health,
    signalHubPreview,
    projectOptions,
    selectedProject,
    setSelectedProject,
    refreshAll,
    lastRefreshAt,
    isRefreshing,
    toggleRuntimePause,
    isRuntimeMutating,
    logout,
  } = useShell();
  const { theme, toggleTheme } = useTheme();
  const queryClient = useQueryClient();
  const [notificationsOpen, setNotificationsOpen] = useState(false);

  const notificationsQuery = useQuery<AppNotificationsResponse>({
    queryKey: queryKeys.appNotifications(8),
    queryFn: () => dashboardApi.app.getNotifications(8),
    enabled: viewer === "user",
    refetchOnWindowFocus: false,
  });

  const markNotificationReadMutation = useMutation({
    mutationFn: (notificationId: number) => dashboardApi.app.markNotificationRead(notificationId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
      ]);
    },
  });

  const markAllNotificationsReadMutation = useMutation({
    mutationFn: () => dashboardApi.app.markAllNotificationsRead(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
      ]);
    },
  });

  const runtimeSummary =
    viewer === "admin"
      ? health?.runtimePaused
        ? "采集已暂停"
        : "采集运行中"
      : null;
  const signalHubSummary =
    viewer === "admin"
      ? signalHubPreview?.available
        ? "SignalHub 在线"
        : "SignalHub 异常"
      : null;
  const systemSummary =
    viewer === "admin" ? [runtimeSummary, signalHubSummary].filter(Boolean).join(" · ") : null;
  const systemSummaryVariant =
    viewer === "admin" && health?.runtimePaused === false && signalHubPreview?.available
      ? "success"
      : "warning";
  const appMeta = viewer === "user" ? (meta as AppMetaResponse | undefined) : undefined;
  const unreadNotificationCount =
    viewer === "user"
      ? appMeta?.unread_notification_count ?? notificationsQuery.data?.unreadCount ?? 0
      : 0;

  return (
    <Card className="surface-glass sticky top-4 z-20 rounded-[28px] p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px_auto] xl:items-center">
        <div className="flex min-w-0 items-center gap-3">
          <Button
            className="hidden lg:inline-flex"
            variant="secondary"
            size="icon"
            onClick={onCycleSidebar}
            title={`切换侧栏，当前为 ${sidebarMode}`}
          >
            <Menu className="size-4" />
          </Button>
          <Button className="lg:hidden" variant="secondary" size="icon" onClick={onOpenMobileNav}>
            <Menu className="size-4" />
          </Button>
          <div className="theme-brand-badge flex size-11 shrink-0 items-center justify-center rounded-[18px]">
            <img src="/admin/brand/logo-mark.png" alt="Virtuals Whale Radar" className="size-7 rounded-[10px] object-cover" />
          </div>
          <div className="hidden min-w-0 sm:block">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary/80">
              Virtuals Whale Radar
            </div>
            <div className="text-sm font-semibold tracking-[-0.03em]">{title}</div>
          </div>
        </div>

        <div className="grid gap-3">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              当前项目
            </div>
            <Select value={selectedProject} onChange={(event) => setSelectedProject(event.target.value)}>
              {projectOptions.length ? (
                projectOptions.map((project) => (
                  <option key={project} value={project}>
                    {project}
                  </option>
                ))
              ) : (
                <option value="">暂无项目</option>
              )}
            </Select>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 xl:justify-end">
          {viewer === "admin" && systemSummary ? (
            <Badge variant={systemSummaryVariant}>{systemSummary}</Badge>
          ) : null}
          {viewer === "user" ? (
            <Button variant="outline" className="relative" onClick={() => setNotificationsOpen(true)}>
              <BellDot className="size-4" />
              提醒
              {unreadNotificationCount > 0 ? (
                <span className="absolute -right-2 -top-2 inline-flex min-w-6 items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[11px] font-semibold text-white">
                  {unreadNotificationCount}
                </span>
              ) : null}
            </Button>
          ) : null}
          <div className="hidden text-right text-xs text-muted-foreground sm:block">
            <div>{authUser ? authUser.nickname : "未登录"}</div>
            <div>上次刷新 {formatDateTime(Math.floor(lastRefreshAt / 1000))}</div>
          </div>
          <Button
            variant="outline"
            className="theme-toggle-button"
            onClick={toggleTheme}
            title={theme === "light" ? "切换到深色模式" : "切换到浅色模式"}
          >
            {theme === "light" ? <MoonStar className="size-4" /> : <SunMedium className="size-4" />}
            {theme === "light" ? "深色模式" : "浅色模式"}
          </Button>
          <Button variant="outline" onClick={() => void refreshAll()} disabled={isRefreshing}>
            <RefreshCcw className={cn("size-4", isRefreshing && "animate-spin")} />
            刷新
          </Button>
          {viewer === "admin" ? (
            <Button
              variant={health?.runtimePaused ? "default" : "secondary"}
              onClick={() => void toggleRuntimePause()}
              disabled={isRuntimeMutating}
            >
              {health?.runtimePaused ? "恢复采集" : "暂停采集"}
            </Button>
          ) : null}
          <Button variant="ghost" onClick={() => void logout()}>
            <LogOut className="size-4" />
            退出
          </Button>
        </div>
      </div>

      {viewer === "user" ? (
        <Sheet open={notificationsOpen} onOpenChange={setNotificationsOpen}>
          <SheetContent className="px-0 py-0">
            <div className="flex h-full min-h-0 flex-col">
              <div className="border-b border-border px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold">账户提醒</div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      未读 {unreadNotificationCount} 条。
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void markAllNotificationsReadMutation.mutateAsync()}
                    disabled={
                      unreadNotificationCount <= 0 || markAllNotificationsReadMutation.isPending
                    }
                  >
                    全部已读
                  </Button>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto px-6 py-5">
                {notificationsQuery.data?.items.length ? (
                  <div className="space-y-3">
                    {notificationsQuery.data.items.map((item) => (
                      <div
                        key={item.id}
                        className={cn(
                          "rounded-[22px] border px-4 py-4 shadow-sm",
                          item.isRead
                            ? "border-border bg-[color:var(--surface-soft)]"
                            : "theme-status-unread border-primary/30",
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Badge variant={item.isRead ? "secondary" : "success"}>
                              {item.isRead ? "已读" : "未读"}
                            </Badge>
                            <div className="text-sm font-medium">{item.title}</div>
                          </div>
                          {item.isRead ? null : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => void markNotificationReadMutation.mutateAsync(item.id)}
                              disabled={markNotificationReadMutation.isPending}
                            >
                              标记已读
                            </Button>
                          )}
                        </div>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span>{formatDateTime(item.createdAt)}</span>
                          {item.actionUrl ? <span>入口：{item.actionUrl}</span> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[22px] border border-dashed border-border surface-empty px-4 py-6 text-sm text-muted-foreground">
                    当前没有新的账户提醒。
                  </div>
                )}
              </div>
            </div>
          </SheetContent>
        </Sheet>
      ) : null}
    </Card>
  );
}

function WorkspaceShell({
  viewer,
  title,
  items,
}: {
  viewer: WorkspaceViewer;
  title: string;
  items: WorkspaceNavItem[];
}) {
  const { value, mobileOpen, setMobileOpen, metaQuery, healthQuery } = useWorkspaceShellContextValue(viewer);
  const location = useLocation();
  const [sidebarMode, setSidebarMode] = useState<SidebarMode>(() => loadSidebarMode(viewer));

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_MODE_STORAGE_PREFIX[viewer], sidebarMode);
    } catch {
      // ignore
    }
  }, [sidebarMode, viewer]);

  const shellGridClass =
    sidebarMode === "expanded"
      ? "lg:grid-cols-[300px_minmax(0,1fr)]"
      : sidebarMode === "rail"
        ? "lg:grid-cols-[96px_minmax(0,1fr)]"
        : "lg:grid-cols-[minmax(0,1fr)]";

  const hasError = viewer === "admin" ? metaQuery.isError || healthQuery.isError : metaQuery.isError;

  return (
    <ShellContext.Provider value={value}>
      <div className="min-h-screen px-4 py-4 lg:px-6 lg:py-6">
        <div className={cn("mx-auto grid max-w-[1800px] gap-5", shellGridClass)}>
          {sidebarMode !== "hidden" ? (
            <div className="hidden lg:block">
              <SidebarPanel title={title} items={items} mode={sidebarMode} />
            </div>
          ) : null}

          <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-5">
            <TopBar
              title={title}
              sidebarMode={sidebarMode}
              onCycleSidebar={() => setSidebarMode((current) => nextSidebarMode(current))}
              onOpenMobileNav={() => setMobileOpen(true)}
            />

            <main className="flex-1">
              {hasError ? (
                <Alert variant="danger" className="mb-4">
                  {viewer === "admin"
                    ? "无法连接到管理员 API，请确认 `/api/admin/*` 路由可访问。"
                    : "无法连接到用户端 API，请确认 `/api/app/*` 路由可访问。"}
                </Alert>
              ) : null}
              <div key={location.pathname} className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
                <Outlet />
              </div>
            </main>
          </div>
        </div>
      </div>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent className="overflow-y-auto bg-sidebar/95">
          <div className="space-y-6 pt-12">
            <BrandBlock title={title} />
            <NavList items={items} mode="expanded" onNavigate={() => setMobileOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </ShellContext.Provider>
  );
}

export function AdminShell() {
  return (
    <WorkspaceShell
      viewer="admin"
      title="Control Room"
      items={[
        { to: "/admin/overview", label: "Overview", icon: Gauge },
        { to: "/admin/projects", label: "Projects", icon: Activity },
        { to: "/admin/signalhub", label: "SignalHub", icon: BellDot },
        { to: "/admin/wallets", label: "Wallets", icon: Wallet },
        { to: "/admin/users", label: "Users", icon: Users },
        { to: "/admin/settings", label: "Settings", icon: Settings2 },
      ]}
    />
  );
}

export function UserShell() {
  return (
    <WorkspaceShell
      viewer="user"
      title="项目观察台"
      items={[
        { to: "/app/overview", label: "实时看板", icon: Gauge },
        { to: "/app/projects", label: "项目列表", icon: Activity },
        { to: "/app/signalhub", label: "即将发射", icon: BellDot },
        { to: "/app/wallets", label: "我的钱包", icon: Wallet },
        { to: "/app/billing", label: "积分充值", icon: Coins },
      ]}
    />
  );
}

export function AuthBanner() {
  const { user } = useAuth();
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-border bg-white/80 px-3 py-2 text-xs font-medium text-muted-foreground">
      <ShieldUser className="size-4 text-primary" />
      {user ? `${user.nickname} / ${user.role}` : "未登录"}
    </div>
  );
}
