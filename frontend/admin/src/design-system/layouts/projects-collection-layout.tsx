import { ChevronDown, Search, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { EmptyState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export type ProjectCollectionMeta = {
  label: string;
  value: ReactNode;
};

export type ProjectCollectionItem = {
  key: string;
  title: string;
  subtitle?: string;
  statusLabel: string;
  statusTone?: "default" | "secondary" | "success" | "warning" | "danger";
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  summary: ProjectCollectionMeta[];
  details?: ProjectCollectionMeta[];
  actions?: ReactNode;
  defaultExpanded?: boolean;
};

export type ProjectCollectionGroup = {
  key: string;
  title: string;
  description?: string;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  items: ProjectCollectionItem[];
};

export type ProjectsCollectionLayoutProps = {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
  searchPlaceholder?: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  onClearSearch?: () => void;
  resultSummary?: string;
  selectionSummary?: string;
  groups: ProjectCollectionGroup[];
};

function ProjectRow({ item }: { item: ProjectCollectionItem }) {
  const [expanded, setExpanded] = useState(Boolean(item.defaultExpanded));
  return (
    <div className="rounded-[24px] border border-border bg-[color:var(--surface-soft)] p-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="flex min-w-0 flex-1 gap-3">
          {item.onCheckedChange ? (
            <input
              type="checkbox"
              checked={Boolean(item.checked)}
              onChange={(event) => item.onCheckedChange?.(event.target.checked)}
              className="mt-1 size-4 rounded border-border"
            />
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-base font-semibold tracking-[-0.03em]">{item.title}</div>
              <Badge variant={item.statusTone || "secondary"}>{item.statusLabel}</Badge>
            </div>
            {item.subtitle ? (
              <div className="mt-1 text-sm text-muted-foreground">{item.subtitle}</div>
            ) : null}
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              {item.summary.map((meta) => (
                <div key={meta.label}>
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    {meta.label}
                  </div>
                  <div className="mt-1 text-sm font-medium">{meta.value}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {item.actions}
          {item.details?.length ? (
            <Button variant="outline" size="sm" onClick={() => setExpanded((current) => !current)}>
              <ChevronDown className={cn("size-4 transition", expanded && "rotate-180")} />
              {expanded ? "收起" : "展开"}
            </Button>
          ) : null}
        </div>
      </div>

      {expanded && item.details?.length ? (
        <div className="mt-4 grid gap-3 border-t border-border/70 pt-4 md:grid-cols-2 xl:grid-cols-4">
          {item.details.map((meta) => (
            <div key={meta.label}>
              <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                {meta.label}
              </div>
              <div className="mt-1 text-sm font-medium">{meta.value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ProjectsCollectionLayout({
  eyebrow,
  title,
  description,
  actions,
  searchPlaceholder = "搜索项目名称、地址或详情链接",
  searchValue,
  onSearchChange,
  onClearSearch,
  resultSummary,
  selectionSummary,
  groups,
}: ProjectsCollectionLayoutProps) {
  const totalItems = useMemo(
    () => groups.reduce((count, group) => count + group.items.length, 0),
    [groups],
  );

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={eyebrow} title={title} description={description} actions={actions} />

      <SectionCard
        title="项目查找"
        description={resultSummary || `当前共 ${totalItems} 个项目分布在不同分组中。`}
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder}
              className="pl-10 pr-10"
            />
            {searchValue ? (
              <button
                type="button"
                onClick={() => (onClearSearch ? onClearSearch() : onSearchChange(""))}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground transition hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            ) : null}
          </div>
          {selectionSummary ? <Badge variant="secondary">{selectionSummary}</Badge> : null}
        </div>
      </SectionCard>

      {groups.map((group) => (
        <SectionCard
          key={group.key}
          title={group.title}
          description={group.description}
          actions={
            group.onToggleCollapsed ? (
              <Button variant="outline" size="sm" onClick={group.onToggleCollapsed}>
                <ChevronDown className={cn("size-4 transition", group.collapsed && "-rotate-90")} />
                {group.collapsed ? "展开" : "折叠"}
              </Button>
            ) : undefined
          }
        >
          {group.collapsed ? (
            <EmptyState
              compact
              title={`${group.title} 已折叠`}
              description="点击右上角展开按钮，即可查看这一组项目。"
            />
          ) : group.items.length ? (
            <div className="space-y-4">
              {group.items.map((item) => (
                <ProjectRow key={item.key} item={item} />
              ))}
            </div>
          ) : (
            <EmptyState compact title="当前没有项目" description="这一组目前还没有匹配的数据。" />
          )}
        </SectionCard>
      ))}
    </div>
  );
}
