import {
  BellDot,
  ChevronRight,
  LogOut,
  Menu,
  MoonStar,
  RefreshCcw,
  SunMedium,
  type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useDesignTheme } from "@/design-system/theme/use-theme";
import { cn } from "@/lib/utils";

export type VisualSidebarMode = "expanded" | "rail" | "hidden";

export type VisualNavItem = {
  key: string;
  label: string;
  icon?: LucideIcon;
  href?: string;
  active?: boolean;
  badge?: string | number;
  onSelect?: () => void;
};

export type VisualProjectOption = {
  value: string;
  label: string;
};

export type VisualStatusPill = {
  label: string;
  tone?: "default" | "secondary" | "success" | "warning" | "danger";
};

export type VisualNotificationItem = {
  key: string;
  title: string;
  body: string;
  timestamp?: string;
  unread?: boolean;
  onRead?: () => void;
};

export type VisualShellProps = {
  title: string;
  brandTitle?: string;
  brandSubtitle?: string;
  brandLogoSrc?: string;
  navItems: VisualNavItem[];
  children: ReactNode;
  sidebarMode?: VisualSidebarMode;
  onSidebarModeChange?: (mode: VisualSidebarMode) => void;
  projectLabel?: string;
  projectOptions?: VisualProjectOption[];
  selectedProject?: string;
  onProjectChange?: (project: string) => void;
  systemPills?: VisualStatusPill[];
  currentUserLabel?: string;
  lastRefreshLabel?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
  onLogout?: () => void;
  notifications?: VisualNotificationItem[];
  onMarkAllNotificationsRead?: () => void;
};

function nextSidebarMode(mode: VisualSidebarMode): VisualSidebarMode {
  if (mode === "expanded") return "rail";
  if (mode === "rail") return "hidden";
  return "expanded";
}

function BrandBlock({
  title,
  subtitle,
  logoSrc,
  mode,
}: {
  title: string;
  subtitle?: string;
  logoSrc: string;
  mode: Exclude<VisualSidebarMode, "hidden">;
}) {
  const compact = mode === "rail";
  return (
    <div className={cn("flex items-center gap-4", compact && "justify-center")}>
      <div className="theme-brand-badge flex size-14 shrink-0 items-center justify-center rounded-[20px]">
        <img src={logoSrc} alt={title} className="size-10 rounded-[12px] object-cover" />
      </div>
      {compact ? null : (
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-primary/80">
            {subtitle || "Design System"}
          </div>
          <div className="text-xl font-semibold tracking-[-0.04em]">{title}</div>
        </div>
      )}
    </div>
  );
}

function NavList({
  items,
  mode,
  onNavigate,
}: {
  items: VisualNavItem[];
  mode: Exclude<VisualSidebarMode, "hidden">;
  onNavigate?: () => void;
}) {
  const compact = mode === "rail";
  return (
    <div className="space-y-2">
      {items.map((item) => {
        const Icon = item.icon;
        const content = (
          <>
            <span className={cn("flex items-center gap-3", compact && "justify-center")}>
              {Icon ? <Icon className="size-4 shrink-0" /> : null}
              {compact ? null : item.label}
            </span>
            {!compact && item.badge !== undefined ? (
              <Badge variant={item.active ? "success" : "secondary"}>{item.badge}</Badge>
            ) : null}
          </>
        );
        const className = cn(
          "group flex items-center rounded-[22px] text-sm font-medium transition",
          compact ? "justify-center px-3 py-3" : "justify-between px-4 py-3",
          item.active
            ? "bg-[color:var(--surface-soft-strong)] text-foreground shadow-sm"
            : "text-muted-foreground hover:bg-[color:var(--surface-soft)] hover:text-foreground",
        );
        if (item.href) {
          return (
            <a key={item.key} href={item.href} title={item.label} onClick={onNavigate} className={className}>
              {content}
            </a>
          );
        }
        return (
          <button
            key={item.key}
            type="button"
            title={item.label}
            onClick={() => {
              item.onSelect?.();
              onNavigate?.();
            }}
            className={className}
          >
            {content}
          </button>
        );
      })}
    </div>
  );
}

function SidebarPanel({
  title,
  subtitle,
  logoSrc,
  items,
  mode,
}: {
  title: string;
  subtitle?: string;
  logoSrc: string;
  items: VisualNavItem[];
  mode: Exclude<VisualSidebarMode, "hidden">;
}) {
  return (
    <aside
      className={cn(
        "flex h-full flex-col gap-6 rounded-[30px] border border-white/50 bg-sidebar/80 shadow-[0_28px_60px_rgba(108,140,126,0.12)]",
        "surface-panel shadow-[var(--shadow-strong)]",
        mode === "expanded" ? "p-5" : "items-center p-3",
      )}
    >
      <BrandBlock title={title} subtitle={subtitle} logoSrc={logoSrc} mode={mode} />
      <div className="w-full">
        <NavList items={items} mode={mode} />
      </div>
    </aside>
  );
}

function NotificationDrawer({
  items,
  open,
  onOpenChange,
  onMarkAllNotificationsRead,
}: {
  items: VisualNotificationItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onMarkAllNotificationsRead?: () => void;
}) {
  const unreadCount = items.filter((item) => item.unread).length;
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="px-0 py-0">
        <div className="flex h-full min-h-0 flex-col">
          <div className="border-b border-border px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">提醒中心</div>
                <div className="mt-1 text-sm text-muted-foreground">未读 {unreadCount} 条。</div>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={onMarkAllNotificationsRead}
                disabled={unreadCount <= 0 || !onMarkAllNotificationsRead}
              >
                全部已读
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">
            {items.length ? (
              <div className="space-y-3">
                {items.map((item) => (
                  <div
                    key={item.key}
                    className={cn(
                      "rounded-[22px] border px-4 py-4 shadow-sm",
                      item.unread
                        ? "theme-status-unread border-primary/30"
                        : "border-border bg-[color:var(--surface-soft)]",
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Badge variant={item.unread ? "success" : "secondary"}>
                          {item.unread ? "未读" : "已读"}
                        </Badge>
                        <div className="text-sm font-medium">{item.title}</div>
                      </div>
                      {item.unread && item.onRead ? (
                        <Button variant="ghost" size="sm" onClick={item.onRead}>
                          标记已读
                        </Button>
                      ) : null}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                    {item.timestamp ? (
                      <div className="mt-3 text-xs text-muted-foreground">{item.timestamp}</div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-[22px] border border-dashed border-border surface-empty px-4 py-6 text-sm text-muted-foreground">
                当前没有新的提醒。
              </div>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function VisualShell({
  title,
  brandTitle = "Virtuals Whale Radar",
  brandSubtitle = "Design System",
  brandLogoSrc = "/admin/brand/logo-mark.png",
  navItems,
  children,
  sidebarMode,
  onSidebarModeChange,
  projectLabel = "当前项目",
  projectOptions = [],
  selectedProject = "",
  onProjectChange,
  systemPills = [],
  currentUserLabel,
  lastRefreshLabel,
  onRefresh,
  isRefreshing = false,
  primaryAction,
  secondaryActions,
  onLogout,
  notifications = [],
  onMarkAllNotificationsRead,
}: VisualShellProps) {
  const { theme, toggleTheme } = useDesignTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [internalSidebarMode, setInternalSidebarMode] = useState<VisualSidebarMode>(
    sidebarMode ?? "expanded",
  );
  const resolvedSidebarMode = sidebarMode ?? internalSidebarMode;
  const shellGridClass = useMemo(() => {
    if (resolvedSidebarMode === "expanded") return "lg:grid-cols-[300px_minmax(0,1fr)]";
    if (resolvedSidebarMode === "rail") return "lg:grid-cols-[96px_minmax(0,1fr)]";
    return "lg:grid-cols-[minmax(0,1fr)]";
  }, [resolvedSidebarMode]);
  const unreadCount = notifications.filter((item) => item.unread).length;

  const setSidebarMode = (mode: VisualSidebarMode) => {
    onSidebarModeChange?.(mode);
    if (sidebarMode === undefined) setInternalSidebarMode(mode);
  };

  return (
    <div className="min-h-screen px-4 py-4 lg:px-6 lg:py-6">
      <div className={cn("mx-auto grid max-w-[1800px] gap-5", shellGridClass)}>
        {resolvedSidebarMode !== "hidden" ? (
          <div className="hidden lg:block">
            <SidebarPanel
              title={brandTitle}
              subtitle={brandSubtitle}
              logoSrc={brandLogoSrc}
              items={navItems}
              mode={resolvedSidebarMode}
            />
          </div>
        ) : null}

        <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-5">
          <Card className="surface-glass sticky top-4 z-20 rounded-[28px] p-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px_auto] xl:items-center">
              <div className="flex min-w-0 items-center gap-3">
                <Button
                  className="hidden lg:inline-flex"
                  variant="secondary"
                  size="icon"
                  onClick={() => setSidebarMode(nextSidebarMode(resolvedSidebarMode))}
                  title={`切换侧栏，当前为 ${resolvedSidebarMode}`}
                >
                  <Menu className="size-4" />
                </Button>
                <Button className="lg:hidden" variant="secondary" size="icon" onClick={() => setMobileOpen(true)}>
                  <Menu className="size-4" />
                </Button>
                <div className="theme-brand-badge flex size-11 shrink-0 items-center justify-center rounded-[18px]">
                  <img src={brandLogoSrc} alt={brandTitle} className="size-7 rounded-[10px] object-cover" />
                </div>
                <div className="hidden min-w-0 sm:block">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary/80">
                    {brandTitle}
                  </div>
                  <div className="text-sm font-semibold tracking-[-0.03em]">{title}</div>
                </div>
              </div>

              <div className="grid gap-3">
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    {projectLabel}
                  </div>
                  <Select value={selectedProject} onChange={(event) => onProjectChange?.(event.target.value)}>
                    {projectOptions.length ? (
                      projectOptions.map((project) => (
                        <option key={project.value} value={project.value}>
                          {project.label}
                        </option>
                      ))
                    ) : (
                      <option value="">暂无项目</option>
                    )}
                  </Select>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                {systemPills.map((pill) => (
                  <Badge key={pill.label} variant={pill.tone || "secondary"}>
                    {pill.label}
                  </Badge>
                ))}
                {notifications.length ? (
                  <Button variant="outline" className="relative" onClick={() => setNotificationsOpen(true)}>
                    <BellDot className="size-4" />
                    提醒
                    {unreadCount > 0 ? (
                      <span className="absolute -right-2 -top-2 inline-flex min-w-6 items-center justify-center rounded-full bg-primary px-1.5 py-0.5 text-[11px] font-semibold text-white">
                        {unreadCount}
                      </span>
                    ) : null}
                  </Button>
                ) : null}
                {(currentUserLabel || lastRefreshLabel) ? (
                  <div className="hidden text-right text-xs text-muted-foreground sm:block">
                    {currentUserLabel ? <div>{currentUserLabel}</div> : null}
                    {lastRefreshLabel ? <div>{lastRefreshLabel}</div> : null}
                  </div>
                ) : null}
                <Button
                  variant="outline"
                  className="theme-toggle-button"
                  onClick={toggleTheme}
                  title={theme === "light" ? "切换到深色模式" : "切换到浅色模式"}
                >
                  {theme === "light" ? <MoonStar className="size-4" /> : <SunMedium className="size-4" />}
                  {theme === "light" ? "深色模式" : "浅色模式"}
                </Button>
                {onRefresh ? (
                  <Button variant="outline" onClick={onRefresh} disabled={isRefreshing}>
                    <RefreshCcw className={cn("size-4", isRefreshing && "animate-spin")} />
                    刷新
                  </Button>
                ) : null}
                {secondaryActions}
                {primaryAction}
                {onLogout ? (
                  <Button variant="ghost" onClick={onLogout}>
                    <LogOut className="size-4" />
                    退出
                  </Button>
                ) : null}
              </div>
            </div>
          </Card>

          <main className="flex-1">
            <div className="space-y-6 animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
              {children}
            </div>
          </main>
        </div>
      </div>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent className="overflow-y-auto bg-sidebar/95">
          <div className="space-y-6 pt-12">
            <BrandBlock title={brandTitle} subtitle={brandSubtitle} logoSrc={brandLogoSrc} mode="expanded" />
            <NavList items={navItems} mode="expanded" onNavigate={() => setMobileOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>

      <NotificationDrawer
        items={notifications}
        open={notificationsOpen}
        onOpenChange={setNotificationsOpen}
        onMarkAllNotificationsRead={onMarkAllNotificationsRead}
      />
    </div>
  );
}

export function VisualShellLink({
  label,
  href,
}: {
  label: string;
  href: string;
}) {
  return (
    <a
      href={href}
      className="inline-flex items-center gap-1 text-sm font-medium text-primary transition hover:opacity-80"
    >
      {label}
      <ChevronRight className="size-4" />
    </a>
  );
}
