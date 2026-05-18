import { Activity, ArrowRight, BadgeCheck, CheckCircle2, Radar, ShieldCheck, WalletCards } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { buildAuthSwitchHref, resolvePostAuthRedirect } from "@/auth/redirect";
import { useAuth } from "@/auth/use-auth";
import { BrandLogo } from "@/components/brand-logo";
import { Button } from "@/components/ui/button";

function formatV(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed) || parsed <= 0) return "0 V";
  if (parsed >= 1000) return `${(parsed / 1000).toFixed(parsed >= 10_000 ? 0 : 1)}k V`;
  if (parsed >= 100) return `${parsed.toFixed(0)} V`;
  return `${parsed.toFixed(2)} V`;
}

function formatSpentV(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed) || parsed <= 0) return "0 V";
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(parsed)} V`;
}

function formatTokenWan(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed) || parsed <= 0) return "0";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(parsed / 10_000);
}

function formatFdvWanUsd(value: string | number | null | undefined) {
  const parsed = Number(value ?? 0);
  if (!Number.isFinite(parsed) || parsed <= 0) return "-";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(parsed / 10_000);
}

function formatAddress(value: string) {
  return value ? `${value.slice(0, 6)}...${value.slice(-4)}` : "-";
}

export function BaseEntryPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { auth, isAuthenticated } = useAuth();
  const baseEntryQuery = useQuery({
    queryKey: queryKeys.publicBaseEntry,
    queryFn: dashboardApi.public.getBaseEntry,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const baseEntry = baseEntryQuery.data;
  const projects = baseEntry?.projects ?? [];
  const showcaseProject = projects[0];
  const showcaseWhales = showcaseProject?.whaleBoard ?? [];
  const previewRows = [
    {
      label: `${showcaseProject?.name ?? "SR"} 买入事件`,
      value: showcaseProject ? String(showcaseProject.buyEventCount || showcaseProject.eventCount || 0) : "--",
      tone: "text-primary",
    },
    {
      label: "参与钱包",
      value: showcaseProject ? String(showcaseProject.uniqueBuyerCount || showcaseProject.whaleRows || 0) : "--",
      tone: "text-[color:var(--warning)]",
    },
    {
      label: "峰值分钟消耗",
      value: showcaseProject ? formatV(showcaseProject.peakMinuteSpentV) : "--",
      tone: "text-[color:var(--success)]",
    },
  ];

  const goHome = () => {
    const redirectTo = new URLSearchParams(location.search).get("redirect");
    navigate(
      resolvePostAuthRedirect({
        role: auth?.user?.role,
        homePath: auth?.home_path || "/app",
        redirectTo,
      }),
      { replace: false },
    );
  };

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-5 py-5 sm:px-8">
        <Link to="/base" className="flex min-w-0 items-center gap-3">
          <span className="theme-brand-badge flex size-11 shrink-0 items-center justify-center rounded-[14px]">
            <BrandLogo className="size-8 rounded-[10px]" />
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold uppercase tracking-[0.18em] text-primary/80">
              Virtuals Whale Radar
            </span>
            <span className="block text-sm text-muted-foreground">Virtuals 项目雷达</span>
          </span>
        </Link>

        {isAuthenticated ? (
          <Button onClick={goHome}>
            进入控制台
            <ArrowRight />
          </Button>
        ) : null}
      </header>

      <section className="mx-auto grid min-h-[calc(100vh-5.25rem)] w-full max-w-7xl items-center gap-8 px-5 pb-10 sm:px-8 lg:grid-cols-[0.92fr_1.08fr]">
        <div className="space-y-8">
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-[color:var(--surface-soft)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              <BadgeCheck className="size-4 text-primary" />
              Virtuals 发射雷达
            </div>
            <h1 className="max-w-2xl text-5xl font-semibold leading-[1.02] text-balance sm:text-6xl">
              Virtuals 项目雷达
            </h1>
            <p className="max-w-xl text-base leading-7 text-muted-foreground">
              聚焦 Virtuals 新项目发射窗口、分钟级大户消耗、税率变化、钱包持仓和链上延迟，同时支持 Base 生态用户用钱包进入和 USDC 购买积分。
            </p>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            {isAuthenticated ? (
              <Button className="h-12 px-5" onClick={goHome}>
                进入我的看板
                <ArrowRight />
              </Button>
            ) : (
              <>
                <Button asChild className="h-12 px-5">
                  <Link to={buildAuthSwitchHref("/auth/login", location.search)}>
                    开始使用
                    <ArrowRight />
                  </Link>
                </Button>
                <Link
                  className="text-sm font-medium text-muted-foreground hover:text-foreground"
                  to={buildAuthSwitchHref("/auth/register", location.search)}
                >
                  用邮箱创建账号
                </Link>
              </>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-[20px] border border-border bg-[color:var(--surface-soft)] p-4">
              <Radar className="mb-3 size-5 text-primary" />
              <div className="text-sm font-semibold">SignalHub</div>
              <div className="mt-1 text-sm text-muted-foreground">发射项目入口</div>
            </div>
            <div className="rounded-[20px] border border-border bg-[color:var(--surface-soft)] p-4">
              <Activity className="mb-3 size-5 text-[color:var(--warning)]" />
              <div className="text-sm font-semibold">大户榜单</div>
              <div className="mt-1 text-sm text-muted-foreground">地址消费排行</div>
            </div>
            <div className="rounded-[20px] border border-border bg-[color:var(--surface-soft)] p-4">
              <WalletCards className="mb-3 size-5 text-[color:var(--success)]" />
              <div className="text-sm font-semibold">我的钱包</div>
              <div className="mt-1 text-sm text-muted-foreground">地址持仓追踪</div>
            </div>
          </div>
        </div>

        <div className="surface-glass overflow-hidden rounded-[28px] border border-border">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                真实发射样本
              </div>
              <div className="mt-1 text-xl font-semibold">Virtuals 观察台</div>
            </div>
            <div className="flex items-center gap-2 rounded-full border border-border bg-[color:var(--surface-soft)] px-3 py-2 text-xs text-muted-foreground">
              <ShieldCheck className="size-4 text-primary" />
              SR 真实数据
            </div>
          </div>

          <div className="grid gap-4 p-5">
            <div className="grid gap-3 sm:grid-cols-3">
              {previewRows.map((item) => (
                <div key={item.label} className="rounded-[18px] border border-border bg-[color:var(--surface-soft)] p-4">
                  <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">{item.label}</div>
                  <div className={`mt-3 text-lg font-semibold ${item.tone}`}>{item.value}</div>
                </div>
              ))}
            </div>

            <div className="overflow-hidden rounded-[18px] border border-border bg-[color:var(--surface-soft)]">
              <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
                <div>
                  <div className="text-sm font-semibold">SR 大户榜单</div>
                  <div className="mt-1 text-xs text-muted-foreground">按累计代币数量排序，排除团队/初始化异常地址。</div>
                </div>
                <div className="shrink-0 rounded-full border border-border bg-background/70 px-3 py-1 text-xs text-muted-foreground">
                  累计税收 {formatV(showcaseProject?.sumTaxV)}
                </div>
              </div>
              {baseEntryQuery.isLoading ? (
                <div className="px-4 py-6 text-sm text-muted-foreground">正在读取真实项目数据...</div>
              ) : showcaseWhales.length ? (
                <div className="overflow-x-auto">
                  <div className="grid min-w-[640px] grid-cols-[1.5fr_0.85fr_0.95fr_1fr] border-b border-border px-4 py-3 text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    <div>钱包地址</div>
                    <div>累计花费 V</div>
                    <div>累计代币数量（万）</div>
                    <div>含税成本 FDV（万 USD）</div>
                  </div>
                  {showcaseWhales.slice(0, 6).map((row) => (
                    <div
                      key={row.wallet}
                      className="grid min-w-[640px] grid-cols-[1.5fr_0.85fr_0.95fr_1fr] items-center border-b border-border/70 px-4 py-3 text-sm last:border-b-0"
                    >
                      <div className="font-mono text-xs text-muted-foreground">{formatAddress(row.wallet)}</div>
                      <div className="font-medium">{formatSpentV(row.spentV)}</div>
                      <div>{formatTokenWan(row.tokenBought)}</div>
                      <div>{formatFdvWanUsd(row.breakevenFdvUsd)}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="px-4 py-6 text-sm text-muted-foreground">
                  当前还没有可公开展示的 SR 大户榜单样本。
                </div>
              )}
            </div>

            <div className="rounded-[18px] border border-border bg-[color:var(--surface-soft)] p-4">
              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  "SR 真实发射窗口样本",
                  "绑定自己关心的钱包",
                  "用 20 积分解锁项目",
                ].map((item) => (
                  <div key={item} className="flex items-start gap-2 text-sm leading-6 text-muted-foreground">
                    <CheckCircle2 className="mt-1 size-4 shrink-0 text-primary" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
