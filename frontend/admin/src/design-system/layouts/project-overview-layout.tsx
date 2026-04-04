import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

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

export type OverviewField = {
  label: string;
  value: ReactNode;
};

export type OverviewMinuteBarItem = {
  key: number;
  value: number;
};

export type OverviewBoardRow = {
  key: string;
  wallet: string;
  name?: string;
  spentV: number;
  tokenBought: number;
  breakevenFdvUsd: number | null;
  updatedAt?: number | string | null;
};

export type OverviewDelayRow = {
  key: string;
  txHash: string;
  blockTime: number | string;
  recordedAt: number | string;
  delaySeconds: number;
};

export type ProjectOverviewLayoutProps = {
  projectName: string;
  statusLabel: string;
  statusTone?: "default" | "secondary" | "success" | "warning" | "danger";
  detailUrl?: string;
  actions?: ReactNode;
  fields: OverviewField[];
  chartTitle?: string;
  chartDescription?: string;
  minuteBars: OverviewMinuteBarItem[];
  whaleBoardRows: OverviewBoardRow[];
  trackedWalletRows: OverviewBoardRow[];
  delayRows: OverviewDelayRow[];
  whaleBoardTitle?: string;
  trackedWalletTitle?: string;
};

function tokenWan(value: number) {
  return value / 10000;
}

function formatSpentVInteger(value: number) {
  return `${formatInteger(Math.round(value))} V`;
}

function formatBreakevenFdvUsd(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "-";
  return formatDecimal(value, 2);
}

function MinuteBars({ items }: { items: OverviewMinuteBarItem[] }) {
  const chartItems = [...items].sort((left, right) => left.key - right.key);
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
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatCurrency(total)}</div>
        </div>
        <div className="rounded-[20px] border border-border bg-[color:var(--surface-muted)] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">峰值分钟</div>
          <div className="mt-2 text-2xl font-semibold tracking-[-0.04em]">{formatCurrency(peak)}</div>
        </div>
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="min-w-[780px]">
          <div className="surface-chart flex h-64 items-end gap-2 rounded-[28px] border border-border px-4 pb-4 pt-6">
            {chartItems.map((item) => {
              const height = peak > 0 ? Math.max(8, (item.value / peak) * 180) : 8;
              return (
                <div key={item.key} className="flex flex-1 flex-col items-center justify-end gap-2">
                  <div className="text-[10px] text-muted-foreground">{formatDecimal(item.value, 2)}</div>
                  <div
                    className="w-full rounded-t-[10px] bg-[linear-gradient(180deg,#77b9af_0%,#248e93_100%)] shadow-[0_10px_28px_rgba(36,142,147,0.18)]"
                    style={{ height }}
                    title={`${formatDateTime(item.key)} / ${formatCurrency(item.value)}`}
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
  rows: OverviewBoardRow[];
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
          <TableHead>买入市值（USD）</TableHead>
          <TableHead>更新时间</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.key}>
            <TableCell>
              <div className="space-y-1">
                {row.name ? <div className="text-sm font-medium">{row.name}</div> : null}
                <div className="font-mono text-xs text-muted-foreground">
                  {formatAddress(row.wallet, 10)}
                </div>
              </div>
            </TableCell>
            <TableCell>{formatSpentVInteger(row.spentV)}</TableCell>
            <TableCell>{formatDecimal(tokenWan(row.tokenBought), 2)}</TableCell>
            <TableCell>{formatBreakevenFdvUsd(row.breakevenFdvUsd)}</TableCell>
            <TableCell>{row.updatedAt ? formatDateTime(row.updatedAt) : "-"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function ProjectOverviewLayout({
  projectName,
  statusLabel,
  statusTone = "secondary",
  detailUrl,
  actions,
  fields,
  chartTitle = "分钟消耗 SpentV",
  chartDescription,
  minuteBars,
  whaleBoardRows,
  trackedWalletRows,
  delayRows,
  whaleBoardTitle = "大户榜单",
  trackedWalletTitle = "追踪钱包持仓",
}: ProjectOverviewLayoutProps) {
  return (
    <>
      <section className="surface-hero overflow-hidden rounded-[32px] border border-white/60 p-6">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-3xl font-semibold tracking-[-0.05em]">{projectName}</h2>
              <Badge variant={statusTone}>{statusLabel}</Badge>
            </div>
          </div>

          <div className="flex flex-wrap gap-3">
            {detailUrl ? (
              <Button asChild variant="outline">
                <a href={detailUrl} target="_blank" rel="noreferrer">
                  项目详情
                  <ExternalLink className="size-4" />
                </a>
              </Button>
            ) : null}
            {actions}
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {fields.map((field) => (
            <div
              key={field.label}
              className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4"
            >
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                {field.label}
              </div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{field.value}</div>
            </div>
          ))}
        </div>
      </section>

      <SectionCard title={chartTitle} description={chartDescription}>
        <MinuteBars items={minuteBars} />
      </SectionCard>

      <SectionCard title={whaleBoardTitle}>
        <BoardTable
          rows={whaleBoardRows}
          emptyTitle="当前还没有榜单数据"
          emptyDescription="项目在这个时间窗口内还没有形成可展示的大户榜。"
        />
      </SectionCard>

      <SectionCard title={trackedWalletTitle}>
        <BoardTable
          rows={trackedWalletRows}
          emptyTitle="当前还没有追踪钱包"
          emptyDescription="等钱包和项目命中后，这里就会显示对应持仓。"
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
          {delayRows.length ? (
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
                {delayRows.map((row) => (
                  <TableRow key={row.key}>
                    <TableCell className="font-mono text-xs">{formatAddress(row.txHash, 10)}</TableCell>
                    <TableCell>{formatDateTime(row.blockTime)}</TableCell>
                    <TableCell>{formatDateTime(row.recordedAt)}</TableCell>
                    <TableCell>{formatDecimal(row.delaySeconds, 1)} 秒</TableCell>
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
