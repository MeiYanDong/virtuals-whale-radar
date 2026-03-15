import type {
  AppMetaResponse,
  DraftProject,
  HealthResponse,
  LaunchConfig,
  MetaResponse,
  MinuteRow,
  SignalHubItem,
} from "@/types/api";

import { compareText, ensureArray } from "@/lib/utils";

export type InboxSyncState =
  | "imported"
  | "draft"
  | "ready"
  | "failed"
  | "unsynced";

export interface InboxListItem extends SignalHubItem {
  syncState: InboxSyncState;
  syncLabel: string;
  syncHint: string;
  matchedConfig?: LaunchConfig;
  draft?: DraftProject;
  sortableLaunchAt: number;
}

type ProjectMeta = MetaResponse | AppMetaResponse;

export function resolveProjectCandidates(meta: ProjectMeta | undefined) {
  if (!meta) return [];
  if ("managedProjects" in meta) {
    return [
      ...ensureArray(meta.managedProjects).map((item) => item.name),
      ...ensureArray(meta.monitoringProjects),
      ...ensureArray(meta.projects),
    ].filter(Boolean);
  }
  return ensureArray(meta.projects).map((item) => item.name).filter(Boolean);
}

export function resolveSelectedProject(meta: ProjectMeta | undefined, selected: string | null) {
  if (!meta) return selected ?? "";
  const candidates = resolveProjectCandidates(meta);
  if (selected && candidates.includes(selected)) return selected;
  return candidates[0] ?? "";
}

export function buildInboxItems(
  response: { items: SignalHubItem[] },
  launchConfigs: LaunchConfig[],
  drafts: Record<string, DraftProject>,
) {
  const configMap = new Map(launchConfigs.map((config) => [config.name.toUpperCase(), config]));

  return ensureArray(response.items)
    .map<InboxListItem>((item) => {
      const key = item.importName.toUpperCase();
      const matchedConfig = configMap.get(key);
      const draft = drafts[item.projectId];
      let syncState: InboxSyncState = "unsynced";
      let syncLabel = "未同步";
      let syncHint = "尚未导入当前监控项目。";

      if (matchedConfig) {
        syncState = "imported";
        syncLabel = "已导入";
        syncHint = `当前已监控 ${matchedConfig.name}。`;
      } else if (item.analysisError) {
        syncState = "failed";
        syncLabel = "导入失败";
        syncHint = item.analysisError;
      } else if (draft) {
        syncState = "draft";
        syncLabel = "草稿待补全";
        syncHint = "已保存草稿，可继续补齐内盘地址后激活。";
      } else if (item.syncReady) {
        syncState = "ready";
        syncLabel = "可导入";
        syncHint = "已识别内盘地址，可直接激活监控。";
      }

      return {
        ...item,
        syncState,
        syncLabel,
        syncHint,
        matchedConfig,
        draft,
        sortableLaunchAt: item.launchTime ? Date.parse(item.launchTime) : Number.MAX_SAFE_INTEGER,
      };
    })
    .sort((a, b) => a.sortableLaunchAt - b.sortableLaunchAt || compareText(a.importName, b.importName));
}

export function sumMinuteSpent(rows: MinuteRow[]) {
  return rows.reduce((total, row) => total + Number(row.minute_spent_v || 0), 0);
}

export function buildMinuteSeries(rows: MinuteRow[]) {
  return rows.map((row) => ({
    minuteKey: row.minute_key,
    spent: Number(row.minute_spent_v || 0),
    fee: Number(row.minute_fee_v || 0),
    tax: Number(row.minute_tax_v || 0),
    buyers: Number(row.minute_unique_buyers || 0),
  }));
}

export function isRuntimeHealthy(health: HealthResponse | undefined) {
  if (!health) return false;
  return Boolean(health.ok) && !health.runtimePaused;
}
