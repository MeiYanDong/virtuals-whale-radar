import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BellDot, Coins, QrCode, Sparkles, WalletCards } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, MetricCard, PageHeader, SectionCard } from "@/components/app-primitives";
import { Alert } from "@/components/ui/alert";
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
import { formatCompactNumber } from "@/lib/format";

const VISIBLE_NOTIFICATION_TYPES = new Set([
  "credit:signup_bonus",
  "credit:manual_topup",
  "credit:manual_adjustment",
  "credit:project_unlock",
  "billing_request_credited",
]);

export function BillingPage() {
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState("starter");
  const [contactOpen, setContactOpen] = useState(false);

  const billingQuery = useQuery({
    queryKey: queryKeys.appBillingSummary,
    queryFn: () => dashboardApi.app.getBillingSummary(),
  });
  const activityQuery = useQuery({
    queryKey: queryKeys.appNotifications(12),
    queryFn: () => dashboardApi.app.getNotifications(12),
  });
  const activityItems = useMemo(
    () => (activityQuery.data?.items ?? []).filter((item) => VISIBLE_NOTIFICATION_TYPES.has(item.type)),
    [activityQuery.data?.items],
  );

  const markNotificationReadMutation = useMutation({
    mutationFn: async (notificationId: number) => dashboardApi.app.markNotificationRead(notificationId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (billingQuery.isLoading) {
    return <LoadingState label="正在加载积分与充值信息..." />;
  }

  if (billingQuery.isError || !billingQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Recharge"
          title="积分与充值"
          description="当前无法读取积分摘要或联系方式。"
        />
        <EmptyState
          title="积分信息加载失败"
          description="请稍后刷新重试。如果问题持续存在，再联系我处理。"
        />
      </div>
    );
  }

  const summary = billingQuery.data;
  const selectedPlan = summary.plans.find((plan) => plan.id === selectedPlanId) ?? summary.plans[0];

  return (
    <div className="space-y-6">
      <Alert className="surface-hero overflow-hidden border-primary/20">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-[0.22em] text-primary/80">
              Referral
            </div>
            <div className="text-base font-semibold text-foreground">{summary.notice}</div>
          </div>
          <Button asChild variant="secondary">
            <a href={summary.referral_url} target="_blank" rel="noreferrer">
              打开注册链接
              <ArrowRight className="size-4" />
            </a>
          </Button>
        </div>
      </Alert>

      <PageHeader
        eyebrow="Recharge"
        title="积分与充值"
        description="先看余额，再决定要不要补分。推荐把积分留给你真正想持续观察的项目。"
      />

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="surface-hero-strong rounded-[32px] border border-white/60 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <Badge variant="secondary">积分账户</Badge>
              <h2 className="text-3xl font-semibold tracking-[-0.05em]">当前剩余 {summary.credit_balance} 积分</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                每个项目的实时看板首次解锁消耗 10 积分。解锁成功后，这个项目以后都能继续看。
              </p>
            </div>
            <div className="rounded-[24px] border border-primary/15 bg-[color:var(--surface-soft)] px-5 py-4 text-right">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">推荐套餐</div>
              <div className="mt-2 text-lg font-semibold">{selectedPlan?.label ?? "10 积分 / 10 元"}</div>
              <div className="mt-1 text-sm text-muted-foreground">付款确认后会手动补分到账</div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <MetricCard
              label="当前积分"
              value={String(summary.credit_balance)}
              hint="建议只解锁你真正想长期盯的盘面。"
              tone={summary.credit_balance > 0 ? "success" : "warning"}
            />
            <MetricCard
              label="累计消耗"
              value={String(summary.credit_spent_total)}
              hint="只统计你真正用来解锁项目的积分。"
            />
            <MetricCard
              label="已解锁项目"
              value={String(summary.unlocked_project_count)}
              hint="这些项目以后都能直接打开实时看板。"
            />
          </div>
        </div>

        <SectionCard
          title="积分规则"
          description="先免费体验，再决定把积分花在哪些项目上。"
        >
          <div className="space-y-3">
              <div className="flex items-center gap-3 rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4">
              <Coins className="size-5 text-primary" />
              <div className="text-sm">新用户注册默认赠送 20 积分。</div>
            </div>
              <div className="flex items-center gap-3 rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4">
              <Sparkles className="size-5 text-primary" />
              <div className="text-sm">每个项目首次解锁消耗 10 积分，解锁后这个盘面以后都能继续看。</div>
            </div>
              <div className="flex items-center gap-3 rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4">
              <WalletCards className="size-5 text-primary" />
              <div className="text-sm">微信付款后直接联系我，我会手动把积分补到你的账号里。</div>
            </div>
          </div>
        </SectionCard>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard
          title="充值方案"
          description="先选套餐，再扫码联系。当前不需要你在 App 内额外提交付款截图。"
        >
          <div className="grid gap-4 md:grid-cols-2">
            {summary.plans.map((plan) => {
              const active = plan.id === selectedPlanId;
              return (
                <div
                  key={plan.id}
                  onClick={() => setSelectedPlanId(plan.id)}
                  className={[
                    "group rounded-[28px] border px-5 py-5 text-left transition",
                    active
                      ? "border-primary bg-[color:var(--surface-soft-strong)] shadow-[var(--shadow-primary)]"
                      : "border-border bg-[color:var(--surface-soft)] hover:-translate-y-0.5 hover:border-primary/40 hover:bg-[color:var(--surface-soft-strong)]",
                  ].join(" ")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedPlanId(plan.id);
                    }
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant={active ? "success" : "secondary"}>{plan.id}</Badge>
                    <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                      {plan.credits} 积分
                    </div>
                  </div>
                  <div className="mt-5 text-2xl font-semibold tracking-[-0.04em]">{plan.priceCny} 元</div>
                  <div className="mt-2 text-sm text-muted-foreground">{plan.label}</div>
                  <div className="mt-5 flex items-center justify-between gap-3">
                    <div className="inline-flex items-center gap-2 text-sm font-medium text-primary">
                      选择此方案
                      <ArrowRight className="size-4 transition group-hover:translate-x-0.5" />
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      variant={active ? "default" : "secondary"}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedPlanId(plan.id);
                        setContactOpen(true);
                      }}
                    >
                      联系付款
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </SectionCard>

        <SectionCard
          title="联系方式二维码"
          description={selectedPlan ? `当前选中：${selectedPlan.label}` : "扫码联系运营。"}
        >
          <div className="grid gap-5 md:grid-cols-[220px_1fr] md:items-center">
            <div className="rounded-[28px] border border-border bg-[color:var(--surface-soft)] p-4 shadow-sm">
              <div className="surface-chart flex aspect-square items-center justify-center rounded-[22px]">
                <img
                  src={summary.contact_qr_url}
                  alt="联系二维码"
                  className="max-h-full max-w-full rounded-[18px] object-contain"
                />
              </div>
            </div>
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-border bg-white/80 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        <QrCode className="size-4 text-primary" />
                        扫码联系
              </div>
              <div className="space-y-2">
                <div className="text-lg font-semibold tracking-[-0.03em]">付款后联系我手动补积分</div>
                <p className="text-sm leading-6 text-muted-foreground">{summary.contact_hint}</p>
              </div>
              <div className="rounded-[24px] border border-border bg-[color:var(--surface-muted)] px-4 py-4 text-sm text-muted-foreground">
                当前积分：{summary.credit_balance}，累计消耗：{summary.credit_spent_total}，已解锁项目：
                {formatCompactNumber(summary.unlocked_project_count)}。
              </div>
            </div>
          </div>
        </SectionCard>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <SectionCard
          title="到账说明"
          description="整个流程很轻，不需要你重复上传截图。"
        >
          <div className="space-y-3">
            <div className="rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4 text-sm text-muted-foreground">
              第一步：先看好你要盯的项目，再决定补多少积分。
            </div>
            <div className="rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4 text-sm text-muted-foreground">
              第二步：选好套餐后扫码联系，微信付款完成即可。
            </div>
            <div className="rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4 text-sm text-muted-foreground">
              第三步：我会手动给你的账号补积分，到账后你就能继续解锁项目。
            </div>
          </div>
        </SectionCard>

        <SectionCard
          title="最近通知"
          description="这里只保留和账户直接相关的提醒：注册赠送、积分到账、人工调账和项目解锁。"
        >
          {activityItems.length ? (
            <div className="space-y-3">
              {activityItems.map((item) => (
                <div
                  key={item.id}
                  className="rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4 shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <BellDot className="size-4 text-primary" />
                      <div className="text-sm font-medium">{item.title}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant={item.isRead ? "secondary" : "success"}>
                        {item.isRead ? "已读" : "未读"}
                      </Badge>
                      <Badge
                        variant={
                          item.kind === "warning"
                            ? "warning"
                            : item.kind === "success"
                              ? "success"
                              : "secondary"
                        }
                      >
                        {item.delta > 0 ? `+${item.delta}` : item.delta}
                      </Badge>
                    </div>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span>{new Date(item.createdAt * 1000).toLocaleString("zh-CN")}</span>
                    {!item.isRead ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void markNotificationReadMutation.mutateAsync(item.id)}
                        disabled={markNotificationReadMutation.isPending}
                      >
                        标记已读
                      </Button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              compact
              title="当前还没有账户提醒"
              description="注册赠送、充值到账和项目解锁后，这里会自动出现账户动态。"
            />
          )}
        </SectionCard>
      </section>

      <Dialog open={contactOpen} onOpenChange={setContactOpen}>
        <DialogContent className="max-w-[720px]">
          <DialogHeader>
            <DialogTitle>扫码联系我补积分</DialogTitle>
            <DialogDescription>
              当前选中：{selectedPlan?.label ?? "10 积分 / 10 元"}。付款完成后，我会手动把积分补到你的账号里。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-6 md:grid-cols-[260px_1fr] md:items-center">
            <div className="rounded-[28px] border border-border bg-[color:var(--surface-soft)] p-4 shadow-sm">
              <div className="surface-chart flex aspect-square items-center justify-center rounded-[22px] p-2">
                <img
                  src={summary.contact_qr_url}
                  alt="联系二维码"
                  className="max-h-full max-w-full rounded-[20px] object-contain"
                />
              </div>
            </div>
            <div className="space-y-4">
              <div className="rounded-[24px] border border-border bg-[color:var(--surface-muted)] px-4 py-4 text-sm text-muted-foreground">
                {summary.contact_hint}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-[20px] border border-border bg-[color:var(--surface-soft)] px-4 py-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">当前积分</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{summary.credit_balance}</div>
                </div>
                <div className="rounded-[20px] border border-border bg-[color:var(--surface-soft)] px-4 py-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">已解锁项目</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                    {summary.unlocked_project_count}
                  </div>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setContactOpen(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
