import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, LockKeyhole, Pause, Play, RotateCcw, WalletCards } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { useShell } from "@/app/shell-context";
import { EmptyState, LoadingState, PageHeader } from "@/components/app-primitives";
import { ProjectOverviewSections } from "@/components/project-overview-sections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";
import type { OverviewActiveResponse, ProjectLockedResponse, ReplayStatusResponse } from "@/types/api";

function isRealtimeStatus(status: string) {
  return ["prelaunch", "live"].includes(String(status || "").toLowerCase());
}

const LIVE_FAST_REFRESH_MS = 250;
const PRELAUNCH_REFRESH_MS = 5_000;
const DEFAULT_REFRESH_MS = 20_000;

function normalizeFastRefreshMs(value: number | null | undefined, fallback: number) {
  const parsed = Number(value ?? fallback);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.max(150, Math.min(Math.round(parsed), DEFAULT_REFRESH_MS));
}

function marketRefreshIntervalMs(status: string, recommendedRefreshMs?: number | null) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return normalizeFastRefreshMs(recommendedRefreshMs, LIVE_FAST_REFRESH_MS);
  if (key === "prelaunch") return PRELAUNCH_REFRESH_MS;
  return DEFAULT_REFRESH_MS;
}

function marketStaleTimeMs(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return 0;
  if (key === "prelaunch") return 2_000;
  return 15_000;
}

function overviewRefreshIntervalMs(data: OverviewActiveResponse | undefined) {
  const item = data?.item;
  if (!item) return false;

  const status = String(item.projectedStatus || item.status || "").toLowerCase();
  if (status === "live") return normalizeFastRefreshMs(item.recommendedRefreshMs, LIVE_FAST_REFRESH_MS);
  if (status === "prelaunch") return PRELAUNCH_REFRESH_MS;
  return false;
}

function detailPageTitle(status: string) {
  return String(status || "").toLowerCase() === "ended" ? "历史项目详情" : "项目详情";
}

function detailStatusLabel(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "prelaunch") return "预热中";
  if (key === "live") return "发射中";
  if (key === "ended") return "已结束";
  if (key === "scheduled") return "待开始";
  return "待补全";
}

function detailStatusVariant(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return "success" as const;
  if (key === "prelaunch") return "warning" as const;
  if (key === "ended") return "secondary" as const;
  return "default" as const;
}

function isReplayControlCandidate() {
  if (typeof window === "undefined") return false;
  const hostname = window.location.hostname;
  const params = new URLSearchParams(window.location.search);
  return (
    (hostname === "127.0.0.1" || hostname === "localhost") &&
    params.get("replayControl") === "1"
  );
}

function replayStateLabel(state: ReplayStatusResponse["state"]) {
  if (state === "running") return "自动模拟中";
  if (state === "ended") return "已结束";
  return "等待手动开始";
}

function replayStateVariant(state: ReplayStatusResponse["state"]) {
  if (state === "running") return "success" as const;
  if (state === "ended") return "secondary" as const;
  return "warning" as const;
}

function ReplayControlPanel({
  status,
  pending,
  onAction,
}: {
  status?: ReplayStatusResponse;
  pending: boolean;
  onAction: (action: "start" | "pause" | "resume" | "speed" | "reset", speed?: number) => void;
}) {
  if (!status?.ok || !status.manual) return null;

  const progressPercent = Math.round((status.progress ?? 0) * 100);
  const isRunning = status.state === "running";
  const isEnded = status.state === "ended";
  const hasStarted = status.elapsedSec > 0 || status.insertedEvents > 0;
  const startAction = hasStarted ? "resume" : "start";
  const startLabel = hasStarted ? "继续模拟" : "开始自动模拟";

  return (
    <section className="rounded-[28px] border border-primary/25 bg-primary/5 px-5 py-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Gauge className="size-4 text-primary" />
            <div className="text-sm font-semibold tracking-[-0.02em]">手动模拟模式</div>
            <Badge variant={replayStateVariant(status.state)}>{replayStateLabel(status.state)}</Badge>
            <Badge variant="secondary">{status.speed}x</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>模拟时间 {formatDateTime(status.now)}</span>
            <span>进度 {progressPercent}%</span>
            <span>
              事件 {status.insertedEvents}/{status.totalEvents}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            className="h-10 w-24"
            value={String(status.speed)}
            onChange={(event) => onAction("speed", Number(event.target.value))}
            disabled={pending || isEnded}
          >
            <option value="1">1x</option>
            <option value="2">2x</option>
            <option value="5">5x</option>
            <option value="10">10x</option>
          </Select>
          {isRunning ? (
            <Button variant="outline" onClick={() => onAction("pause")} disabled={pending}>
              <Pause className="size-4" />
              暂停
            </Button>
          ) : (
            <Button onClick={() => onAction(startAction, status.speed)} disabled={pending || isEnded}>
              <Play className="size-4" />
              {isEnded ? "已结束" : startLabel}
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              if (!window.confirm("这会清空当前临时回放数据并回到发射起点，只影响 18080 模拟环境。确认继续吗？")) {
                return;
              }
              onAction("reset");
            }}
            disabled={pending}
          >
            <RotateCcw className="size-4" />
            回到起点
          </Button>
        </div>
      </div>
    </section>
  );
}

function confirmProjectUnlock(projectName: string, unlockCost: number) {
  return window.confirm(
    `解锁 ${projectName} 的项目详情将消耗 ${unlockCost} 积分，解锁后以后都能直接查看。确认继续吗？`,
  );
}

export function OverviewPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { projectId } = useParams();
  const {
    viewer,
    meta,
    selectedProject,
    setSelectedProject,
    refreshAll,
  } = useShell();
  const detailProjectId = projectId && /^\d+$/.test(projectId) ? Number.parseInt(projectId, 10) : null;
  const isProjectDetailView = detailProjectId !== null;
  const hasInvalidProjectId = Boolean(projectId) && detailProjectId === null;
  const projectsHref = viewer === "admin" ? "/admin/projects" : "/app/projects";

  const overviewQuery = useQuery({
    queryKey: isProjectDetailView
      ? viewer === "admin"
        ? queryKeys.adminProjectOverview(detailProjectId)
        : queryKeys.appProjectOverview(detailProjectId)
      : viewer === "admin"
        ? queryKeys.overviewActive(selectedProject)
        : queryKeys.appOverviewActive(selectedProject),
    queryFn: () => {
      if (isProjectDetailView && detailProjectId !== null) {
        return viewer === "admin"
          ? dashboardApi.admin.getProjectOverview(detailProjectId)
          : dashboardApi.app.getProjectOverview(detailProjectId);
      }
      return viewer === "admin"
        ? dashboardApi.admin.getOverviewActive(selectedProject)
        : dashboardApi.app.getOverviewActive(selectedProject);
    },
    enabled: Boolean(meta) && !hasInvalidProjectId && (!isProjectDetailView || detailProjectId !== null),
    staleTime: 0,
    refetchInterval: (query) => overviewRefreshIntervalMs(query.state.data as OverviewActiveResponse | undefined),
    refetchIntervalInBackground: false,
    gcTime: 60_000,
  });

  const lockedDetails =
    viewer === "user" && overviewQuery.error instanceof ApiError && overviewQuery.error.status === 403
      ? (overviewQuery.error.details as ProjectLockedResponse)
      : null;
  const lockedProject = lockedDetails?.project ?? null;
  const targetProjectId = detailProjectId ?? lockedProject?.id ?? 0;
  const currentProjectName = overviewQuery.data?.item?.name ?? lockedProject?.name ?? "";

  const unlockMutation = useMutation({
    mutationFn: async () => {
      if (!targetProjectId) {
        throw new Error("当前没有可解锁的项目。");
      }
      return dashboardApi.app.unlockProject(targetProjectId);
    },
    onSuccess: async () => {
      if (currentProjectName) {
        setSelectedProject(currentProjectName);
      }
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjectAccess(targetProjectId) }),
        queryClient.invalidateQueries({ queryKey: ["app-project-access"] }),
      ];
      if (detailProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.appProjectOverview(detailProjectId) }));
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.appProjectMarket(detailProjectId) }));
      }
      if (currentProjectName) {
        invalidations.push(
          queryClient.invalidateQueries({
            queryKey: queryKeys.appOverviewActive(currentProjectName),
          }),
        );
      }
      await Promise.all([...invalidations, refreshAll()]);
      toast.success(`${currentProjectName || "当前项目"} 已解锁。`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activeProjects = overviewQuery.data?.activeProjects ?? [];
  const currentItem = overviewQuery.data?.item ?? null;
  const marketProjectId = currentItem?.id ?? null;
  const marketStatus = String(currentItem?.projectedStatus || currentItem?.status || "");
  const marketRefreshMs = marketRefreshIntervalMs(marketStatus, currentItem?.recommendedRefreshMs);
  const marketQuery = useQuery({
    queryKey:
      marketProjectId !== null
        ? viewer === "admin"
          ? queryKeys.adminProjectMarket(marketProjectId)
          : queryKeys.appProjectMarket(marketProjectId)
        : ["project-market", "idle"],
    queryFn: () => {
      if (marketProjectId === null) {
        throw new Error("project market requires a project id");
      }
      return viewer === "admin"
        ? dashboardApi.admin.getProjectMarket(marketProjectId)
        : dashboardApi.app.getProjectMarket(marketProjectId);
    },
    enabled: Boolean(currentItem && marketProjectId !== null),
    staleTime: marketStaleTimeMs(marketStatus),
    refetchInterval: currentItem && marketProjectId !== null ? marketRefreshMs : false,
    refetchIntervalInBackground: false,
    gcTime: 60_000,
  });
  const displayItem = useMemo(
    () =>
      currentItem && marketQuery.data
        ? {
            ...currentItem,
            tokenPriceV: marketQuery.data.tokenPriceV,
            tokenPriceUsd: marketQuery.data.tokenPriceUsd,
            virtualPriceUsd: marketQuery.data.virtualPriceUsd,
            liveFdvUsd: marketQuery.data.liveFdvUsd,
            marketPriceSource: marketQuery.data.marketPriceSource ?? undefined,
            marketPriceStale: marketQuery.data.marketPriceStale ?? undefined,
            marketPriceMode: marketQuery.data.marketPriceMode ?? undefined,
            marketPriceLabel: marketQuery.data.marketPriceLabel ?? undefined,
            recommendedRefreshMs: marketQuery.data.recommendedRefreshMs ?? undefined,
            marketCacheTtlMs: marketQuery.data.marketCacheTtlMs ?? undefined,
            marketCacheHit: marketQuery.data.marketCacheHit ?? undefined,
            priceUpdatedAt: marketQuery.data.priceUpdatedAt ?? undefined,
            priceLatencyMs: marketQuery.data.priceLatencyMs ?? undefined,
            priceBlockNumber: marketQuery.data.priceBlockNumber ?? undefined,
            buyTaxRate: marketQuery.data.buyTaxRate ?? undefined,
            buyTaxRateSource: marketQuery.data.buyTaxRateSource ?? undefined,
            predictedBuyTaxRate: marketQuery.data.predictedBuyTaxRate ?? undefined,
            observedBuyTaxRate: marketQuery.data.observedBuyTaxRate ?? undefined,
            observedBuyTaxRateRaw: marketQuery.data.observedBuyTaxRateRaw ?? undefined,
            observedBuyTaxAt: marketQuery.data.observedBuyTaxAt ?? undefined,
            observedBuyTaxAgeSec: marketQuery.data.observedBuyTaxAgeSec ?? undefined,
            observedBuyTaxFresh: marketQuery.data.observedBuyTaxFresh ?? undefined,
            observedBuyTaxFreshSec: marketQuery.data.observedBuyTaxFreshSec ?? undefined,
            observedBuyTaxSamples: marketQuery.data.observedBuyTaxSamples ?? undefined,
            taxEvidenceStatus: marketQuery.data.taxEvidenceStatus ?? undefined,
            taxEvidenceDivergencePct: marketQuery.data.taxEvidenceDivergencePct ?? undefined,
            taxConfigKnown: marketQuery.data.taxConfigKnown ?? undefined,
            taxConfigStatus: marketQuery.data.taxConfigStatus ?? undefined,
            taxConfigWarning: marketQuery.data.taxConfigWarning ?? undefined,
            taxScheduleDurationValue: marketQuery.data.taxScheduleDurationValue ?? undefined,
            taxScheduleUnitSeconds: marketQuery.data.taxScheduleUnitSeconds ?? undefined,
            taxStartAt: marketQuery.data.taxStartAt ?? undefined,
            taxEndAt: marketQuery.data.taxEndAt ?? undefined,
            antiSniperTaxType: marketQuery.data.antiSniperTaxType ?? undefined,
            launchMode: marketQuery.data.launchMode ?? undefined,
            launchModeLabel: marketQuery.data.launchModeLabel ?? undefined,
            launchModeRaw: marketQuery.data.launchModeRaw ?? undefined,
            isRobotics: marketQuery.data.isRobotics ?? undefined,
            isProject60days: marketQuery.data.isProject60days ?? undefined,
            airdropPercent: marketQuery.data.airdropPercent ?? undefined,
            virtualsStatus: marketQuery.data.virtualsStatus ?? undefined,
            virtualsFactory: marketQuery.data.virtualsFactory ?? undefined,
            virtualsCategory: marketQuery.data.virtualsCategory ?? undefined,
            estimatedFdvUsdWithTax: marketQuery.data.estimatedFdvUsdWithTax ?? undefined,
            estimatedFdvWanUsdWithTax: marketQuery.data.estimatedFdvWanUsdWithTax ?? undefined,
          }
        : currentItem,
    [currentItem, marketQuery.data],
  );
  const replayControlEnabled = viewer === "admin" && isReplayControlCandidate();
  const replayStatusQuery = useQuery({
    queryKey: queryKeys.replayStatus,
    queryFn: dashboardApi.replay.getStatus,
    enabled: replayControlEnabled,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => ((query.state.data as ReplayStatusResponse | undefined)?.ok ? 500 : false),
    refetchIntervalInBackground: false,
  });
  const replayControlMutation = useMutation({
    mutationFn: async ({
      action,
      speed,
    }: {
      action: "start" | "pause" | "resume" | "speed" | "reset";
      speed?: number;
    }) => dashboardApi.replay.control(action, speed),
    onSuccess: async () => {
      const invalidations = [queryClient.invalidateQueries({ queryKey: queryKeys.replayStatus })];
      if (detailProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.adminProjectOverview(detailProjectId) }));
      }
      if (marketProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.adminProjectMarket(marketProjectId) }));
      }
      await Promise.all(invalidations);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const replayControl = replayControlEnabled ? (
    <ReplayControlPanel
      status={replayStatusQuery.data}
      pending={replayControlMutation.isPending}
      onAction={(action, speed) => void replayControlMutation.mutateAsync({ action, speed })}
    />
  ) : null;

  useEffect(() => {
    if (displayItem && displayItem.name !== selectedProject) {
      setSelectedProject(displayItem.name);
    }
  }, [displayItem, selectedProject, setSelectedProject]);

  if (hasInvalidProjectId) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Projects"
          title="项目详情"
          description="当前链接里的项目编号不正确。"
          actions={
            <Button asChild variant="secondary">
              <Link to={projectsHref}>回项目列表</Link>
            </Button>
          }
        />
        <EmptyState
          title="项目编号无效"
          description="请从项目列表重新进入需要查看的项目。"
        />
      </div>
    );
  }

  if (!meta || overviewQuery.isLoading) {
    return <LoadingState label={isProjectDetailView ? "正在加载项目详情..." : "正在加载实时看板..."} />;
  }

  if (lockedDetails && lockedProject) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={isProjectDetailView ? "Projects" : "Overview"}
          title={
            isProjectDetailView
              ? `${lockedProject.name} · 解锁后查看项目详情`
              : `${lockedProject.name} · 解锁后查看实时看板`
          }
          description={
            isProjectDetailView
              ? "这个项目的历史盘面已经准备好了，但完整详情还没解锁。"
              : "这个项目已经进入观察窗口，但完整盘面还没解锁。"
          }
          actions={
            <>
              <Button
                onClick={() => {
                  if (!confirmProjectUnlock(lockedProject.name, lockedDetails.access.unlockCost)) return;
                  void unlockMutation.mutateAsync();
                }}
                disabled={!lockedDetails.access.canUnlockNow || unlockMutation.isPending}
              >
                <LockKeyhole className="size-4" />
                解锁项目详情
              </Button>
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                <WalletCards className="size-4" />
                去充值页
              </Button>
            </>
          }
        />

        <section className="surface-hero-strong overflow-hidden rounded-[32px] border border-white/60 p-6">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="warning">未解锁</Badge>
            <Badge variant="secondary">首次解锁扣 {lockedDetails.access.unlockCost} 积分</Badge>
          </div>
          <h2 className="mt-4 text-3xl font-semibold tracking-[-0.05em]">{lockedProject.name}</h2>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">开始时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(lockedProject.startAt)}</div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">结束时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {formatDateTime(lockedProject.resolvedEndAt)}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前积分</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {lockedDetails.access.creditBalance}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">详情链接</div>
              <div className="mt-2 truncate text-sm">
                {lockedProject.detailUrl ? (
                  <a className="text-primary hover:underline" href={lockedProject.detailUrl} target="_blank" rel="noreferrer">
                    打开项目详情
                  </a>
                ) : (
                  "未填写"
                )}
              </div>
            </div>
          </div>
        </section>

        <EmptyState
          title={lockedDetails.access.canUnlockNow ? "解锁后就能查看完整盘面" : "当前积分不足"}
          description={
            lockedDetails.access.canUnlockNow
              ? "确认扣除积分后，这个项目的分钟图、大户榜和追踪钱包持仓以后都能直接打开。"
              : `当前剩余 ${lockedDetails.access.creditBalance} 积分，不足以解锁该项目。先去充值页补分，再回来解锁就行。`
          }
          action={
            <div className="flex flex-wrap gap-3">
              {lockedDetails.access.canUnlockNow ? (
                <Button
                  onClick={() => {
                    if (!confirmProjectUnlock(lockedProject.name, lockedDetails.access.unlockCost)) return;
                    void unlockMutation.mutateAsync();
                  }}
                  disabled={unlockMutation.isPending}
                >
                  <LockKeyhole className="size-4" />
                  确认解锁
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                去充值页
              </Button>
              <Button asChild variant="ghost">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  if (overviewQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={isProjectDetailView ? "Projects" : "Overview"}
          title={isProjectDetailView ? "项目详情" : "实时发射看板"}
          description={isProjectDetailView ? "当前无法读取项目详情聚合数据。" : "当前无法读取活跃项目聚合数据。"}
          actions={
            <>
              {isProjectDetailView ? (
                <Button asChild variant="ghost">
                  <Link to={projectsHref}>回项目列表</Link>
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void refreshAll()}>
                立即刷新
              </Button>
            </>
          }
        />
        <EmptyState
          title={isProjectDetailView ? "项目详情接口异常" : "实时看板接口异常"}
          description={
            isProjectDetailView
              ? viewer === "admin"
                ? "请检查 `/api/admin/projects/{id}/overview` 是否可访问，以及该项目是否仍存在于受管项目列表中。"
                : "请检查 `/api/app/projects/{id}/overview` 是否可访问，以及当前项目是否仍在公开可读列表中。"
              : viewer === "admin"
                ? "请检查 `/api/admin/overview-active` 是否可访问，以及当前 writer 实例是否正常返回活跃项目聚合数据。"
                : "请检查 `/api/app/overview-active` 是否可访问，以及当前用户是否已有可读项目。"
          }
        />
      </div>
    );
  }

  if (isProjectDetailView) {
    if (!currentItem) {
      return (
        <div className="space-y-6">
          <PageHeader
            eyebrow="Projects"
            title="项目详情"
            description="这个项目当前没有可展示的详情数据。"
            actions={
              <Button asChild variant="secondary">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            }
          />
          <EmptyState
            title="项目详情不存在"
            description="项目可能已被移除，或者当前账号没有访问权限。"
          />
        </div>
      );
    }
    const detailItem = displayItem ?? currentItem;

    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Projects"
          title={`${detailItem.name} · ${detailPageTitle(detailItem.projectedStatus || detailItem.status)}`}
          description={
            viewer === "admin"
              ? "这里保留项目在整个发射窗口内的分钟消耗、大户榜、追踪钱包和录入延迟，方便管理员复盘。"
              : "这里保留项目在整个发射窗口内的分钟消耗、大户榜、追踪钱包和录入延迟，方便第二天回看。"
          }
          actions={
            <>
              <Badge variant={detailStatusVariant(detailItem.projectedStatus || detailItem.status)}>
                {detailStatusLabel(detailItem.projectedStatus || detailItem.status)}
              </Badge>
              <span className="self-center text-sm text-muted-foreground">
                发射窗口 {formatDateTime(detailItem.startAt)} - {formatDateTime(detailItem.resolvedEndAt)}
              </span>
            </>
          }
        />

        {replayControl}

        <ProjectOverviewSections
          item={detailItem}
          minutes={overviewQuery.data?.minutes ?? []}
          whaleBoard={overviewQuery.data?.whaleBoard ?? []}
          trackedWallets={overviewQuery.data?.trackedWallets ?? []}
          delays={overviewQuery.data?.delays ?? []}
          actions={
            <>
              {isRealtimeStatus(detailItem.projectedStatus || detailItem.status) ? (
                <Button asChild variant="outline">
                  <Link
                    to={
                      viewer === "admin"
                        ? `/admin/overview?project=${encodeURIComponent(detailItem.name)}`
                        : `/app/overview?project=${encodeURIComponent(detailItem.name)}`
                    }
                  >
                    切回实时看板
                  </Link>
                </Button>
              ) : null}
              <Button asChild variant="secondary">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            </>
          }
        />
      </div>
    );
  }

  if (!overviewQuery.data?.hasActiveProject || !activeProjects.length) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Overview"
          title="实时发射看板"
          description="只展示预热中或发射中的项目。"
          actions={
            <Button asChild variant="secondary">
              <Link to={projectsHref}>去项目列表</Link>
            </Button>
          }
        />
        <EmptyState
          title="当前没有活跃项目"
          description="当项目进入预热或正式发射阶段，这里会自动出现实时数据。现在可以先去项目列表挑你想关注的目标。"
        />
      </div>
    );
  }

  if (!currentItem) {
    return <LoadingState label="正在定位活跃项目..." />;
  }
  const activeItem = displayItem ?? currentItem;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title={`${activeItem.name} · 实时发射看板`}
        description="这里集中看正在发射项目的资金变化、大户榜和你的钱包持仓。"
        actions={
          <>
            <Badge variant={detailStatusVariant(activeItem.projectedStatus || activeItem.status)}>
              {detailStatusLabel(activeItem.projectedStatus || activeItem.status)}
            </Badge>
            <div className="min-w-[240px]">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                活跃项目
              </div>
              <Select value={activeItem.name} onChange={(event) => setSelectedProject(event.target.value)}>
                {activeProjects.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" onClick={() => void refreshAll()}>
              立即刷新
            </Button>
          </>
        }
      />

      {replayControl}

      <ProjectOverviewSections
        item={activeItem}
        minutes={overviewQuery.data?.minutes ?? []}
        whaleBoard={overviewQuery.data?.whaleBoard ?? []}
        trackedWallets={overviewQuery.data?.trackedWallets ?? []}
        delays={overviewQuery.data?.delays ?? []}
        actions={
          <Button asChild variant="secondary">
            <Link to={projectsHref}>回项目列表</Link>
          </Button>
        }
      />
    </div>
  );
}
