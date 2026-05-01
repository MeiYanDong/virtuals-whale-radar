import { ExternalLink, Info } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { EmptyState, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatAddress,
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
  breakevenFdvV: number | null;
  breakevenFdvUsd: number | null;
  isTeamCandidate: boolean;
  costExcluded: boolean;
  costExclusionReason?: string | null;
  updatedAt: number;
};

function toNumber(value: number | string | null | undefined) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toOptionalNumber(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
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

function formatVPair(value: number | null, total: number | null) {
  if (value === null || total === null || !Number.isFinite(value) || !Number.isFinite(total) || total <= 0) {
    return "-";
  }
  return `${formatInteger(Math.round(value))}/${formatInteger(Math.round(total))}`;
}

function formatBuyTaxRate(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return `${formatDecimal(value, 0)}%`;
}

function taxEvidenceLabel(item: OverviewActiveProjectItem, buyTaxRate: number | null) {
  const observed = toOptionalNumber(item.observedBuyTaxRate);
  const predicted = toOptionalNumber(item.predictedBuyTaxRate);
  const age = toOptionalNumber(item.observedBuyTaxAgeSec);
  const suffix = age !== null ? ` · ${formatInteger(Math.round(age))}s 前` : "";
  switch (item.taxEvidenceStatus) {
    case "chain_override":
      return `链上实测覆盖官网预测：${formatBuyTaxRate(observed)}（预测 ${formatBuyTaxRate(predicted)}）${suffix}`;
    case "chain_confirmed":
      return `链上实测已确认：${formatBuyTaxRate(observed)}${suffix}`;
    case "chain_observed":
      return `链上实测税率：${formatBuyTaxRate(observed)}${suffix}`;
    case "chain_stale":
      return `官网预测税率 ${formatBuyTaxRate(buyTaxRate)}，最近链上实测 ${formatBuyTaxRate(observed)} 已过期${suffix}`;
    case "chain_stale_no_prediction":
      return `最近链上实测 ${formatBuyTaxRate(observed)} 已过期${suffix}`;
    case "api_only":
      return `官网预测税率：${formatBuyTaxRate(buyTaxRate)}`;
    case "unknown_bonding_v5_anti_sniper_type":
      return item.taxConfigWarning || "发现未知 anti-sniper 类型，先不预测税率，等待链上实测。";
    case "official_config_missing":
      return item.taxConfigWarning || "未拿到 Virtuals 官方税率配置，等待官网配置或链上实测。";
    default:
      if (item.taxConfigWarning) return item.taxConfigWarning;
      return buyTaxRate !== null ? `当前税率：${formatBuyTaxRate(buyTaxRate)}` : "等待税率证据";
  }
}

function taxRateBadgeLabel(item: OverviewActiveProjectItem, buyTaxRate: number | null) {
  if (buyTaxRate !== null) return `Tax Rate ${formatBuyTaxRate(buyTaxRate)}`;
  if (item.taxEvidenceStatus || item.taxConfigStatus) return "Tax Rate ?";
  return null;
}

function taxEvidenceBadgeVariant(item: OverviewActiveProjectItem): "success" | "danger" | "warning" {
  if (item.taxEvidenceStatus === "chain_override") return "danger";
  if (item.taxEvidenceStatus === "unknown_bonding_v5_anti_sniper_type") return "danger";
  if (item.taxEvidenceStatus === "chain_confirmed" || item.taxEvidenceStatus === "chain_observed") return "success";
  return "warning";
}

function InfoHint({ label }: { label: string }) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-label={label}
        className="inline-flex size-5 shrink-0 cursor-help items-center justify-center rounded-full text-muted-foreground transition hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
      >
        <Info className="size-3.5" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full z-50 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-[14px] border border-border bg-popover px-3 py-2 text-left text-xs font-normal leading-5 tracking-normal text-foreground opacity-0 shadow-[var(--shadow-soft)] transition duration-150 group-focus-within:opacity-100 group-hover:opacity-100 sm:w-80"
      >
        {label}
      </span>
    </span>
  );
}

function MetricLabel({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs uppercase tracking-[0.16em] text-muted-foreground">
      <span>{children}</span>
      {hint ? <InfoHint label={hint} /> : null}
    </div>
  );
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

function formatMarketMeta(item: OverviewActiveProjectItem) {
  const parts: string[] = [];
  if (item.priceUpdatedAt) parts.push(`更新 ${formatDateTime(item.priceUpdatedAt)}`);
  if (item.priceBlockNumber) parts.push(`区块 #${formatInteger(item.priceBlockNumber)}`);
  if (item.priceLatencyMs !== null && item.priceLatencyMs !== undefined) {
    parts.push(`${item.priceLatencyMs}ms`);
  }
  if (item.marketPriceStale) parts.push("VIRTUAL 美元价格源过期");
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
          <TableHead>含税成本 FDV（万 USD）</TableHead>
          <TableHead>更新时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          return (
            <TableRow key={row.wallet}>
              <TableCell>
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {row.name ? <div className="text-sm font-medium">{row.name}</div> : null}
                    {row.costExcluded ? (
                      <Badge
                        variant="warning"
                        className="shrink-0 px-2 py-0.5 text-[11px] font-semibold tracking-normal"
                      >
                        疑似团队
                      </Badge>
                    ) : null}
                  </div>
                  <div className="font-mono text-xs text-muted-foreground">{row.wallet}</div>
                  {row.costExcluded ? (
                    <div className="max-w-xl text-xs leading-5 text-muted-foreground">
                      已排除成本位：{row.costExclusionReason || "开盘极早期的大额低成本买入。"}
                    </div>
                  ) : null}
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
    breakevenFdvV:
      item.breakevenFdvV === null || item.breakevenFdvV === undefined ? null : toNumber(item.breakevenFdvV),
    breakevenFdvUsd:
      item.breakevenFdvUsd === null || item.breakevenFdvUsd === undefined
        ? null
        : toNumber(item.breakevenFdvUsd),
    isTeamCandidate: Boolean(item.isTeamCandidate),
    costExcluded: Boolean(item.costExcluded),
    costExclusionReason: item.costExclusionReason ?? null,
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
  const tokenPriceUsd =
    item.tokenPriceUsd === null || item.tokenPriceUsd === undefined ? null : toNumber(item.tokenPriceUsd);
  const liveFdvUsd =
    item.liveFdvUsd === null || item.liveFdvUsd === undefined ? null : toNumber(item.liveFdvUsd);
  const virtualPriceUsd =
    item.virtualPriceUsd === null || item.virtualPriceUsd === undefined ? null : toNumber(item.virtualPriceUsd);
  const buyTaxRate =
    item.buyTaxRate === null || item.buyTaxRate === undefined ? null : toNumber(item.buyTaxRate);
  const taxEvidence = taxEvidenceLabel(item, buyTaxRate);
  const taxBadgeLabel = taxRateBadgeLabel(item, buyTaxRate);
  const launchModeLabel =
    item.launchModeLabel && item.launchMode !== "unknown" ? item.launchModeLabel : null;
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
  const taxEvidenceText =
    hasTaxAdjustedFdv || taxBadgeLabel || item.taxConfigWarning ? taxEvidence : "等待价格与税率数据";
  const comparisonFdvUsd = hasTaxAdjustedFdv
    ? estimatedFdvWanUsdWithTax * 10000
    : liveFdvUsd !== null && Number.isFinite(liveFdvUsd)
      ? liveFdvUsd
      : null;
  const comparisonFdvV =
    comparisonFdvUsd !== null && virtualPriceUsd !== null && virtualPriceUsd > 0
      ? comparisonFdvUsd / virtualPriceUsd
      : null;
  const comparisonLabel = hasTaxAdjustedFdv ? "含税估算 FDV" : "当前 FDV（不含税）";
  const rawWhaleSpentV = whaleRows.reduce((sum, row) => sum + row.spentV, 0);
  const comparableWhaleRows = whaleRows.filter(
    (row) =>
      row.spentV > 0 &&
      row.tokenBought > 0 &&
      row.breakevenFdvV !== null &&
      Number.isFinite(row.breakevenFdvV),
  );
  const costExcludedRows = comparableWhaleRows.filter((row) => row.costExcluded);
  const costMetricRows = comparableWhaleRows.filter((row) => !row.costExcluded);
  const totalComparableSpentV = costMetricRows.reduce((sum, row) => sum + row.spentV, 0);
  const totalComparableToken = costMetricRows.reduce((sum, row) => sum + row.tokenBought, 0);
  const weightedCostFdvV =
    totalComparableToken > 0
      ? costMetricRows.reduce((sum, row) => sum + (row.breakevenFdvV ?? 0) * row.tokenBought, 0) /
        totalComparableToken
      : null;
  const usdCostRows = costMetricRows.filter(
    (row) => row.breakevenFdvUsd !== null && Number.isFinite(row.breakevenFdvUsd),
  );
  const totalUsdCostToken = usdCostRows.reduce((sum, row) => sum + row.tokenBought, 0);
  const weightedCostFdvUsdFromRows =
    totalUsdCostToken > 0
      ? usdCostRows.reduce((sum, row) => sum + (row.breakevenFdvUsd ?? 0) * row.tokenBought, 0) /
        totalUsdCostToken
      : null;
  const weightedCostFdvWanUsd =
    weightedCostFdvV !== null && virtualPriceUsd !== null && virtualPriceUsd > 0
      ? (weightedCostFdvV * virtualPriceUsd) / 10000
      : weightedCostFdvUsdFromRows !== null && weightedCostFdvUsdFromRows > 0
        ? weightedCostFdvUsdFromRows / 10000
        : null;
  const belowCostRows =
    comparisonFdvV !== null
      ? costMetricRows.filter((row) => (row.breakevenFdvV ?? 0) < comparisonFdvV)
      : [];
  const costPosition =
    comparisonFdvV !== null && costMetricRows.length
      ? `${Math.min(belowCostRows.length + 1, costMetricRows.length)}/${costMetricRows.length}`
      : "-";
  const belowCostSpentV = belowCostRows.reduce((sum, row) => sum + row.spentV, 0);
  const excludedSpentV = costExcludedRows.reduce((sum, row) => sum + row.spentV, 0);
  const costPositionHint =
    comparisonFdvV !== null && costMetricRows.length
      ? `仅有 ${formatInteger(belowCostRows.length)} 名榜单大户的买入成本低于当前${comparisonLabel}，当前估值排在第 ${costPosition}。`
      : "等待榜单成本与当前估值数据。";
  const vCostPositionHint =
    comparisonFdvV !== null && totalComparableSpentV > 0
      ? `榜单里仅有 ${formatInteger(Math.round(belowCostSpentV))} V 的买入资金成本低于当前${comparisonLabel}，分母是参与成本位计算的榜单 V。`
      : "等待榜单成本与当前估值数据。";
  const vCostPosition = comparisonFdvV !== null ? formatVPair(belowCostSpentV, totalComparableSpentV) : "-";
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
              {launchModeLabel ? <Badge variant="secondary">{launchModeLabel}</Badge> : null}
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
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前项目累计税收（V）</div>
            <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">{formatSpentVInteger(toNumber(item.sumTaxV))}</div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
            <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{priceLabel}（USD）</div>
            <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatLiveTokenPriceUsd(tokenPriceUsd)}</div>
            <div className="mt-4 border-t border-border/60 pt-3">
              <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">当前 FDV（不含税，万 USD）</div>
              <div className="mt-1 text-lg font-semibold tracking-[-0.03em]">{formatLiveFdvUsd(liveFdvUsd)}</div>
            </div>
            {marketMeta ? <div className="mt-2 text-xs text-muted-foreground">{marketMeta}</div> : null}
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
                {taxBadgeLabel ? (
                  <Badge variant={taxEvidenceBadgeVariant(item)}>
                    {taxBadgeLabel}
                  </Badge>
                ) : null}
              </div>
              <div>
                <div className="text-3xl font-semibold tracking-[-0.04em]">
                  {hasTaxAdjustedFdv ? formatWanUsd(estimatedFdvWanUsdWithTax) : "-"}
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {taxEvidenceText}
                </div>
              </div>
            </div>
          </div>
          <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4 xl:col-span-2">
            <div className="flex items-start justify-between gap-3">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">打新成本位</div>
              <Badge variant="secondary">对比 {comparisonLabel}</Badge>
            </div>
            <div className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <div>
                <MetricLabel>榜单 V</MetricLabel>
                <div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">
                  {formatSpentVInteger(totalComparableSpentV)}
                </div>
                {costExcludedRows.length ? (
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    已排除 {costExcludedRows.length} 个疑似团队地址（{formatSpentVInteger(excludedSpentV)}），原始榜单{" "}
                    {formatSpentVInteger(rawWhaleSpentV)}
                  </div>
                ) : null}
              </div>
              <div>
                <MetricLabel hint="不是当前市值。这里用榜单大户实际总支出 V 除以扣税后到手代币数量，再乘以总供应量，反推这批大户的含税回本 FDV；展示时按当前 VIRTUAL 美元价格折算为万 USD。">
                  榜单含税成本
                </MetricLabel>
                <div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">
                  {formatWanUsd(weightedCostFdvWanUsd)}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">万 USD</div>
              </div>
              <div>
                <MetricLabel hint={costPositionHint}>成本位</MetricLabel>
                <div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{costPosition}</div>
              </div>
              <div>
                <MetricLabel hint={vCostPositionHint}>V 成本位</MetricLabel>
                <div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{vCostPosition}</div>
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
