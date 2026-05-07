import { useQuery } from "@tanstack/react-query";
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

function pct(value: number | string | null | undefined) {
  const text = formatDecimal(value, 2);
  return text === "-" ? text : `${text}%`;
}

function pnlTone(value: number | string | null | undefined) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "text-muted-foreground";
  if (num > 30) return "text-[color:var(--success-foreground)]";
  if (num < 0) return "text-[color:var(--danger-foreground)]";
  return "text-foreground";
}

function flagLabel(flag: string) {
  const labels: Record<string, string> = {
    no_fdv_cost_guard: "缺 FDV 成本",
    no_board_spent_guard: "缺榜单 V",
    no_tax_guard: "缺税率",
    large_project_budget: "预算过大",
    low_sample_first_buy: "样本少",
    high_slippage: "高滑点",
    high_latency: "高延迟",
    tax_signal_risk: "税率异常",
    early_board_spent: "早期榜单",
  };
  return labels[flag] ?? flag;
}

function firstBuySummary(item: StrategyLabResultItem) {
  const first = item.firstBuy;
  if (!first) return "-";
  const parts = [
    first.tax_rate ? `tax ${first.tax_rate}` : null,
    first.board_spent_v ? `榜单 ${formatDecimal(first.board_spent_v, 0)} V` : null,
    first.entry_tax_fdv_wan_usd ? `FDV ${formatDecimal(first.entry_tax_fdv_wan_usd, 2)} 万` : null,
    first.board_cost_wan_usd ? `成本 ${formatDecimal(first.board_cost_wan_usd, 2)} 万` : null,
  ].filter(Boolean);
  return parts.join(" / ") || "-";
}

function RiskFlags({ flags }: { flags: string[] }) {
  if (!flags.length) {
    return <Badge variant="success">无关键风险</Badge>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {flags.slice(0, 4).map((flag) => (
        <Badge key={flag} variant={flag.includes("early") ? "warning" : "danger"}>
          {flagLabel(flag)}
        </Badge>
      ))}
      {flags.length > 4 ? <Badge variant="secondary">+{flags.length - 4}</Badge> : null}
    </div>
  );
}

function ResultTable({
  items,
  emptyTitle,
}: {
  items: StrategyLabResultItem[];
  emptyTitle: string;
}) {
  if (!items.length) {
    return <EmptyState compact title={emptyTitle} description="当前报告没有对应记录。" />;
  }
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[980px]">
        <TableHeader>
          <TableRow>
            <TableHead>Rule</TableHead>
            <TableHead>Dataset</TableHead>
            <TableHead>Scenario</TableHead>
            <TableHead className="text-right">Buys</TableHead>
            <TableHead className="text-right">Spent</TableHead>
            <TableHead className="text-right">PnL</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead>First Buy</TableHead>
            <TableHead>Risk</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item, index) => (
            <TableRow key={`${item.dataset}-${item.ruleName}-${item.scenarioName}-${index}`}>
              <TableCell>
                <div className="font-medium">{item.ruleName}</div>
                <div className="mt-1 text-xs text-muted-foreground">{item.suite}</div>
              </TableCell>
              <TableCell className="text-muted-foreground">{item.dataset}</TableCell>
              <TableCell>{item.scenarioName}</TableCell>
              <TableCell className="text-right">{formatInteger(item.buyCount)}</TableCell>
              <TableCell className="text-right">{formatDecimal(item.totalSpentV, 0)} V</TableCell>
              <TableCell className={cn("text-right font-semibold", pnlTone(item.finalPnlPct))}>
                {pct(item.finalPnlPct)}
              </TableCell>
              <TableCell className="text-right">{formatDecimal(item.score, 2)}</TableCell>
              <TableCell className="max-w-[300px] text-xs leading-5 text-muted-foreground">
                {firstBuySummary(item)}
              </TableCell>
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
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              {label}
            </div>
            <div className="mt-3 text-3xl font-semibold tracking-[-0.04em]">{value}</div>
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

function DatasetGrid({ report }: { report: StrategyLabReportResponse }) {
  const datasets = Object.entries(report.datasetStats ?? {});
  if (!datasets.length) return null;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {datasets.map(([name, stats]) => (
        <div key={name} className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] p-4">
          <div className="truncate text-sm font-semibold">{name}</div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-xs text-muted-foreground">Samples</div>
              <div className="font-semibold">{formatInteger(stats.sampleCount)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Duration</div>
              <div className="font-semibold">{formatInteger(stats.durationSec)}s</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Tax</div>
              <div className="font-semibold">
                {formatDecimal(stats.taxMin, 0)}-{formatDecimal(stats.taxMax, 0)}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Board V</div>
              <div className="font-semibold">{formatDecimal(stats.boardSpentMaxV, 0)}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function StableZoneTable({ items }: { items: StrategyLabStableZoneItem[] }) {
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>Suite</TableHead>
            <TableHead className="text-right">Triggered</TableHead>
            <TableHead className="text-right">Positive</TableHead>
            <TableHead className="text-right">Median</TableHead>
            <TableHead className="text-right">Min</TableHead>
            <TableHead className="text-right">Max</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.suite}>
              <TableCell className="font-medium">{item.suite}</TableCell>
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

function VariableContributionTable({
  items,
}: {
  items: Record<string, StrategyLabVariableContributionItem>;
}) {
  const rows = Object.entries(items);
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead>Rule</TableHead>
            <TableHead className="text-right">PnL</TableHead>
            <TableHead className="text-right">Delta</TableHead>
            <TableHead className="text-right">Buys</TableHead>
            <TableHead>Risk</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map(([name, item]) => (
            <TableRow key={name}>
              <TableCell className="font-medium">{name}</TableCell>
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
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {rows.slice(0, 10).map(([name, item]) => (
        <div key={name} className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div className="truncate text-sm font-semibold">{name}</div>
            <Badge variant={item.positiveRate >= 0.9 ? "success" : item.positiveRate >= 0.75 ? "warning" : "secondary"}>
              {pct(item.positiveRate * 100)}
            </Badge>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 text-sm text-muted-foreground">
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
  const reportQuery = useQuery({
    queryKey: queryKeys.strategyLabReport,
    queryFn: dashboardApi.admin.getStrategyLabReport,
    refetchOnWindowFocus: false,
  });

  if (reportQuery.isLoading) {
    return <LoadingState label="正在加载 Strategy Lab 报告..." />;
  }

  const report = reportQuery.data;
  if (!report?.available) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Strategy Lab"
          title="策略测试矩阵"
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
        title="策略测试矩阵"
        description="SR / ISC / TDS replay 的候选策略、拒绝项与变量贡献。"
        actions={
          <Button variant="outline" onClick={() => void reportQuery.refetch()} disabled={reportQuery.isFetching}>
            <RefreshCcw className={cn("size-4", reportQuery.isFetching && "animate-spin")} />
            刷新
          </Button>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <MetricTile label="Rules" value={formatInteger(report.ruleCount)} hint="策略规则" icon={FlaskConical} />
        <MetricTile label="Scenarios" value={formatInteger(report.scenarioCount)} hint="压力场景" icon={ShieldCheck} />
        <MetricTile label="Results" value={formatInteger(report.resultCount)} hint="测试结果" icon={FileJson2} />
        <MetricTile
          label="Candidates"
          value={formatInteger(report.dryRunCandidates.length)}
          hint="可观察候选"
          icon={CheckCircle2}
          tone="success"
        />
        <MetricTile
          label="Reject"
          value={formatInteger(report.rejectList.length)}
          hint="拒绝/对照项"
          icon={AlertTriangle}
          tone="warning"
        />
        <MetricTile
          label="Generated"
          value={report.generatedAt ? formatDateTime(report.generatedAt).slice(5) : "-"}
          hint={report.sourcePath || "-"}
          icon={TrendingUp}
        />
      </div>

      <SectionCard title="数据集" description="本轮 replay 输入样本。">
        <DatasetGrid report={report} />
      </SectionCard>

      <SectionCard title="Dry-run Candidates" description="当前只作为 would-buy 观察候选。">
        <ResultTable items={report.dryRunCandidates} emptyTitle="没有候选策略" />
      </SectionCard>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <SectionCard title="Top By Risk Adjusted Score">
          <ResultTable items={report.topByRiskAdjustedScore.slice(0, 10)} emptyTitle="没有风险调整榜" />
        </SectionCard>

        <SectionCard title="Stable Zone">
          <StableZoneTable items={report.stableZone} />
        </SectionCard>
      </div>

      <div className="grid gap-6 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <SectionCard title="Variable Contribution">
          <VariableContributionTable items={report.variableContribution} />
        </SectionCard>

        <SectionCard title="Suite Summary">
          <SuiteSummaryList items={report.suiteSummary} />
        </SectionCard>
      </div>

      <SectionCard title="Reject List" description="不能直接进入 dry-run 或交易候选的规则。">
        <ResultTable items={report.rejectList} emptyTitle="没有拒绝项" />
      </SectionCard>

      <SectionCard title="Failure Cases">
        <ResultTable items={report.failureCases.slice(0, 12)} emptyTitle="没有失败样本" />
      </SectionCard>

      {report.overfitWarnings.length ? (
        <div className="rounded-[24px] border border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)]/35 p-5">
          <div className="flex items-center gap-2 font-semibold text-[color:var(--warning-foreground)]">
            <AlertTriangle className="size-4" />
            Overfit Warnings
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
