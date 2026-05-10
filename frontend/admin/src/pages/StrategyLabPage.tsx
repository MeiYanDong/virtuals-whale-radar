import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  FileJson2,
  FlaskConical,
  RefreshCcw,
  ShieldCheck,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatDecimal, formatInteger } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  StrategyLabReportResponse,
  StrategyLabResultItem,
  StrategyLabStableZoneItem,
  StrategyLabSuiteSummary,
  StrategyLabVariableContributionItem,
} from "@/types/api";

function asNumber(value: number | string | null | undefined) {
  const num = Number(value ?? 0);
  return Number.isFinite(num) ? num : 0;
}

function pct(value: number | string | null | undefined) {
  const text = formatDecimal(value, 2);
  return text === "-" ? text : `${text}%`;
}

function formatV(value: number | string | null | undefined) {
  return `${formatDecimal(value, 0)} V`;
}

function formatWanUsd(value: number | string | null | undefined) {
  return `${formatDecimal(value, 2)} 万 USD`;
}

function formatSec(value: number | string | null | undefined) {
  const seconds = asNumber(value);
  if (seconds <= 0) return "无";
  if (seconds % 60 === 0) return `${formatInteger(seconds / 60)} 分钟`;
  return `${formatInteger(seconds)} 秒`;
}

function pnlTone(value: number | string | null | undefined) {
  const num = asNumber(value);
  if (num > 30) return "text-[color:var(--success-foreground)]";
  if (num < 0) return "text-[color:var(--danger-foreground)]";
  return "text-foreground";
}

function badgeForPnl(value: number | string | null | undefined) {
  const num = asNumber(value);
  if (num > 30) return "success";
  if (num < 0) return "danger";
  return "secondary";
}

function decisionLabel(item: StrategyLabResultItem) {
  const pnl = asNumber(item.finalPnlPct);
  const riskCount = item.riskFlags?.length ?? 0;
  if (!item.buyCount) return "未触发";
  if (pnl <= 0) return "拒绝";
  if (riskCount > 0) return "仅供对照";
  if (pnl >= 30) return "可观察";
  return "谨慎观察";
}

function decisionVariant(item: StrategyLabResultItem) {
  const label = decisionLabel(item);
  if (label === "可观察") return "success";
  if (label === "拒绝") return "danger";
  if (label === "仅供对照" || label === "谨慎观察") return "warning";
  return "secondary";
}

function flagLabel(flag: string) {
  const labels: Record<string, string> = {
    no_fdv_cost_guard: "没有使用榜单成本保护",
    no_board_spent_guard: "没有限制榜单 V 门槛",
    no_tax_guard: "没有使用税率门槛",
    large_project_budget: "单项目预算偏大",
    low_sample_first_buy: "首次买入样本偏少",
    high_slippage: "滑点压力较高",
    high_latency: "延迟压力较高",
    tax_signal_risk: "税率信号异常",
    early_board_spent: "过早依赖榜单资金",
  };
  return labels[flag] ?? "未归类风险";
}

function suiteLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    ablation: "消融对照",
    control: "基础对照",
    dry_run_candidates: "观察候选",
    combo_burst_x_cooldown: "连买限制与冷却组合",
    combo_cooldown_x_max_spend: "冷却与预算组合",
    combo_min_rows_x_spent: "有效成本地址与榜单 V 组合",
    combo_spent_x_fdv: "榜单 V 与成本保护组合",
    combo_spent_x_tax: "榜单 V 与税率组合",
    combo_spent_x_tax_no_fdv: "无成本保护组合",
    combo_spent_x_tax_x_fdv: "榜单 V、税率、成本保护组合",
    combo_tax_x_fdv: "税率与成本保护组合",
    single_burst_gradient: "连买限制梯度",
    single_cooldown_gradient: "冷却时间梯度",
    single_fdv_discount_gradient: "成本保护折扣梯度",
    single_max_spend_gradient: "预算上限梯度",
    single_min_rows_gradient: "有效成本地址数梯度",
    single_spent_gradient: "榜单 V 门槛梯度",
    single_tax_gradient: "税率门槛梯度",
  };
  const key = String(value ?? "").trim();
  return labels[key] ?? "其他测试组";
}

function datasetLabel(value: string | null | undefined) {
  const text = String(value ?? "").toLowerCase();
  if (text.startsWith("sr_")) return text.includes("highres") ? "SR 高精度回放" : "SR 完整窗口";
  if (text.startsWith("isc_")) return "ISC 十分钟窗口";
  if (text.startsWith("tds_")) return "TDS 完整窗口";
  return "历史回放数据";
}

function scenarioLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    actual: "真实走势",
    price_up_50pct: "价格上行 50%",
    late_dump_50pct: "后段下跌 50%",
    tax_offset_minus2: "税率读数低 2 点",
    tax_offset_plus2: "税率读数高 2 点",
    tax_missing: "税率缺失",
    delayed_decision_5s: "决策延迟 5 秒",
    delayed_decision_10s: "决策延迟 10 秒",
    delayed_entry_5s: "成交延迟 5 秒",
    entry_slippage_2pct: "成交滑点 2%",
    sparse_samples_5s: "5 秒采样",
    sparse_samples_10s: "10 秒采样",
  };
  const key = String(value ?? "").trim();
  if (!key) return "未命名场景";
  return labels[key] ?? key.replaceAll("_", " ");
}

function scenarioCategoryLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    actual: "真实数据",
    price_shape: "价格压力",
    tax_anomaly: "税率异常",
    latency: "延迟压力",
    sampling: "采样压力",
    execution: "成交压力",
  };
  const key = String(value ?? "").trim();
  return labels[key] ?? "压力场景";
}

function ruleTone(item: StrategyLabResultItem) {
  const name = String(item.ruleName ?? "").toLowerCase();
  if (name.includes("aggressive")) return "激进";
  if (name.includes("conservative")) return "保守";
  if (name.includes("mid")) return "均衡";
  if (name.includes("control") || name.includes("only_")) return "对照";
  return "策略";
}

function getRule(item: StrategyLabResultItem) {
  return item.rule ?? {};
}

function ruleConditions(item: StrategyLabResultItem) {
  const rule = getRule(item);
  const parts = [];
  if (rule.spentThresholdV) parts.push(`榜单累计投入 ≥ ${formatV(rule.spentThresholdV)}`);
  else parts.push("不限制榜单 V");

  parts.push(`榜单人数 ≥ ${formatInteger(rule.minWhaleRows ?? 20)}`);

  if (rule.maxTaxRate) parts.push(`税率 ≤ ${formatDecimal(rule.maxTaxRate, 0)}%`);
  else parts.push("不看税率");

  if (rule.fdvDiscount) {
    const discount = asNumber(rule.fdvDiscount);
    const suffix = discount === 1 ? "榜单成本" : `榜单成本 × ${formatDecimal(discount, 2)}`;
    parts.push(`含税估算 FDV ≤ ${suffix}`);
  } else {
    parts.push("不使用成本保护");
  }

  const minCostRows = rule.minCostRows ?? rule.minRows;
  if (minCostRows && Number(minCostRows) > 0) parts.push(`有效成本地址 ≥ ${formatInteger(minCostRows)}`);
  return parts;
}

function executionRules(item: StrategyLabResultItem) {
  const rule = getRule(item);
  return [
    `每次买入 ${formatV(rule.buySizeV ?? 50)}`,
    `普通冷却 ${formatSec(rule.cooldownSec ?? 60)}`,
    `项目上限 ${formatV(rule.maxProjectSpendV ?? 300)}`,
    rule.burstLimit
      ? `${formatSec(rule.burstWindowSec ?? 120)} 内连续 ${formatInteger(rule.burstLimit)} 次后冷却 ${formatSec(rule.burstCooldownSec ?? 600)}`
      : "不限制连续买入",
  ];
}

function firstBuyFacts(item: StrategyLabResultItem) {
  const first = item.firstBuy;
  if (!first) return ["没有触发买入"];
  return [
    first.tax_rate ? `触发税率 ${formatDecimal(first.tax_rate, 0)}%` : null,
    first.board_spent_v ? `榜单 V ${formatV(first.board_spent_v)}` : null,
    first.entry_tax_fdv_wan_usd ? `买入参考 FDV ${formatWanUsd(first.entry_tax_fdv_wan_usd)}` : null,
    first.board_cost_wan_usd ? `榜单成本 ${formatWanUsd(first.board_cost_wan_usd)}` : null,
    first.cost_position ? `成本位 ${first.cost_position}` : null,
    first.v_cost_position ? `V 成本位 ${first.v_cost_position}` : null,
  ].filter(Boolean) as string[];
}

function technicalFacts(item: StrategyLabResultItem) {
  const first = item.firstBuy;
  if (!first) return [];
  return [
    first.entry_spot_fdv_wan_usd ? `当刻池子 FDV（不含税）${formatWanUsd(first.entry_spot_fdv_wan_usd)}` : null,
    item.worstDrawdownPct ? `旧回测最小值字段 ${pct(item.worstDrawdownPct)}（不作为用户回撤指标）` : null,
    `规则 ${item.ruleName}`,
    `场景 ${item.scenarioName}`,
    `数据 ${item.dataset}`,
  ].filter(Boolean) as string[];
}

function firstBuyTime(item: StrategyLabResultItem) {
  const timestamp = item.firstBuy?.entry_timestamp ?? item.firstBuy?.trigger_timestamp ?? item.firstBuy?.signal_timestamp;
  return timestamp ? formatDateTime(timestamp) : "未触发";
}

function resultConclusion(item: StrategyLabResultItem) {
  const pnl = asNumber(item.finalPnlPct);
  const risks = item.riskFlags ?? [];
  if (!item.buyCount) return "未触发买入，只能作为未成交样本参考。";
  if (risks.length) return "有收益但存在保护缺口，不能直接进入自动交易。";
  if (pnl > 30) return "收益表现较好，适合进入 dry-run 观察。";
  if (pnl > 0) return "收益为正，但优势不强，需要继续观察。";
  return "回放亏损，不建议进入候选。";
}

const SNAPSHOT_LABELS: Record<string, string> = {
  "1m": "1 分钟",
  "3m": "3 分钟",
  "5m": "5 分钟",
  "10m": "10 分钟",
  end: "窗口结束",
};

function snapshotRows(item: StrategyLabResultItem) {
  const snapshots = item.firstBuy?.return_snapshots_pct ?? item.avgReturnSnapshotsPct ?? {};
  return Object.entries(SNAPSHOT_LABELS)
    .map(([key, label]) => ({ key, label, value: snapshots[key] }))
    .filter((row) => row.value !== null && row.value !== undefined && row.value !== "");
}

function ValuationPath({ item }: { item: StrategyLabResultItem }) {
  const rows = snapshotRows(item);
  if (!rows.length) return null;
  return (
    <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">估值轨迹</div>
        <div className="text-xs text-muted-foreground">相对买入参考 FDV</div>
      </div>
      <div className="mt-3 grid grid-cols-5 gap-2">
        {rows.map((row) => (
          <div key={row.key} className="rounded-[14px] border border-border/70 bg-card/70 px-2 py-2 text-center">
            <div className="text-[11px] text-muted-foreground">{row.label}</div>
            <div className={cn("mt-1 text-sm font-semibold", pnlTone(row.value))}>{pct(row.value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RiskFlags({ flags }: { flags: string[] }) {
  if (!flags.length) {
    return <Badge variant="success">保护项齐全</Badge>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.slice(0, 4).map((flag) => (
        <Badge key={flag} variant={flag.includes("early") ? "warning" : "danger"}>
          {flagLabel(flag)}
        </Badge>
      ))}
      {flags.length > 4 ? <Badge variant="secondary">另有 {flags.length - 4} 项</Badge> : null}
    </div>
  );
}

function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  const toneClass =
    tone === "success"
      ? "border-[color:var(--success-soft)] bg-[color:var(--success-soft)]/35"
      : tone === "warning"
        ? "border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)]/35"
        : tone === "danger"
          ? "border-[color:var(--danger-soft)] bg-[color:var(--danger-soft)]/35"
          : "border-border/80 bg-card/95";
  return (
    <Card className={cn("overflow-hidden", toneClass)}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
              {label}
            </div>
            <div className="mt-3 text-3xl font-semibold">{value}</div>
          </div>
          <span className="flex size-10 items-center justify-center rounded-full bg-primary/10 text-primary">
            <Icon className="size-5" />
          </span>
        </div>
        <div className="mt-3 text-sm text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  );
}

function DecisionSummary({ item }: { item: StrategyLabResultItem | null }) {
  if (!item) return null;
  return (
    <section className="rounded-[28px] border border-[color:var(--success-soft)] bg-[color:var(--success-soft)]/20 p-5">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">当前最值得观察</div>
          <h2 className="mt-2 text-2xl font-semibold">
            {ruleTone(item)}策略：{ruleConditions(item).join(" / ")}
          </h2>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted-foreground">{resultConclusion(item)}</p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs">
            {firstBuyFacts(item).slice(0, 5).map((fact) => (
              <span key={fact} className="rounded-full border border-border/70 bg-card/80 px-3 py-1 text-muted-foreground">
                {fact}
              </span>
            ))}
          </div>
        </div>
        <div className="grid min-w-[300px] grid-cols-3 gap-3 text-center">
          <div className="rounded-[18px] border border-border/80 bg-card/80 p-3">
            <div className="text-xs text-muted-foreground">评级</div>
            <div className="mt-1 font-semibold">{decisionLabel(item)}</div>
          </div>
          <div className="rounded-[18px] border border-border/80 bg-card/80 p-3">
            <div className="text-xs text-muted-foreground">投入</div>
            <div className="mt-1 font-semibold">{formatV(item.totalSpentV)}</div>
          </div>
          <div className="rounded-[18px] border border-border/80 bg-card/80 p-3">
            <div className="text-xs text-muted-foreground">收益</div>
            <div className={cn("mt-1 font-semibold", pnlTone(item.finalPnlPct))}>{pct(item.finalPnlPct)}</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function NoCandidateSummary({ project }: { project: string }) {
  return (
    <section className="rounded-[28px] border border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)]/25 p-5">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-5 text-[color:var(--warning-foreground)]" />
        <div>
          <div className="text-sm font-semibold">{project ? `${project} 暂无可进入观察的策略` : "暂无可进入观察的策略"}</div>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-muted-foreground">
            当前筛选条件下没有通过 dry-run 候选门槛的真实走势策略。可以继续看“拒绝项”和“失败样本”，确认是收益不足、保护项缺失，还是该项目样本本身不适合这套规则。
          </p>
        </div>
      </div>
    </section>
  );
}

function ProjectFilterControls({
  current,
  onChange,
}: {
  current: string;
  onChange: (project: string) => void;
}) {
  const options = [
    { value: "", label: "全部" },
    { value: "SR", label: "SR" },
    { value: "ISC", label: "ISC" },
    { value: "TDS", label: "TDS" },
  ];
  return (
    <section className="rounded-[24px] border border-border/80 bg-card/85 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-sm font-semibold">回放项目</div>
          <div className="mt-1 text-sm text-muted-foreground">这里切换的是历史策略回放，不影响顶部的全局采集项目。</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button
              key={option.value || "all"}
              variant={(current || "") === option.value ? "default" : "outline"}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>
    </section>
  );
}

function MethodNote() {
  return (
    <section className="rounded-[24px] border border-border/80 bg-card/80 p-5">
      <div className="text-sm font-semibold">回测口径</div>
      <div className="mt-3 grid gap-3 text-sm text-muted-foreground md:grid-cols-3">
        <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
          <div className="font-medium text-foreground">买入判断</div>
          <p className="mt-1 leading-6">硬门槛先满足：榜单人数 20、榜单累计投入至少 50,000 V、税率降到 95% 或更低。</p>
        </div>
        <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
          <div className="font-medium text-foreground">成本保护</div>
          <p className="mt-1 leading-6">触发时再用含税估算 FDV 和榜单加权成本比较；有效成本地址是榜单中可用于成本计算、未被排除的地址。</p>
        </div>
        <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
          <div className="font-medium text-foreground">结算口径</div>
          <p className="mt-1 leading-6">用窗口结束后的当前 FDV 估算最终价值；这里只筛选 dry-run 观察候选，不代表自动买入开关已打开。</p>
        </div>
      </div>
    </section>
  );
}

function DatasetGrid({ report }: { report: StrategyLabReportResponse }) {
  const datasets = Object.entries(report.datasetStats ?? {});
  if (!datasets.length) return null;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {datasets.map(([name, stats]) => (
        <div key={name} className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] p-4">
          <div className="truncate text-sm font-semibold">{datasetLabel(name)}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground" title={name}>
            历史采样源
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">样本数</div>
              <div className="font-semibold">{formatInteger(stats.sampleCount)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">窗口时长</div>
              <div className="font-semibold">{formatSec(stats.durationSec)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">税率范围</div>
              <div className="font-semibold">
                {formatDecimal(stats.taxMin, 0)}%-{formatDecimal(stats.taxMax, 0)}%
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">最高榜单 V</div>
              <div className="font-semibold">{formatV(stats.boardSpentMaxV)}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function StrategyCards({
  items,
  emptyTitle,
  limit,
}: {
  items: StrategyLabResultItem[];
  emptyTitle: string;
  limit?: number;
}) {
  const visibleItems = typeof limit === "number" ? items.slice(0, limit) : items;
  if (!visibleItems.length) {
    return <EmptyState compact title={emptyTitle} description="当前报告没有对应记录。" />;
  }
  return (
    <div className="grid gap-4">
      {visibleItems.map((item, index) => (
        <article
          key={`${item.dataset}-${item.ruleName}-${item.scenarioName}-${index}`}
          className="rounded-[24px] border border-border/80 bg-card/90 p-4"
        >
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(280px,0.75fr)]">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={decisionVariant(item)}>{decisionLabel(item)}</Badge>
                <Badge variant={badgeForPnl(item.finalPnlPct)}>{ruleTone(item)}策略</Badge>
                <Badge variant="secondary">{suiteLabel(item.suite)}</Badge>
                <Badge variant="secondary">{scenarioCategoryLabel(item.scenarioCategory)}</Badge>
              </div>
              <h3 className="mt-3 text-lg font-semibold">{ruleConditions(item).join(" / ")}</h3>
              <div className="mt-3 flex flex-wrap gap-2">
                {executionRules(item).map((part) => (
                  <span
                    key={part}
                    className="rounded-full border border-border/70 bg-[color:var(--surface-soft)] px-3 py-1 text-xs text-muted-foreground"
                  >
                    {part}
                  </span>
                ))}
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">测试环境</div>
                  <div className="mt-1 font-semibold">{datasetLabel(item.dataset)} · {scenarioLabel(item.scenarioName)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">采样 {formatInteger(item.sampleCount)} 条</div>
                </div>
                <div className="rounded-[18px] bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">首次触发</div>
                  <div className="mt-1 font-semibold">{firstBuyTime(item)}</div>
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">
                    {firstBuyFacts(item).slice(0, 5).join(" · ")}
                  </div>
                </div>
              </div>
              <div className="mt-3">
                <ValuationPath item={item} />
              </div>
              <details className="mt-3 text-xs text-muted-foreground">
                <summary className="cursor-pointer select-none">技术标识</summary>
                <div className="mt-2 grid gap-1 break-all rounded-[16px] bg-[color:var(--surface-soft)] p-3">
                  {technicalFacts(item).map((fact) => (
                    <div key={fact}>{fact}</div>
                  ))}
                </div>
              </details>
            </div>

            <div className="grid gap-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-[18px] border border-border/80 bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">买入次数</div>
                  <div className="mt-1 text-xl font-semibold">{formatInteger(item.buyCount)}</div>
                </div>
                <div className="rounded-[18px] border border-border/80 bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">累计投入</div>
                  <div className="mt-1 text-xl font-semibold">{formatV(item.totalSpentV)}</div>
                </div>
                <div className="rounded-[18px] border border-border/80 bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">最终收益</div>
                  <div className={cn("mt-1 text-xl font-semibold", pnlTone(item.finalPnlPct))}>{pct(item.finalPnlPct)}</div>
                </div>
                <div className="rounded-[18px] border border-border/80 bg-[color:var(--surface-soft)] p-3">
                  <div className="text-xs text-muted-foreground">最终价值</div>
                  <div className="mt-1 text-xl font-semibold">{formatV(item.finalValueV)}</div>
                </div>
              </div>
              <div className="rounded-[18px] border border-border/80 bg-[color:var(--surface-soft)] p-3">
                <div className="text-xs text-muted-foreground">风险判断</div>
                <div className="mt-2">
                  <RiskFlags flags={item.riskFlags ?? []} />
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{resultConclusion(item)}</p>
              </div>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function StableZoneTable({ items }: { items: StrategyLabStableZoneItem[] }) {
  if (!items.length) {
    return (
      <div className="rounded-[20px] border border-border/70 bg-[color:var(--surface-soft)] p-4 text-sm text-muted-foreground">
        没有稳定区间。当前项目在硬门槛后没有足够触发样本形成稳定组合。
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>测试组</TableHead>
            <TableHead className="text-right">触发次数</TableHead>
            <TableHead className="text-right">正收益率</TableHead>
            <TableHead className="text-right">中位收益</TableHead>
            <TableHead className="text-right">最低收益</TableHead>
            <TableHead className="text-right">最高收益</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.suite}>
              <TableCell className="font-medium">{suiteLabel(item.suite)}</TableCell>
              <TableCell className="text-right">{formatInteger(item.triggered)}</TableCell>
              <TableCell className="text-right">{pct(Number(item.positiveRate) * 100)}</TableCell>
              <TableCell className="text-right">{pct(item.medianFinalPnlPct)}</TableCell>
              <TableCell className="text-right">{pct(item.minFinalPnlPct)}</TableCell>
              <TableCell className="text-right">{pct(item.maxFinalPnlPct)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function variableLabel(name: string) {
  const labels: Record<string, string> = {
    only_tax92: "只看税率 ≤ 92%",
    only_tax95: "只看税率 ≤ 95%",
    only_spent100k: "只看榜单 V ≥ 10 万",
    only_fdv: "只看含税 FDV 低于榜单成本",
    spent100k_plus_tax92: "榜单 V + 税率",
    spent100k_plus_fdv: "榜单 V + 成本保护",
    tax92_plus_fdv: "税率 + 成本保护",
    cancel_cooldown: "取消普通冷却",
    cancel_max_spend: "取消项目预算上限",
    cancel_min_rows: "取消有效成本地址数要求",
  };
  return labels[name] ?? name.replaceAll("_", " ");
}

function VariableContributionTable({
  items,
}: {
  items: Record<string, StrategyLabVariableContributionItem>;
}) {
  const rows = Object.entries(items);
  if (!rows.length) {
    return (
      <div className="rounded-[20px] border border-border/70 bg-[color:var(--surface-soft)] p-4 text-sm text-muted-foreground">
        没有变量贡献数据。当前筛选下没有通过硬门槛的触发样本。
      </div>
    );
  }
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>变量变化</TableHead>
            <TableHead className="text-right">最终收益</TableHead>
            <TableHead className="text-right">相对基准</TableHead>
            <TableHead className="text-right">买入次数</TableHead>
            <TableHead>风险解释</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([name, item]) => (
            <TableRow key={name}>
              <TableCell className="font-medium">{variableLabel(name)}</TableCell>
              <TableCell className={cn("text-right font-semibold", pnlTone(item.finalPnlPct))}>
                {pct(item.finalPnlPct)}
              </TableCell>
              <TableCell className={cn("text-right", pnlTone(item.deltaVsBaselinePct))}>
                {pct(item.deltaVsBaselinePct)}
              </TableCell>
              <TableCell className="text-right">{formatInteger(item.buyCount)}</TableCell>
              <TableCell>
                <RiskFlags flags={item.riskFlags ?? []} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function SuiteSummaryList({ items }: { items: Record<string, StrategyLabSuiteSummary> }) {
  const rows = Object.entries(items).sort(([, a], [, b]) => b.medianFinalPnlPct - a.medianFinalPnlPct);
  if (!rows.length) {
    return (
      <div className="rounded-[20px] border border-border/70 bg-[color:var(--surface-soft)] p-4 text-sm text-muted-foreground">
        没有测试组汇总。当前项目没有任何策略在硬门槛后触发。
      </div>
    );
  }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {rows.slice(0, 10).map(([name, item]) => (
        <div key={name} className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="truncate text-sm font-semibold">{suiteLabel(name)}</div>
            <Badge variant={item.positiveRate >= 0.9 ? "success" : item.positiveRate >= 0.75 ? "warning" : "secondary"}>
              正收益 {pct(item.positiveRate * 100)}
            </Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-sm text-muted-foreground xl:grid-cols-4">
            <span>触发 {formatInteger(item.triggered)}</span>
            <span>中位 {pct(item.medianFinalPnlPct)}</span>
            <span>最低 {pct(item.minFinalPnlPct)}</span>
            <span>最高 {pct(item.maxFinalPnlPct)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export function StrategyLabPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const projectFilter = String(searchParams.get("project") || "").trim().toUpperCase();
  const updateProjectFilter = (project: string) => {
    const next = new URLSearchParams(searchParams);
    if (project) next.set("project", project);
    else next.delete("project");
    setSearchParams(next);
  };
  const reportQuery = useQuery({
    queryKey: queryKeys.strategyLabReport(projectFilter),
    queryFn: () => dashboardApi.admin.getStrategyLabReport(projectFilter),
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: true,
    refetchOnReconnect: true,
    refetchInterval: 15000,
  });

  const bestActualCandidate = useMemo(() => {
    const candidates = reportQuery.data?.dryRunCandidates ?? [];
    return candidates.find((item) => item.scenarioName === "actual") ?? candidates[0] ?? null;
  }, [reportQuery.data?.dryRunCandidates]);

  if (reportQuery.isLoading) {
    return <LoadingState label="正在加载策略审查报告..." />;
  }

  const report = reportQuery.data;
  if (!report?.available) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Strategy Lab"
          title="策略实验室"
          description="只读展示离线 replay 测试结果。"
          actions={
            <Button variant="outline" onClick={() => void reportQuery.refetch()}>
              <RefreshCcw className="size-4" />
              刷新
            </Button>
          }
        />
        <EmptyState
          title="未找到策略报告"
          description={report?.message || "服务器还没有生成 strategy-test-matrix JSON 报告。"}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Strategy Lab"
        title="策略实验室"
        description={
          projectFilter
            ? `当前只看 ${projectFilter} 的历史发射回放，不混入其他项目。`
            : "把 SR / ISC / TDS 的历史发射数据回放成买入策略审查，不直接展示内部原始字段。"
        }
        actions={
          <Button variant="outline" onClick={() => void reportQuery.refetch()} disabled={reportQuery.isFetching}>
            <RefreshCcw className={cn("size-4", reportQuery.isFetching && "animate-spin")} />
            刷新
          </Button>
        }
      />

      <ProjectFilterControls current={projectFilter} onChange={updateProjectFilter} />

      {projectFilter ? (
        <div className="rounded-[20px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-3 text-sm text-muted-foreground">
          当前筛选：<span className="font-semibold text-foreground">{projectFilter}</span>。指标、候选、拒绝项和稳定区间均按当前项目重新计算。
        </div>
      ) : null}

      {bestActualCandidate ? (
        <DecisionSummary item={bestActualCandidate} />
      ) : (
        <NoCandidateSummary project={projectFilter} />
      )}
      <MethodNote />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricTile label="测试规则" value={formatInteger(report.ruleCount)} hint="不同买入条件组合" icon={FlaskConical} />
        <MetricTile label="压力场景" value={formatInteger(report.scenarioCount)} hint="延迟、税率、价格走势等" icon={ShieldCheck} />
        <MetricTile label="回放结果" value={formatInteger(report.resultCount)} hint="规则 × 场景的总样本" icon={FileJson2} />
        <MetricTile
          label="观察候选"
          value={formatInteger(report.dryRunCandidates.length)}
          hint="可进入 dry-run 观察"
          icon={CheckCircle2}
          tone="success"
        />
        <MetricTile
          label="拒绝项"
          value={formatInteger(report.rejectList.length)}
          hint="收益或保护条件不合格"
          icon={AlertTriangle}
          tone="warning"
        />
        <MetricTile
          label="报告时间"
          value={report.generatedAt ? formatDateTime(report.generatedAt).slice(5) : "-"}
          hint="本地离线报告"
          icon={TrendingUp}
        />
      </div>

      <SectionCard title="回放数据源" description="每个历史项目提供一段真实发射窗口，策略只在这些样本上复盘。">
        <DatasetGrid report={report} />
      </SectionCard>

      <SectionCard title="可进入观察的候选策略" description="这些策略不是自动交易结论，只代表可以进入 dry-run 做实时观察。">
        <StrategyCards items={report.dryRunCandidates} emptyTitle="没有候选策略" />
      </SectionCard>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <SectionCard title="风险调整后表现最好" description="包含真实场景和压力场景，用于看策略在不同假设下是否稳定。">
          <StrategyCards items={report.topByRiskAdjustedScore} emptyTitle="没有风险调整榜" limit={8} />
        </SectionCard>

        <SectionCard title="稳定区间" description="按测试组汇总，看哪类变量组合更稳。">
          <StableZoneTable items={report.stableZone} />
        </SectionCard>
      </div>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SectionCard title="变量贡献" description="逐个取消或替换条件，看哪个条件真正贡献了收益与风控。">
          <VariableContributionTable items={report.variableContribution} />
        </SectionCard>

        <SectionCard title="测试组汇总" description="按策略族群汇总触发次数、正收益比例和收益分布。">
          <SuiteSummaryList items={report.suiteSummary} />
        </SectionCard>
      </div>

      <SectionCard title="拒绝项" description="这些规则可能盈利，但缺少关键保护，不能直接进入交易候选。">
        <StrategyCards items={report.rejectList} emptyTitle="没有拒绝项" limit={10} />
      </SectionCard>

      <SectionCard title="失败样本" description="回放亏损或压力测试表现差的情况，用于找策略边界。">
        <StrategyCards items={report.failureCases} emptyTitle="没有失败样本" limit={8} />
      </SectionCard>

      {report.overfitWarnings.length ? (
        <div className="rounded-[24px] border border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)]/35 p-5">
          <div className="flex items-center gap-2 font-semibold text-[color:var(--warning-foreground)]">
            <AlertTriangle className="size-4" />
            过拟合提醒
          </div>
          <div className="mt-3 grid gap-2 text-sm text-muted-foreground">
            {report.overfitWarnings.map((warning) => (
              <div key={warning}>{warning}</div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
