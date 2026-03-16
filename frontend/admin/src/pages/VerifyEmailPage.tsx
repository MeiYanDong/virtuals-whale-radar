import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, LoaderCircle, MailWarning } from "lucide-react";
import { useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { Button } from "@/components/ui/button";
import { AuthFrame } from "@/pages/LoginPage";
import { useAuth } from "@/auth/use-auth";

export function VerifyEmailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refresh } = useAuth();
  const token = String(searchParams.get("token") || "").trim();

  const verifyMutation = useMutation({
    mutationFn: () => dashboardApi.auth.verifyEmail(token),
    onSuccess: async (result) => {
      await refresh();
      toast.success("邮箱验证成功，20 积分已到账。");
      navigate(result.home_path, { replace: true });
    },
  });

  useEffect(() => {
    if (!token) {
      return;
    }
    if (verifyMutation.status !== "idle") {
      return;
    }
    void verifyMutation.mutate();
  }, [token, verifyMutation]);

  const renderBody = () => {
    if (!token) {
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-3 text-foreground">
            <MailWarning className="size-5 text-primary" />
            <div className="text-lg font-semibold">缺少验证链接</div>
          </div>
          <p className="text-sm leading-6 text-muted-foreground">
            当前链接里没有验证参数。回到登录页后，可以重新发送验证邮件。
          </p>
          <Button asChild className="h-12 rounded-[18px]">
            <Link to="/auth/login">回到登录</Link>
          </Button>
        </div>
      );
    }

    if (verifyMutation.isPending || verifyMutation.status === "idle") {
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-3 text-foreground">
            <LoaderCircle className="size-5 animate-spin text-primary" />
            <div className="text-lg font-semibold">正在完成邮箱验证</div>
          </div>
          <p className="text-sm leading-6 text-muted-foreground">
            验证成功后会自动登录，并把 20 积分发到你的账户里。
          </p>
        </div>
      );
    }

    if (verifyMutation.isSuccess) {
      return (
        <div className="space-y-4">
          <div className="flex items-center gap-3 text-foreground">
            <CheckCircle2 className="size-5 text-primary" />
            <div className="text-lg font-semibold">验证成功，正在进入应用</div>
          </div>
        </div>
      );
    }

    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3 text-foreground">
          <MailWarning className="size-5 text-primary" />
          <div className="text-lg font-semibold">验证链接无效或已过期</div>
        </div>
        <p className="text-sm leading-6 text-muted-foreground">
          你可以回到登录页，输入邮箱和密码后重新发送验证邮件。
        </p>
        <Button asChild className="h-12 rounded-[18px]">
          <Link to="/auth/login">回到登录</Link>
        </Button>
      </div>
    );
  };

  return (
    <AuthFrame
      eyebrow="Verify Email"
      title="完成邮箱验证，正式开始使用"
      description="只有邮箱验证成功后，账号才会正式创建，钱包、积分和解锁记录也会绑定到这个账号上。"
    >
      <div className="mx-auto flex h-full max-w-md flex-col justify-center">
        {renderBody()}
      </div>
    </AuthFrame>
  );
}
