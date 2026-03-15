import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, LockKeyhole, WalletCards } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { useShell } from "@/app/shell-context";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatAddress,
  formatCurrency,
  formatDateTime,
  formatDecimal,
  formatShortDateTime,
} from "@/lib/format";
import type { OverviewBoardItem, ProjectLockedResponse } from "@/types/api";

type BoardRow = {
  wallet: string;
  name?: string;
  spentV: number;
  tokenBought: number;
  updatedAt: number;
};

function toNumber(value: number | string | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function tokenWan(value: number) {
  return value / 10000;
}

function costPerWan(spentV: number, tokenBought: number) {
  if (tokenBought <= 0) return null;
  return spentV / (tokenBought / 10000);
}

function MinuteBars({
  items,
}: {
  items: Array<{ minute_key: number; minute_spent_v: string | number }>;
}) {
  const chartItems = useMemo(
    () =>
      [...items]
        .sort((left, right) => left.minute_key - right.minute_key)
        .map((item) => ({
          key: item.minute_key,
          value: toNumber(item.minute_spent_v),
        })),
    [items],
  );

  const peak = Math.max(...chartItems.map((item) => item.value), 0);
  const total = chartItems.reduce((sum, item) => sum + item.value, 0);

  if (!chartItems.length) {
    return (
      <EmptyState
        compact
        title="暂无分钟消耗数据"
        description="当前活跃项目还没有形成分钟聚合，等交易进入后这里会出现实时柱状图。"
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-[20px] border border-border bg-muted/70 px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">分钟条数</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{chartItems.length}</div>
        </div>
        <div className="rounded-[20px] border border-border bg-muted/70 px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">累计 SpentV</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatCurrency(total)}</div>
        </div>
        <div className="rounded-[20px] border border-border bg-muted/70 px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">峰值分钟</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatCurrency(peak)}</div>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="min-w-[780px]">
          <div className="flex h-64 items-end gap-2 rounded-[28px] border border-border bg-[linear-gradient(180deg,rgba(255,255,255,0.9),rgba(232,245,240,0.92))] px-4 pb-4 pt-6">
            {chartItems.map((item) => {
              const height = peak > 0 ? Math.max(8, (item.value / peak) * 180) : 8;
              return (
                <div key={item.key} className="flex flex-1 flex-col items-center justify-end gap-2">
                  <div className="text-[10px] text-muted-foreground">{formatDecimal(item.value, 2)}</div>
                  <div
                    className="w-full rounded-t-[10px] bg-[linear-gradient(180deg,#77b9af_0%,#248e93_100%)] shadow-[0_10px_28px_rgba(36,142,147,0.18)]"
                    style={{ height }}
                    title={`${formatDateTime(item.key * 60)} / ${formatCurrency(item.value)}`}
                  />
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>{formatShortDateTime(chartItems[0]?.key * 60)}</span>
            <span>{formatShortDateTime(chartItems[chartItems.length - 1]?.key * 60)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function BoardTable({
  rows,
  emptyTitle,
  emptyDescription,
}: {
  rows: BoardRow[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (!rows.length) {
    return <EmptyState compact title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>钱包地址</TableHead>
          <TableHead>累计花费 V</TableHead>
          <TableHead>累计代币数量（万）</TableHead>
          <TableHead>成本（万）</TableHead>
          <TableHead>更新时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const cost = costPerWan(row.spentV, row.tokenBought);
          return (
            <TableRow key={row.wallet}>
              <TableCell>
                <div className="space-y-1">
                  {row.name ? <div className="text-sm font-medium">{row.name}</div> : null}
                  <div className="font-mono text-xs text-muted-foreground">{row.wallet}</div>
                </div>
              </TableCell>
              <TableCell>{formatCurrency(row.spentV)}</TableCell>
              <TableCell>{formatDecimal(tokenWan(row.tokenBought), 2)}</TableCell>
              <TableCell>{cost === null ? "-" : formatCurrency(cost)}</TableCell>
              <TableCell>{row.updatedAt ? formatDateTime(row.updatedAt) : "-"}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function toBoardRows(items: OverviewBoardItem[]) {
  return items.map((item) => ({
    wallet: item.wallet,
    name: item.name || undefined,
    spentV: toNumber(item.spentV),
    tokenBought: toNumber(item.tokenBought),
    updatedAt: item.updatedAt,
  }));
}

function confirmLockedProjectUnlock(projectName: string, unlockCost: number) {
  return window.confirm(
    `解锁 ${projectName} 的 Overview 将消耗 ${unlockCost} 积分，解锁后永久可读。确认继续吗？`,
  );
}

export function OverviewPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { viewer, meta, selectedProject, setSelectedProject, refreshAll } = useShell();
  const overviewQuery = useQuery({
    queryKey:
      viewer === "admin"
        ? queryKeys.overviewActive(selectedProject)
        : queryKeys.appOverviewActive(selectedProject),
    queryFn: () =>
      viewer === "admin"
        ? dashboardApi.admin.getOverviewActive(selectedProject)
        : dashboardApi.app.getOverviewActive(selectedProject),
    enabled: Boolean(meta),
  });

  const lockedDetails =
    viewer === "user" && overviewQuery.error instanceof ApiError && overviewQuery.error.status === 403
      ? (overviewQuery.error.details as ProjectLockedResponse)
      : null;
  const lockedProjectName = lockedDetails?.project?.name ?? "";

  const unlockMutation = useMutation({
    mutationFn: async () => {
      if (!lockedDetails?.project?.id) {
        throw new Error("当前没有可解锁的项目。");
      }
      return dashboardApi.app.unlockProject(lockedDetails.project.id);
    },
    onSuccess: async () => {
      if (lockedProjectName) {
        setSelectedProject(lockedProjectName);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjects }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.appOverviewActive(lockedProjectName || selectedProject),
        }),
        refreshAll(),
      ]);
      toast.success(`${lockedProjectName || "当前项目"} 已解锁。`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activeProjects = overviewQuery.data?.activeProjects ?? [];
  const activeProject = overviewQuery.data?.item ?? null;

  useEffect(() => {
    if (activeProject && activeProject.name !== selectedProject) {
      setSelectedProject(activeProject.name);
    }
  }, [activeProject, selectedProject, setSelectedProject]);

  const whaleRows = useMemo(() => toBoardRows(overviewQuery.data?.whaleBoard ?? []), [overviewQuery.data?.whaleBoard]);
  const trackedWalletRows = useMemo(
    () => toBoardRows(overviewQuery.data?.trackedWallets ?? []),
    [overviewQuery.data?.trackedWallets],
  );

  if (!meta || overviewQuery.isLoading) {
    return <LoadingState label="正在加载实时看板..." />;
  }

  if (lockedDetails) {
    const project = lockedDetails.project;
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Overview"
          title="项目已锁定"
          description="当前活跃项目存在，但你还没有该项目的 Overview 访问权限。"
          actions={
            <>
              <Button
                onClick={() => {
                  if (!confirmLockedProjectUnlock(project.name, lockedDetails.access.unlockCost)) return;
                  void unlockMutation.mutateAsync();
                }}
                disabled={!lockedDetails.access.canUnlockNow || unlockMutation.isPending}
              >
                <LockKeyhole className="size-4" />
                解锁该项目
              </Button>
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                <WalletCards className="size-4" />
                去 Billing
              </Button>
            </>
          }
        />

        <section className="overflow-hidden rounded-[32px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(36,142,147,0.18),transparent_40%),linear-gradient(180deg,rgba(255,255,255,0.96),rgba(235,245,241,0.94))] p-6 shadow-[0_28px_60px_rgba(36,142,147,0.12)]">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="warning">未解锁</Badge>
            <Badge variant="secondary">首次解锁扣 {lockedDetails.access.unlockCost} 积分</Badge>
          </div>
          <h2 className="mt-4 text-3xl font-semibold tracking-[-0.05em]">{project.name}</h2>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">开始时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(project.startAt)}</div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">结束时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {formatDateTime(project.resolvedEndAt)}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前积分</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {lockedDetails.access.creditBalance}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">详情链接</div>
              <div className="mt-2 truncate text-sm">
                {project.detailUrl ? (
                  <a className="text-primary hover:underline" href={project.detailUrl} target="_blank" rel="noreferrer">
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
          title={lockedDetails.access.canUnlockNow ? "解锁后即可查看实时大盘" : "当前积分不足"}
          description={
            lockedDetails.access.canUnlockNow
              ? "确认扣除积分后，将永久获得该项目的 Overview 访问权限。"
              : `当前剩余 ${lockedDetails.access.creditBalance} 积分，不足以解锁该项目。请先前往 Billing 联系充值。`
          }
          action={
            <div className="flex flex-wrap gap-3">
              {lockedDetails.access.canUnlockNow ? (
                <Button
                  onClick={() => {
                    if (!confirmLockedProjectUnlock(project.name, lockedDetails.access.unlockCost)) return;
                    void unlockMutation.mutateAsync();
                  }}
                  disabled={unlockMutation.isPending}
                >
                  <LockKeyhole className="size-4" />
                  确认解锁
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                去 Billing
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
          eyebrow="Overview"
          title="实时发射看板"
          description="当前无法读取活跃项目聚合数据。"
          actions={
            <Button variant="secondary" onClick={() => void refreshAll()}>
              立即刷新
            </Button>
          }
        />
        <EmptyState
          title="实时看板接口异常"
          description={
            viewer === "admin"
              ? "请检查 `/api/admin/overview-active` 是否可访问，以及当前 writer 实例是否正常返回活跃项目聚合数据。"
              : "请检查 `/api/app/overview-active` 是否可访问，以及当前用户是否已有可读项目。"
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
              <Link to="../projects">打开 Projects</Link>
            </Button>
          }
        />
        <EmptyState
          title="当前没有活跃项目"
          description="没有处于 prelaunch 或 live 状态的项目。请先去 SignalHub 加入关注，或在 Projects 中手动创建并安排项目时间。"
        />
      </div>
    );
  }

  if (!activeProject) {
    return <LoadingState label="正在定位活跃项目..." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title="实时发射看板"
        description="当前活跃项目的只读实时数据。"
        actions={
          <>
            <div className="min-w-[240px]">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                活跃项目
              </div>
              <Select
                value={activeProject.name}
                onChange={(event) => setSelectedProject(event.target.value)}
              >
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

      <section className="overflow-hidden rounded-[32px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(119,185,175,0.34),transparent_36%),linear-gradient(180deg,rgba(255,255,255,0.96),rgba(235,245,241,0.94))] p-6 shadow-[0_28px_60px_rgba(36,142,147,0.12)]">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-3xl font-semibold tracking-[-0.05em]">{activeProject.name}</h2>
              <Badge variant={activeProject.projectedStatus === "live" ? "success" : "warning"}>
                {activeProject.projectedStatus === "live" ? "发射中" : "预热中"}
              </Badge>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            {activeProject.detailUrl ? (
              <Button asChild variant="outline">
                <a href={activeProject.detailUrl} target="_blank" rel="noreferrer">
                  项目详情
                  <ExternalLink className="size-4" />
                </a>
              </Button>
            ) : null}
            <Button asChild variant="secondary">
              <Link to={`../projects?project=${encodeURIComponent(activeProject.name)}`}>打开 Projects</Link>
            </Button>
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">开始时间</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(activeProject.startAt)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">结束时间</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(activeProject.resolvedEndAt)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">代币地址</div>
            <div className="mt-2 font-mono text-sm">{formatAddress(activeProject.tokenAddr, 8)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">内盘地址</div>
            <div className="mt-2 font-mono text-sm">{formatAddress(activeProject.internalPoolAddr, 8)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4 md:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">项目详情链接</div>
            <div className="mt-2 truncate text-sm">
              {activeProject.detailUrl ? (
                <a className="text-primary hover:underline" href={activeProject.detailUrl} target="_blank" rel="noreferrer">
                  {activeProject.detailUrl}
                </a>
              ) : (
                "未填写"
              )}
            </div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-white/72 px-4 py-4 xl:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前项目累计税收</div>
            <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
              {formatCurrency(activeProject.sumTaxV)}
            </div>
          </div>
        </div>
      </section>

      <SectionCard
        title="分钟消耗 SpentV"
        description={`默认时间窗口 ${formatDateTime(activeProject.chartFromAt)} 至 ${formatDateTime(activeProject.chartToAt)}`}
      >
        <MinuteBars items={overviewQuery.data?.minutes ?? []} />
      </SectionCard>

      <SectionCard title="Whale Board">
        <BoardTable
          rows={whaleRows}
          emptyTitle="当前没有 Whale Board 数据"
          emptyDescription="活跃项目还没有形成可展示的大户榜单，等实时交易进入后这里会自动刷新。"
        />
      </SectionCard>

      <SectionCard title="追踪钱包持仓">
        <BoardTable
          rows={trackedWalletRows}
          emptyTitle="当前还没有追踪钱包"
          emptyDescription="请先去 Wallets 页面添加钱包地址和名称，Overview 才会显示对应的持仓行。"
        />
      </SectionCard>

      <details className="group rounded-[28px] border border-border bg-white/78 px-6 py-5 shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
          <div>
            <div className="text-lg font-semibold tracking-[-0.03em]">交易录入延迟</div>
            <div className="mt-1 text-sm text-muted-foreground">默认折叠。</div>
          </div>
          <Badge variant="secondary" className="group-open:hidden">
            点击展开
          </Badge>
          <Badge variant="secondary" className="hidden group-open:inline-flex">
            已展开
          </Badge>
        </summary>

        <div className="mt-5">
          {overviewQuery.data?.delays.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>交易</TableHead>
                  <TableHead>区块时间</TableHead>
                  <TableHead>记录时间</TableHead>
                  <TableHead>延迟</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {overviewQuery.data.delays.map((row) => (
                  <TableRow key={row.tx_hash}>
                    <TableCell className="font-mono text-xs">{row.tx_hash}</TableCell>
                    <TableCell>{formatDateTime(row.block_timestamp)}</TableCell>
                    <TableCell>{formatDateTime(row.recorded_at)}</TableCell>
                    <TableCell>{formatDecimal(row.delay_sec, 1)} 秒</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              compact
              title="当前没有延迟样本"
              description="活跃项目还没有形成录入延迟样本，或最近窗口里没有新的解析记录。"
            />
          )}
        </div>
      </details>
    </div>
  );
}
