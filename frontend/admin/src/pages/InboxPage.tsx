import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckSquare,
  ChevronDown,
  ExternalLink,
  Eye,
  Link2,
  PlusCircle,
  Search,
  Square,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { useShell } from "@/app/shell-context";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatAddress,
  formatCountdown,
  formatDateTime,
  parseDatetimeLocalValue,
  toDatetimeLocalValue,
} from "@/lib/format";
import type { AppMetaResponse, ManagedProjectItem, ManagedProjectUpsertPayload, SignalHubItem } from "@/types/api";

type WatchEditorState = {
  existingId?: number;
  signalhub_project_id: string;
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

function startTsFromSignalHub(item: SignalHubItem) {
  const parsed = Date.parse(item.launchTime || "");
  if (Number.isFinite(parsed)) {
    return Math.floor(parsed / 1000);
  }
  return Math.floor(Date.now() / 1000) + 30 * 60;
}

function isItemComplete(item: SignalHubItem, managed?: ManagedProjectItem | null) {
  return Boolean(
    managed?.token_addr ||
      item.contractAddress ||
      managed?.internal_pool_addr ||
      item.liquidityPool,
  );
}

function resolvedEndFromSignalHub(item: SignalHubItem, managed?: ManagedProjectItem | null) {
  const startAt = managed?.start_at ?? startTsFromSignalHub(item);
  return managed?.resolved_end_at ?? startAt + 99 * 60;
}

function watchStateLabel(managed?: ManagedProjectItem | null) {
  if (!managed) return "未关注";
  if (managed.status === "draft") return "待补全";
  if (managed.status === "scheduled") return "已关注";
  if (managed.status === "prelaunch") return "预热中";
  if (managed.status === "live") return "发射中";
  if (managed.status === "ended") return "已结束";
  return managed.status;
}

function watchStateVariant(managed?: ManagedProjectItem | null) {
  if (!managed) return "secondary" as const;
  if (managed.status === "draft") return "warning" as const;
  if (managed.status === "scheduled") return "default" as const;
  if (managed.status === "prelaunch" || managed.status === "live") return "success" as const;
  if (managed.status === "ended") return "secondary" as const;
  return "danger" as const;
}

function buildWatchEditorState(item: SignalHubItem, managed?: ManagedProjectItem | null): WatchEditorState {
  const startAt = managed?.start_at ?? startTsFromSignalHub(item);
  return {
    existingId: managed?.id,
    signalhub_project_id: item.projectId,
    name: managed?.name ?? item.importName,
    detail_url: managed?.detail_url ?? item.url ?? "",
    token_addr: managed?.token_addr ?? item.contractAddress ?? "",
    internal_pool_addr: managed?.internal_pool_addr ?? item.liquidityPool ?? "",
    start_at: toDatetimeLocalValue(startAt),
    manual_end_at: managed?.manual_end_at ? toDatetimeLocalValue(managed.manual_end_at) : "",
    collect_enabled: managed ? Boolean(managed.collect_enabled) : true,
    backfill_enabled: managed ? Boolean(managed.backfill_enabled) : true,
    source: managed?.source ?? "signalhub",
    status: managed?.status ?? (isItemComplete(item, managed) ? "scheduled" : "draft"),
  };
}

function buildWatchPayload(
  state: WatchEditorState,
  fallbackItem?: SignalHubItem | null,
): ManagedProjectUpsertPayload {
  const startAt = parseDatetimeLocalValue(state.start_at);
  if (!startAt) {
    throw new Error("开始时间不能为空。");
  }
  const manualEndAt = state.manual_end_at ? parseDatetimeLocalValue(state.manual_end_at) : null;
  const hasEnoughFields = Boolean((state.token_addr || fallbackItem?.contractAddress) && (state.internal_pool_addr || fallbackItem?.liquidityPool));
  return {
    id: state.existingId,
    signalhub_project_id: state.signalhub_project_id,
    name: state.name.trim(),
    detail_url: state.detail_url.trim(),
    token_addr: state.token_addr.trim() || null,
    internal_pool_addr: state.internal_pool_addr.trim() || null,
    start_at: startAt,
    manual_end_at: manualEndAt,
    is_watched: true,
    collect_enabled: state.collect_enabled,
    backfill_enabled: state.backfill_enabled,
    source: state.source || "signalhub",
    status: ["prelaunch", "live", "ended"].includes(state.status)
      ? state.status
      : hasEnoughFields
        ? "scheduled"
        : "draft",
  };
}

export function InboxPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { viewer, meta, refreshAll } = useShell();
  const isAdmin = viewer === "admin";
  const appMeta = !isAdmin ? (meta as AppMetaResponse | null) : null;
  const adminMeta = meta && "signalHub" in meta ? meta : null;
  const [keyword, setKeyword] = useState("");
  const [timeFilterHours, setTimeFilterHours] = useState(72);
  const [watchedOnly, setWatchedOnly] = useState(false);
  const [visibleCount, setVisibleCount] = useState(12);
  const [selectedProjectIds, setSelectedProjectIds] = useState<string[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetItem, setSheetItem] = useState<SignalHubItem | null>(null);
  const [editorState, setEditorState] = useState<WatchEditorState | null>(null);

  const signalHubLimit = 50;
  const signalHubWithinHours = timeFilterHours;
  const signalHubQueryKey = queryKeys.signalHub(signalHubLimit, signalHubWithinHours);

  const managedProjectsQuery = useQuery({
    queryKey: isAdmin ? queryKeys.managedProjects : queryKeys.appProjects,
    queryFn: () =>
      isAdmin ? dashboardApi.admin.getManagedProjects() : dashboardApi.app.getProjects(),
  });

  const inboxQuery = useQuery({
    queryKey: isAdmin ? signalHubQueryKey : queryKeys.appSignalHub(signalHubLimit, signalHubWithinHours),
    queryFn: () =>
      isAdmin
        ? dashboardApi.admin.getSignalHubUpcoming(signalHubLimit, signalHubWithinHours)
        : dashboardApi.app.getSignalHubUpcoming(signalHubLimit, signalHubWithinHours),
    enabled: Boolean(meta),
  });

  const managedBySignalHubId = useMemo(() => {
    const map = new Map<string, ManagedProjectItem>();
    for (const item of managedProjectsQuery.data?.items ?? []) {
      if (item.signalhub_project_id) {
        map.set(item.signalhub_project_id, item);
      }
    }
    return map;
  }, [managedProjectsQuery.data?.items]);

  const managedByName = useMemo(() => {
    const map = new Map<string, ManagedProjectItem>();
    for (const item of managedProjectsQuery.data?.items ?? []) {
      map.set(item.name.toUpperCase(), item);
    }
    return map;
  }, [managedProjectsQuery.data?.items]);

  const resolveManaged = (item: SignalHubItem) =>
    managedBySignalHubId.get(item.projectId) ?? managedByName.get(item.importName.toUpperCase()) ?? null;

  const rows = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return (inboxQuery.data?.items ?? []).filter((item) => {
      const managed =
        managedBySignalHubId.get(item.projectId) ?? managedByName.get(item.importName.toUpperCase()) ?? null;
      if (watchedOnly && !managed) {
        return false;
      }
      if (!search) return true;
      return [item.importName, item.name, item.displayTitle, item.symbol]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(search));
    });
  }, [inboxQuery.data?.items, keyword, watchedOnly, managedByName, managedBySignalHubId]);

  const watchMutation = useMutation({
    mutationFn: async (payloads: ManagedProjectUpsertPayload[]) => {
      if (!isAdmin) {
        throw new Error("用户视图不可写入关注列表。");
      }
      await Promise.all(payloads.map((payload) => dashboardApi.admin.upsertManagedProject(payload)));
    },
    onSuccess: async (_, payloads) => {
      toast.success(`已加入关注 ${payloads.length} 个项目。`);
      setSelectedProjectIds([]);
      setSheetOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        queryClient.invalidateQueries({ queryKey: signalHubQueryKey }),
        refreshAll(),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const unwatchMutation = useMutation({
    mutationFn: async (ids: number[]) => {
      if (!isAdmin) {
        throw new Error("用户视图不可取消关注。");
      }
      await Promise.all(ids.map((id) => dashboardApi.admin.deleteManagedProject(id)));
    },
    onSuccess: async (_, ids) => {
      toast.success(`已取消关注 ${ids.length} 个项目。`);
      setSelectedProjectIds([]);
      setSheetOpen(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.managedProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        queryClient.invalidateQueries({ queryKey: signalHubQueryKey }),
        refreshAll(),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const openPreview = (item: SignalHubItem) => {
    const managed = resolveManaged(item);
    setSheetItem(item);
    setEditorState(buildWatchEditorState(item, managed));
    setSheetOpen(true);
  };

  const selectedRows = rows.filter((item) => selectedProjectIds.includes(item.projectId));
  const visibleRows = rows.slice(0, visibleCount);
  const allSelected = rows.length > 0 && rows.every((item) => selectedProjectIds.includes(item.projectId));
  const unlockableCount = !isAdmin
    ? rows.filter((item) => item.managedProjectId && !item.isUnlocked && item.canUnlockNow).length
    : 0;

  const confirmUnwatch = (count: number) => {
    if (count <= 0) return false;
    return window.confirm(
      count === 1
        ? "取消关注后，项目会从 Projects 列表移除并停止调度，但历史数据会保留。确认继续吗？"
        : `取消关注 ${count} 个项目后，它们会从 Projects 列表移除并停止调度，但历史数据会保留。确认继续吗？`,
    );
  };

  const watchSelected = async () => {
    if (!selectedRows.length) return;
    const payloads = selectedRows.map((item) => buildWatchPayload(buildWatchEditorState(item, resolveManaged(item)), item));
    await watchMutation.mutateAsync(payloads);
  };

  const unwatchSelected = async () => {
    const ids = selectedRows
      .map((item) => resolveManaged(item))
      .filter((item): item is ManagedProjectItem => Boolean(item))
      .map((item) => item.id);
    if (!ids.length) return;
    if (!confirmUnwatch(ids.length)) return;
    await unwatchMutation.mutateAsync(ids);
  };

  if (!meta || managedProjectsQuery.isLoading) {
    return <LoadingState label="正在加载 SignalHub 关注列表..." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="SignalHub"
        title={isAdmin ? "关注列表入口" : "即将发射"}
        description={isAdmin ? "筛选 upcoming 项目并加入或取消关注。" : "先浏览即将发射的项目，挑出真正值得提前盯的候选。"}
        actions={
          isAdmin ? (
            <>
              <Button
                variant="secondary"
                onClick={() => setSelectedProjectIds(allSelected ? [] : rows.map((item) => item.projectId))}
              >
                {allSelected ? <Square className="size-4" /> : <CheckSquare className="size-4" />}
                {allSelected ? "取消全选" : "全选"}
              </Button>
              <Button
                onClick={() => void watchSelected()}
                disabled={!selectedRows.length || watchMutation.isPending}
              >
                <PlusCircle className="size-4" />
                加入关注
              </Button>
              <Button
                variant="outline"
                onClick={() => void unwatchSelected()}
                disabled={!selectedRows.length || unwatchMutation.isPending}
              >
                <Trash2 className="size-4" />
                取消关注
              </Button>
            </>
          ) : null
        }
      />

      {adminMeta && !adminMeta.signalHub.enabled ? (
        <Alert variant="warning">
          当前没有配置 `SIGNALHUB_BASE_URL`，SignalHub 页面无法拉取 upcoming 项目。
        </Alert>
      ) : null}

      {!isAdmin && appMeta ? (
        <Alert>
          当前剩余 {appMeta.credit_balance} 积分。已纳入管理且可立即解锁的项目有 {unlockableCount} 个，
          先从这里挑项目，再回项目列表解锁真正想持续观察的盘面。
        </Alert>
      ) : null}

      <SectionCard
        title="upcoming 项目"
        description={
          isAdmin
            ? "默认展示 72 小时内的 upcoming 项目；首屏先看 12 条，需要时再继续展开。"
            : "默认先看 72 小时内的 upcoming 项目；你可以按时间窗口筛一遍，再决定要不要继续跟。"
        }
        actions={
          <div className="flex w-full flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              {[
                { label: "24h", value: 24 },
                { label: "72h", value: 72 },
                { label: "7天", value: 168 },
              ].map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="sm"
                  variant={timeFilterHours === option.value ? "default" : "secondary"}
                  onClick={() => {
                    setTimeFilterHours(option.value);
                    setVisibleCount(12);
                  }}
                >
                  {option.label}
                </Button>
              ))}
              <Button
                type="button"
                size="sm"
                variant={watchedOnly ? "default" : "secondary"}
                onClick={() => {
                  setWatchedOnly((current) => !current);
                  setVisibleCount(12);
                }}
              >
                已关注
              </Button>
            </div>
            <div className="relative w-full min-w-[260px] max-w-[360px]">
              <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-10"
                value={keyword}
                onChange={(event) => {
                  setKeyword(event.target.value);
                  setVisibleCount(12);
                }}
                placeholder="搜索项目名、标题或 symbol"
              />
            </div>
          </div>
        }
      >
        {inboxQuery.isLoading ? (
          <LoadingState label={isAdmin ? "正在拉取 upcoming 项目..." : "正在加载即将发射项目..."} />
        ) : inboxQuery.isError ? (
          <EmptyState
            title="即将发射项目加载失败"
            description={isAdmin ? "当前无法加载 upcoming 项目，请确认 SignalHub 服务在线并检查 `/signalhub/upcoming` 接口。" : "现在暂时拉不到新的项目列表，稍后刷新再看。"}
          />
        ) : rows.length ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  {isAdmin ? <TableHead className="w-[56px]">选择</TableHead> : null}
                  <TableHead>项目名称</TableHead>
                  <TableHead>开始时间</TableHead>
                  <TableHead>结束时间</TableHead>
                  <TableHead>项目详情</TableHead>
                  <TableHead>字段完整度</TableHead>
                  <TableHead>当前关注状态</TableHead>
                  <TableHead className="w-[220px]">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRows.map((item) => {
                  const managed = resolveManaged(item);
                  const complete = isItemComplete(item, managed);
                  return (
                    <TableRow key={item.projectId}>
                      {isAdmin ? (
                        <TableCell>
                          <input
                            type="checkbox"
                            checked={selectedProjectIds.includes(item.projectId)}
                            onChange={() =>
                              setSelectedProjectIds((current) =>
                                current.includes(item.projectId)
                                  ? current.filter((id) => id !== item.projectId)
                                  : [...current, item.projectId],
                              )
                            }
                          />
                        </TableCell>
                      ) : null}
                      <TableCell>
                        <div className="space-y-1">
                          <div className="font-medium">{item.importName}</div>
                          <div className="text-xs text-muted-foreground">
                            {item.name || item.displayTitle || "暂无标题"}
                          </div>
                          <div className="text-xs text-muted-foreground">
                            {item.symbol ? `Symbol ${item.symbol}` : "无 symbol"} / 倒计时 {formatCountdown(item.secondsToLaunch)}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>{formatDateTime(item.launchTime)}</TableCell>
                      <TableCell>{formatDateTime(resolvedEndFromSignalHub(item, managed))}</TableCell>
                      <TableCell>
                        {item.url ? (
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-primary hover:underline"
                          >
                            打开
                            <ExternalLink className="size-3" />
                          </a>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={complete ? "success" : "warning"}>
                          {complete ? "字段完整" : "待补地址"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Badge variant={watchStateVariant(managed)}>{watchStateLabel(managed)}</Badge>
                          {!isAdmin && item.managedProjectId ? (
                            <Badge variant={item.isUnlocked ? "success" : "warning"}>
                              {item.isUnlocked ? "实时看板已解锁" : `待解锁 · ${item.unlockCost ?? 10} 积分`}
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <Button variant="secondary" size="sm" onClick={() => openPreview(item)}>
                            <Eye className="size-4" />
                            预览
                          </Button>
                          {isAdmin ? (
                            managed ? (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  if (!confirmUnwatch(1)) return;
                                  void unwatchMutation.mutateAsync([managed.id]);
                                }}
                                disabled={unwatchMutation.isPending}
                              >
                                <Trash2 className="size-4" />
                                取消关注
                              </Button>
                            ) : (
                              <Button
                                size="sm"
                                onClick={() =>
                                  void watchMutation.mutateAsync([
                                    buildWatchPayload(buildWatchEditorState(item, managed), item),
                                  ])
                                }
                                disabled={watchMutation.isPending}
                              >
                                <PlusCircle className="size-4" />
                                加入关注
                              </Button>
                            )
                          ) : item.managedProjectId ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                void navigate(
                                  item.isUnlocked
                                    ? `/app/projects?project=${encodeURIComponent(item.importName)}`
                                    : item.canUnlockNow
                                      ? `/app/projects?project=${encodeURIComponent(item.importName)}`
                                      : "/app/billing",
                                )
                              }
                            >
                              <Link2 className="size-4" />
                              {item.isUnlocked ? "打开项目" : item.canUnlockNow ? "去项目列表解锁" : "去充值页"}
                            </Button>
                          ) : null}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            {rows.length > visibleRows.length ? (
              <div className="mt-4 flex items-center justify-between gap-3 border-t border-border/70 pt-4">
                <div className="text-sm text-muted-foreground">
                  已显示 {visibleRows.length} / {rows.length} 个项目
                </div>
                <Button
                  variant="secondary"
                  onClick={() => setVisibleCount((current) => Math.min(current + 12, rows.length))}
                >
                  <ChevronDown className="size-4" />
                  查看更多
                </Button>
              </div>
            ) : null}
          </div>
        ) : (
          <EmptyState
            title="当前没有符合条件的项目"
            description="SignalHub 当前窗口内没有 upcoming 数据，或当前关键词没有命中任何项目。"
          />
        )}
      </SectionCard>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="px-0 py-0">
          <SheetTitle className="sr-only">
            {sheetItem ? `${sheetItem.importName} SignalHub 详情` : "SignalHub 详情"}
          </SheetTitle>
          <SheetDescription className="sr-only">
            查看 SignalHub 项目详情，并在管理员视图中决定是否加入关注。
          </SheetDescription>
          {sheetItem && editorState ? (
            <div className="flex h-full min-h-0 flex-col">
              <div className="flex-1 overflow-y-auto px-6 py-8">
                <div className="space-y-6">
                  <div className="space-y-3">
                    <div className="flex items-center gap-2">
                      <Badge variant={watchStateVariant(resolveManaged(sheetItem))}>
                        {watchStateLabel(resolveManaged(sheetItem))}
                      </Badge>
                      <span className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
                        SignalHub Preview
                      </span>
                    </div>
                    <h2 className="text-2xl font-semibold tracking-[-0.04em]">{sheetItem.importName}</h2>
                    <p className="text-sm leading-6 text-muted-foreground">
                      {isAdmin
                        ? "这里可以在加入关注前补充地址、调整时间窗口，保存后项目会直接同步到 Projects 页面。"
                        : "这里先看项目详情和解析结果，判断它值不值得进入你的观察列表。"}
                    </p>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        项目名称
                      </div>
                      <Input
                        value={editorState.name}
                        readOnly={!isAdmin}
                        onChange={(event) =>
                          setEditorState((current) => (current ? { ...current, name: event.target.value } : current))
                        }
                      />
                    </div>
                    <div>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        项目详情
                      </div>
                      <Input
                        value={editorState.detail_url}
                        readOnly={!isAdmin}
                        onChange={(event) =>
                          setEditorState((current) =>
                            current ? { ...current, detail_url: event.target.value } : current,
                          )
                        }
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
                          readOnly={!isAdmin}
                          onChange={(event) =>
                            setEditorState((current) =>
                              current ? { ...current, start_at: event.target.value } : current,
                            )
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
                          readOnly={!isAdmin}
                          onChange={(event) =>
                            setEditorState((current) =>
                              current ? { ...current, manual_end_at: event.target.value } : current,
                            )
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
                          readOnly={!isAdmin}
                          onChange={(event) =>
                            setEditorState((current) =>
                              current ? { ...current, token_addr: event.target.value } : current,
                            )
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
                          readOnly={!isAdmin}
                          onChange={(event) =>
                            setEditorState((current) =>
                              current ? { ...current, internal_pool_addr: event.target.value } : current,
                            )
                          }
                          placeholder="0x..."
                        />
                      </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">SignalHub 代币</div>
                        <div className="mt-2 font-mono text-sm">
                          {sheetItem.contractAddress ? formatAddress(sheetItem.contractAddress, 8) : "待识别"}
                        </div>
                      </div>
                      <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                        <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">SignalHub 内盘</div>
                        <div className="mt-2 font-mono text-sm">
                          {sheetItem.liquidityPool ? formatAddress(sheetItem.liquidityPool, 8) : "待识别"}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4 text-sm text-muted-foreground">
                      <div className="flex items-center gap-2 font-medium text-foreground">
                        <Link2 className="size-4 text-primary" />
                        解析后的结束时间
                      </div>
                      <div className="mt-2">
                        {formatDateTime(
                          editorState.manual_end_at
                            ? parseDatetimeLocalValue(editorState.manual_end_at)
                            : (parseDatetimeLocalValue(editorState.start_at) ?? startTsFromSignalHub(sheetItem)) + 99 * 60,
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="border-t border-border bg-card/96 px-6 py-4 backdrop-blur">
                <div className="flex justify-end gap-3">
                  <Button variant="ghost" onClick={() => setSheetOpen(false)}>
                    关闭
                  </Button>
                  {isAdmin ? (
                    <Button
                      onClick={() =>
                        void watchMutation.mutateAsync([buildWatchPayload(editorState, sheetItem)])
                      }
                      disabled={watchMutation.isPending}
                    >
                      保存并加入关注
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
