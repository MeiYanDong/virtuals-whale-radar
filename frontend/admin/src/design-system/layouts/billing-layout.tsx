import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import { EmptyState, MetricCard, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";

export type BillingMetric = {
  label: string;
  value: string;
  hint: string;
  tone?: "default" | "success" | "warning" | "danger";
};

export type BillingPlan = {
  key: string;
  name: string;
  priceLabel: string;
  description: string;
  highlight?: string;
  actionLabel?: string;
  onAction?: () => void;
};

export type BillingActivityItem = {
  key: string;
  title: string;
  body: string;
  createdAt?: number | string;
  unread?: boolean;
};

export type BillingLayoutProps = {
  title: string;
  description: string;
  announcementTitle?: string;
  announcementBody?: string;
  referralLabel?: string;
  referralUrl?: string;
  metrics: BillingMetric[];
  plans: BillingPlan[];
  qrTitle: string;
  qrDescription: string;
  qrImageSrc: string;
  qrImageAlt: string;
  activityTitle?: string;
  activityItems?: BillingActivityItem[];
  footerAction?: ReactNode;
};

export function BillingLayout({
  title,
  description,
  announcementTitle,
  announcementBody,
  referralLabel,
  referralUrl,
  metrics,
  plans,
  qrTitle,
  qrDescription,
  qrImageSrc,
  qrImageAlt,
  activityTitle = "最近动态",
  activityItems = [],
  footerAction,
}: BillingLayoutProps) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} actions={footerAction} />

      {announcementTitle || announcementBody ? (
        <section className="surface-hero rounded-[30px] border border-white/60 p-5">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              {announcementTitle ? (
                <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary/80">
                  {announcementTitle}
                </div>
              ) : null}
              {announcementBody ? (
                <p className="max-w-3xl text-sm leading-6 text-foreground/90">{announcementBody}</p>
              ) : null}
            </div>
            {referralUrl && referralLabel ? (
              <Button asChild variant="outline">
                <a href={referralUrl} target="_blank" rel="noreferrer">
                  {referralLabel}
                  <ExternalLink className="size-4" />
                </a>
              </Button>
            ) : null}
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        {metrics.map((metric) => (
          <MetricCard
            key={metric.label}
            label={metric.label}
            value={metric.value}
            hint={metric.hint}
            tone={metric.tone}
          />
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <SectionCard title="充值方案" description="先扫码联系，再由管理员手动补积分。">
          <div className="grid gap-4 lg:grid-cols-2">
            {plans.map((plan) => (
              <div
                key={plan.key}
                className="rounded-[26px] border border-border bg-[color:var(--surface-soft)] px-5 py-5 shadow-sm"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold tracking-[-0.03em]">{plan.name}</div>
                    <div className="mt-1 text-sm text-muted-foreground">{plan.description}</div>
                  </div>
                  {plan.highlight ? <Badge variant="success">{plan.highlight}</Badge> : null}
                </div>
                <div className="mt-5 text-3xl font-semibold tracking-[-0.05em]">{plan.priceLabel}</div>
                {plan.actionLabel ? (
                  <Button className="mt-5 w-full" variant="secondary" onClick={plan.onAction}>
                    {plan.actionLabel}
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title={qrTitle} description={qrDescription}>
          <div className="rounded-[26px] border border-border bg-[color:var(--surface-empty)] p-4 text-center">
            <div className="mx-auto flex max-w-[340px] items-center justify-center rounded-[24px] bg-white p-4 shadow-[0_18px_40px_rgba(17,33,38,0.08)]">
              <img src={qrImageSrc} alt={qrImageAlt} className="h-auto w-full rounded-[18px] object-contain" />
            </div>
            <p className="mx-auto mt-4 max-w-sm text-sm leading-6 text-muted-foreground">
              扫码后直接联系管理员，付款确认后会由后台手动补到你的账户。
            </p>
          </div>
        </SectionCard>
      </div>

      <SectionCard title={activityTitle} description="用户看到的是账户动态，不是后台流水。">
        {activityItems.length ? (
          <div className="space-y-3">
            {activityItems.map((item) => (
              <div
                key={item.key}
                className="rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4"
              >
                <div className="flex items-center gap-2">
                  <div className="text-sm font-medium">{item.title}</div>
                  {item.unread ? <Badge variant="success">未读</Badge> : null}
                </div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                {item.createdAt ? (
                  <div className="mt-3 text-xs text-muted-foreground">{formatDateTime(item.createdAt)}</div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            compact
            title="当前没有账户动态"
            description="后续到账、解锁和系统提醒会集中显示在这里。"
          />
        )}
      </SectionCard>
    </div>
  );
}
