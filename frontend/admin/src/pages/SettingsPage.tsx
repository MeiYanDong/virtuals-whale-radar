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

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="全局设置"
        description="这里只保留系统级参数和运行控制，不再混入项目编辑或钱包配置。"
      />

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <SectionCard title="Runtime" description="控制全局采集状态，并查看当前运行摘要。">
          <div className="grid gap-4 md:grid-cols-2">
            <Alert>
              运行状态：
              <span className="ml-2 font-medium">{health.runtimePaused ? "Paused" : "Live"}</span>
            </Alert>
            <Alert>
              UI 心跳：
              <span className="ml-2 font-medium">{health.runtimeUiOnline ? "Online" : "Offline"}</span>
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

        <SectionCard title="采集节奏" description="控制管理后台自身的数据刷新频率。">
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
            <div className="rounded-[22px] border border-border bg-white/70 px-4 py-4 text-sm text-muted-foreground">
              这里控制的是管理员后台轮询节奏，不改变链上采集逻辑本身。
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
