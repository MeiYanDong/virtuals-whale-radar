import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LockKeyhole, WalletCards } from "lucide-react";
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
import type { ProjectLockedResponse } from "@/types/api";

function isRealtimeStatus(status: string) {
  return ["prelaunch", "live"].includes(String(status || "").toLowerCase());
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
    staleTime: 15_000,
    gcTime: 60_000,
  });
  const displayItem = useMemo(
    () =>
      currentItem && marketQuery.data
        ? {
            ...currentItem,
            tokenPriceV: marketQuery.data.tokenPriceV,
            tokenPriceUsd: marketQuery.data.tokenPriceUsd,
            liveFdvUsd: marketQuery.data.liveFdvUsd,
            marketPriceSource: marketQuery.data.marketPriceSource ?? undefined,
            marketPriceStale: marketQuery.data.marketPriceStale ?? undefined,
          }
        : currentItem,
    [currentItem, marketQuery.data],
  );

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
