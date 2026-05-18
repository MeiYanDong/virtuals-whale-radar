import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BellDot,
  CheckCircle2,
  Coins,
  ExternalLink,
  Loader2,
  QrCode,
  RefreshCcw,
  ShieldCheck,
  TicketPercent,
  WalletCards,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCompactNumber } from "@/lib/format";
import { payOnchainCreditWithWallet } from "@/lib/base-wallet";
import type { BillingPlan, OnchainCreditPaymentIntent, WalletAuthSource } from "@/types/api";

const PROJECT_UNLOCK_CREDITS = 20;
const ONCHAIN_INTENTS_LIMIT = 8;
const CONTACT_QR_FALLBACK_SRCS = [
  "/brand/contact-qr-placeholder.svg",
  "/admin/brand/contact-qr-placeholder.svg",
];

const VISIBLE_NOTIFICATION_TYPES = new Set([
  "credit:signup_bonus",
  "credit:manual_topup",
  "credit:manual_adjustment",
  "credit:onchain_usdc_topup",
  "credit:project_unlock",
  "billing_request_credited",
]);

function planUnlockLabel(plan: BillingPlan) {
  const projectCount = Math.floor(plan.credits / PROJECT_UNLOCK_CREDITS);
  if (projectCount <= 0) return "小额实测";
  return `可解锁 ${projectCount} 个项目`;
}

function planFallbackPriceLabel(plan: BillingPlan) {
  if (plan.priceCny <= 0) return "小额支付测试";
  return "支付后自动到账";
}

function buildContactQrCandidates(source: string) {
  const candidates: string[] = [];
  const add = (value: string) => {
    const normalized = String(value || "").trim();
    if (normalized && !candidates.includes(normalized)) {
      candidates.push(normalized);
    }
  };
  add(source);
  if (source.startsWith("/admin/brand/")) {
    add(source.replace("/admin/brand/", "/brand/"));
  }
  if (source.startsWith("/brand/")) {
    add(source.replace("/brand/", "/admin/brand/"));
  }
  CONTACT_QR_FALLBACK_SRCS.forEach(add);
  return candidates;
}

function txExplorerUrl(txHash: string) {
  return `https://basescan.org/tx/${txHash}`;
}

function intentStatusLabel(intent: OnchainCreditPaymentIntent) {
  if (intent.status === "confirmed") return "已到账";
  if (intent.status === "expired") return "已过期";
  if (intent.tx_hash) return "待确认";
  return "待付款";
}

function intentStatusVariant(intent: OnchainCreditPaymentIntent): "secondary" | "success" | "warning" {
  if (intent.status === "confirmed") return "success";
  if (intent.status === "expired") return "secondary";
  return "warning";
}

export function BillingPage() {
  const queryClient = useQueryClient();
  const [selectedPlanId, setSelectedPlanId] = useState("starter");
  const [payingSource, setPayingSource] = useState<WalletAuthSource | null>(null);
  const [qrSourceIndex, setQrSourceIndex] = useState(0);
  const [recoveryTxByIntent, setRecoveryTxByIntent] = useState<Record<number, string>>({});

  const billingQuery = useQuery({
    queryKey: queryKeys.appBillingSummary,
    queryFn: () => dashboardApi.app.getBillingSummary(),
  });
  const activityQuery = useQuery({
    queryKey: queryKeys.appNotifications(12),
    queryFn: () => dashboardApi.app.getNotifications(12),
  });
  const onchainIntentsQuery = useQuery({
    queryKey: queryKeys.appOnchainPaymentIntents(ONCHAIN_INTENTS_LIMIT),
    queryFn: () => dashboardApi.app.getOnchainPaymentIntents(ONCHAIN_INTENTS_LIMIT),
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

  const onchainPaymentMutation = useMutation({
    mutationFn: async ({ planId, source }: { planId: string; source: WalletAuthSource }) => {
      setPayingSource(source);
      return payOnchainCreditWithWallet(planId, source);
    },
    onSuccess: async (result) => {
      queryClient.setQueryData(queryKeys.appBillingSummary, result.billing);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
      ]);
      toast.success(`Base USDC 已确认，${result.item.credits} 积分已到账。`);
    },
    onError: async (error: Error) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.appOnchainPaymentIntents(ONCHAIN_INTENTS_LIMIT) });
      toast.error(error.message || "Base USDC 支付未完成。");
    },
    onSettled: async () => {
      setPayingSource(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.appOnchainPaymentIntents(ONCHAIN_INTENTS_LIMIT) });
    },
  });

  const verifyIntentMutation = useMutation({
    mutationFn: async ({ intentId, txHash }: { intentId: number; txHash: string }) =>
      dashboardApi.app.verifyOnchainPaymentIntent(intentId, txHash, 90),
    onSuccess: async (result) => {
      queryClient.setQueryData(queryKeys.appBillingSummary, result.billing);
      setRecoveryTxByIntent((current) => {
        const next = { ...current };
        delete next[result.item.id];
        return next;
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: ["app-notifications"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appOnchainPaymentIntents(ONCHAIN_INTENTS_LIMIT) }),
      ]);
      toast.success(result.alreadyConfirmed ? "这笔充值已经入账。" : `${result.item.credits} 积分已到账。`);
    },
    onError: (error: Error) => toast.error(error.message || "暂时还不能确认这笔支付。"),
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
  const onchainEnabled = Boolean(summary.onchain_payment?.enabled);
  const qrCandidates = buildContactQrCandidates(summary.contact_qr_url);
  const qrSrc = qrCandidates[Math.min(qrSourceIndex, qrCandidates.length - 1)];
  const onchainIntentItems = onchainIntentsQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Billing"
        title="积分与充值"
        description="每个项目首次解锁消耗 20 积分。选择套餐后用 Base Account 或 OKX Wallet 支付 USDC，积分到账后即可解锁看板。"
        actions={
          summary.referral_url ? (
            <Button asChild variant="secondary">
              <a href={summary.referral_url} target="_blank" rel="noreferrer">
                <TicketPercent className="size-4" />
                Virtuals 邀请码
              </a>
            </Button>
          ) : null
        }
      />

      <Alert className="border-primary/20 bg-[color:var(--surface-soft)]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <TicketPercent className="mt-0.5 size-4 shrink-0 text-primary" />
            <div className="space-y-1">
              <div className="text-sm font-semibold">Virtuals 注册福利</div>
              <p className="text-sm leading-6 text-muted-foreground">{summary.notice}</p>
            </div>
          </div>
          {summary.referral_url ? (
            <Button asChild size="sm" variant="outline">
              <a href={summary.referral_url} target="_blank" rel="noreferrer">
                打开注册链接
                <ArrowRight className="size-4" />
              </a>
            </Button>
          ) : null}
        </div>
      </Alert>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <section className="surface-hero-strong rounded-[28px] border border-white/60 p-5">
            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-[20px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  当前积分
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{summary.credit_balance}</div>
                <div className="mt-2 text-sm text-muted-foreground">
                  {summary.credit_balance >= PROJECT_UNLOCK_CREDITS ? "可继续解锁项目" : "低于单项目解锁成本"}
                </div>
              </div>
              <div className="rounded-[20px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  解锁成本
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">20</div>
                <div className="mt-2 text-sm text-muted-foreground">积分 / 项目，解锁后永久可看</div>
              </div>
              <div className="rounded-[20px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  已解锁
                </div>
                <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">
                  {formatCompactNumber(summary.unlocked_project_count)}
                </div>
                <div className="mt-2 text-sm text-muted-foreground">
                  累计消耗 {formatCompactNumber(summary.credit_spent_total)} 积分
                </div>
              </div>
            </div>
          </section>

          <SectionCard
            title="选择套餐"
            description="20 积分可解锁 1 个项目；100 积分适合同时跟踪 5 个项目。"
          >
            <div className="grid gap-3">
              {summary.plans.map((plan) => {
                const active = plan.id === selectedPlan?.id;
                return (
                  <button
                    key={plan.id}
                    type="button"
                    onClick={() => setSelectedPlanId(plan.id)}
                    className={[
                      "grid gap-3 rounded-[20px] border px-4 py-4 text-left transition md:grid-cols-[1fr_auto] md:items-center",
                      active
                        ? "border-primary bg-[color:var(--surface-soft-strong)] shadow-[var(--shadow-primary)]"
                        : "border-border bg-[color:var(--surface-soft)] hover:border-primary/40 hover:bg-[color:var(--surface-soft-strong)]",
                    ].join(" ")}
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={plan.isTest ? "warning" : active ? "success" : "secondary"}>
                          {plan.isTest ? "test" : plan.id}
                        </Badge>
                        <span className="text-sm font-semibold">{plan.label}</span>
                      </div>
                      <div className="mt-2 text-sm text-muted-foreground">
                        {planUnlockLabel(plan)} · {planFallbackPriceLabel(plan)}
                      </div>
                    </div>
                    <div className="text-left md:text-right">
                      <div className="text-xl font-semibold tracking-[-0.03em]">{plan.priceUsdc} USDC</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.14em] text-muted-foreground">
                        {plan.credits} credits
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>

            <div className="mt-4 rounded-[20px] border border-primary/15 bg-[color:var(--surface-muted)] px-4 py-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <WalletCards className="size-4 text-primary" />
                    钱包支付
                  </div>
                  <div className="text-sm leading-6 text-muted-foreground">
                    当前选中 {selectedPlan?.credits ?? 0} 积分 / {selectedPlan?.priceUsdc ?? "0"} USDC。
                    {onchainEnabled ? " 完成钱包确认后，积分会自动到账。" : " 当前暂时无法使用钱包支付，请扫码联系处理。"}
                  </div>
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    type="button"
                    disabled={!selectedPlan || !onchainEnabled || onchainPaymentMutation.isPending}
                    onClick={() => {
                      if (selectedPlan) {
                        void onchainPaymentMutation.mutateAsync({
                          planId: selectedPlan.id,
                          source: "base_wallet",
                        });
                      }
                    }}
                  >
                    {payingSource === "base_wallet" ? <Loader2 className="animate-spin" /> : <WalletCards />}
                    Base Account
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!selectedPlan || !onchainEnabled || onchainPaymentMutation.isPending}
                    onClick={() => {
                      if (selectedPlan) {
                        void onchainPaymentMutation.mutateAsync({
                          planId: selectedPlan.id,
                          source: "okx_wallet",
                        });
                      }
                    }}
                  >
                    {payingSource === "okx_wallet" ? <Loader2 className="animate-spin" /> : <WalletCards />}
                    OKX Wallet
                  </Button>
                </div>
              </div>
            </div>
          </SectionCard>

          <SectionCard
            title="链上支付记录"
            description="交易已提交但暂未到账时，在这里重新确认同一笔 Base USDC 支付。"
          >
            {onchainIntentsQuery.isLoading ? (
              <div className="flex items-center gap-2 rounded-[18px] border border-border bg-[color:var(--surface-soft)] px-4 py-4 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                正在读取链上支付记录...
              </div>
            ) : onchainIntentItems.length ? (
              <div className="space-y-3">
                {onchainIntentItems.map((intent) => {
                  const draftTx = recoveryTxByIntent[intent.id] ?? "";
                  const txValue = (intent.tx_hash || draftTx).trim();
                  const isVerifyPending =
                    verifyIntentMutation.isPending &&
                    verifyIntentMutation.variables?.intentId === intent.id;
                  const canVerify = intent.status === "pending" && Boolean(txValue);
                  return (
                    <div
                      key={intent.id}
                      className="rounded-[18px] border border-border bg-[color:var(--surface-soft)] px-4 py-4"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={intentStatusVariant(intent)}>{intentStatusLabel(intent)}</Badge>
                            <span className="text-sm font-semibold">
                              {intent.credits} 积分 / {intent.amount_usdc} USDC
                            </span>
                          </div>
                          <div className="mt-2 text-xs text-muted-foreground">
                            创建于 {new Date(intent.created_at * 1000).toLocaleString("zh-CN")}
                          </div>
                        </div>
                        {intent.tx_hash ? (
                          <Button asChild variant="outline" size="sm">
                            <a href={txExplorerUrl(intent.tx_hash)} target="_blank" rel="noreferrer">
                              查看交易
                              <ExternalLink className="size-4" />
                            </a>
                          </Button>
                        ) : null}
                      </div>

                      {intent.status === "pending" ? (
                        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                          <Input
                            value={txValue}
                            readOnly={Boolean(intent.tx_hash)}
                            placeholder="粘贴 Base 交易哈希"
                            className="font-mono text-xs"
                            onChange={(event) =>
                              setRecoveryTxByIntent((current) => ({
                                ...current,
                                [intent.id]: event.target.value,
                              }))
                            }
                          />
                          <Button
                            type="button"
                            variant={intent.tx_hash ? "outline" : "default"}
                            disabled={!canVerify || isVerifyPending}
                            onClick={() =>
                              verifyIntentMutation.mutate({
                                intentId: intent.id,
                                txHash: txValue,
                              })
                            }
                          >
                            {isVerifyPending ? <Loader2 className="animate-spin" /> : <RefreshCcw className="size-4" />}
                            {intent.tx_hash ? "重新确认" : "确认到账"}
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState
                compact
                title="还没有链上支付记录"
                description="发起 Base USDC 支付后，交易记录会显示在这里。"
              />
            )}
          </SectionCard>

          <SectionCard
            title="最近账户动态"
            description="只保留注册赠送、充值到账、人工调账和项目解锁。"
          >
            {activityItems.length ? (
              <div className="space-y-3">
                {activityItems.slice(0, 6).map((item) => (
                  <div
                    key={item.id}
                    className="rounded-[18px] border border-border bg-[color:var(--surface-soft)] px-4 py-4"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <BellDot className="size-4 shrink-0 text-primary" />
                        <div className="truncate text-sm font-medium">{item.title}</div>
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
        </div>

        <aside className="space-y-5">
          <SectionCard title="支付说明" description="确认钱包弹窗里的网络和金额后再支付。">
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-3 rounded-[16px] border border-border bg-[color:var(--surface-soft)] px-3 py-3">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <ShieldCheck className="size-4 text-primary" />
                  网络
                </div>
                <div className="font-medium">Base Mainnet</div>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-[16px] border border-border bg-[color:var(--surface-soft)] px-3 py-3">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Coins className="size-4 text-primary" />
                  资产
                </div>
                <div className="font-medium">USDC</div>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-[16px] border border-border bg-[color:var(--surface-soft)] px-3 py-3">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <CheckCircle2 className="size-4 text-primary" />
                  到账
                </div>
                <div className="font-medium">自动到账</div>
              </div>
              <div className="flex items-start gap-2 rounded-[16px] border border-border bg-[color:var(--surface-muted)] px-3 py-3 text-muted-foreground">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>支付完成后请停留片刻，系统确认后会自动刷新积分。长时间未到账时再联系运营处理。</span>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="需要帮助？" description="钱包支付失败或希望人工处理时再扫码联系。">
            <div className="rounded-[18px] border border-border bg-white p-3 shadow-sm">
              <div className="flex h-[320px] items-center justify-center overflow-hidden rounded-[14px] bg-white">
                <img
                  src={qrSrc}
                  alt="联系二维码"
                  loading="lazy"
                  onError={() =>
                    setQrSourceIndex((index) => Math.min(index + 1, qrCandidates.length - 1))
                  }
                  className="h-full w-full object-contain"
                />
              </div>
            </div>
            <div className="mt-3 rounded-[16px] border border-border bg-[color:var(--surface-muted)] px-3 py-3 text-sm leading-6 text-muted-foreground">
              <div className="mb-1 flex items-center gap-2 font-medium text-foreground">
                <QrCode className="size-4 text-primary" />
                扫码联系运营
              </div>
              {summary.contact_hint}
            </div>
          </SectionCard>
        </aside>
      </section>
    </div>
  );
}
