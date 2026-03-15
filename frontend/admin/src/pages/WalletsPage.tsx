import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PencilLine, RefreshCcw, Trash2, Wallet2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useShell } from "@/app/shell-context";
import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "@/components/app-primitives";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatAddress, formatCompactNumber, formatCurrency, formatDateTime } from "@/lib/format";
import type { UserWalletItem, WalletConfigItem } from "@/types/api";

function isUserWalletItem(item: WalletConfigItem | UserWalletItem): item is UserWalletItem {
  return "id" in item;
}

export function WalletsPage() {
  const queryClient = useQueryClient();
  const { viewer, meta, selectedProject } = useShell();
  const isAdmin = viewer === "admin";
  const [walletInput, setWalletInput] = useState("");
  const [walletNameInput, setWalletNameInput] = useState("");
  const [editingWallet, setEditingWallet] = useState<number | string>("");

  const walletConfigsQuery = useQuery({
    queryKey: isAdmin ? queryKeys.walletConfigs : queryKeys.userWalletConfigs,
    queryFn: () => (isAdmin ? dashboardApi.admin.getWalletConfigs() : dashboardApi.app.getWallets()),
  });

  const walletPositionsQuery = useQuery({
    queryKey: isAdmin ? queryKeys.wallets(selectedProject) : queryKeys.userWallets(selectedProject),
    queryFn: () =>
      isAdmin
        ? dashboardApi.admin.getWallets(selectedProject)
        : dashboardApi.app.getWalletPositions(selectedProject),
    enabled: Boolean(selectedProject),
  });

  const addWalletMutation = useMutation({
    mutationFn: async (): Promise<unknown> => {
      if (isAdmin) {
        return dashboardApi.admin.addWallet(walletInput.trim(), walletNameInput.trim());
      }
      if (editingWallet) {
        return dashboardApi.app.updateWallet(Number(editingWallet), { name: walletNameInput.trim() });
      }
      return dashboardApi.app.addWallet(walletInput.trim(), walletNameInput.trim());
    },
    onSuccess: async () => {
      toast.success(editingWallet ? "钱包名称已更新。" : "钱包已添加。");
      setWalletInput("");
      setWalletNameInput("");
      setEditingWallet("");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: isAdmin ? queryKeys.walletConfigs : queryKeys.userWalletConfigs,
        }),
        queryClient.invalidateQueries({ queryKey: isAdmin ? ["wallets"] : ["user-wallets"] }),
        queryClient.invalidateQueries({ queryKey: isAdmin ? queryKeys.meta : queryKeys.appMeta }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deleteWalletMutation = useMutation({
    mutationFn: (wallet: string | number) =>
      isAdmin ? dashboardApi.admin.deleteWallet(String(wallet)) : dashboardApi.app.deleteWallet(Number(wallet)),
    onSuccess: async () => {
      toast.success("钱包已删除。");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: isAdmin ? queryKeys.walletConfigs : queryKeys.userWalletConfigs,
        }),
        queryClient.invalidateQueries({ queryKey: isAdmin ? ["wallets"] : ["user-wallets"] }),
        queryClient.invalidateQueries({ queryKey: isAdmin ? queryKeys.meta : queryKeys.appMeta }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const recalcMutation = useMutation({
    mutationFn: (wallet: string) => dashboardApi.admin.recalcWallet(selectedProject, wallet),
    onSuccess: async (result) => {
      toast.success(`已重算 ${formatAddress(result.wallet)}，耗时 ${result.durationMs}ms`);
      await queryClient.invalidateQueries({ queryKey: queryKeys.wallets(selectedProject) });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (!meta) {
    return <LoadingState />;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Wallets"
        title={isAdmin ? "监控钱包" : "我的钱包"}
        description={
          isAdmin
            ? "统一管理全局追踪钱包的地址与名称，并保留当前项目的钱包持仓快照。"
            : "先把自己的钱包加进来，之后看项目时就能立刻知道自己有没有进场。"
        }
      />

      <SectionCard
        title="钱包配置"
        description={isAdmin ? "保存到本地数据库的监控钱包列表。" : "这里只保存你自己的钱包，不会被其他用户看到。"}
        actions={
          <div className="flex flex-wrap gap-2">
            <Input
              placeholder="钱包名称"
              value={walletNameInput}
              onChange={(event) => setWalletNameInput(event.target.value)}
            />
            <Input
              placeholder="监控钱包 0x..."
              value={walletInput}
              readOnly={Boolean(editingWallet)}
              onChange={(event) => setWalletInput(event.target.value)}
            />
            <Button onClick={() => void addWalletMutation.mutate()} disabled={!walletInput.trim()}>
              {editingWallet ? "保存名称" : "添加钱包"}
            </Button>
            {editingWallet ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setEditingWallet("");
                  setWalletInput("");
                  setWalletNameInput("");
                }}
              >
                <X className="size-4" />
                取消
              </Button>
            ) : null}
          </div>
        }
      >
        {walletConfigsQuery.data?.items.length ? (
          <div className="flex flex-wrap gap-3">
            {walletConfigsQuery.data.items.map((item) => (
              <div
                key={isUserWalletItem(item) ? `${item.id}-${item.wallet}` : item.wallet}
                className="flex items-center gap-3 rounded-full border border-border bg-white/80 px-4 py-3"
              >
                <Wallet2 className="size-4 text-primary" />
                <div>
                  <div className="text-sm font-medium">{item.name || "未命名钱包"}</div>
                  <div className="font-mono text-xs text-muted-foreground">{item.wallet}</div>
                </div>
                <button
                  className="rounded-full p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  onClick={() => {
                    setEditingWallet(isUserWalletItem(item) ? item.id : item.wallet);
                    setWalletInput(item.wallet);
                    setWalletNameInput(item.name || "");
                  }}
                  title="编辑钱包名称"
                >
                  <PencilLine className="size-4" />
                </button>
                <button
                  className="rounded-full p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  onClick={() => void deleteWalletMutation.mutate(isUserWalletItem(item) ? item.id : item.wallet)}
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState compact title="还没有钱包" description="先添加自己的钱包，后面看项目时才能直接看到持仓变化。" />
        )}
      </SectionCard>

      <SectionCard
        title="当前项目持仓"
        description={selectedProject ? `${selectedProject} 下的钱包仓位快照` : "请选择项目查看持仓"}
      >
        {selectedProject ? (
          walletPositionsQuery.data?.items.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>钱包</TableHead>
                  <TableHead>Token</TableHead>
                  <TableHead>Spent</TableHead>
                  <TableHead>Token Bought</TableHead>
                  <TableHead>更新时间</TableHead>
                  {isAdmin ? <TableHead className="text-right">操作</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {walletPositionsQuery.data.items.map((row) => (
                  <TableRow key={`${row.project}-${row.wallet}-${row.token_addr}`}>
                    <TableCell className="font-mono">{formatAddress(row.wallet)}</TableCell>
                    <TableCell className="font-mono">{formatAddress(row.token_addr)}</TableCell>
                    <TableCell>{formatCurrency(row.sum_spent_v_est)}</TableCell>
                    <TableCell>{formatCompactNumber(row.sum_token_bought)}</TableCell>
                    <TableCell>{formatDateTime(row.updated_at)}</TableCell>
                    {isAdmin ? (
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => void recalcMutation.mutate(row.wallet)}
                        >
                          <RefreshCcw className="size-4" />
                          重算
                        </Button>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              compact
              title="当前项目暂无钱包持仓"
              description={
                isAdmin
                  ? "可以先回到 Projects 或 Inbox 导入项目，或者等待新的钱包事件进入数据库。"
                  : "你可以先添加自己的钱包，或者等当前项目出现新的持仓数据。"
              }
            />
          )
        ) : (
          <EmptyState compact title="先选一个项目" description="顶部项目切换器会决定这里展示哪一个项目的钱包仓位。" />
        )}
      </SectionCard>
    </div>
  );
}
