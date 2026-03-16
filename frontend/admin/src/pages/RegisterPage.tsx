import { useMutation } from "@tanstack/react-query";
import { ArrowRight, KeyRound, Mail, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { buildAuthSwitchHref, resolvePostAuthRedirect } from "@/auth/redirect";
import { useAuth } from "@/auth/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthFrame } from "@/pages/LoginPage";

export function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, auth, register } = useAuth();
  const [nickname, setNickname] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verificationSent, setVerificationSent] = useState<{
    email: string;
    expiresAt: number;
  } | null>(null);

  useEffect(() => {
    if (!isAuthenticated || !auth?.home_path) return;
    const redirectTo = new URLSearchParams(location.search).get("redirect");
    navigate(
      resolvePostAuthRedirect({
        role: auth.user?.role,
        homePath: auth.home_path,
        redirectTo,
      }),
      { replace: true },
    );
  }, [auth?.home_path, auth?.user?.role, isAuthenticated, location.search, navigate]);

  const registerMutation = useMutation({
    mutationFn: () => register(nickname.trim(), email.trim(), password),
    onSuccess: (result) => {
      setVerificationSent({
        email: result.email,
        expiresAt: result.expires_at,
      });
      setPassword("");
      toast.success("验证邮件已发送，请前往邮箱完成验证。");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const resendMutation = useMutation({
    mutationFn: () =>
      dashboardApi.auth.resendVerification(verificationSent?.email || email.trim()),
    onSuccess: (result) => {
      setVerificationSent({
        email: result.email,
        expiresAt: result.expires_at,
      });
      toast.success("验证邮件已重新发送。");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (verificationSent) {
    return (
      <AuthFrame
        eyebrow="Verify Email"
        title="先完成邮箱验证，再开始看项目"
        description="验证成功后，账号才会正式创建，20 积分也会到账。你可以回到登录页，或者直接去邮箱点开验证链接。"
      >
        <div className="mx-auto flex h-full max-w-md flex-col justify-center">
          <div className="space-y-6">
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Check Your Inbox</div>
              <div className="text-3xl font-semibold tracking-[-0.05em]">验证邮件已发送</div>
              <p className="text-sm leading-6 text-muted-foreground">
                我们已经向 <span className="font-medium text-foreground">{verificationSent.email}</span> 发送了验证邮件。
                验证成功后，你会自动登录，并收到 20 积分。
              </p>
            </div>

            <div className="rounded-[24px] border border-border/80 bg-[color:var(--surface-soft)] px-5 py-4 text-sm leading-6 text-muted-foreground">
              验证链接默认在{" "}
              <span className="font-medium text-foreground">
                {new Intl.DateTimeFormat("zh-CN", {
                  hour: "2-digit",
                  minute: "2-digit",
                }).format(new Date(verificationSent.expiresAt * 1000))}
              </span>{" "}
              前有效。如果没收到，先检查垃圾邮件箱，再点下面重新发送。
            </div>

            <div className="flex flex-col gap-3 sm:flex-row">
              <Button
                className="h-12 flex-1 rounded-[18px]"
                onClick={() => void resendMutation.mutate()}
                disabled={resendMutation.isPending}
              >
                重新发送验证邮件
                <ArrowRight className="size-4" />
              </Button>
              <Button asChild variant="outline" className="h-12 flex-1 rounded-[18px]">
                <Link to={buildAuthSwitchHref("/auth/login", location.search)}>回到登录</Link>
              </Button>
            </div>
          </div>
        </div>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      eyebrow="Register"
      title="先完成邮箱验证，再开始看项目"
      description="注册后我们会先发一封验证邮件。邮箱验证成功后，账号才会正式创建，你也会收到 20 积分去体验真正想看的盘面。"
    >
      <div className="mx-auto flex h-full max-w-md flex-col justify-center">
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Create Account</div>
            <div className="text-3xl font-semibold tracking-[-0.05em]">开始使用</div>
            <p className="text-sm leading-6 text-muted-foreground">
              新账号在邮箱验证成功后会收到 20 积分，足够你先体验项目列表、加钱包，并解锁前两个真正想看的盘面。
            </p>
          </div>

          <div className="space-y-4">
            <label className="block space-y-2">
              <span className="text-sm font-medium">昵称</span>
              <div className="relative">
                <UserRound className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-12 rounded-[18px] pl-11"
                  value={nickname}
                  onChange={(event) => setNickname(event.target.value)}
                  placeholder="输入昵称"
                />
              </div>
            </label>

            <label className="block space-y-2">
              <span className="text-sm font-medium">邮箱</span>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-12 rounded-[18px] pl-11"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                />
              </div>
            </label>

            <label className="block space-y-2">
              <span className="text-sm font-medium">密码</span>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="h-12 rounded-[18px] pl-11"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="至少 8 位"
                />
              </div>
            </label>
          </div>

          <Button
            className="h-12 w-full rounded-[18px]"
            onClick={() => void registerMutation.mutate()}
            disabled={!nickname.trim() || !email.trim() || !password.trim() || registerMutation.isPending}
          >
            注册并发送验证邮件
            <ArrowRight className="size-4" />
          </Button>

          <div className="text-sm text-muted-foreground">
            已有账号？
            <Link className="ml-2 font-medium text-primary hover:underline" to={buildAuthSwitchHref("/auth/login", location.search)}>
              去登录
            </Link>
          </div>
        </div>
      </div>
    </AuthFrame>
  );
}
