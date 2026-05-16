import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Gauge, Info, LockKeyhole, Pause, Play, RotateCcw, WalletCards } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { useShell } from "@/app/shell-context";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { ProjectOverviewSections } from "@/components/project-overview-sections";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";
import type {
  LaunchSellRuntimeConfigResponse,
  LaunchStrategyRuntimeConfigResponse,
  OverviewActiveResponse,
  ProjectLockedResponse,
  ReplayStatusResponse,
} from "@/types/api";

function isRealtimeStatus(status: string) {
  return ["prelaunch", "live"].includes(String(status || "").toLowerCase());
}

const LIVE_FAST_REFRESH_MS = 250;
const PRELAUNCH_REFRESH_MS = 5_000;
const DEFAULT_REFRESH_MS = 20_000;

function normalizeFastRefreshMs(value: number | null | undefined, fallback: number) {
  const parsed = Number(value ?? fallback);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.max(150, Math.min(Math.round(parsed), DEFAULT_REFRESH_MS));
}

function marketRefreshIntervalMs(status: string, recommendedRefreshMs?: number | null) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return normalizeFastRefreshMs(recommendedRefreshMs, LIVE_FAST_REFRESH_MS);
  if (key === "prelaunch") return PRELAUNCH_REFRESH_MS;
  return DEFAULT_REFRESH_MS;
}

function marketStaleTimeMs(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return 0;
  if (key === "prelaunch") return 2_000;
  return 15_000;
}

function overviewRefreshIntervalMs(data: OverviewActiveResponse | undefined) {
  const item = data?.item;
  if (!item) return false;

  const status = String(item.projectedStatus || item.status || "").toLowerCase();
  if (status === "live") return normalizeFastRefreshMs(item.recommendedRefreshMs, LIVE_FAST_REFRESH_MS);
  if (status === "prelaunch") return PRELAUNCH_REFRESH_MS;
  return false;
}

function detailPageTitle(status: string) {
  return String(status || "").toLowerCase() === "ended" ? "历史项目详情" : "项目详情";
}

function detailStatusLabel(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "prelaunch") return "预热中";
  if (key === "live") return "发射中";
  if (key === "ended") return "已结束";
  if (key === "scheduled") return "待开始";
  return "待补全";
}

function detailStatusVariant(status: string) {
  const key = String(status || "").toLowerCase();
  if (key === "live") return "success" as const;
  if (key === "prelaunch") return "warning" as const;
  if (key === "ended") return "secondary" as const;
  return "default" as const;
}

function isReplayControlCandidate() {
  if (typeof window === "undefined") return false;
  const hostname = window.location.hostname;
  const params = new URLSearchParams(window.location.search);
  return (
    (hostname === "127.0.0.1" || hostname === "localhost") &&
    params.get("replayControl") === "1"
  );
}

function replayStateLabel(state: ReplayStatusResponse["state"]) {
  if (state === "running") return "自动模拟中";
  if (state === "ended") return "已结束";
  return "等待手动开始";
}

function replayStateVariant(state: ReplayStatusResponse["state"]) {
  if (state === "running") return "success" as const;
  if (state === "ended") return "secondary" as const;
  return "warning" as const;
}

function ReplayControlPanel({
  status,
  pending,
  onAction,
}: {
  status?: ReplayStatusResponse;
  pending: boolean;
  onAction: (action: "start" | "pause" | "resume" | "speed" | "reset", speed?: number) => void;
}) {
  if (!status?.ok || !status.manual) return null;

  const progressPercent = Math.round((status.progress ?? 0) * 100);
  const isRunning = status.state === "running";
  const isEnded = status.state === "ended";
  const hasStarted = status.elapsedSec > 0 || status.insertedEvents > 0;
  const startAction = hasStarted ? "resume" : "start";
  const startLabel = hasStarted ? "继续模拟" : "开始自动模拟";

  return (
    <section className="rounded-[28px] border border-primary/25 bg-primary/5 px-5 py-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Gauge className="size-4 text-primary" />
            <div className="text-sm font-semibold tracking-[-0.02em]">手动模拟模式</div>
            <Badge variant={replayStateVariant(status.state)}>{replayStateLabel(status.state)}</Badge>
            <Badge variant="secondary">{status.speed}x</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>模拟时间 {formatDateTime(status.now)}</span>
            <span>进度 {progressPercent}%</span>
            <span>
              事件 {status.insertedEvents}/{status.totalEvents}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            className="h-10 w-24"
            value={String(status.speed)}
            onChange={(event) => onAction("speed", Number(event.target.value))}
            disabled={pending || isEnded}
          >
            <option value="1">1x</option>
            <option value="2">2x</option>
            <option value="5">5x</option>
            <option value="10">10x</option>
          </Select>
          {isRunning ? (
            <Button variant="outline" onClick={() => onAction("pause")} disabled={pending}>
              <Pause className="size-4" />
              暂停
            </Button>
          ) : (
            <Button onClick={() => onAction(startAction, status.speed)} disabled={pending || isEnded}>
              <Play className="size-4" />
              {isEnded ? "已结束" : startLabel}
            </Button>
          )}
          <Button
            variant="secondary"
            onClick={() => {
              if (!window.confirm("这会清空当前临时回放数据并回到发射起点，只影响 18080 模拟环境。确认继续吗？")) {
                return;
              }
              onAction("reset");
            }}
            disabled={pending}
          >
            <RotateCcw className="size-4" />
            回到起点
          </Button>
        </div>
      </div>
    </section>
  );
}

type LaunchStrategyFormState = {
  enabled: boolean;
  mode: "simulate" | "broadcast";
  baseBuyV: string;
  dipBuyV: string;
  dipFromOwnCostPct: string;
  flatPausePct: string;
  maxBuyV: string;
  maxProjectV: string;
  updatedReason: string;
};

type LaunchSellFormState = {
  enabled: boolean;
  mode: "simulate" | "broadcast";
  maxTaxRate: string;
  roiLowPct: string;
  roiHighPct: string;
  largeBuyLowV: string;
  largeBuyHighV: string;
  sellLowPct: string;
  sellHighPct: string;
  cooldownSec: string;
  catchUpEventsSec: string;
  updatedReason: string;
};

function formFromLaunchStrategyConfig(data?: LaunchStrategyRuntimeConfigResponse): LaunchStrategyFormState {
  const item = data?.item;
  const baseBuyV = formatEditableNumber(item?.baseBuyV ?? "25");
  const dipBuyV = formatEditableNumber(item?.dipBuyV ?? "50");
  const rawMaxBuyV = formatEditableNumber(item?.maxBuyV ?? "50");
  const baseBuy = parseStrategyInputNumber(baseBuyV);
  const dipBuy = parseStrategyInputNumber(dipBuyV);
  const maxBuy = parseStrategyInputNumber(rawMaxBuyV);
  const maxBuyV =
    baseBuy !== null && dipBuy !== null && maxBuy !== null
      ? formatStrategyInputNumber(Math.max(baseBuy, dipBuy, maxBuy))
      : rawMaxBuyV;

  return {
    enabled: item?.enabled ?? false,
    mode: item?.mode ?? "simulate",
    baseBuyV,
    dipBuyV,
    dipFromOwnCostPct: formatEditableNumber(item?.dipFromOwnCostPct ?? "20", 0),
    flatPausePct: formatEditableNumber(item?.flatPausePct ?? "10", 0),
    maxBuyV,
    maxProjectV: formatEditableNumber(item?.maxProjectV ?? "150"),
    updatedReason: "",
  };
}

function formFromLaunchSellConfig(data?: LaunchSellRuntimeConfigResponse): LaunchSellFormState {
  const item = data?.item;
  const roiLowPct = formatEditableNumber(item?.roiLowPct ?? "30", 0);
  const rawRoiHighPct = formatEditableNumber(item?.roiHighPct ?? "50", 0);
  const largeBuyLowV = formatEditableNumber(item?.largeBuyLowV ?? "5000", 0);
  const rawLargeBuyHighV = formatEditableNumber(item?.largeBuyHighV ?? "8000", 0);
  const sellLowPct = formatEditableNumber(item?.sellLowPct ?? "30", 0);
  const rawSellHighPct = formatEditableNumber(item?.sellHighPct ?? "50", 0);
  const roiLow = parseStrategyInputNumber(roiLowPct);
  const roiHigh = parseStrategyInputNumber(rawRoiHighPct);
  const largeLow = parseStrategyInputNumber(largeBuyLowV);
  const largeHigh = parseStrategyInputNumber(rawLargeBuyHighV);
  const sellLow = parseStrategyInputNumber(sellLowPct);
  const sellHigh = parseStrategyInputNumber(rawSellHighPct);

  return {
    enabled: item?.enabled ?? false,
    mode: item?.mode ?? "simulate",
    maxTaxRate: formatEditableNumber(item?.maxTaxRate ?? "30", 0),
    roiLowPct,
    roiHighPct:
      roiLow !== null && roiHigh !== null ? formatStrategyInputNumber(Math.max(roiLow, roiHigh)) : rawRoiHighPct,
    largeBuyLowV,
    largeBuyHighV:
      largeLow !== null && largeHigh !== null
        ? formatStrategyInputNumber(Math.max(largeLow, largeHigh))
        : rawLargeBuyHighV,
    sellLowPct,
    sellHighPct:
      sellLow !== null && sellHigh !== null
        ? formatStrategyInputNumber(Math.max(sellLow, sellHigh))
        : rawSellHighPct,
    cooldownSec: formatEditableNumber(item?.cooldownSec ?? 60, 0),
    catchUpEventsSec: formatEditableNumber(item?.catchUpEventsSec ?? 120, 0),
    updatedReason: "",
  };
}

function formatEditableNumber(value: string | number | null | undefined, maximumFractionDigits = 4) {
  const parsed = Number(value ?? "");
  if (!Number.isFinite(parsed)) return String(value ?? "");
  return parsed.toLocaleString("en-US", {
    maximumFractionDigits,
    useGrouping: false,
  });
}

function formatConfigValue(value: string | number | null | undefined, suffix = "", maximumFractionDigits = 4) {
  const parsed = Number(value ?? "");
  if (!Number.isFinite(parsed)) return "-";
  return `${parsed.toLocaleString(undefined, { maximumFractionDigits })}${suffix}`;
}

function parseStrategyInputNumber(value: string | number | null | undefined) {
  const parsed = Number(value ?? "");
  return Number.isFinite(parsed) ? parsed : null;
}

function formatStrategyInputNumber(value: number) {
  return formatEditableNumber(value, 4);
}

function normalizeLaunchStrategyFormForSubmit(form: LaunchStrategyFormState): LaunchStrategyFormState {
  const baseBuy = parseStrategyInputNumber(form.baseBuyV);
  const dipBuy = parseStrategyInputNumber(form.dipBuyV);
  const maxBuy = parseStrategyInputNumber(form.maxBuyV);
  const next = { ...form };

  if (baseBuy !== null && dipBuy !== null && maxBuy !== null) {
    const requiredMaxBuy = Math.max(baseBuy, dipBuy, maxBuy);
    next.maxBuyV = formatStrategyInputNumber(requiredMaxBuy);
  }

  return next;
}

function normalizeLaunchSellFormForSubmit(form: LaunchSellFormState): LaunchSellFormState {
  const roiLow = parseStrategyInputNumber(form.roiLowPct);
  const roiHigh = parseStrategyInputNumber(form.roiHighPct);
  const largeLow = parseStrategyInputNumber(form.largeBuyLowV);
  const largeHigh = parseStrategyInputNumber(form.largeBuyHighV);
  const sellLow = parseStrategyInputNumber(form.sellLowPct);
  const sellHigh = parseStrategyInputNumber(form.sellHighPct);
  const next = { ...form };

  if (roiLow !== null && roiHigh !== null) next.roiHighPct = formatStrategyInputNumber(Math.max(roiLow, roiHigh));
  if (largeLow !== null && largeHigh !== null) next.largeBuyHighV = formatStrategyInputNumber(Math.max(largeLow, largeHigh));
  if (sellLow !== null && sellHigh !== null) next.sellHighPct = formatStrategyInputNumber(Math.max(sellLow, sellHigh));

  return next;
}

function applyLaunchStrategyPatch(
  current: LaunchStrategyFormState,
  patch: Partial<LaunchStrategyFormState>,
): Partial<LaunchStrategyFormState> {
  const next = { ...current, ...patch };
  const baseBuy = parseStrategyInputNumber(next.baseBuyV);
  const dipBuy = parseStrategyInputNumber(next.dipBuyV);
  const maxBuy = parseStrategyInputNumber(next.maxBuyV);

  if ((patch.baseBuyV !== undefined || patch.dipBuyV !== undefined) && baseBuy !== null && dipBuy !== null && maxBuy !== null) {
    const requiredMaxBuy = Math.max(baseBuy, dipBuy, maxBuy);
    if (requiredMaxBuy > maxBuy) {
      return { ...patch, maxBuyV: formatStrategyInputNumber(requiredMaxBuy) };
    }
  }

  return patch;
}

function applyLaunchSellPatch(
  current: LaunchSellFormState,
  patch: Partial<LaunchSellFormState>,
): Partial<LaunchSellFormState> {
  const next = { ...current, ...patch };
  const roiLow = parseStrategyInputNumber(next.roiLowPct);
  const roiHigh = parseStrategyInputNumber(next.roiHighPct);
  const largeLow = parseStrategyInputNumber(next.largeBuyLowV);
  const largeHigh = parseStrategyInputNumber(next.largeBuyHighV);
  const sellLow = parseStrategyInputNumber(next.sellLowPct);
  const sellHigh = parseStrategyInputNumber(next.sellHighPct);
  const out: Partial<LaunchSellFormState> = { ...patch };

  if (patch.roiLowPct !== undefined && roiLow !== null && roiHigh !== null && roiLow > roiHigh) {
    out.roiHighPct = formatStrategyInputNumber(roiLow);
  }
  if (patch.largeBuyLowV !== undefined && largeLow !== null && largeHigh !== null && largeLow > largeHigh) {
    out.largeBuyHighV = formatStrategyInputNumber(largeLow);
  }
  if (patch.sellLowPct !== undefined && sellLow !== null && sellHigh !== null && sellLow > sellHigh) {
    out.sellHighPct = formatStrategyInputNumber(sellLow);
  }

  return out;
}

function friendlyLaunchStrategyError(error: Error) {
  const message = error.message || "";
  const normalized = message.toLowerCase();
  if (normalized.includes("basebuyv") && normalized.includes("maxbuyv")) {
    return "基础买入不能高于单笔上限。";
  }
  if (normalized.includes("dipbuyv") && normalized.includes("maxbuyv")) {
    return "抄底买入不能高于单笔上限。";
  }
  if (normalized.includes("maxprojectv") && normalized.includes("already sent")) {
    return "项目预算不能低于已买入金额。";
  }
  if (normalized.includes("must be positive")) {
    return "买入金额和预算必须大于 0。";
  }
  if (normalized.includes("cannot be negative")) {
    return "参数不能为负数。";
  }
  if (normalized.includes("cannot exceed 100")) {
    return "百分比不能超过 100%。";
  }
  if (error instanceof ApiError) {
    return "自动买入配置保存失败，请检查参数。";
  }
  return message || "自动买入配置保存失败。";
}

function friendlyLaunchSellError(error: Error) {
  const message = error.message || "";
  const normalized = message.toLowerCase();
  if (normalized.includes("roihighpct") && normalized.includes("roilowpct")) {
    return "收益率二档不能低于一档。";
  }
  if (normalized.includes("largebuyhighv") && normalized.includes("largebuylowv")) {
    return "大单二档不能低于一档。";
  }
  if (normalized.includes("sellhighpct") && normalized.includes("selllowpct")) {
    return "卖出二档不能低于一档。";
  }
  if (normalized.includes("cannot exceed 100")) {
    return "税率和卖出比例不能超过 100%。";
  }
  if (normalized.includes("must be positive")) {
    return "大单回看和大单门槛必须大于 0。";
  }
  if (normalized.includes("cannot be negative")) {
    return "参数不能为负数。";
  }
  if (error instanceof ApiError) {
    return "自动卖出配置保存失败，请检查参数。";
  }
  return message || "自动卖出配置保存失败。";
}

const strategyMetricCardClass =
  "launch-strategy-metric rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-4";
const strategyActionClass = "launch-strategy-action";
const strategyFieldClass = "launch-strategy-field space-y-2";
const strategyLabelClass =
  "launch-strategy-label text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground";
const strategyInputClass = "launch-strategy-input";
const defaultStrategyPatch: Partial<LaunchStrategyFormState> = {
  baseBuyV: "25",
  dipBuyV: "50",
  dipFromOwnCostPct: "20",
  flatPausePct: "10",
  maxBuyV: "50",
  maxProjectV: "150",
};
const defaultSellPatch: Partial<LaunchSellFormState> = {
  maxTaxRate: "30",
  roiLowPct: "30",
  roiHighPct: "50",
  largeBuyLowV: "5000",
  largeBuyHighV: "8000",
  sellLowPct: "30",
  sellHighPct: "50",
  cooldownSec: "60",
  catchUpEventsSec: "120",
};

function StrategyInfoHint({ label }: { label: string }) {
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

function StrategyFieldLabel({
  label,
  unit,
  hint,
}: {
  label: string;
  unit: string;
  hint?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={strategyLabelClass}>{label}</span>
        {hint ? <StrategyInfoHint label={hint} /> : null}
      </div>
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/80">
        {unit}
      </span>
    </div>
  );
}

function LaunchStrategyControlPanel({
  data,
  form,
  pending,
  onChange,
  onSave,
}: {
  data?: LaunchStrategyRuntimeConfigResponse;
  form: LaunchStrategyFormState;
  pending: boolean;
  onChange: (patch: Partial<LaunchStrategyFormState>) => void;
  onSave: (mode: "broadcast" | "disabled") => void;
}) {
  const item = data?.item;
  const activeFuse = data?.runtime.activeFuse;
  const statusVariant = form.enabled ? "success" : "secondary";
  const statusLabel = form.enabled ? "已启用" : "未启用";
  const lastAudit = data?.audit[0];

  return (
    <SectionCard
      className="launch-strategy-panel overflow-hidden border-primary/20"
      title="自动买入控制"
      description="管理员运行时参数。保存后由自动买入执行器热读取；真实广播仍受独立 RPC、熔断和系统门禁保护。"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusVariant}>{statusLabel}</Badge>
          <Badge variant="secondary">版本 {item?.version ?? 0}</Badge>
        </div>
      }
    >
      <div className="launch-strategy-control grid gap-4 xl:grid-cols-[0.62fr_1.38fr]">
        <div className="space-y-3">
          <div className={strategyMetricCardClass}>
            <div className={strategyLabelClass}>已买入</div>
            <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
              {formatConfigValue(data?.runtime.sentProjectV ?? "0", " V")}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">自动买入已成交总额</div>
          </div>
          {activeFuse ? (
            <div className="launch-strategy-fuse rounded-[22px] border border-[color:var(--danger)] bg-[color:var(--danger-soft)] px-4 py-4 text-sm text-[color:var(--danger-foreground)]">
              当前存在 active fuse，执行器会阻断广播。
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          <div className="launch-strategy-command-bar flex flex-col gap-3 rounded-[24px] border border-border bg-[color:var(--surface-soft)] px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <div className={strategyLabelClass}>参数设置</div>
              <div className="text-sm text-muted-foreground">保存后自动买入执行器会热读取这些参数。</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                className={strategyActionClass}
                onClick={() => onChange(defaultStrategyPatch)}
              >
                恢复默认
              </Button>
              <Button
                type="button"
                variant="outline"
                className="launch-strategy-action launch-strategy-action-danger"
                onClick={() => onSave("disabled")}
                disabled={pending}
              >
                停用自动买入
              </Button>
              <Button
                type="button"
                className="launch-strategy-action launch-strategy-action-primary"
                onClick={() => onSave("broadcast")}
                disabled={pending}
              >
                保存并启用
              </Button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="基础买入" unit="VIRTUAL" />
              <Input
                className={strategyInputClass}
                inputMode="decimal"
                aria-label="基础买入，单位 VIRTUAL"
                value={form.baseBuyV}
                onChange={(event) => onChange(applyLaunchStrategyPatch(form, { baseBuyV: event.target.value }))}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="抄底买入" unit="VIRTUAL" />
              <Input
                className={strategyInputClass}
                inputMode="decimal"
                aria-label="抄底买入，单位 VIRTUAL"
                value={form.dipBuyV}
                onChange={(event) => onChange(applyLaunchStrategyPatch(form, { dipBuyV: event.target.value }))}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="单笔上限" unit="VIRTUAL" />
              <Input
                className={strategyInputClass}
                inputMode="decimal"
                aria-label="单笔上限，单位 VIRTUAL"
                value={form.maxBuyV}
                onChange={(event) => onChange({ maxBuyV: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="项目预算" unit="VIRTUAL" />
              <Input
                className={strategyInputClass}
                inputMode="decimal"
                aria-label="项目预算，单位 VIRTUAL"
                value={form.maxProjectV}
                onChange={(event) => onChange({ maxProjectV: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="抄底阈值"
                unit="%"
                hint="当当前含税估算 FDV 低于我方历史加权买入 FDV 这个比例以上时，下一次满足买入条件会使用抄底买入金额。默认 20%，表示比我方成本低 20% 才加大买入。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="抄底阈值，单位百分比"
                value={form.dipFromOwnCostPct}
                onChange={(event) => onChange({ dipFromOwnCostPct: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="横盘跳过"
                unit="%"
                hint="某税率档买入后，如果下一相邻税率档的含税估算 FDV 相对上一买点变化不超过这个比例，就跳过这一档；只跳过一次，下一档会重新判断。默认 10%。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="横盘跳过，单位百分比"
                value={form.flatPausePct}
                onChange={(event) => onChange({ flatPausePct: event.target.value })}
              />
            </div>
          </div>

          {lastAudit ? (
            <div className="text-xs text-muted-foreground">
              上次调整：版本 {lastAudit.version} / {formatDateTime(lastAudit.createdAt)}
            </div>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}

function LaunchSellControlPanel({
  data,
  form,
  pending,
  onChange,
  onSave,
}: {
  data?: LaunchSellRuntimeConfigResponse;
  form: LaunchSellFormState;
  pending: boolean;
  onChange: (patch: Partial<LaunchSellFormState>) => void;
  onSave: (mode: "broadcast" | "disabled") => void;
}) {
  const item = data?.item;
  const activeFuse = data?.runtime.activeFuse;
  const statusVariant = form.enabled ? "success" : "secondary";
  const statusLabel = form.enabled ? "已启用" : "未启用";
  const lastAudit = data?.audit[0];

  return (
    <SectionCard
      className="launch-strategy-panel overflow-hidden border-border"
      title="自动卖出控制"
      description="管理员运行时参数。保存后由自动卖出执行器热读取；真实广播仍受独立 RPC、熔断、授权和系统门禁保护。"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusVariant}>{statusLabel}</Badge>
          <Badge variant="secondary">版本 {item?.version ?? 0}</Badge>
        </div>
      }
    >
      <div className="launch-strategy-control grid gap-4 xl:grid-cols-[0.62fr_1.38fr]">
        <div className="space-y-3">
          <div className={strategyMetricCardClass}>
            <div className={strategyLabelClass}>已卖出目标</div>
            <div className="mt-2 text-3xl font-semibold tracking-[-0.04em]">
              {formatConfigValue(data?.runtime.soldPct ?? "0", "%", 2)}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              成功卖出 {data?.runtime.sellCount ?? 0} 次
              {data?.runtime.lastSellAt ? ` / 最近 ${formatDateTime(data.runtime.lastSellAt)}` : ""}
            </div>
          </div>
          {activeFuse ? (
            <div className="launch-strategy-fuse rounded-[22px] border border-[color:var(--danger)] bg-[color:var(--danger-soft)] px-4 py-4 text-sm text-[color:var(--danger-foreground)]">
              当前存在 active fuse，自动卖出会阻断广播。
            </div>
          ) : null}
        </div>

        <div className="space-y-4">
          <div className="launch-strategy-command-bar flex flex-col gap-3 rounded-[24px] border border-border bg-[color:var(--surface-soft)] px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <div className={strategyLabelClass}>卖出规则</div>
              <div className="text-sm text-muted-foreground">收益率和大单买入必须同时满足，才会触发自动卖出。</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                className={strategyActionClass}
                onClick={() => onChange(defaultSellPatch)}
              >
                恢复默认
              </Button>
              <Button
                type="button"
                variant="outline"
                className="launch-strategy-action launch-strategy-action-danger"
                onClick={() => onSave("disabled")}
                disabled={pending}
              >
                停用自动卖出
              </Button>
              <Button
                type="button"
                className="launch-strategy-action launch-strategy-action-primary"
                onClick={() => onSave("broadcast")}
                disabled={pending}
              >
                保存并启用
              </Button>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="税率窗口"
                unit="%"
                hint="只有当前买入税率低于或等于这个数值时，自动卖出才开始观察。默认 30%。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="自动卖出税率窗口，单位百分比"
                value={form.maxTaxRate}
                onChange={(event) => onChange({ maxTaxRate: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="收益率一档"
                unit="%"
                hint="我方持仓按当前现货 FDV 估算的收益率达到这一档，且同时出现一档大单买入时，卖出一档比例。默认 30%。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="收益率一档，单位百分比"
                value={form.roiLowPct}
                onChange={(event) => onChange(applyLaunchSellPatch(form, { roiLowPct: event.target.value }))}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="收益率二档" unit="%" />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="收益率二档，单位百分比"
                value={form.roiHighPct}
                onChange={(event) => onChange({ roiHighPct: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="大单一档"
                unit="VIRTUAL"
                hint="税率窗口内最近回看时间里，单笔买入达到这个数量，并且收益率也达到一档，才会卖出一档比例。默认 5,000 VIRTUAL。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="大单一档，单位 VIRTUAL"
                value={form.largeBuyLowV}
                onChange={(event) => onChange(applyLaunchSellPatch(form, { largeBuyLowV: event.target.value }))}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="大单二档" unit="VIRTUAL" />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="大单二档，单位 VIRTUAL"
                value={form.largeBuyHighV}
                onChange={(event) => onChange({ largeBuyHighV: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="大单回看"
                unit="秒"
                hint="每轮判断只看最近这段时间内尚未处理过的大单买入，避免很久以前的大单反复触发。默认 120 秒。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="大单回看，单位秒"
                value={form.catchUpEventsSec}
                onChange={(event) => onChange({ catchUpEventsSec: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="卖出一档" unit="%" />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="卖出一档，单位百分比"
                value={form.sellLowPct}
                onChange={(event) => onChange(applyLaunchSellPatch(form, { sellLowPct: event.target.value }))}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel label="卖出二档" unit="%" />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="卖出二档，单位百分比"
                value={form.sellHighPct}
                onChange={(event) => onChange({ sellHighPct: event.target.value })}
              />
            </div>
            <div className={strategyFieldClass}>
              <StrategyFieldLabel
                label="冷却"
                unit="秒"
                hint="成功卖出后，在这段时间内不再触发新的自动卖出，避免同一波行情连续广播。默认 60 秒。"
              />
              <Input
                className={strategyInputClass}
                inputMode="numeric"
                aria-label="自动卖出冷却时间，单位秒"
                value={form.cooldownSec}
                onChange={(event) => onChange({ cooldownSec: event.target.value })}
              />
            </div>
          </div>

          {lastAudit ? (
            <div className="text-xs text-muted-foreground">
              上次调整：版本 {lastAudit.version} / {formatDateTime(lastAudit.createdAt)}
            </div>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}

function confirmProjectUnlock(projectName: string, unlockCost: number) {
  return window.confirm(
    `解锁 ${projectName} 的项目详情将消耗 ${unlockCost} 积分，解锁后以后都能直接查看。确认继续吗？`,
  );
}

export function OverviewPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { projectId } = useParams();
  const {
    viewer,
    meta,
    selectedProject,
    setSelectedProject,
    refreshAll,
  } = useShell();
  const detailProjectId = projectId && /^\d+$/.test(projectId) ? Number.parseInt(projectId, 10) : null;
  const isProjectDetailView = detailProjectId !== null;
  const hasInvalidProjectId = Boolean(projectId) && detailProjectId === null;
  const projectsHref = viewer === "admin" ? "/admin/projects" : "/app/projects";

  const overviewQuery = useQuery({
    queryKey: isProjectDetailView
      ? viewer === "admin"
        ? queryKeys.adminProjectOverview(detailProjectId)
        : queryKeys.appProjectOverview(detailProjectId)
      : viewer === "admin"
        ? queryKeys.overviewActive(selectedProject)
        : queryKeys.appOverviewActive(selectedProject),
    queryFn: () => {
      if (isProjectDetailView && detailProjectId !== null) {
        return viewer === "admin"
          ? dashboardApi.admin.getProjectOverview(detailProjectId)
          : dashboardApi.app.getProjectOverview(detailProjectId);
      }
      return viewer === "admin"
        ? dashboardApi.admin.getOverviewActive(selectedProject)
        : dashboardApi.app.getOverviewActive(selectedProject);
    },
    enabled: Boolean(meta) && !hasInvalidProjectId && (!isProjectDetailView || detailProjectId !== null),
    staleTime: 0,
    refetchInterval: (query) => overviewRefreshIntervalMs(query.state.data as OverviewActiveResponse | undefined),
    refetchIntervalInBackground: false,
    gcTime: 60_000,
  });

  const lockedDetails =
    viewer === "user" && overviewQuery.error instanceof ApiError && overviewQuery.error.status === 403
      ? (overviewQuery.error.details as ProjectLockedResponse)
      : null;
  const lockedProject = lockedDetails?.project ?? null;
  const targetProjectId = detailProjectId ?? lockedProject?.id ?? 0;
  const currentProjectName = overviewQuery.data?.item?.name ?? lockedProject?.name ?? "";
  const [launchStrategyDraft, setLaunchStrategyDraft] = useState<Partial<LaunchStrategyFormState>>({});
  const [launchSellDraft, setLaunchSellDraft] = useState<Partial<LaunchSellFormState>>({});

  const launchStrategyConfigQuery = useQuery({
    queryKey: detailProjectId ? queryKeys.adminLaunchStrategyConfig(detailProjectId) : ["admin-launch-strategy-config", 0],
    queryFn: () => dashboardApi.admin.getLaunchStrategyConfig(detailProjectId || 0),
    enabled: viewer === "admin" && isProjectDetailView && detailProjectId !== null,
  });

  const launchSellConfigQuery = useQuery({
    queryKey: detailProjectId ? queryKeys.adminLaunchSellConfig(detailProjectId) : ["admin-launch-sell-config", 0],
    queryFn: () => dashboardApi.admin.getLaunchSellConfig(detailProjectId || 0),
    enabled: viewer === "admin" && isProjectDetailView && detailProjectId !== null,
    refetchInterval: 5_000,
  });

  const launchStrategyForm = useMemo(
    () => ({
      ...formFromLaunchStrategyConfig(launchStrategyConfigQuery.data),
      ...launchStrategyDraft,
    }),
    [launchStrategyConfigQuery.data, launchStrategyDraft],
  );

  const launchSellForm = useMemo(
    () => ({
      ...formFromLaunchSellConfig(launchSellConfigQuery.data),
      ...launchSellDraft,
    }),
    [launchSellConfigQuery.data, launchSellDraft],
  );

  const launchStrategyConfigMutation = useMutation({
    mutationFn: async (payload: LaunchStrategyFormState) => {
      if (!detailProjectId) {
        throw new Error("当前没有可配置的项目。");
      }
      return dashboardApi.admin.setLaunchStrategyConfig(detailProjectId, payload);
    },
    onSuccess: async () => {
      setLaunchStrategyDraft({});
      toast.success("自动买入配置已保存。");
      if (detailProjectId) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.adminLaunchStrategyConfig(detailProjectId) });
      }
    },
    onError: (error: Error) => toast.error(friendlyLaunchStrategyError(error)),
  });

  const launchSellConfigMutation = useMutation({
    mutationFn: async (payload: LaunchSellFormState) => {
      if (!detailProjectId) {
        throw new Error("当前没有可配置的项目。");
      }
      return dashboardApi.admin.setLaunchSellConfig(detailProjectId, payload);
    },
    onSuccess: async () => {
      setLaunchSellDraft({});
      toast.success("自动卖出配置已保存。");
      if (detailProjectId) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.adminLaunchSellConfig(detailProjectId) });
      }
    },
    onError: (error: Error) => toast.error(friendlyLaunchSellError(error)),
  });

  const saveLaunchStrategyConfig = (mode: "broadcast" | "disabled") => {
    const next: LaunchStrategyFormState = {
      ...normalizeLaunchStrategyFormForSubmit(launchStrategyForm),
      enabled: mode !== "disabled",
      mode: mode === "broadcast" ? "broadcast" : "simulate",
      updatedReason:
        launchStrategyForm.updatedReason.trim() ||
        (mode === "broadcast" ? "管理员手动保存并启用自动买入" : "管理员手动停用自动买入"),
    };
    if (mode === "disabled" && !window.confirm("确认停用自动买入？")) return;
    if (mode === "broadcast") {
      const base = Number(next.baseBuyV);
      const dip = Number(next.dipBuyV);
      const message =
        base >= 100 || dip >= 200
          ? `将以 ${next.baseBuyV} / ${next.dipBuyV} VIRTUAL 作为买入金额，并启用自动买入。确认继续？`
          : "保存后会按当前参数启用自动买入。确认继续？";
      if (!window.confirm(message)) return;
    }
    launchStrategyConfigMutation.mutate(next);
  };

  const saveLaunchSellConfig = (mode: "broadcast" | "disabled") => {
    const next: LaunchSellFormState = {
      ...normalizeLaunchSellFormForSubmit(launchSellForm),
      enabled: mode !== "disabled",
      mode: mode === "broadcast" ? "broadcast" : "simulate",
      updatedReason:
        launchSellForm.updatedReason.trim() ||
        (mode === "broadcast" ? "管理员手动保存并启用自动卖出" : "管理员手动停用自动卖出"),
    };
    if (mode === "disabled" && !window.confirm("确认停用自动卖出？")) return;
    if (mode === "broadcast") {
      const message = `将启用自动卖出：税率 <= ${next.maxTaxRate}%，收益率 ${next.roiLowPct}/${next.roiHighPct}%，大单 ${next.largeBuyLowV}/${next.largeBuyHighV} VIRTUAL。确认继续？`;
      if (!window.confirm(message)) return;
    }
    launchSellConfigMutation.mutate(next);
  };

  const teamOverrideMutation = useMutation({
    mutationFn: async (payload: {
      projectId: number;
      wallet: string;
      action: "include" | "exclude";
      reason?: string;
    }) => dashboardApi.admin.setTeamAddressOverride(payload.projectId, payload),
    onSuccess: async (_result, variables) => {
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: queryKeys.adminProjectOverview(variables.projectId) }),
      ];
      if (currentProjectName) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.overviewActive(currentProjectName) }));
      }
      await Promise.all(invalidations);
      toast.success(variables.action === "exclude" ? "已加入自动过滤。" : "已纳入成本位。");
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const teamOverridePendingWallet = teamOverrideMutation.isPending
    ? teamOverrideMutation.variables?.wallet ?? null
    : null;

  const setTeamOverride = (wallet: string, action: "include" | "exclude", reason?: string) => {
    const projectIdForOverride = overviewQuery.data?.item?.id ?? detailProjectId;
    if (viewer !== "admin" || !projectIdForOverride) {
      toast.error("当前没有可操作的管理员项目。");
      return;
    }
    teamOverrideMutation.mutate({
      projectId: projectIdForOverride,
      wallet,
      action,
      reason,
    });
  };

  const unlockMutation = useMutation({
    mutationFn: async () => {
      if (!targetProjectId) {
        throw new Error("当前没有可解锁的项目。");
      }
      return dashboardApi.app.unlockProject(targetProjectId);
    },
    onSuccess: async () => {
      if (currentProjectName) {
        setSelectedProject(currentProjectName);
      }
      const invalidations = [
        queryClient.invalidateQueries({ queryKey: queryKeys.appBillingSummary }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjects }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appProjectAccess(targetProjectId) }),
        queryClient.invalidateQueries({ queryKey: ["app-project-access"] }),
      ];
      if (detailProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.appProjectOverview(detailProjectId) }));
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.appProjectMarket(detailProjectId) }));
      }
      if (currentProjectName) {
        invalidations.push(
          queryClient.invalidateQueries({
            queryKey: queryKeys.appOverviewActive(currentProjectName),
          }),
        );
      }
      await Promise.all([...invalidations, refreshAll()]);
      toast.success(`${currentProjectName || "当前项目"} 已解锁。`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const activeProjects = overviewQuery.data?.activeProjects ?? [];
  const currentItem = overviewQuery.data?.item ?? null;
  const marketProjectId = currentItem?.id ?? null;
  const marketStatus = String(currentItem?.projectedStatus || currentItem?.status || "");
  const marketRefreshMs = marketRefreshIntervalMs(marketStatus, currentItem?.recommendedRefreshMs);
  const marketQuery = useQuery({
    queryKey:
      marketProjectId !== null
        ? viewer === "admin"
          ? queryKeys.adminProjectMarket(marketProjectId)
          : queryKeys.appProjectMarket(marketProjectId)
        : ["project-market", "idle"],
    queryFn: () => {
      if (marketProjectId === null) {
        throw new Error("project market requires a project id");
      }
      return viewer === "admin"
        ? dashboardApi.admin.getProjectMarket(marketProjectId)
        : dashboardApi.app.getProjectMarket(marketProjectId);
    },
    enabled: Boolean(currentItem && marketProjectId !== null),
    staleTime: marketStaleTimeMs(marketStatus),
    refetchInterval: currentItem && marketProjectId !== null ? marketRefreshMs : false,
    refetchIntervalInBackground: false,
    gcTime: 60_000,
  });
  const displayItem = useMemo(
    () =>
      currentItem && marketQuery.data
        ? {
            ...currentItem,
            tokenPriceV: marketQuery.data.tokenPriceV,
            tokenPriceUsd: marketQuery.data.tokenPriceUsd,
            virtualPriceUsd: marketQuery.data.virtualPriceUsd,
            liveFdvUsd: marketQuery.data.liveFdvUsd,
            marketPriceSource: marketQuery.data.marketPriceSource ?? undefined,
            marketPriceStale: marketQuery.data.marketPriceStale ?? undefined,
            marketPriceMode: marketQuery.data.marketPriceMode ?? undefined,
            marketPriceLabel: marketQuery.data.marketPriceLabel ?? undefined,
            recommendedRefreshMs: marketQuery.data.recommendedRefreshMs ?? undefined,
            marketCacheTtlMs: marketQuery.data.marketCacheTtlMs ?? undefined,
            marketCacheHit: marketQuery.data.marketCacheHit ?? undefined,
            priceUpdatedAt: marketQuery.data.priceUpdatedAt ?? undefined,
            priceLatencyMs: marketQuery.data.priceLatencyMs ?? undefined,
            priceBlockNumber: marketQuery.data.priceBlockNumber ?? undefined,
            buyTaxRate: marketQuery.data.buyTaxRate ?? undefined,
            buyTaxRateSource: marketQuery.data.buyTaxRateSource ?? undefined,
            predictedBuyTaxRate: marketQuery.data.predictedBuyTaxRate ?? undefined,
            observedBuyTaxRate: marketQuery.data.observedBuyTaxRate ?? undefined,
            observedBuyTaxRateRaw: marketQuery.data.observedBuyTaxRateRaw ?? undefined,
            observedBuyTaxAt: marketQuery.data.observedBuyTaxAt ?? undefined,
            observedBuyTaxAgeSec: marketQuery.data.observedBuyTaxAgeSec ?? undefined,
            observedBuyTaxFresh: marketQuery.data.observedBuyTaxFresh ?? undefined,
            observedBuyTaxFreshSec: marketQuery.data.observedBuyTaxFreshSec ?? undefined,
            observedBuyTaxSamples: marketQuery.data.observedBuyTaxSamples ?? undefined,
            taxEvidenceStatus: marketQuery.data.taxEvidenceStatus ?? undefined,
            taxEvidenceDivergencePct: marketQuery.data.taxEvidenceDivergencePct ?? undefined,
            taxConfigKnown: marketQuery.data.taxConfigKnown ?? undefined,
            taxConfigStatus: marketQuery.data.taxConfigStatus ?? undefined,
            taxConfigWarning: marketQuery.data.taxConfigWarning ?? undefined,
            taxScheduleDurationValue: marketQuery.data.taxScheduleDurationValue ?? undefined,
            taxScheduleUnitSeconds: marketQuery.data.taxScheduleUnitSeconds ?? undefined,
            taxStartAt: marketQuery.data.taxStartAt ?? undefined,
            taxEndAt: marketQuery.data.taxEndAt ?? undefined,
            antiSniperTaxType: marketQuery.data.antiSniperTaxType ?? undefined,
            launchMode: marketQuery.data.launchMode ?? undefined,
            launchModeLabel: marketQuery.data.launchModeLabel ?? undefined,
            launchModeRaw: marketQuery.data.launchModeRaw ?? undefined,
            isRobotics: marketQuery.data.isRobotics ?? undefined,
            isProject60days: marketQuery.data.isProject60days ?? undefined,
            airdropPercent: marketQuery.data.airdropPercent ?? undefined,
            virtualsStatus: marketQuery.data.virtualsStatus ?? undefined,
            virtualsFactory: marketQuery.data.virtualsFactory ?? undefined,
            virtualsCategory: marketQuery.data.virtualsCategory ?? undefined,
            estimatedFdvUsdWithTax: marketQuery.data.estimatedFdvUsdWithTax ?? undefined,
            estimatedFdvWanUsdWithTax: marketQuery.data.estimatedFdvWanUsdWithTax ?? undefined,
          }
        : currentItem,
    [currentItem, marketQuery.data],
  );
  const replayControlEnabled = viewer === "admin" && isReplayControlCandidate();
  const replayStatusQuery = useQuery({
    queryKey: queryKeys.replayStatus,
    queryFn: dashboardApi.replay.getStatus,
    enabled: replayControlEnabled,
    retry: false,
    staleTime: 0,
    refetchInterval: (query) => ((query.state.data as ReplayStatusResponse | undefined)?.ok ? 500 : false),
    refetchIntervalInBackground: false,
  });
  const replayControlMutation = useMutation({
    mutationFn: async ({
      action,
      speed,
    }: {
      action: "start" | "pause" | "resume" | "speed" | "reset";
      speed?: number;
    }) => dashboardApi.replay.control(action, speed),
    onSuccess: async () => {
      const invalidations = [queryClient.invalidateQueries({ queryKey: queryKeys.replayStatus })];
      if (detailProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.adminProjectOverview(detailProjectId) }));
      }
      if (marketProjectId !== null) {
        invalidations.push(queryClient.invalidateQueries({ queryKey: queryKeys.adminProjectMarket(marketProjectId) }));
      }
      await Promise.all(invalidations);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const replayControl = replayControlEnabled ? (
    <ReplayControlPanel
      status={replayStatusQuery.data}
      pending={replayControlMutation.isPending}
      onAction={(action, speed) => void replayControlMutation.mutateAsync({ action, speed })}
    />
  ) : null;

  useEffect(() => {
    if (displayItem && displayItem.name !== selectedProject) {
      setSelectedProject(displayItem.name);
    }
  }, [displayItem, selectedProject, setSelectedProject]);

  if (hasInvalidProjectId) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Projects"
          title="项目详情"
          description="当前链接里的项目编号不正确。"
          actions={
            <Button asChild variant="secondary">
              <Link to={projectsHref}>回项目列表</Link>
            </Button>
          }
        />
        <EmptyState
          title="项目编号无效"
          description="请从项目列表重新进入需要查看的项目。"
        />
      </div>
    );
  }

  if (!meta || overviewQuery.isLoading) {
    return <LoadingState label={isProjectDetailView ? "正在加载项目详情..." : "正在加载实时看板..."} />;
  }

  if (lockedDetails && lockedProject) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={isProjectDetailView ? "Projects" : "Overview"}
          title={
            isProjectDetailView
              ? `${lockedProject.name} · 解锁后查看项目详情`
              : `${lockedProject.name} · 解锁后查看实时看板`
          }
          description={
            isProjectDetailView
              ? "这个项目的历史盘面已经准备好了，但完整详情还没解锁。"
              : "这个项目已经进入观察窗口，但完整盘面还没解锁。"
          }
          actions={
            <>
              <Button
                onClick={() => {
                  if (!confirmProjectUnlock(lockedProject.name, lockedDetails.access.unlockCost)) return;
                  void unlockMutation.mutateAsync();
                }}
                disabled={!lockedDetails.access.canUnlockNow || unlockMutation.isPending}
              >
                <LockKeyhole className="size-4" />
                解锁项目详情
              </Button>
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                <WalletCards className="size-4" />
                去充值页
              </Button>
            </>
          }
        />

        <section className="surface-hero-strong overflow-hidden rounded-[32px] border border-white/60 p-6">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="warning">未解锁</Badge>
            <Badge variant="secondary">首次解锁扣 {lockedDetails.access.unlockCost} 积分</Badge>
          </div>
          <h2 className="mt-4 text-3xl font-semibold tracking-[-0.05em]">{lockedProject.name}</h2>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">开始时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">{formatDateTime(lockedProject.startAt)}</div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">结束时间</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {formatDateTime(lockedProject.resolvedEndAt)}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">当前积分</div>
              <div className="mt-2 text-lg font-semibold tracking-[-0.03em]">
                {lockedDetails.access.creditBalance}
              </div>
            </div>
            <div className="rounded-[22px] border border-border/80 bg-[color:var(--surface-soft)] px-4 py-4">
              <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">详情链接</div>
              <div className="mt-2 truncate text-sm">
                {lockedProject.detailUrl ? (
                  <a className="text-primary hover:underline" href={lockedProject.detailUrl} target="_blank" rel="noreferrer">
                    打开项目详情
                  </a>
                ) : (
                  "未填写"
                )}
              </div>
            </div>
          </div>
        </section>

        <EmptyState
          title={lockedDetails.access.canUnlockNow ? "解锁后就能查看完整盘面" : "当前积分不足"}
          description={
            lockedDetails.access.canUnlockNow
              ? "确认扣除积分后，这个项目的分钟图、大户榜和追踪钱包持仓以后都能直接打开。"
              : `当前剩余 ${lockedDetails.access.creditBalance} 积分，不足以解锁该项目。先去充值页补分，再回来解锁就行。`
          }
          action={
            <div className="flex flex-wrap gap-3">
              {lockedDetails.access.canUnlockNow ? (
                <Button
                  onClick={() => {
                    if (!confirmProjectUnlock(lockedProject.name, lockedDetails.access.unlockCost)) return;
                    void unlockMutation.mutateAsync();
                  }}
                  disabled={unlockMutation.isPending}
                >
                  <LockKeyhole className="size-4" />
                  确认解锁
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void navigate("/app/billing")}>
                去充值页
              </Button>
              <Button asChild variant="ghost">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  if (overviewQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={isProjectDetailView ? "Projects" : "Overview"}
          title={isProjectDetailView ? "项目详情" : "实时发射看板"}
          description={isProjectDetailView ? "当前无法读取项目详情聚合数据。" : "当前无法读取活跃项目聚合数据。"}
          actions={
            <>
              {isProjectDetailView ? (
                <Button asChild variant="ghost">
                  <Link to={projectsHref}>回项目列表</Link>
                </Button>
              ) : null}
              <Button variant="secondary" onClick={() => void refreshAll()}>
                立即刷新
              </Button>
            </>
          }
        />
        <EmptyState
          title={isProjectDetailView ? "项目详情接口异常" : "实时看板接口异常"}
          description={
            isProjectDetailView
              ? viewer === "admin"
                ? "请检查 `/api/admin/projects/{id}/overview` 是否可访问，以及该项目是否仍存在于受管项目列表中。"
                : "请检查 `/api/app/projects/{id}/overview` 是否可访问，以及当前项目是否仍在公开可读列表中。"
              : viewer === "admin"
                ? "请检查 `/api/admin/overview-active` 是否可访问，以及当前 writer 实例是否正常返回活跃项目聚合数据。"
                : "请检查 `/api/app/overview-active` 是否可访问，以及当前用户是否已有可读项目。"
          }
        />
      </div>
    );
  }

  if (isProjectDetailView) {
    if (!currentItem) {
      return (
        <div className="space-y-6">
          <PageHeader
            eyebrow="Projects"
            title="项目详情"
            description="这个项目当前没有可展示的详情数据。"
            actions={
              <Button asChild variant="secondary">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            }
          />
          <EmptyState
            title="项目详情不存在"
            description="项目可能已被移除，或者当前账号没有访问权限。"
          />
        </div>
      );
    }
    const detailItem = displayItem ?? currentItem;

    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Projects"
          title={`${detailItem.name} · ${detailPageTitle(detailItem.projectedStatus || detailItem.status)}`}
          description={
            viewer === "admin"
              ? "这里保留项目在整个发射窗口内的分钟消耗、大户榜、追踪钱包和录入延迟，方便管理员复盘。"
              : "这里保留项目在整个发射窗口内的分钟消耗、大户榜、追踪钱包和录入延迟，方便第二天回看。"
          }
          actions={
            <>
              <Badge variant={detailStatusVariant(detailItem.projectedStatus || detailItem.status)}>
                {detailStatusLabel(detailItem.projectedStatus || detailItem.status)}
              </Badge>
              <span className="self-center text-sm text-muted-foreground">
                发射窗口 {formatDateTime(detailItem.startAt)} - {formatDateTime(detailItem.resolvedEndAt)}
              </span>
            </>
          }
        />

        {replayControl}

        {viewer === "admin" ? (
          <>
            <LaunchStrategyControlPanel
              data={launchStrategyConfigQuery.data}
              form={launchStrategyForm}
              pending={launchStrategyConfigMutation.isPending}
              onChange={(patch) => setLaunchStrategyDraft((prev) => ({ ...prev, ...patch }))}
              onSave={saveLaunchStrategyConfig}
            />
            <LaunchSellControlPanel
              data={launchSellConfigQuery.data}
              form={launchSellForm}
              pending={launchSellConfigMutation.isPending}
              onChange={(patch) => setLaunchSellDraft((prev) => ({ ...prev, ...patch }))}
              onSave={saveLaunchSellConfig}
            />
          </>
        ) : null}

        <ProjectOverviewSections
          item={detailItem}
          minutes={overviewQuery.data?.minutes ?? []}
          whaleBoard={overviewQuery.data?.whaleBoard ?? []}
          trackedWallets={overviewQuery.data?.trackedWallets ?? []}
          delays={overviewQuery.data?.delays ?? []}
          canManageTeamOverrides={viewer === "admin"}
          teamOverridePendingWallet={teamOverridePendingWallet}
          onSetTeamOverride={setTeamOverride}
          actions={
            <>
              {isRealtimeStatus(detailItem.projectedStatus || detailItem.status) ? (
                <Button asChild variant="outline">
                  <Link
                    to={
                      viewer === "admin"
                        ? `/admin/overview?project=${encodeURIComponent(detailItem.name)}`
                        : `/app/overview?project=${encodeURIComponent(detailItem.name)}`
                    }
                  >
                    切回实时看板
                  </Link>
                </Button>
              ) : null}
              <Button asChild variant="secondary">
                <Link to={projectsHref}>回项目列表</Link>
              </Button>
            </>
          }
        />
      </div>
    );
  }

  if (!overviewQuery.data?.hasActiveProject || !activeProjects.length) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow="Overview"
          title="实时发射看板"
          description="只展示预热中或发射中的项目。"
          actions={
            <Button asChild variant="secondary">
              <Link to={projectsHref}>去项目列表</Link>
            </Button>
          }
        />
        <EmptyState
          title="当前没有活跃项目"
          description="当项目进入预热或正式发射阶段，这里会自动出现实时数据。现在可以先去项目列表挑你想关注的目标。"
        />
      </div>
    );
  }

  if (!currentItem) {
    return <LoadingState label="正在定位活跃项目..." />;
  }
  const activeItem = displayItem ?? currentItem;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Overview"
        title={`${activeItem.name} · 实时发射看板`}
        description="这里集中看正在发射项目的资金变化、大户榜和你的钱包持仓。"
        actions={
          <>
            <Badge variant={detailStatusVariant(activeItem.projectedStatus || activeItem.status)}>
              {detailStatusLabel(activeItem.projectedStatus || activeItem.status)}
            </Badge>
            <div className="min-w-[240px]">
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                活跃项目
              </div>
              <Select value={activeItem.name} onChange={(event) => setSelectedProject(event.target.value)}>
                {activeProjects.map((item) => (
                  <option key={item.id} value={item.name}>
                    {item.name}
                  </option>
                ))}
              </Select>
            </div>
            <Button variant="secondary" onClick={() => void refreshAll()}>
              立即刷新
            </Button>
          </>
        }
      />

      {replayControl}

      <ProjectOverviewSections
        item={activeItem}
        minutes={overviewQuery.data?.minutes ?? []}
        whaleBoard={overviewQuery.data?.whaleBoard ?? []}
        trackedWallets={overviewQuery.data?.trackedWallets ?? []}
        delays={overviewQuery.data?.delays ?? []}
        canManageTeamOverrides={viewer === "admin"}
        teamOverridePendingWallet={teamOverridePendingWallet}
        onSetTeamOverride={setTeamOverride}
        actions={
          <Button asChild variant="secondary">
            <Link to={projectsHref}>回项目列表</Link>
          </Button>
        }
      />
    </div>
  );
}
