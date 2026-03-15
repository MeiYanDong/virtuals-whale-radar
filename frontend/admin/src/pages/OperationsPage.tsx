import { useMutation, useQuery } from "@tanstack/react-query";
import { LoaderCircle, PauseCircle, PlayCircle, Save, ScanSearch } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useShell } from "@/app/shell-context";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime, formatRelativeSeconds, toDatetimeLocalRange, parseDatetimeLocalValue } from "@/lib/format";

export function OperationsPage() {
  const { meta, health, selectedProject, toggleRuntimePause, isRuntimeMutating } = useShell();
  const defaults = toDatetimeLocalRange(6);
  const [dbBatchSize, setDbBatchSize] = useState("1");
  const [scanStart, setScanStart] = useState(defaults.start);
  const [scanEnd, setScanEnd] = useState(defaults.end);
  const [currentJobId, setCurrentJobId] = useState("");

  const dbBatchQuery = useQuery({
    queryKey: queryKeys.dbBatch,
    queryFn: dashboardApi.admin.getDbBatchSize,
  });

  const delaysQuery = useQuery({
    queryKey: queryKeys.delays(selectedProject, 20),
    queryFn: () => dashboardApi.admin.getEventDelays(selectedProject, 20),
    enabled: Boolean(selectedProject),
  });

  const scanJobQuery = useQuery({
    queryKey: queryKeys.scanJob(currentJobId),
    queryFn: () => dashboardApi.admin.getScanJob(currentJobId),
    enabled: Boolean(currentJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ["done", "failed", "canceled"].includes(status) ? false : 2000;
    },
  });

  const setDbBatchMutation = useMutation({
    mutationFn: () => dashboardApi.admin.setDbBatchSize(Number(dbBatchSize)),
    onSuccess: () => toast.success("DB 批量大小已更新。"),
    onError: (error: Error) => toast.error(error.message),
  });

  const scanMutation = useMutation({
    mutationFn: async () => {
      const startTs = parseDatetimeLocalValue(scanStart);
      const endTs = parseDatetimeLocalValue(scanEnd);
      if (!startTs || !endTs) throw new Error("请选择有效的起止时间。");
      return dashboardApi.admin.createScanJob(selectedProject || null, startTs, endTs);
    },
    onSuccess: (result) => {
      setCurrentJobId(result.jobId);
      toast.success(`回扫任务已创建：${result.jobId}`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const cancelMutation = useMutation({
    mutationFn: () => dashboardApi.admin.cancelScanJob(currentJobId),
    onSuccess: () => toast.success("已请求取消回扫任务。"),
    onError: (error: Error) => toast.error(error.message),
  });

  if (!meta || !health) {
    return <LoadingState />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Operations"
        title="运维与控制"
        description="原来散落在旧头部的运行控制、DB 批量、回扫和延迟诊断都集中到这里。"
      />

      <section className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
        <SectionCard title="运行控制" description="高频开关保留在顶栏，这里提供完整状态和手动控制。">
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
          </div>
        </SectionCard>

        <SectionCard title="DB 批量与回扫" description="低频运维动作收纳到单独页面，避免干扰日常分析流程。">
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-3 rounded-[24px] border border-border bg-white/70 p-4">
              <div className="text-sm font-medium">DB 批量大小</div>
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

            <div className="space-y-3 rounded-[24px] border border-border bg-white/70 p-4">
              <div className="text-sm font-medium">区间回扫</div>
              <Input type="datetime-local" value={scanStart} onChange={(event) => setScanStart(event.target.value)} />
              <Input type="datetime-local" value={scanEnd} onChange={(event) => setScanEnd(event.target.value)} />
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void scanMutation.mutate()} disabled={scanMutation.isPending}>
                  <ScanSearch className="size-4" />
                  创建回扫任务
                </Button>
                <Button
                  variant="outline"
                  onClick={() => void cancelMutation.mutate()}
                  disabled={!currentJobId || cancelMutation.isPending}
                >
                  取消任务
                </Button>
              </div>
            </div>
          </div>

          {currentJobId ? (
            <div className="mt-4 rounded-[22px] border border-border bg-muted px-4 py-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">当前回扫任务</div>
                  <div className="mt-2 font-mono text-sm">{currentJobId}</div>
                </div>
                <Badge variant="secondary">{scanJobQuery.data?.status ?? "查询中"}</Badge>
              </div>
              <div className="mt-3 text-sm text-muted-foreground">
                {scanJobQuery.isFetching ? (
                  <span className="inline-flex items-center gap-2">
                    <LoaderCircle className="size-4 animate-spin" />
                    正在刷新任务状态...
                  </span>
                ) : scanJobQuery.data ? (
                  <>
                    创建于 {formatDateTime(scanJobQuery.data.createdAt)}，状态 {scanJobQuery.data.status}
                  </>
                ) : (
                  "等待任务状态..."
                )}
              </div>
            </div>
          ) : null}
        </SectionCard>
      </section>

      <SectionCard
        title="交易录入延迟"
        description={selectedProject ? `${selectedProject} 的最近 20 笔入库延迟` : "选择项目后查看延迟明细"}
      >
        {selectedProject ? (
          delaysQuery.data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>交易哈希</TableHead>
                  <TableHead>区块时间</TableHead>
                  <TableHead>录入时间</TableHead>
                  <TableHead>延迟</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {delaysQuery.data.items.map((row) => (
                  <TableRow key={row.tx_hash}>
                    <TableCell className="font-mono text-xs">{row.tx_hash}</TableCell>
                    <TableCell>{formatDateTime(row.block_timestamp)}</TableCell>
                    <TableCell>{formatDateTime(row.recorded_at)}</TableCell>
                    <TableCell>{formatRelativeSeconds(row.delay_sec)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState compact title="暂无延迟明细" description="项目还没有产生事件，或者录入队列当前为空。" />
          )
        ) : (
          <EmptyState compact title="尚未选择项目" description="Operations 页会跟随顶部当前项目切换。" />
        )}
      </SectionCard>
    </div>
  );
}
