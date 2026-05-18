import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, WalletCards } from "lucide-react";
import { toast } from "sonner";

import { queryKeys } from "@/api/query-keys";
import { Button, type ButtonProps } from "@/components/ui/button";
import { signInWithWallet, walletSourceLabel } from "@/lib/base-wallet";
import { cn } from "@/lib/utils";
import type { AuthMeResponse, AuthSuccessResponse, WalletAuthSource } from "@/types/api";

interface BaseSignInButtonProps {
  className?: string;
  label?: string;
  source?: WalletAuthSource;
  variant?: ButtonProps["variant"];
  size?: ButtonProps["size"];
  onSuccess?: (result: AuthSuccessResponse) => void | Promise<void>;
}

export function BaseSignInButton({
  className,
  label,
  source = "base_wallet",
  variant = "default",
  size = "default",
  onSuccess,
}: BaseSignInButtonProps) {
  const queryClient = useQueryClient();
  const sourceLabel = walletSourceLabel(source);
  const mutation = useMutation({
    mutationFn: () => signInWithWallet(source),
    onSuccess: (result) => {
      queryClient.setQueryData<AuthMeResponse>(queryKeys.authMe, {
        authenticated: true,
        user: result.user,
        home_path: result.home_path,
      });
      toast.success(`${sourceLabel} 登录成功。`);
      void onSuccess?.(result);
      void Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: queryKeys.authMe }),
        queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
        queryClient.invalidateQueries({ queryKey: queryKeys.userWalletConfigs }),
      ]);
    },
    onError: (error: Error) => {
      toast.error(error.message || `${sourceLabel} 登录失败。`);
    },
  });

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={cn("min-w-0", className)}
      onClick={() => void mutation.mutate()}
      disabled={mutation.isPending}
    >
      {mutation.isPending ? <Loader2 className="animate-spin" /> : <WalletCards />}
      <span className="truncate">{mutation.isPending ? "签名中..." : (label ?? `${sourceLabel} 登录`)}</span>
    </Button>
  );
}
