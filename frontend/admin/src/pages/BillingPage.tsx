import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Coins, QrCode, Sparkles, WalletCards } from "lucide-react";
import { useState } from "react";

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

export function BillingPage() {
  const [selectedPlanId, setSelectedPlanId] = useState("starter");
  const [contactOpen, setContactOpen] = useState(false);
  const billingQuery = useQuery({
    queryKey: queryKeys.appBillingSummary,
    queryFn: () => dashboardApi.app.getBillingSummary(),
  });

  if (billingQuery.isLoading) {
    return <LoadingState label="正在加载积分与 Billing 信息..." />;
  }

  if (billingQuery.isError || !billingQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Billing"
          title="积分与 Billing"
          description="当前无法读取积分摘要或联系方式配置。"
        />
        <EmptyState
          title="Billing 信息加载失败"
          description="请检查 `/api/app/billing/summary` 是否可用，以及后端是否提供联系方式二维码资源。"
        />
      </div>
    );
  }

  const summary = billingQuery.data;
  const selectedPlan = summary.plans.find((plan) => plan.id === selectedPlanId) ?? summary.plans[0];

  return (
    <div className="space-y-6">
      <Alert className="overflow-hidden border-primary/20 bg-[linear-gradient(135deg,rgba(36,142,147,0.12),rgba(220,232,199,0.42))]">
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
        eyebrow="Billing"
        title="积分与 Billing"
        description="项目 Overview 详细数据按项目首次解锁扣分。充值先走线下联系，管理员确认后手动补积分。"
      />

      <section className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="rounded-[32px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(36,142,147,0.22),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.96),rgba(232,245,240,0.92))] p-6 shadow-[0_28px_60px_rgba(36,142,147,0.12)]">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-2">
              <Badge variant="secondary">积分账户</Badge>
              <h2 className="text-3xl font-semibold tracking-[-0.05em]">当前剩余 {summary.credit_balance} 积分</h2>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                每个项目的 Overview 详细数据首次解锁消耗 10 积分。解锁成功后，该项目永久可读。
              </p>
            </div>
            <div className="rounded-[24px] border border-primary/15 bg-white/72 px-5 py-4 text-right">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">推荐套餐</div>
              <div className="mt-2 text-lg font-semibold">{selectedPlan?.label ?? "10 积分 / 10 元"}</div>
              <div className="mt-1 text-sm text-muted-foreground">付款后联系管理员手动到账</div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <MetricCard
              label="当前积分"
              value={String(summary.credit_balance)}
              hint="可用于解锁新的项目 Overview。"
              tone={summary.credit_balance > 0 ? "success" : "warning"}
            />
            <MetricCard
              label="累计消耗"
              value={String(summary.credit_spent_total)}
              hint="仅统计项目解锁实际消耗的积分。"
            />
            <MetricCard
              label="已解锁项目"
              value={String(summary.unlocked_project_count)}
              hint="这些项目的 Overview 已永久可读。"
            />
          </div>
        </div>

        <SectionCard
          title="积分规则"
          description="当前只保留最小可售闭环，不接微信支付。"
        >
          <div className="space-y-3">
            <div className="flex items-center gap-3 rounded-[22px] border border-border bg-white/80 px-4 py-4">
              <Coins className="size-5 text-primary" />
              <div className="text-sm">新用户注册赠送 20 积分。</div>
            </div>
            <div className="flex items-center gap-3 rounded-[22px] border border-border bg-white/80 px-4 py-4">
              <Sparkles className="size-5 text-primary" />
              <div className="text-sm">每个项目首次解锁消耗 10 积分，解锁后永久可看。</div>
            </div>
            <div className="flex items-center gap-3 rounded-[22px] border border-border bg-white/80 px-4 py-4">
              <WalletCards className="size-5 text-primary" />
              <div className="text-sm">线下付款完成后，管理员会手动给账号补积分。</div>
            </div>
          </div>
        </SectionCard>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <SectionCard
          title="充值方案"
          description="点击任一方案后，右侧会锁定对应的联系方式卡片。"
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
                      ? "border-primary bg-[linear-gradient(180deg,rgba(36,142,147,0.12),rgba(255,255,255,0.92))] shadow-[0_18px_34px_rgba(36,142,147,0.14)]"
                      : "border-border bg-white/80 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-white",
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
            <div className="rounded-[28px] border border-border bg-white/80 p-4 shadow-sm">
              <div className="flex aspect-square items-center justify-center rounded-[22px] bg-[linear-gradient(180deg,rgba(242,248,243,0.98),rgba(220,232,199,0.72))]">
                <img
                  src={summary.contact_qr_url}
                  alt="Billing 联系二维码"
                  className="size-full rounded-[18px] object-cover"
                />
              </div>
            </div>
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-border bg-white/80 px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                <QrCode className="size-4 text-primary" />
                扫码联系
              </div>
              <div className="space-y-2">
                <div className="text-lg font-semibold tracking-[-0.03em]">付款后联系管理员手动补积分</div>
                <p className="text-sm leading-6 text-muted-foreground">{summary.contact_hint}</p>
              </div>
              <div className="rounded-[24px] border border-border bg-muted/70 px-4 py-4 text-sm text-muted-foreground">
                当前积分：{summary.credit_balance}，累计消耗：{summary.credit_spent_total}，已解锁项目：
                {formatCompactNumber(summary.unlocked_project_count)}。
              </div>
            </div>
          </div>
        </SectionCard>
      </section>

      <Dialog open={contactOpen} onOpenChange={setContactOpen}>
        <DialogContent className="max-w-[720px]">
          <DialogHeader>
            <DialogTitle>联系运营完成线下付款</DialogTitle>
            <DialogDescription>
              当前选中：{selectedPlan?.label ?? "10 积分 / 10 元"}。扫码联系后，付款完成由管理员手动补积分。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-6 md:grid-cols-[260px_1fr] md:items-center">
            <div className="rounded-[28px] border border-border bg-white/80 p-4 shadow-sm">
              <img
                src={summary.contact_qr_url}
                alt="Billing 联系二维码"
                className="aspect-square w-full rounded-[20px] object-cover"
              />
            </div>
            <div className="space-y-4">
              <div className="rounded-[24px] border border-border bg-muted/70 px-4 py-4 text-sm text-muted-foreground">
                {summary.contact_hint}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-[20px] border border-border bg-white/80 px-4 py-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">当前积分</div>
                  <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{summary.credit_balance}</div>
                </div>
                <div className="rounded-[20px] border border-border bg-white/80 px-4 py-4">
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
