import { useMutation, useQuery } from "@tanstack/react-query";
import { PauseCircle, PlayCircle, Save } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useShell } from "@/app/shell-context";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";

export function SettingsPage() {
  const {
    meta,
    health,
    refreshMode,
    setRefreshMode,
    toggleRuntimePause,
    isRuntimeMutating,
  } = useShell();
  const [dbBatchSize, setDbBatchSize] = useState("");

  const dbBatchQuery = useQuery({
    queryKey: queryKeys.dbBatch,
    queryFn: dashboardApi.admin.getDbBatchSize,
  });

  const schedulerQuery = useQuery({
    queryKey: queryKeys.projectScheduler,
    queryFn: dashboardApi.admin.getProjectSchedulerStatus,
  });

  const setDbBatchMutation = useMutation({
    mutationFn: () =>
      dashboardApi.admin.setDbBatchSize(Number(dbBatchSize || dbBatchQuery.data?.dbBatchSize || 1)),
    onSuccess: () => toast.success("DB 批量大小已更新。"),
    onError: (error: Error) => toast.error(error.message),
  });

  if (!meta || !health || !("wallets" in meta)) {
    return <LoadingState />;
  }

  const backfillRpcPool = health.backfillRpcPool ?? [];
  const backfillRpcUsage = health.backfillRpcUsage;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="全局设置"
        description="这里只保留系统级参数和运行控制，不再混入项目编辑或钱包配置。"
      />

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <SectionCard title="Runtime" description="控制全局采集状态，并查看当前运行摘要。">
          <div className="grid gap-4 md:grid-cols-3">
            <Alert>
              运行状态：
              <span className="ml-2 font-medium">{health.runtimePaused ? "Paused" : "Live"}</span>
            </Alert>
            <Alert>
              Scan Jobs：
              <span className="ml-2 font-medium">{health.scanJobs}</span>
            </Alert>
            <Alert>
              最后暂停更新时间：
              <span className="ml-2 font-medium">{formatDateTime(health.runtimePauseUpdatedAt)}</span>
            </Alert>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button onClick={() => void toggleRuntimePause()} disabled={isRuntimeMutating}>
              {health.runtimePaused ? <PlayCircle className="size-4" /> : <PauseCircle className="size-4" />}
              {health.runtimePaused ? "恢复采集" : "暂停采集"}
            </Button>
            <Badge variant="secondary">当前角色：{health.role ?? "-"}</Badge>
          </div>
        </SectionCard>

        <SectionCard title="后台刷新节奏" description="控制管理后台外壳状态的全局刷新频率。">
          <div className="space-y-3">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                刷新模式
              </div>
              <Select
                value={refreshMode}
                onChange={(event) => setRefreshMode(event.target.value as typeof refreshMode)}
              >
                <option value="normal">常规 15s</option>
                <option value="fast">极速 5s</option>
                <option value="super">超速 2.5s</option>
              </Select>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4 text-sm leading-6 text-muted-foreground">
              这里控制的是后台外壳状态刷新频率，例如顶部健康状态、SignalHub 预览和项目调度器。
              发射中的核心指标会使用独立的快速刷新策略；当前池价、含税估算 FDV、Tax Rate 和打新成本位不会被这里的 2.5s / 5s / 15s 限制。
            </div>
          </div>
        </SectionCard>
      </section>

      <SectionCard title="项目调度器" description="查看调度循环、预热窗口和最近受管项目的自动推进状态。">
        {schedulerQuery.isLoading ? (
          <LoadingState label="正在加载调度器状态..." />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-4">
              <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">调度项目数</div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {schedulerQuery.data?.count ?? 0}
                </div>
              </div>
              <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">活跃项目</div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {schedulerQuery.data?.activeCount ?? 0}
                </div>
              </div>
              <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">扫描频率</div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {schedulerQuery.data?.intervalSec ?? "-"}s
                </div>
              </div>
              <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">预热窗口</div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {schedulerQuery.data ? Math.floor(schedulerQuery.data.prelaunchLeadSec / 60) : "-"}m
                </div>
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Alert>
                调度器运行：
                <span className="ml-2 font-medium">
                  {schedulerQuery.data?.runtimePaused ? "等待 Runtime 恢复" : "正常"}
                </span>
              </Alert>
              <Alert>
                最后扫描：
                <span className="ml-2 font-medium">{formatDateTime(schedulerQuery.data?.lastRunAt)}</span>
              </Alert>
            </div>

            <div className="space-y-3">
              {(schedulerQuery.data?.items ?? []).slice(0, 6).map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-3 rounded-[22px] border border-border bg-white/70 px-4 py-4 md:flex-row md:items-center md:justify-between"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{item.name}</div>
                      <Badge variant={item.status === item.projectedStatus ? "secondary" : "warning"}>
                        {item.status} → {item.projectedStatus}
                      </Badge>
                      <Badge variant={item.isComplete ? "success" : "warning"}>
                        {item.isComplete ? "字段完整" : "待补全"}
                      </Badge>
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">
                      开始 {formatDateTime(item.startAt)} / 结束 {formatDateTime(item.resolvedEndAt)}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      Chart {formatDateTime(item.chartFromAt)} - {formatDateTime(item.chartToAt)} / Scan Job {item.lastScanJobId || "-"}
                    </div>
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    <div>Collect {item.collectEnabled ? "On" : "Off"}</div>
                    <div>Backfill {item.backfillEnabled ? "On" : "Off"}</div>
                    <div>Last Scan {formatDateTime(item.lastScanQueuedAt)}</div>
                  </div>
                </div>
              ))}
              {!schedulerQuery.data?.items.length ? (
                <div className="rounded-[22px] border border-dashed border-border bg-white/55 px-4 py-5 text-sm text-muted-foreground">
                  当前没有受管项目进入调度器。
                </div>
              ) : null}
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard
        title="回扫节点池"
        description="展示主项目 backfill 节点池的本地使用估算与健康状态。这里的 RU 仅基于本地请求统计，不等于 Chainstack 官方账单真值。"
      >
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">节点模式</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{health.backfillRpcMode || "-"}</div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">累计请求</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                {backfillRpcUsage?.totalRequestCount ?? 0}
              </div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">估算 RU</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                {backfillRpcUsage?.totalEstimatedRu ?? 0}
              </div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">最近使用</div>
              <div className="mt-3 text-sm font-medium">
                {formatDateTime(backfillRpcUsage?.lastUsedAt ?? null)}
              </div>
            </div>
          </div>

          <Alert variant="warning">
            当前 RU 为运行时本地估算值，只用于节点健康判断与容量趋势观察，不代表 Chainstack 控制台中的官方账单数据。
          </Alert>

          <div className="space-y-3">
            {backfillRpcPool.map((item) => (
              <div
                key={item.url}
                className="rounded-[22px] border border-border bg-white/70 px-4 py-4"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="font-medium">{item.label}</div>
                      <Badge variant={item.isCoolingDown ? "warning" : "success"}>
                        {item.isCoolingDown ? "冷却中" : "可用"}
                      </Badge>
                      <Badge variant={item.supportsLogs ? "success" : "warning"}>
                        Logs {item.supportsLogs ? "On" : "Off"}
                      </Badge>
                      <Badge variant={item.supportsHistoricalBlocks ? "success" : "warning"}>
                        History {item.supportsHistoricalBlocks ? "On" : "Off"}
                      </Badge>
                      <Badge variant={item.supportsBasicRpc ? "success" : "warning"}>
                        Basic {item.supportsBasicRpc ? "On" : "Off"}
                      </Badge>
                    </div>
                    <div className="break-all text-xs text-muted-foreground">{item.url}</div>
                    <div className="grid gap-2 text-xs text-muted-foreground md:grid-cols-3">
                      <div>最近探测：{formatDateTime(item.lastCheckedAt)}</div>
                      <div>最近使用：{formatDateTime(item.lastUsedAt)}</div>
                      <div>冷却截止：{formatDateTime(item.cooldownUntil)}</div>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2 md:min-w-[320px]">
                    <Alert>
                      请求数：
                      <span className="ml-2 font-medium">{item.requestCount}</span>
                    </Alert>
                    <Alert>
                      估算 RU：
                      <span className="ml-2 font-medium">{item.estimatedRu}</span>
                    </Alert>
                    <Alert>
                      Basic：
                      <span className="ml-2 font-medium">{item.basicRequestCount}</span>
                    </Alert>
                    <Alert>
                      History：
                      <span className="ml-2 font-medium">{item.historicalBlockRequestCount}</span>
                    </Alert>
                    <Alert className="sm:col-span-2">
                      Logs：
                      <span className="ml-2 font-medium">{item.logsRequestCount}</span>
                    </Alert>
                  </div>
                </div>

                {item.lastError ? (
                  <div className="mt-3 rounded-[18px] border border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)] px-3 py-3 text-xs text-[color:var(--warning-foreground)]">
                    最近错误：{item.lastError}
                  </div>
                ) : null}
              </div>
            ))}
            {!backfillRpcPool.length ? (
              <div className="rounded-[22px] border border-dashed border-border bg-white/55 px-4 py-5 text-sm text-muted-foreground">
                当前还没有可展示的回扫节点池状态。
              </div>
            ) : null}
          </div>
        </div>
      </SectionCard>

      <section className="grid gap-4 xl:grid-cols-[0.85fr_1.15fr]">
        <SectionCard title="DB 批量调节" description="保留原后台中的入库批量调节能力，但移动到统一设置页。">
          <div className="space-y-3">
            <Input
              type="number"
              min="1"
              max="100"
              value={dbBatchSize || String(dbBatchQuery.data?.dbBatchSize ?? 1)}
              onChange={(event) => setDbBatchSize(event.target.value)}
            />
            <Button onClick={() => void setDbBatchMutation.mutate()} disabled={setDbBatchMutation.isPending}>
              <Save className="size-4" />
              应用批量
            </Button>
            <div className="text-sm text-muted-foreground">
              当前后端值：{dbBatchQuery.data?.dbBatchSize ?? "-"}
            </div>
          </div>
        </SectionCard>

        <SectionCard title="固定参数摘要" description="当前先以只读方式展示固定参数，后续再决定是否开放编辑。">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">钱包数量</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{meta.wallets.length}</div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Top N</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{meta.topN}</div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">SignalHub</div>
              <div className="mt-3">
                <Badge variant={meta.signalHub.enabled ? "success" : "warning"}>
                  {meta.signalHub.enabled ? "已启用" : "未启用"}
                </Badge>
              </div>
            </div>
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">监控项目</div>
              <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                {meta.monitoringProjects.length}
              </div>
            </div>
          </div>
        </SectionCard>
      </section>
    </div>
  );
}
