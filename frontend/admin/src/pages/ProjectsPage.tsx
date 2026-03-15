import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  PencilLine,
  PlayCircle,
  Plus,
  ScanSearch,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { useShell } from "@/app/shell-context";
import { Alert } from "@/components/ui/alert";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { formatAddress, formatDateTime, toDatetimeLocalValue, parseDatetimeLocalValue } from "@/lib/format";
import type { AppMetaResponse, ManagedProjectItem } from "@/types/api";

type EditorState = {
  id?: number;
  signalhub_project_id?: string | null;
  name: string;
  detail_url: string;
  token_addr: string;
  internal_pool_addr: string;
  start_at: string;
  manual_end_at: string;
  collect_enabled: boolean;
  backfill_enabled: boolean;
  source: string;
  status: string;
};

function projectStatusLabel(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "scheduled") return "待执行";
  if (key === "prelaunch") return "预热中";
  if (key === "live") return "发射中";
  if (key === "ended") return "已结束";
  if (key === "removed") return "已移除";
  return "待补全";
}

function projectStatusVariant(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live" || key === "prelaunch") return "success" as const;
  if (key === "ended") return "secondary" as const;
  if (key === "removed") return "danger" as const;
  if (key === "scheduled") return "default" as const;
  return "warning" as const;
}

function buildEditorState(item?: ManagedProjectItem): EditorState {
  const startAt = item?.start_at ?? Math.floor(Date.now() / 1000) + 30 * 60;
  return {
    id: item?.id,
    signalhub_project_id: item?.signalhub_project_id ?? null,
    name: item?.name ?? "",
    detail_url: item?.detail_url ?? "",
    token_addr: item?.token_addr ?? "",
    internal_pool_addr: item?.internal_pool_addr ?? "",
    start_at: toDatetimeLocalValue(startAt),
    manual_end_at: item?.manual_end_at ? toDatetimeLocalValue(item.manual_end_at) : "",
    collect_enabled: Boolean(item ? item.collect_enabled : true),
    backfill_enabled: Boolean(item ? item.backfill_enabled : true),
    source: item?.source ?? "manual",
    status: item?.status ?? "draft",
  };
}

function deriveProjectStatus(currentStatus: string, hasPool: boolean) {
  const key = String(currentStatus || "").toLowerCase();
  if (["prelaunch", "live", "ended"].includes(key)) return key;
  return hasPool ? "scheduled" : "draft";
}

function confirmProjectUnlock(item: ManagedProjectItem) {
  return window.confirm(
    `解锁 ${item.name} 的项目详情将消耗 ${item.unlock_cost ?? 10} 积分，解锁后以后都能直接查看。确认继续吗？`,
  );
}

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { viewer, meta, refreshAll, setSelectedProject } = useShell();
  const isAdmin = viewer === "admin";
  const appMeta = !isAdmin ? (meta as AppMetaResponse | null) : null;
  const [expandedIds, setExpandedIds] = useState<number[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editorState, setEditorState] = useState<EditorState>(buildEditorState());

  const managedProjectsQuery = useQuery({
    queryKey: isAdmin ? queryKeys.managedProjects : queryKeys.appProjects,
    queryFn: () =>
      isAdmin ? dashboardApi.admin.getManagedProjects() : dashboardApi.app.getProjects(),
  });

  const projects = useMemo(() => managedProjectsQuery.data?.items ?? [], [managedProjectsQuery.data?.items]);

  const unlockMutation = useMutation({
    mutationFn: async (item: ManagedProjectItem) => dashboardApi.app.unlockProject(item.id),
    onSuccess: async (_, item) => {
      const status = String(item.status).toLowerCase();
      const isActiveOverview = ["prelaunch", "live"].includes(status);
      const destination = isActiveOverview
        ? `/app/overview?project=${encodeURIComponent(item.name)}`
        : `/app/projects/${item.id}`;
      toast.success(
        isActiveOverview
          ? `${item.name} 已解锁，现在就能直接打开实时看板。`
          : `${item.name} 已解锁，现在就能打开项目详情回看历史盘面。`,
      );
      if (isActiveOverview) {
        setSelectedProject(item.name);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjectAccess(item.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appOverviewActive(item.name) }),
        refreshAll(),
      ]);
      void navigate(destination);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const saveMutation = useMutation({
    mutationFn: async (state: EditorState) => {
      const startAt = parseDatetimeLocalValue(state.start_at);
      if (!startAt) {
        throw new Error("开始时间不能为空。");
      }
      const manualEndAt = state.manual_end_at ? parseDatetimeLocalValue(state.manual_end_at) : null;
      const hasPool = Boolean(state.internal_pool_addr.trim());
      return dashboardApi.admin.upsertManagedProject({
        id: state.id,
        signalhub_project_id: state.signalhub_project_id ?? undefined,
        name: state.name.trim(),
        detail_url: state.detail_url.trim(),
        token_addr: state.token_addr.trim() || null,
        internal_pool_addr: state.internal_pool_addr.trim() || null,
        start_at: startAt,
        manual_end_at: manualEndAt,
        is_watched: true,
        collect_enabled: state.collect_enabled,
        backfill_enabled: state.backfill_enabled,
        source: state.source,
        status: deriveProjectStatus(state.status, hasPool),
      });
    },
    onSuccess: async () => {
      toast.success("项目已保存。");
      setSheetOpen(false);
      setEditorState(buildEditorState());
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        refreshAll(),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      await Promise.all(ids.map((id) => dashboardApi.admin.deleteManagedProject(id)));
      return ids;
    },
    onSuccess: async (ids) => {
      toast.success(`已删除 ${ids.length} 个项目。`);
      setSelectedIds((current) => current.filter((id) => !ids.includes(id)));
      setExpandedIds((current) => current.filter((id) => !ids.includes(id)));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        refreshAll(),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const toggleCollectMutation = useMutation({
    mutationFn: async (item: ManagedProjectItem) =>
      dashboardApi.admin.upsertManagedProject({
        ...item,
        is_watched: Boolean(item.is_watched),
        collect_enabled: !item.collect_enabled,
        backfill_enabled: Boolean(item.backfill_enabled),
      }),
    onSuccess: async (_, item) => {
      toast.success(
        `${item.name} ${item.collect_enabled ? "已暂停采集资格" : "已恢复采集资格"}。`,
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        refreshAll(),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const scanMutation = useMutation({
    mutationFn: async (item: ManagedProjectItem) =>
      dashboardApi.admin.createScanJob(item.name, item.start_at, item.resolved_end_at),
    onSuccess: async (_, item) => {
      toast.success(`${item.name} 已发起按项目窗口的回扫任务。`);
      await refreshAll();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const openCreateSheet = () => {
    setEditorState(buildEditorState());
    setSheetOpen(true);
  };

  const openEditSheet = (item: ManagedProjectItem) => {
    setEditorState(buildEditorState(item));
    setSheetOpen(true);
  };

  const toggleExpanded = (projectId: number) => {
    setExpandedIds((current) =>
      current.includes(projectId) ? current.filter((id) => id !== projectId) : [...current, projectId],
    );
  };

  const toggleSelected = (projectId: number) => {
    setSelectedIds((current) =>
      current.includes(projectId) ? current.filter((id) => id !== projectId) : [...current, projectId],
    );
  };

  const allSelected = projects.length > 0 && selectedIds.length === projects.length;
  const unlockableCount = !isAdmin
    ? projects.filter((item) => !item.is_unlocked && item.can_unlock_now).length
    : 0;

  const confirmDelete = (count: number) => {
    if (count <= 0) return false;
    return window.confirm(
      count === 1
        ? "删除后会取消关注、从 Projects 移除并停止调度，但历史数据会保留。确认继续吗？"
        : `删除 ${count} 个项目后会取消关注、从 Projects 移除并停止调度，但历史数据会保留。确认继续吗？`,
    );
  };

  if (!meta || managedProjectsQuery.isLoading) {
    return <LoadingState label="正在加载项目管理列表..." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Projects"
        title={isAdmin ? "项目管理" : "项目列表"}
        description={
          isAdmin
            ? "管理受管项目的新增、删除、编辑、采集和回扫。"
            : "先看项目时间、详情和状态，再决定要不要解锁实时看板。"
        }
        actions={
          isAdmin ? (
            <>
              <Button variant="secondary" onClick={openCreateSheet}>
                <Plus className="size-4" />
                新建项目
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  if (!confirmDelete(selectedIds.length)) return;
                  void deleteMutation.mutateAsync(selectedIds);
                }}
                disabled={!selectedIds.length || deleteMutation.isPending}
              >
                <Trash2 className="size-4" />
                删除项目
              </Button>
            </>
          ) : null
        }
      />

      {!isAdmin && appMeta ? (
        <Alert>
          当前剩余 {appMeta.credit_balance} 积分，可立即解锁 {unlockableCount} 个项目的实时看板。
          建议先挑你真正想持续观察的项目，再把积分花出去。
        </Alert>
      ) : null}

      <SectionCard
        title="项目列表"
        description={
          isAdmin
            ? "每行一个项目；展开后才显示详细字段和运行控制，避免把所有低频表单摊在首屏。"
            : "每行一个项目；展开后先看基础信息，觉得值得盯再解锁实时看板。"
        }
        actions={
          isAdmin && projects.length ? (
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={() =>
                  setSelectedIds(allSelected ? [] : projects.map((item) => item.id))
                }
              />
              全选
            </label>
          ) : null
        }
      >
        {projects.length ? (
          <div className="space-y-4">
            {projects.map((item) => {
              const expanded = expandedIds.includes(item.id);
              const selected = selectedIds.includes(item.id);
              return (
                <div
                  key={item.id}
                  className="rounded-[26px] border border-border bg-white/80 px-5 py-5 shadow-sm"
                >
                  <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                    <div className="flex min-w-0 items-start gap-3">
                      {isAdmin ? (
                        <input
                          className="mt-1"
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleSelected(item.id)}
                        />
                      ) : null}
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="text-xl font-semibold tracking-[-0.03em]">{item.name}</h3>
                          <Badge variant={projectStatusVariant(item.status)}>
                            {projectStatusLabel(item.status)}
                          </Badge>
                          <Badge variant="secondary">{item.source || "manual"}</Badge>
                          {!isAdmin ? (
                            <Badge variant={item.is_unlocked ? "success" : "warning"}>
                              {item.is_unlocked ? "实时看板已解锁" : `待解锁 · ${item.unlock_cost ?? 10} 积分`}
                            </Badge>
                          ) : null}
                        </div>
                        <div className="grid gap-2 text-sm text-muted-foreground md:grid-cols-3">
                          <div>开始时间：{formatDateTime(item.start_at)}</div>
                          <div>结束时间：{formatDateTime(item.resolved_end_at)}</div>
                          <div className="truncate">
                            项目详情：
                            {item.detail_url ? (
                              <a
                                className="ml-1 inline-flex items-center gap-1 text-primary"
                                href={item.detail_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                打开
                                <ExternalLink className="size-3" />
                              </a>
                            ) : (
                              "未填写"
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    <Button variant="ghost" onClick={() => toggleExpanded(item.id)}>
                      {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                      {expanded ? "收起" : "展开"}
                    </Button>
                  </div>

                  {expanded ? (
                    <div className="mt-5 grid gap-4 xl:grid-cols-[1fr_auto]">
                      <div className="grid gap-3 md:grid-cols-2">
                        <div className="rounded-[22px] border border-border bg-muted px-4 py-4">
                          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">代币地址</div>
                          <div className="mt-2 font-mono text-sm">
                            {item.token_addr ? formatAddress(item.token_addr) : "未填写"}
                          </div>
                        </div>
                        <div className="rounded-[22px] border border-border bg-muted px-4 py-4">
                          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">内盘地址</div>
                          <div className="mt-2 font-mono text-sm">
                            {item.internal_pool_addr ? formatAddress(item.internal_pool_addr) : "未填写"}
                          </div>
                        </div>
                        <div className="rounded-[22px] border border-border bg-muted px-4 py-4">
                          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">运行状态</div>
                          <div className="mt-2 text-sm">
                            采集 {item.collect_enabled ? "已启用" : "已关闭"} / 回扫{" "}
                            {item.backfill_enabled ? "已启用" : "已关闭"}
                          </div>
                        </div>
                        <div className="rounded-[22px] border border-border bg-muted px-4 py-4">
                          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">更新时间</div>
                          <div className="mt-2 text-sm">{formatDateTime(item.updated_at)}</div>
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-2 xl:flex-col xl:items-stretch">
                        {isAdmin ? (
                          <>
                            <Button
                              variant={item.collect_enabled ? "secondary" : "default"}
                              onClick={() => void toggleCollectMutation.mutateAsync(item)}
                              disabled={toggleCollectMutation.isPending}
                            >
                              <PlayCircle className="size-4" />
                              {item.collect_enabled ? "暂停采集" : "恢复采集"}
                            </Button>
                            <Button
                              variant="outline"
                              onClick={() => void scanMutation.mutateAsync(item)}
                              disabled={scanMutation.isPending}
                            >
                              <ScanSearch className="size-4" />
                              立即回扫
                            </Button>
                            <Button variant="outline" onClick={() => openEditSheet(item)}>
                              <PencilLine className="size-4" />
                              编辑
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                if (!confirmDelete(1)) return;
                                void deleteMutation.mutateAsync([item.id]);
                              }}
                              disabled={deleteMutation.isPending}
                            >
                              <Trash2 className="size-4" />
                              删除
                            </Button>
                          </>
                        ) : (
                          <>
                            {item.is_unlocked ? (
                              <Button
                                variant="secondary"
                                onClick={() => {
                                  setSelectedProject(item.name);
                                  const status = String(item.status).toLowerCase();
                                  const destination = ["prelaunch", "live"].includes(status)
                                    ? `/app/overview?project=${encodeURIComponent(item.name)}`
                                    : `/app/projects/${item.id}`;
                                  void navigate(destination);
                                }}
                              >
                                <PlayCircle className="size-4" />
                                {["prelaunch", "live"].includes(String(item.status).toLowerCase())
                                  ? "打开实时看板"
                                  : String(item.status).toLowerCase() === "ended"
                                    ? "查看历史详情"
                                    : "查看项目详情"}
                              </Button>
                            ) : (
                              <Button
                                onClick={() => {
                                  if (!confirmProjectUnlock(item)) return;
                                  void unlockMutation.mutateAsync(item);
                                }}
                                disabled={!item.can_unlock_now || unlockMutation.isPending}
                              >
                                <PlayCircle className="size-4" />
                                解锁项目详情
                              </Button>
                            )}
                            <Button
                              variant="outline"
                              onClick={() => void navigate("/app/billing")}
                            >
                              <Plus className="size-4" />
                              去充值页
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState
            title="还没有受管项目"
            description={
              isAdmin
                ? "先去 SignalHub 勾选关注，或者手动创建一个项目，之后它们会统一出现在这里。"
                : "当前还没有可看的项目，稍后回来看看，或先去“即将发射”挑候选项目。"
            }
            action={
              isAdmin ? (
                <Button onClick={openCreateSheet}>
                  <Plus className="size-4" />
                  新建项目
                </Button>
              ) : null
            }
          />
        )}
      </SectionCard>

      <Sheet open={isAdmin && sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="px-0 py-0">
          <SheetTitle className="sr-only">
            {editorState.id ? "编辑项目" : "新建项目"}
          </SheetTitle>
          <SheetDescription className="sr-only">
            编辑受管项目资料、运行状态与时间窗口。
          </SheetDescription>
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex-1 overflow-y-auto px-6 py-8">
              <div className="space-y-6">
                <div className="space-y-2">
                  <Badge variant="secondary">Managed Project</Badge>
                  <h2 className="text-2xl font-semibold tracking-[-0.04em]">
                    {editorState.id ? "编辑项目" : "新建项目"}
                  </h2>
                  <p className="text-sm leading-6 text-muted-foreground">
                    `Projects` 页面只维护项目资料和运行控制，后续自动调度会围绕这里的数据模型展开。
                  </p>
                </div>

                <div className="space-y-4">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      项目名称
                    </div>
                    <Input
                      value={editorState.name}
                      onChange={(event) => setEditorState((current) => ({ ...current, name: event.target.value }))}
                    />
                  </div>
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      项目详情
                    </div>
                    <Input
                      value={editorState.detail_url}
                      onChange={(event) =>
                        setEditorState((current) => ({ ...current, detail_url: event.target.value }))
                      }
                      placeholder="https://..."
                    />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        开始时间
                      </div>
                      <Input
                        type="datetime-local"
                        value={editorState.start_at}
                        onChange={(event) =>
                          setEditorState((current) => ({ ...current, start_at: event.target.value }))
                        }
                      />
                    </div>
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        手动结束时间
                      </div>
                      <Input
                        type="datetime-local"
                        value={editorState.manual_end_at}
                        onChange={(event) =>
                          setEditorState((current) => ({ ...current, manual_end_at: event.target.value }))
                        }
                      />
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        代币地址
                      </div>
                      <Input
                        value={editorState.token_addr}
                        onChange={(event) =>
                          setEditorState((current) => ({ ...current, token_addr: event.target.value }))
                        }
                        placeholder="0x..."
                      />
                    </div>
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        内盘地址
                      </div>
                      <Input
                        value={editorState.internal_pool_addr}
                        onChange={(event) =>
                          setEditorState((current) => ({
                            ...current,
                            internal_pool_addr: event.target.value,
                          }))
                        }
                        placeholder="0x..."
                      />
                    </div>
                  </div>

                  <div className="grid gap-3 text-sm text-muted-foreground md:grid-cols-2">
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={editorState.collect_enabled}
                        onChange={(event) =>
                          setEditorState((current) => ({
                            ...current,
                            collect_enabled: event.target.checked,
                          }))
                        }
                      />
                      启用采集
                    </label>
                    <label className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={editorState.backfill_enabled}
                        onChange={(event) =>
                          setEditorState((current) => ({
                            ...current,
                            backfill_enabled: event.target.checked,
                          }))
                        }
                      />
                      启用回扫
                    </label>
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-border bg-card/96 px-6 py-4 backdrop-blur">
              <div className="flex justify-end gap-3">
                <Button variant="ghost" onClick={() => setSheetOpen(false)}>
                  取消
                </Button>
                <Button onClick={() => void saveMutation.mutateAsync(editorState)} disabled={saveMutation.isPending}>
                  {editorState.id ? "保存项目" : "创建项目"}
                </Button>
              </div>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
