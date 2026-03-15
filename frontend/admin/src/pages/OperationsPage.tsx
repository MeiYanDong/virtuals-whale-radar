import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Coins, Eye, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, MetricCard, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { formatDateTime } from "@/lib/format";

export function OperationsPage() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [creditAmount, setCreditAmount] = useState("");
  const [amountPaid, setAmountPaid] = useState("");
  const [adminNote, setAdminNote] = useState("");

  const operationsQuery = useQuery({
    queryKey: queryKeys.adminBillingRequests(statusFilter, keyword.trim().toLowerCase(), 120),
    queryFn: () =>
      dashboardApi.admin.getBillingRequests({
        status: statusFilter || undefined,
        q: keyword.trim() || undefined,
        limit: 120,
      }),
  });

  const selectedItem = useMemo(
    () => operationsQuery.data?.items.find((item) => item.id === selectedId) ?? null,
    [operationsQuery.data?.items, selectedId],
  );

  const creditMutation = useMutation({
    mutationFn: async () => {
      if (!selectedItem) {
        throw new Error("请先选择一条充值申请。");
      }
      const credits = Number.parseInt(creditAmount.trim(), 10);
      if (!Number.isFinite(credits) || credits <= 0) {
        throw new Error("入账积分必须是正整数。");
      }
      return dashboardApi.admin.creditBillingRequest(selectedItem.id, {
        credits,
        amount_paid: amountPaid.trim() || undefined,
        admin_note: adminNote.trim() || undefined,
      });
    },
    onSuccess: async () => {
      toast.success("充值申请已入账。");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["admin-billing-requests"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.adminUsers }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const notifyMutation = useMutation({
    mutationFn: async () => {
      if (!selectedItem) {
        throw new Error("请先选择一条充值申请。");
      }
      return dashboardApi.admin.notifyBillingRequest(selectedItem.id, {
        admin_note: adminNote.trim() || undefined,
      });
    },
    onSuccess: async () => {
      toast.success("已标记为已通知用户。");
      await queryClient.invalidateQueries({ queryKey: ["admin-billing-requests"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (operationsQuery.isLoading) {
    return <LoadingState label="正在加载运营工单..." />;
  }

  const items = operationsQuery.data?.items ?? [];
  const pendingCount = items.filter((item) => item.status === "pending_review").length;
  const creditedCount = items.filter((item) => item.status === "credited").length;
  const notifiedCount = items.filter((item) => item.status === "notified").length;

  function openRequestSheet(item: NonNullable<typeof selectedItem>) {
    setSelectedId(item.id);
    setCreditAmount(String(item.requested_credits || ""));
    setAmountPaid(item.payment_amount || "");
    setAdminNote(item.admin_note || "");
    setSheetOpen(true);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Operations"
        title="充值处理流"
        description="统一处理用户上传的付款凭证，让运营路径固定为待确认付款、已入账、已通知用户。"
      />

      <section className="grid gap-4 md:grid-cols-3">
        <MetricCard label="待确认付款" value={String(pendingCount)} hint="等待管理员核对付款凭证。" tone="warning" />
        <MetricCard label="已入账" value={String(creditedCount)} hint="积分已补到账号，待运营通知。" tone="success" />
        <MetricCard label="已通知用户" value={String(notifiedCount)} hint="充值处理链路已闭环。" />
      </section>

      <SectionCard
        title="充值申请"
        description="优先处理待确认付款的申请，再收尾已入账但未通知的记录。"
        actions={
          <div className="flex flex-wrap gap-2">
            <div className="relative min-w-[220px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="搜索用户、邮箱或备注"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
              />
            </div>
            <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">全部状态</option>
              <option value="pending_review">待确认付款</option>
              <option value="credited">已入账</option>
              <option value="notified">已通知用户</option>
            </Select>
          </div>
        }
      >
        {items.length ? (
          <div className="space-y-3">
            {items.map((item) => (
              <div
                key={item.id}
                className="rounded-[24px] border border-border bg-white/80 px-5 py-5 shadow-sm"
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        variant={
                          item.status === "pending_review"
                            ? "warning"
                            : item.status === "credited"
                              ? "success"
                              : "secondary"
                        }
                      >
                        {item.status_label}
                      </Badge>
                      <div className="font-medium">
                        {item.userNickname || "未知用户"} / {item.userEmail || "-"}
                      </div>
                    </div>
                    <div className="grid gap-1 text-sm text-muted-foreground md:grid-cols-2">
                      <div>方案：{item.plan_id || "manual"}</div>
                      <div>申请积分：{item.requested_credits}</div>
                      <div>实付金额：{item.payment_amount || "-"}</div>
                      <div>提交时间：{formatDateTime(item.created_at)}</div>
                    </div>
                    <div className="text-sm text-muted-foreground">用户备注：{item.note || "-"}</div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                    {item.proof_url ? (
                      <Button asChild variant="secondary" size="sm">
                        <a href={item.proof_url} target="_blank" rel="noreferrer">
                          <Eye className="size-4" />
                          查看凭证
                        </a>
                      </Button>
                    ) : null}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => openRequestSheet(item)}
                    >
                      <Coins className="size-4" />
                      处理工单
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            title="当前没有匹配的充值申请"
            description="用户上传付款凭证后，这里会出现待处理工单。"
          />
        )}
      </SectionCard>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent className="px-0 py-0">
          <SheetTitle className="sr-only">充值工单详情</SheetTitle>
          <SheetDescription className="sr-only">核对付款凭证、执行入账并标记通知状态。</SheetDescription>
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-border px-6 py-5">
              <div className="flex items-center gap-2">
                <Badge
                  variant={
                    selectedItem?.status === "pending_review"
                      ? "warning"
                      : selectedItem?.status === "credited"
                        ? "success"
                        : "secondary"
                  }
                >
                  {selectedItem?.status_label || "未选择工单"}
                </Badge>
                <div className="text-sm font-medium">
                  {selectedItem ? `${selectedItem.userNickname || "-"} / ${selectedItem.userEmail || "-"}` : "请选择工单"}
                </div>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-5">
              {selectedItem ? (
                <div className="space-y-5">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-[22px] border border-border bg-white/80 px-4 py-4 text-sm text-muted-foreground">
                      <div>申请积分：{selectedItem.requested_credits}</div>
                      <div className="mt-2">方案：{selectedItem.plan_id || "manual"}</div>
                      <div className="mt-2">提交时间：{formatDateTime(selectedItem.created_at)}</div>
                    </div>
                    <div className="rounded-[22px] border border-border bg-white/80 px-4 py-4 text-sm text-muted-foreground">
                      <div>实付金额：{selectedItem.payment_amount || "-"}</div>
                      <div className="mt-2">运营备注：{selectedItem.admin_note || "-"}</div>
                      <div className="mt-2">用户备注：{selectedItem.note || "-"}</div>
                    </div>
                  </div>

                  {selectedItem.proof_url ? (
                    <div className="space-y-3">
                      <div className="text-sm font-medium">付款凭证</div>
                      <a href={selectedItem.proof_url} target="_blank" rel="noreferrer">
                        <img
                          src={selectedItem.proof_url}
                          alt={selectedItem.proof_original_name || "付款凭证"}
                          className="max-h-[320px] w-full rounded-[24px] border border-border object-contain bg-white/80"
                        />
                      </a>
                    </div>
                  ) : null}

                  <div className="space-y-3">
                    <div className="text-sm font-medium">运营处理</div>
                    <Input
                      type="number"
                      inputMode="numeric"
                      min={1}
                      step={1}
                      value={creditAmount}
                      onChange={(event) => setCreditAmount(event.target.value)}
                      placeholder="实际入账积分"
                    />
                    <Input
                      inputMode="decimal"
                      value={amountPaid}
                      onChange={(event) => setAmountPaid(event.target.value)}
                      placeholder="实付金额"
                    />
                    <Textarea
                      value={adminNote}
                      onChange={(event) => setAdminNote(event.target.value)}
                      placeholder="运营备注，例如核对结果、到账说明、沟通记录"
                    />
                  </div>
                </div>
              ) : (
                <div className="rounded-[22px] border border-dashed border-border bg-white/70 px-4 py-6 text-sm text-muted-foreground">
                  请选择一条充值申请。
                </div>
              )}
            </div>

            <div className="border-t border-border px-6 py-4">
              <div className="flex flex-wrap justify-end gap-2">
                {selectedItem?.status === "pending_review" ? (
                  <Button onClick={() => void creditMutation.mutateAsync()} disabled={creditMutation.isPending}>
                    确认入账
                  </Button>
                ) : null}
                {selectedItem?.status === "credited" ? (
                  <Button variant="secondary" onClick={() => void notifyMutation.mutateAsync()} disabled={notifyMutation.isPending}>
                    标记已通知用户
                  </Button>
                ) : null}
                <Button variant="ghost" onClick={() => setSheetOpen(false)}>
                  关闭
                </Button>
              </div>
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
