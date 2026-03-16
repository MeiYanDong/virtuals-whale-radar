import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ChevronDown,
  ChevronUp,
  Coins,
  Eye,
  KeyRound,
  Search,
  ShieldBan,
  ShieldCheck,
  Trash2,
  UserPlus,
  Wallet2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatAddress, formatDateTime } from "@/lib/format";

function parseIntegerField(
  rawValue: string,
  fieldLabel: string,
  options: {
    allowNegative?: boolean;
    allowZero?: boolean;
  } = {},
) {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return { ok: false as const, error: `${fieldLabel}不能为空` };
  }

  const pattern = options.allowNegative ? /^-?\d+$/ : /^\d+$/;
  if (!pattern.test(trimmed)) {
    return { ok: false as const, error: `${fieldLabel}必须是整数` };
  }

  const value = Number.parseInt(trimmed, 10);
  if (!Number.isFinite(value)) {
    return { ok: false as const, error: `${fieldLabel}必须是整数` };
  }
  if (!options.allowZero && value === 0) {
    return { ok: false as const, error: `${fieldLabel}不能为 0` };
  }
  if (!options.allowNegative && value < 0) {
    return { ok: false as const, error: `${fieldLabel}不能为负数` };
  }
  return { ok: true as const, value };
}

function userStatusVariant(status: string) {
  if (status === "active") {
    return "success" as const;
  }
  if (status === "archived") {
    return "warning" as const;
  }
  return "danger" as const;
}

function userStatusLabel(status: string) {
  if (status === "archived") {
    return "archived";
  }
  return status === "active" ? "active" : "disabled";
}

function userSourceLabel(source: string) {
  return source === "admin_created" ? "管理员创建" : "用户注册";
}

export function UsersPage() {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("active");
  const [roleFilter, setRoleFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [selectedUserIds, setSelectedUserIds] = useState<number[]>([]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  const [resetPassword, setResetPassword] = useState("");
  const [creditDelta, setCreditDelta] = useState("");
  const [creditNote, setCreditNote] = useState("");
  const [topupCredits, setTopupCredits] = useState("");
  const [topupAmount, setTopupAmount] = useState("");
  const [topupNote, setTopupNote] = useState("");
  const [manualAdjustOpen, setManualAdjustOpen] = useState(false);

  const [createNickname, setCreateNickname] = useState("");
  const [createEmail, setCreateEmail] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createInitialCredits, setCreateInitialCredits] = useState("");
  const [createNote, setCreateNote] = useState("");

  const normalizedKeyword = keyword.trim();
  const normalizedStatusFilter = statusFilter.trim().toLowerCase();
  const normalizedRoleFilter = roleFilter.trim().toLowerCase();
  const normalizedSourceFilter = sourceFilter.trim().toLowerCase();

  const usersQuery = useQuery({
    queryKey: queryKeys.adminUsersList(
      normalizedKeyword,
      normalizedStatusFilter,
      normalizedRoleFilter,
      normalizedSourceFilter,
    ),
    queryFn: () =>
      dashboardApi.admin.getUsers({
        q: normalizedKeyword || undefined,
        status: normalizedStatusFilter || undefined,
        role: normalizedRoleFilter || undefined,
        source: normalizedSourceFilter || undefined,
      }),
  });

  const userDetailQuery = useQuery({
    queryKey: queryKeys.adminUserDetail(selectedUserId ?? 0),
    queryFn: () => dashboardApi.admin.getUserDetail(selectedUserId ?? 0),
    enabled: Boolean(selectedUserId),
  });

  const userWalletsQuery = useQuery({
    queryKey: queryKeys.adminUserWallets(selectedUserId ?? 0),
    queryFn: () => dashboardApi.admin.getUserWallets(selectedUserId ?? 0),
    enabled: Boolean(selectedUserId),
  });

  const userLedgerQuery = useQuery({
    queryKey: queryKeys.adminUserCreditLedger(selectedUserId ?? 0),
    queryFn: () => dashboardApi.admin.getUserCreditLedger(selectedUserId ?? 0),
    enabled: Boolean(selectedUserId),
  });

  const userAccessQuery = useQuery({
    queryKey: queryKeys.adminUserProjectAccess(selectedUserId ?? 0),
    queryFn: () => dashboardApi.admin.getUserProjectAccess(selectedUserId ?? 0),
    enabled: Boolean(selectedUserId),
  });

  const rows = useMemo(() => usersQuery.data?.items ?? [], [usersQuery.data?.items]);
  const currentRowIds = useMemo(() => rows.map((row) => row.id), [rows]);
  const selectedUser = userDetailQuery.data?.item;

  const visibleSelectedUserIds = useMemo(
    () => selectedUserIds.filter((id) => currentRowIds.includes(id)),
    [currentRowIds, selectedUserIds],
  );
  const allCurrentSelected =
    rows.length > 0 && currentRowIds.every((id) => visibleSelectedUserIds.includes(id));
  const hasSelection = visibleSelectedUserIds.length > 0;

  async function invalidateUsersData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUserDetail(selectedUserId ?? 0) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUserWallets(selectedUserId ?? 0) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUserCreditLedger(selectedUserId ?? 0) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.adminUserProjectAccess(selectedUserId ?? 0) }),
    ]);
  }

  function clearSelection() {
    setSelectedUserIds([]);
  }

  function removeDeletedUsersFromView(userIds: number[]) {
    if (selectedUserId && userIds.includes(selectedUserId)) {
      setSelectedUserId(null);
      setSheetOpen(false);
    }
    setSelectedUserIds((current) => current.filter((id) => !userIds.includes(id)));
  }

  const statusMutation = useMutation({
    mutationFn: ({ userId, status }: { userId: number; status: "active" | "disabled" | "archived" }) =>
      dashboardApi.admin.setUserStatus(userId, status),
    onSuccess: async () => {
      toast.success("用户状态已更新。");
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createUserMutation = useMutation({
    mutationFn: (payload: {
      nickname: string;
      email: string;
      password: string;
      initial_credits?: number;
      note?: string;
    }) => dashboardApi.admin.createUser(payload),
    onSuccess: async () => {
      toast.success("用户已创建。");
      setCreateDialogOpen(false);
      setCreateNickname("");
      setCreateEmail("");
      setCreatePassword("");
      setCreateInitialCredits("");
      setCreateNote("");
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const batchStatusMutation = useMutation({
    mutationFn: ({
      userIds,
      status,
    }: {
      userIds: number[];
      status: "disabled" | "archived";
    }) => dashboardApi.admin.batchSetUsersStatus(userIds, status),
    onSuccess: async (_, variables) => {
      toast.success(variables.status === "archived" ? "已批量归档用户。" : "已批量禁用用户。");
      clearSelection();
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const batchDeleteMutation = useMutation({
    mutationFn: (userIds: number[]) => dashboardApi.admin.batchDeleteUsers(userIds),
    onSuccess: async (result) => {
      toast.success(`已删除 ${result.deletedCount} 个用户。`);
      removeDeletedUsersFromView(result.deletedUserIds);
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: ({ userId, password }: { userId: number; password: string }) =>
      dashboardApi.admin.resetUserPassword(userId, password),
    onSuccess: async () => {
      toast.success("密码已重置。");
      setResetPassword("");
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const adjustCreditsMutation = useMutation({
    mutationFn: ({ userId, delta, note }: { userId: number; delta: number; note: string }) =>
      dashboardApi.admin.adjustUserCredits(userId, { delta, note }),
    onSuccess: async () => {
      toast.success("积分已调整。");
      setCreditDelta("");
      setCreditNote("");
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const topupCreditsMutation = useMutation({
    mutationFn: ({
      userId,
      credits,
      amountPaid,
      note,
    }: {
      userId: number;
      credits: number;
      amountPaid?: string;
      note?: string;
    }) =>
      dashboardApi.admin.topupUserCredits(userId, {
        credits,
        amount_paid: amountPaid,
        note,
      }),
    onSuccess: async () => {
      toast.success("充值积分已入账。");
      setTopupCredits("");
      setTopupAmount("");
      setTopupNote("");
      await invalidateUsersData();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const walletToggleMutation = useMutation({
    mutationFn: ({
      userId,
      walletId,
      isEnabled,
    }: {
      userId: number;
      walletId: number;
      isEnabled: boolean;
    }) => dashboardApi.admin.setUserWalletStatus(userId, walletId, isEnabled),
    onSuccess: async () => {
      toast.success("钱包状态已更新。");
      await queryClient.invalidateQueries({ queryKey: queryKeys.adminUserWallets(selectedUserId ?? 0) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const walletDeleteMutation = useMutation({
    mutationFn: ({ userId, walletId }: { userId: number; walletId: number }) =>
      dashboardApi.admin.deleteUserWallet(userId, walletId),
    onSuccess: async () => {
      toast.success("用户钱包已删除。");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
        queryClient.invalidateQueries({ queryKey: queryKeys.adminUserWallets(selectedUserId ?? 0) }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const creditDeltaValidation = useMemo(
    () =>
      creditDelta.trim()
        ? parseIntegerField(creditDelta, "调整积分", { allowNegative: true })
        : null,
    [creditDelta],
  );
  const topupCreditsValidation = useMemo(
    () => (topupCredits.trim() ? parseIntegerField(topupCredits, "充值积分") : null),
    [topupCredits],
  );
  const createInitialCreditsValidation = useMemo(
    () =>
      createInitialCredits.trim()
        ? parseIntegerField(createInitialCredits, "初始积分", { allowZero: true })
        : null,
    [createInitialCredits],
  );

  async function handleAdjustCreditsSubmit(userId: number) {
    const parsed = parseIntegerField(creditDelta, "调整积分", { allowNegative: true });
    if (!parsed.ok) {
      toast.error(parsed.error);
      return;
    }
    if (!creditNote.trim()) {
      toast.error("备注不能为空。");
      return;
    }
    await adjustCreditsMutation.mutateAsync({
      userId,
      delta: parsed.value,
      note: creditNote.trim(),
    });
  }

  async function handleTopupSubmit(userId: number) {
    const parsed = parseIntegerField(topupCredits, "充值积分");
    if (!parsed.ok) {
      toast.error(parsed.error);
      return;
    }
    await topupCreditsMutation.mutateAsync({
      userId,
      credits: parsed.value,
      amountPaid: topupAmount.trim() || undefined,
      note: topupNote.trim() || undefined,
    });
  }

  async function handleCreateUserSubmit() {
    if (!createNickname.trim() || !createEmail.trim() || !createPassword.trim()) {
      toast.error("昵称、邮箱和初始密码不能为空。");
      return;
    }
    let initialCredits = 0;
    if (createInitialCredits.trim()) {
      const parsed = parseIntegerField(createInitialCredits, "初始积分", { allowZero: true });
      if (!parsed.ok) {
        toast.error(parsed.error);
        return;
      }
      initialCredits = parsed.value;
    }
    await createUserMutation.mutateAsync({
      nickname: createNickname.trim(),
      email: createEmail.trim(),
      password: createPassword,
      initial_credits: initialCredits || undefined,
      note: createNote.trim() || undefined,
    });
  }

  function toggleRow(userId: number, checked: boolean) {
    setSelectedUserIds((current) => {
      if (checked) {
        if (current.includes(userId)) {
          return current;
        }
        return [...current, userId];
      }
      return current.filter((id) => id !== userId);
    });
  }

  function toggleSelectAllCurrent(checked: boolean) {
    if (checked) {
      setSelectedUserIds((current) => Array.from(new Set([...current, ...currentRowIds])));
      return;
    }
    setSelectedUserIds((current) => current.filter((id) => !currentRowIds.includes(id)));
  }

  async function handleBatchStatus(status: "disabled" | "archived") {
    if (!visibleSelectedUserIds.length) {
      toast.error("请先选择用户。");
      return;
    }
    const ok = window.confirm(
      status === "archived"
        ? `确认归档当前选中的 ${visibleSelectedUserIds.length} 个用户吗？`
        : `确认禁用当前选中的 ${visibleSelectedUserIds.length} 个用户吗？`,
    );
    if (!ok) {
      return;
    }
    await batchStatusMutation.mutateAsync({ userIds: visibleSelectedUserIds, status });
  }

  async function handleBatchDelete() {
    if (!visibleSelectedUserIds.length) {
      toast.error("请先选择用户。");
      return;
    }
    const ok = window.confirm(
      `确认永久删除当前选中的 ${visibleSelectedUserIds.length} 个用户吗？此操作会删除用户钱包、会话、积分流水和解锁记录，无法恢复。`,
    );
    if (!ok) {
      return;
    }
    await batchDeleteMutation.mutateAsync(visibleSelectedUserIds);
  }

  async function handleSingleDelete(userId: number) {
    const ok = window.confirm("确认永久删除该用户吗？此操作无法恢复。");
    if (!ok) {
      return;
    }
    await batchDeleteMutation.mutateAsync([userId]);
  }

  if (usersQuery.isLoading) {
    return <LoadingState label="正在加载用户列表..." />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Users"
        title="用户管理"
        description="集中管理注册用户、测试账号和私有钱包。当前页支持多选、批量归档和管理员直接建号。"
      />

      <SectionCard
        title="用户列表"
        description="默认只看活跃用户。测试账号建议批量归档；需要清库时再做批量删除。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="搜索昵称或邮箱"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
              />
            </div>
            <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">全部状态</option>
              <option value="active">active</option>
              <option value="disabled">disabled</option>
              <option value="archived">archived</option>
            </Select>
            <Select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
              <option value="">全部角色</option>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </Select>
            <Select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
              <option value="">全部来源</option>
              <option value="self_signup">用户注册</option>
              <option value="admin_created">管理员创建</option>
            </Select>
            <Button variant="secondary" onClick={() => setCreateDialogOpen(true)}>
              <UserPlus className="size-4" />
              新建用户
            </Button>
          </div>
        }
      >
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-border bg-[color:var(--surface-soft)] px-4 py-3 text-sm">
          <div className="text-muted-foreground">
            当前结果 <span className="font-semibold text-foreground">{rows.length}</span> 人，
            已选 <span className="font-semibold text-foreground">{visibleSelectedUserIds.length}</span> 人。
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleBatchStatus("disabled")}
              disabled={!hasSelection || batchStatusMutation.isPending}
            >
              <ShieldBan className="size-4" />
              批量禁用
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleBatchStatus("archived")}
              disabled={!hasSelection || batchStatusMutation.isPending}
            >
              <Archive className="size-4" />
              批量归档
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={() => void handleBatchDelete()}
              disabled={!hasSelection || batchDeleteMutation.isPending}
            >
              <Trash2 className="size-4" />
              批量删除
            </Button>
          </div>
        </div>

        {rows.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-12">
                  <input
                    type="checkbox"
                    className="size-4 rounded border border-border"
                    checked={allCurrentSelected}
                    onChange={(event) => toggleSelectAllCurrent(event.target.checked)}
                    aria-label="全选当前结果"
                  />
                </TableHead>
                <TableHead>昵称</TableHead>
                <TableHead>注册邮箱</TableHead>
                <TableHead>来源</TableHead>
                <TableHead>角色</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>邮箱验证</TableHead>
                <TableHead>当前积分</TableHead>
                <TableHead>累计消耗</TableHead>
                <TableHead>已解锁项目</TableHead>
                <TableHead>钱包数</TableHead>
                <TableHead>最近登录</TableHead>
                <TableHead>注册时间</TableHead>
                <TableHead className="text-right">详情</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) => {
                const checked = selectedUserIds.includes(item.id);
                return (
                  <TableRow key={item.id}>
                    <TableCell>
                      <input
                        type="checkbox"
                        className="size-4 rounded border border-border"
                        checked={checked}
                        onChange={(event) => toggleRow(item.id, event.target.checked)}
                        aria-label={`选择用户 ${item.nickname}`}
                      />
                    </TableCell>
                    <TableCell>{item.nickname}</TableCell>
                    <TableCell>{item.email}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{userSourceLabel(item.source)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{item.role}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={userStatusVariant(item.status)}>{userStatusLabel(item.status)}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={item.email_verified_at ? "success" : "warning"}>
                        {item.email_verified_at ? "已验证" : "未验证"}
                      </Badge>
                    </TableCell>
                    <TableCell>{item.credit_balance}</TableCell>
                    <TableCell>{item.credit_spent_total}</TableCell>
                    <TableCell>{item.unlocked_project_count}</TableCell>
                    <TableCell>{item.wallet_count}</TableCell>
                    <TableCell>{formatDateTime(item.last_login_at)}</TableCell>
                    <TableCell>{formatDateTime(item.created_at)}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          setSelectedUserId(item.id);
                          setSheetOpen(true);
                        }}
                      >
                        <Eye className="size-4" />
                        详情
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="当前没有用户"
            description="你可以切换筛选条件，或直接通过“新建用户”为内测用户和私域用户开通账号。"
          />
        )}
      </SectionCard>

      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>新建用户</DialogTitle>
            <DialogDescription>
              适合给内测用户、私域用户或需要手动开通的账号直接创建登录入口。
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 md:grid-cols-2">
            <Input
              placeholder="昵称"
              value={createNickname}
              onChange={(event) => setCreateNickname(event.target.value)}
            />
            <Input
              placeholder="邮箱"
              value={createEmail}
              onChange={(event) => setCreateEmail(event.target.value)}
            />
            <Input
              type="password"
              placeholder="初始密码"
              value={createPassword}
              onChange={(event) => setCreatePassword(event.target.value)}
            />
            <Input
              type="number"
              inputMode="numeric"
              step={1}
              min={0}
              placeholder="初始积分（可选）"
              value={createInitialCredits}
              onChange={(event) => setCreateInitialCredits(event.target.value)}
            />
          </div>
          {createInitialCreditsValidation && !createInitialCreditsValidation.ok ? (
            <div className="text-xs text-[color:var(--danger)]">{createInitialCreditsValidation.error}</div>
          ) : (
            <div className="text-xs text-muted-foreground">
              管理员创建的用户默认视为邮箱已验证；如填写初始积分，会同步写入积分流水。
            </div>
          )}
          <Textarea
            placeholder="备注（可选，例如渠道来源、内测说明、开通原因）"
            value={createNote}
            onChange={(event) => setCreateNote(event.target.value)}
          />

          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void handleCreateUserSubmit()} disabled={createUserMutation.isPending}>
              创建用户
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="px-0 py-0">
          <SheetTitle className="sr-only">
            {selectedUser ? `${selectedUser.nickname} 用户详情` : "用户详情"}
          </SheetTitle>
          <SheetDescription className="sr-only">
            查看用户资料、积分、解锁项目与私有钱包，并执行禁用、归档或删除。
          </SheetDescription>
          <div className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto px-6 py-8">
            {userDetailQuery.isLoading ||
            userWalletsQuery.isLoading ||
            userLedgerQuery.isLoading ||
            userAccessQuery.isLoading ? (
              <LoadingState label="正在加载用户详情..." />
            ) : selectedUser ? (
              <>
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={userStatusVariant(selectedUser.status)}>{userStatusLabel(selectedUser.status)}</Badge>
                    <Badge variant="secondary">{selectedUser.role}</Badge>
                    <Badge variant="secondary">{userSourceLabel(selectedUser.source)}</Badge>
                    <Badge variant={selectedUser.email_verified_at ? "success" : "warning"}>
                      {selectedUser.email_verified_at ? "邮箱已验证" : "邮箱未验证"}
                    </Badge>
                  </div>
                  <h2 className="text-2xl font-semibold tracking-[-0.04em]">{selectedUser.nickname}</h2>
                  <p className="text-sm text-muted-foreground">{selectedUser.email}</p>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">最近登录</div>
                    <div className="mt-2 text-sm">{formatDateTime(selectedUser.last_login_at)}</div>
                  </div>
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">密码状态</div>
                    <div className="mt-2 text-sm">{selectedUser.password_set ? "已设置密码" : "未设置密码"}</div>
                  </div>
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">注册来源</div>
                    <div className="mt-2 text-sm">{userSourceLabel(selectedUser.source)}</div>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">当前积分</div>
                    <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{selectedUser.credit_balance}</div>
                  </div>
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">累计消耗</div>
                    <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                      {selectedUser.credit_spent_total}
                    </div>
                  </div>
                  <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">已解锁项目</div>
                    <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                      {selectedUser.unlocked_project_count}
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-medium">账户操作</div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant={selectedUser.status === "active" ? "outline" : "default"}
                      onClick={() =>
                        void statusMutation.mutateAsync({
                          userId: selectedUser.id,
                          status: selectedUser.status === "active" ? "disabled" : "active",
                        })
                      }
                    >
                      {selectedUser.status === "active" ? (
                        <ShieldBan className="size-4" />
                      ) : (
                        <ShieldCheck className="size-4" />
                      )}
                      {selectedUser.status === "active" ? "禁用用户" : "恢复为活跃"}
                    </Button>
                    {selectedUser.role !== "admin" ? (
                      <Button
                        variant="outline"
                        onClick={() =>
                          void statusMutation.mutateAsync({
                            userId: selectedUser.id,
                            status: "archived",
                          })
                        }
                      >
                        <Archive className="size-4" />
                        归档用户
                      </Button>
                    ) : null}
                    {selectedUser.role !== "admin" ? (
                      <Button variant="destructive" onClick={() => void handleSingleDelete(selectedUser.id)}>
                        <Trash2 className="size-4" />
                        删除用户
                      </Button>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-medium">重置密码</div>
                  <div className="flex gap-2">
                    <Input
                      type="password"
                      placeholder="输入新密码"
                      value={resetPassword}
                      onChange={(event) => setResetPassword(event.target.value)}
                    />
                    <Button
                      onClick={() =>
                        void resetPasswordMutation.mutateAsync({
                          userId: selectedUser.id,
                          password: resetPassword,
                        })
                      }
                      disabled={!resetPassword.trim()}
                    >
                      <KeyRound className="size-4" />
                      重置
                    </Button>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Coins className="size-4 text-primary" />
                    积分运营
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                      <div className="space-y-2">
                        <div>
                          <div className="text-sm font-medium">微信付款后手动入账</div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            用户微信付款后，你直接在这里补积分即可。微信记录和你的备注，足够支撑当前阶段的人工入账。
                          </p>
                        </div>
                      </div>
                      <div className="mt-3 space-y-2">
                        <Input
                          type="number"
                          inputMode="numeric"
                          step={1}
                          min={1}
                          placeholder="充值积分，例如 100"
                          value={topupCredits}
                          onChange={(event) => setTopupCredits(event.target.value)}
                        />
                        {topupCreditsValidation && !topupCreditsValidation.ok ? (
                          <div className="text-xs text-[color:var(--danger)]">{topupCreditsValidation.error}</div>
                        ) : (
                          <div className="text-xs text-muted-foreground">
                            仅支持正整数。确认微信到账后，直接在这里手动补分。
                          </div>
                        )}
                        <Input
                          inputMode="decimal"
                          placeholder="实付金额，例如 90"
                          value={topupAmount}
                          onChange={(event) => setTopupAmount(event.target.value)}
                        />
                        <Input
                          placeholder="备注（例如微信昵称、付款时间、订单说明）"
                          value={topupNote}
                          onChange={(event) => setTopupNote(event.target.value)}
                        />
                        <Button
                          className="w-full"
                          onClick={() => void handleTopupSubmit(selectedUser.id)}
                          disabled={
                            !topupCredits.trim() ||
                            Boolean(topupCreditsValidation && !topupCreditsValidation.ok) ||
                            topupCreditsMutation.isPending
                          }
                        >
                          确认入账
                        </Button>
                      </div>
                    </div>

                    <div className="rounded-[22px] border border-dashed border-border bg-white/56 px-4 py-4">
                      <button
                        type="button"
                        className="flex w-full items-center justify-between gap-4 text-left"
                        onClick={() => setManualAdjustOpen((current) => !current)}
                      >
                        <div>
                          <div className="text-sm font-medium">高级操作：手工修正积分</div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            仅用于补账、纠错或人工扣分。支持负数，且必须填写备注，流水会标记为
                            `manual_adjustment`。
                          </p>
                        </div>
                        {manualAdjustOpen ? (
                          <ChevronUp className="size-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="size-4 text-muted-foreground" />
                        )}
                      </button>

                      {manualAdjustOpen ? (
                        <div className="mt-4 space-y-2 border-t border-border/70 pt-4">
                          <Input
                            type="number"
                            inputMode="numeric"
                            step={1}
                            placeholder="增减积分，支持负数"
                            value={creditDelta}
                            onChange={(event) => setCreditDelta(event.target.value)}
                          />
                          {creditDeltaValidation && !creditDeltaValidation.ok ? (
                            <div className="text-xs text-[color:var(--danger)]">{creditDeltaValidation.error}</div>
                          ) : (
                            <div className="text-xs text-muted-foreground">
                              示例：`50` 表示补分，`-10` 表示扣分。
                            </div>
                          )}
                          <Input
                            placeholder="备注（必填）"
                            value={creditNote}
                            onChange={(event) => setCreditNote(event.target.value)}
                          />
                          <Button
                            className="w-full"
                            variant="secondary"
                            onClick={() => void handleAdjustCreditsSubmit(selectedUser.id)}
                            disabled={
                              !creditDelta.trim() ||
                              !creditNote.trim() ||
                              Boolean(creditDeltaValidation && !creditDeltaValidation.ok) ||
                              adjustCreditsMutation.isPending
                            }
                          >
                            提交调整
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Wallet2 className="size-4 text-primary" />
                    用户钱包
                  </div>
                  {userWalletsQuery.data?.items.length ? (
                    <div className="space-y-3">
                      {userWalletsQuery.data.items.map((wallet) => (
                        <div key={wallet.id} className="rounded-[22px] border border-border bg-white/72 px-4 py-4">
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <div className="font-medium">{wallet.name || "未命名钱包"}</div>
                              <div className="mt-1 font-mono text-xs text-muted-foreground">
                                {formatAddress(wallet.wallet, 8)}
                              </div>
                            </div>
                            <div className="flex gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() =>
                                  void walletToggleMutation.mutateAsync({
                                    userId: selectedUser.id,
                                    walletId: wallet.id,
                                    isEnabled: !wallet.is_enabled,
                                  })
                                }
                              >
                                {wallet.is_enabled ? "禁用" : "启用"}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() =>
                                  void walletDeleteMutation.mutateAsync({
                                    userId: selectedUser.id,
                                    walletId: wallet.id,
                                  })
                                }
                              >
                                <Trash2 className="size-4" />
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <EmptyState compact title="该用户还没有钱包" description="用户添加钱包后，这里会出现私有钱包列表。" />
                  )}
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-medium">积分流水</div>
                  {userLedgerQuery.data?.items.length ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>时间</TableHead>
                          <TableHead>变化值</TableHead>
                          <TableHead>类型</TableHead>
                          <TableHead>项目</TableHead>
                          <TableHead>金额 / 附注</TableHead>
                          <TableHead>备注</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {userLedgerQuery.data.items.map((row) => (
                          <TableRow key={row.id}>
                            <TableCell>{formatDateTime(row.created_at)}</TableCell>
                            <TableCell className={row.delta >= 0 ? "text-emerald-700" : "text-rose-700"}>
                              {row.delta > 0 ? `+${row.delta}` : row.delta}
                            </TableCell>
                            <TableCell>{row.type}</TableCell>
                            <TableCell>{row.project_name || "-"}</TableCell>
                            <TableCell>
                              <div className="space-y-1 text-xs">
                                <div>{row.payment_amount ? `实付 ${row.payment_amount}` : "-"}</div>
                                {row.payment_proof_ref ? (
                                  <div className="break-all text-muted-foreground">{row.payment_proof_ref}</div>
                                ) : null}
                              </div>
                            </TableCell>
                            <TableCell>{row.note || row.operator_nickname || "-"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <EmptyState compact title="还没有积分流水" description="注册赠送、解锁扣分和管理员手工加减积分都会记录在这里。" />
                  )}
                </div>

                <div className="space-y-3">
                  <div className="text-sm font-medium">已解锁项目</div>
                  {userAccessQuery.data?.items.length ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>项目</TableHead>
                          <TableHead>状态</TableHead>
                          <TableHead>解锁成本</TableHead>
                          <TableHead>解锁时间</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {userAccessQuery.data.items.map((row) => (
                          <TableRow key={row.id}>
                            <TableCell>{row.project_name || `#${row.project_id}`}</TableCell>
                            <TableCell>{row.project_status || "-"}</TableCell>
                            <TableCell>{row.unlock_cost}</TableCell>
                            <TableCell>{formatDateTime(row.unlocked_at)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <EmptyState compact title="还没有已解锁项目" description="用户解锁项目 Overview 后，这里会保留权限记录。" />
                  )}
                </div>
              </>
            ) : (
              <EmptyState compact title="未找到用户" description="当前选择的用户不存在，或已被删除。" />
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
