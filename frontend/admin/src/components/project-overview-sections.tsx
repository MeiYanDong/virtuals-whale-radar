import { ExternalLink } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { EmptyState, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatAddress,
  formatCurrency,
  formatDateTime,
  formatDecimal,
  formatInteger,
  formatShortDateTime,
} from "@/lib/format";
import type { MinuteRow, OverviewActiveProjectItem, OverviewBoardItem, EventDelayRow } from "@/types/api";

const TAX_FDV_GLOW_MS = 2000;
const LOCAL_TAX_FDV_SIM_START_HOLD_MS = 1800;
const LOCAL_TAX_FDV_SIM_REPLAY_MS = 5800;

type BoardRow = {
  wallet: string;
  name?: string;
  spentV: number;
  tokenBought: number;
  breakevenFdvUsd: number | null;
  updatedAt: number;
};

function toNumber(value: number | string | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function tokenWan(value: number) {
  return value / 10000;
}

function formatSpentVInteger(value: number) {
  return `${formatInteger(Math.round(value))} V`;
}

function formatBreakevenFdvUsd(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return formatDecimal(value / 10000, 2);
}

function formatLiveTokenPriceV(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return `${formatDecimal(value, 10)} V`;
}

function formatLiveTokenPriceUsd(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return `${formatDecimal(value, 10)} USD`;
}

function formatLiveFdvUsd(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return formatDecimal(value / 10000, 2);
}

function formatWanUsd(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return formatDecimal(value, 2);
}

function formatBuyTaxRate(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return `${formatDecimal(value, 0)}%`;
}

// Local-only visual replay for checking the cross-threshold glow without mutating DB/API data.
function getLocalTaxFdvSimulationScenario() {
  if (typeof window === "undefined") return null;
  if (window.location.hostname !== "127.0.0.1" && window.location.hostname !== "localhost") return null;

  const mode = new URLSearchParams(window.location.search).get("taxFdvSim");
  if (mode === "up") return { start: 96.58, end: 106.58 };
  if (mode === "down") return { start: 106.58, end: 86.58 };
  return null;
}

function projectStatusLabel(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return "发射中";
  if (key === "prelaunch") return "预热中";
  if (key === "ended") return "已结束";
  if (key === "removed") return "已移除";
  if (key === "scheduled") return "待开始";
  return "待补全";
}

function projectStatusVariant(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return "success" as const;
  if (key === "prelaunch") return "warning" as const;
  if (key === "ended" || key === "scheduled") return "secondary" as const;
  if (key === "removed") return "danger" as const;
  return "default" as const;
}

function marketBaseLabel(item: OverviewActiveProjectItem) {
  if (item.marketPriceLabel) return item.marketPriceLabel;
  const status = String(item.projectedStatus || item.status || "").toLowerCase();
  if (status === "live") return "实时价格";
  if (status === "scheduled" || status === "prelaunch") return "开盘参考价";
  return "当前池价";
}

function marketFdvLabel(item: OverviewActiveProjectItem) {
  const mode = String(item.marketPriceMode || "").toLowerCase();
  const status = String(item.projectedStatus || item.status || "").toLowerCase();
  if (mode === "reference" || status === "scheduled" || status === "prelaunch") {
    return "参考 FDV（万 USD）";
  }
  if (mode === "live" || status === "live") return "实时 FDV（万 USD）";
  return "当前 FDV（万 USD）";
}

function formatMarketMeta(item: OverviewActiveProjectItem) {
  const parts: string[] = [];
  if (item.priceUpdatedAt) parts.push(`更新 ${formatDateTime(item.priceUpdatedAt)}`);
  if (item.priceBlockNumber) parts.push(`区块 #${formatInteger(item.priceBlockNumber)}`);
  if (item.priceLatencyMs !== null && item.priceLatencyMs !== undefined) {
    parts.push(`${item.priceLatencyMs}ms`);
  }
  if (item.marketPriceStale) parts.push("VIRTUAL/USD 价格源过期");
  return parts.join(" / ");
}

function MinuteBars({
  items,
}: {
  items: MinuteRow[];
}) {
  const chartItems = [...items]
    .sort((left, right) => left.minute_key - right.minute_key)
    .map((item) => ({
      key: item.minute_key,
      value: toNumber(item.minute_spent_v),
    }));

  const peak = Math.max(...chartItems.map((item) => item.value), 0);
  const total = chartItems.reduce((sum, item) => sum + item.value, 0);

  if (!chartItems.length) {
    return (
      <EmptyState
        compact
        title="暂无分钟消耗数据"
        description="当前项目还没有形成分钟聚合，等交易进入后这里会出现对应窗口的柱状图。"
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-[20px] border border-border bg-[color:var(--surface-muted)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">分钟条数</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{chartItems.length}</div>
        </div>
        <div className="rounded-[20px] border border-border bg-[color:var(--surface-muted)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">累计 SpentV</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatSpentVInteger(total)}</div>
        </div>
        <div className="rounded-[20px] border border-border bg-[color:var(--surface-muted)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">峰值分钟</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatSpentVInteger(peak)}</div>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="min-w-[780px]">
          <div className="surface-chart flex h-64 items-end gap-2 rounded-[28px] border border-border px-4 pb-4 pt-6">
            {chartItems.map((item) => {
              const height = peak > 0 ? Math.max(8, (item.value / peak) * 180) : 8;
              return (
                <div key={item.key} className="flex flex-1 flex-col items-center justify-end gap-2">
                  <div className="text-[10px] text-muted-foreground">{formatInteger(Math.round(item.value))}</div>
                  <div
                    className="w-full rounded-t-[10px] bg-[linear-gradient(180deg,#77b9af_0%,#248e93_100%)] shadow-[0_10px_28px_rgba(36,142,147,0.18)]"
                    style={{ height }}
                    title={`${formatDateTime(item.key)} / ${formatSpentVInteger(item.value)}`}
                  />
                </div>
              );
            })}
          </div>
          <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
            <span>{formatShortDateTime(chartItems[0]?.key)}</span>
            <span>{formatShortDateTime(chartItems[chartItems.length - 1]?.key)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function BoardTable({
  rows,
  emptyTitle,
  emptyDescription,
}: {
  rows: BoardRow[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  if (!rows.length) {
    return <EmptyState compact title={emptyTitle} description={emptyDescription} />;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>钱包地址</TableHead>
          <TableHead>累计花费 V</TableHead>
          <TableHead>累计代币数量（万）</TableHead>
          <TableHead>买入市值（万 USD）</TableHead>
          <TableHead>更新时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          return (
            <TableRow key={row.wallet}>
              <TableCell>
                <div className="space-y-1">
                  {row.name ? <div className="text-sm font-medium">{row.name}</div> : null}
                  <div className="font-mono text-xs text-muted-foreground">{row.wallet}</div>
                </div>
              </TableCell>
              <TableCell>{formatSpentVInteger(row.spentV)}</TableCell>
              <TableCell>{formatDecimal(tokenWan(row.tokenBought), 2)}</TableCell>
              <TableCell>{formatBreakevenFdvUsd(row.breakevenFdvUsd)}</TableCell>
              <TableCell>{row.updatedAt ? formatDateTime(row.updatedAt) : "-"}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function toBoardRows(items: OverviewBoardItem[]) {
  return items.map((item) => ({
    wallet: item.wallet,
    name: item.name || undefined,
    spentV: toNumber(item.spentV),
    tokenBought: toNumber(item.tokenBought),
    breakevenFdvUsd:
      item.breakevenFdvUsd === null || item.breakevenFdvUsd === undefined
        ? null
        : toNumber(item.breakevenFdvUsd),
    updatedAt: item.updatedAt,
  }));
}

export function ProjectOverviewSections({
  item,
  minutes,
  whaleBoard,
  trackedWallets,
  delays,
  actions,
}: {
  item: OverviewActiveProjectItem;
  minutes: MinuteRow[];
  whaleBoard: OverviewBoardItem[];
  trackedWallets: OverviewBoardItem[];
  delays: EventDelayRow[];
  actions?: ReactNode;
}) {
  const whaleRows = toBoardRows(whaleBoard);
  const trackedWalletRows = toBoardRows(trackedWallets);
  const tokenPriceV =
    item.tokenPriceV === null || item.tokenPriceV === undefined ? null : toNumber(item.tokenPriceV);
  const tokenPriceUsd =
    item.tokenPriceUsd === null || item.tokenPriceUsd === undefined ? null : toNumber(item.tokenPriceUsd);
  const liveFdvUsd =
    item.liveFdvUsd === null || item.liveFdvUsd === undefined ? null : toNumber(item.liveFdvUsd);
  const buyTaxRate =
    item.buyTaxRate === null || item.buyTaxRate === undefined ? null : toNumber(item.buyTaxRate);
  const rawEstimatedFdvWanUsdWithTax =
    item.estimatedFdvWanUsdWithTax !== null && item.estimatedFdvWanUsdWithTax !== undefined
      ? toNumber(item.estimatedFdvWanUsdWithTax)
      : item.estimatedFdvUsdWithTax !== null && item.estimatedFdvUsdWithTax !== undefined
        ? toNumber(item.estimatedFdvUsdWithTax) / 10000
        : null;
  const [taxFdvSimulation, setTaxFdvSimulation] = useState<number | null>(
    () => getLocalTaxFdvSimulationScenario()?.start ?? null,
  );
  const estimatedFdvWanUsdWithTax = taxFdvSimulation ?? rawEstimatedFdvWanUsdWithTax;
  const priceLabel = marketBaseLabel(item);
  const marketMeta = formatMarketMeta(item);
  const hasTaxAdjustedFdv =
    estimatedFdvWanUsdWithTax !== null && Number.isFinite(estimatedFdvWanUsdWithTax);
  const taxFdvBucket = hasTaxAdjustedFdv ? Math.floor(estimatedFdvWanUsdWithTax / 10) : null;
  const [taxFdvGlow, setTaxFdvGlow] = useState<"up" | "down" | null>(null);
  const previousTaxFdvBucketRef = useRef<number | null>(null);
  const suppressNextTaxFdvGlowRef = useRef(false);
  const triggerGlowTimeoutRef = useRef<number | null>(null);
  const clearGlowTimeoutRef = useRef<number | null>(null);
  const showTaxFdvGlow = (direction: "up" | "down") => {
    if (triggerGlowTimeoutRef.current !== null) window.clearTimeout(triggerGlowTimeoutRef.current);
    if (clearGlowTimeoutRef.current !== null) window.clearTimeout(clearGlowTimeoutRef.current);

    setTaxFdvGlow(null);
    triggerGlowTimeoutRef.current = window.setTimeout(() => {
      setTaxFdvGlow(direction);
      clearGlowTimeoutRef.current = window.setTimeout(() => setTaxFdvGlow(null), TAX_FDV_GLOW_MS);
    }, 20);
  };

  useEffect(() => {
    const scenario = getLocalTaxFdvSimulationScenario();
    if (!scenario) return undefined;

    let stepTimeout: number | null = null;
    const replaySimulation = () => {
      if (stepTimeout !== null) window.clearTimeout(stepTimeout);
      if (triggerGlowTimeoutRef.current !== null) window.clearTimeout(triggerGlowTimeoutRef.current);
      if (clearGlowTimeoutRef.current !== null) window.clearTimeout(clearGlowTimeoutRef.current);

      const startBucket = Math.floor(scenario.start / 10);
      const previousBucket = previousTaxFdvBucketRef.current;
      suppressNextTaxFdvGlowRef.current = previousBucket !== null && previousBucket !== startBucket;
      setTaxFdvGlow(null);
      setTaxFdvSimulation(scenario.start);
      stepTimeout = window.setTimeout(() => {
        suppressNextTaxFdvGlowRef.current = true;
        setTaxFdvSimulation(scenario.end);
        showTaxFdvGlow(scenario.end > scenario.start ? "up" : "down");
      }, LOCAL_TAX_FDV_SIM_START_HOLD_MS);
    };

    const startTimeout = window.setTimeout(replaySimulation, 500);
    const loopInterval = window.setInterval(replaySimulation, LOCAL_TAX_FDV_SIM_REPLAY_MS);
    return () => {
      window.clearTimeout(startTimeout);
      if (stepTimeout !== null) window.clearTimeout(stepTimeout);
      window.clearInterval(loopInterval);
    };
  }, []);

  useEffect(() => {
    if (taxFdvBucket === null) {
      previousTaxFdvBucketRef.current = null;
      return;
    }

    const previousBucket = previousTaxFdvBucketRef.current;
    previousTaxFdvBucketRef.current = taxFdvBucket;
    if (suppressNextTaxFdvGlowRef.current) {
      suppressNextTaxFdvGlowRef.current = false;
      return;
    }
    if (previousBucket === null || previousBucket === taxFdvBucket) return;

    const direction = taxFdvBucket > previousBucket ? "up" : "down";
    showTaxFdvGlow(direction);
  }, [taxFdvBucket]);

  useEffect(() => {
    return () => {
      if (triggerGlowTimeoutRef.current !== null) window.clearTimeout(triggerGlowTimeoutRef.current);
      if (clearGlowTimeoutRef.current !== null) window.clearTimeout(clearGlowTimeoutRef.current);
    };
  }, []);

  return (
    <>
      <section className="surface-hero overflow-hidden rounded-[32px] border border-white/60 p-6">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-3xl font-semibold tracking-[-0.05em]">{item.name}</h2>
              <Badge variant={projectStatusVariant(item.projectedStatus || item.status)}>
                {projectStatusLabel(item.projectedStatus || item.status)}
              </Badge>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            {item.detailUrl ? (
              <Button asChild variant="outline">
                <a href={item.detailUrl} target="_blank" rel="noreferrer">
                  项目详情
                  <ExternalLink className="size-4" />
                </a>
              </Button>
            ) : null}
            {actions}
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">开始时间</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(item.startAt)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">结束时间</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(item.resolvedEndAt)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">代币地址</div>
            <div className="mt-2 font-mono text-sm">{formatAddress(item.tokenAddr, 8)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">内盘地址</div>
            <div className="mt-2 font-mono text-sm">{formatAddress(item.internalPoolAddr, 8)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4 md:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">项目详情链接</div>
            <div className="mt-2 truncate text-sm">
              {item.detailUrl ? (
                <a className="text-primary hover:underline" href={item.detailUrl} target="_blank" rel="noreferrer">
                  {item.detailUrl}
                </a>
              ) : (
                "未填写"
              )}
            </div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4 xl:col-span-2">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前项目累计税收</div>
            <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">{formatCurrency(item.sumTaxV)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{priceLabel}（USD）</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatLiveTokenPriceUsd(tokenPriceUsd)}</div>
            {marketMeta ? <div className="mt-2 text-xs text-muted-foreground">{marketMeta}</div> : null}
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{priceLabel}（V）</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatLiveTokenPriceV(tokenPriceV)}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{marketFdvLabel(item)}</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatLiveFdvUsd(liveFdvUsd)}</div>
          </div>
          <div
            className="tax-fdv-card min-h-[150px] rounded-[22px] border border-primary/35 bg-[color:var(--surface-soft)] px-4 py-4"
            data-testid="tax-fdv-card"
            data-glow={taxFdvGlow ?? undefined}
          >
            <div className="relative z-10 flex h-full flex-col justify-between gap-4">
              <div className="flex items-start justify-between gap-3">
                <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  含税估算 FDV（万 USD）
                </div>
                {buyTaxRate !== null ? <Badge variant="warning">Tax Rate {formatBuyTaxRate(buyTaxRate)}</Badge> : null}
              </div>
              <div>
                <div className="text-3xl font-semibold tracking-[-0.04em]">
                  {hasTaxAdjustedFdv ? formatWanUsd(estimatedFdvWanUsdWithTax) : "-"}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {hasTaxAdjustedFdv ? `按${priceLabel}与当前税率折算` : "等待价格与税率数据"}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <SectionCard
        title="分钟消耗 SpentV"
        description={`默认时间窗口 ${formatDateTime(item.chartFromAt)} 至 ${formatDateTime(item.chartToAt)}`}
      >
        <MinuteBars items={minutes} />
      </SectionCard>

      <SectionCard title="大户榜单">
        <BoardTable
          rows={whaleRows}
          emptyTitle="当前还没有大户数据"
          emptyDescription="项目在这个时间窗口内还没有形成可展示的大户榜。"
        />
      </SectionCard>

      <SectionCard title="追踪钱包持仓">
        <BoardTable
          rows={trackedWalletRows}
          emptyTitle="当前还没有追踪钱包"
          emptyDescription="先去“我的钱包”添加地址和名称，之后这里就能直接看到自己有没有进场。"
        />
      </SectionCard>

      <details className="group rounded-[28px] border border-border bg-[color:var(--surface-soft)] px-6 py-5 shadow-sm">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
          <div>
            <div className="text-lg font-semibold tracking-[-0.03em]">交易录入延迟</div>
            <div className="mt-1 text-sm text-muted-foreground">默认折叠。</div>
          </div>
          <Badge variant="secondary" className="group-open:hidden">
            点击展开
          </Badge>
          <Badge variant="secondary" className="hidden group-open:inline-flex">
            已展开
          </Badge>
        </summary>

        <div className="mt-5">
          {delays.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>交易</TableHead>
                  <TableHead>区块时间</TableHead>
                  <TableHead>记录时间</TableHead>
                  <TableHead>延迟</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {delays.map((row) => (
                  <TableRow key={row.tx_hash}>
                    <TableCell className="font-mono text-xs">{row.tx_hash}</TableCell>
                    <TableCell>{formatDateTime(row.block_timestamp)}</TableCell>
                    <TableCell>{formatDateTime(row.recorded_at)}</TableCell>
                    <TableCell>{formatDecimal(row.delay_sec, 1)} 秒</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              compact
              title="当前没有延迟样本"
              description="这个项目在当前窗口里还没有形成录入延迟样本。"
            />
          )}
        </div>
      </details>
    </>
  );
}
