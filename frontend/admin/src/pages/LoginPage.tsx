import type { ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { ArrowRight, KeyRound, Mail, MoonStar, SunMedium } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { dashboardApi } from "@/api/dashboard-api";
import { ApiError } from "@/api/client";
import { useTheme } from "@/app/use-theme";
import { buildAuthSwitchHref, resolvePostAuthRedirect } from "@/auth/redirect";
import { useAuth } from "@/auth/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function AuthFrame({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className="theme-auth-shell min-h-screen px-4 py-8">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-6xl items-center">
        <div className="theme-auth-frame grid w-full gap-8 overflow-hidden rounded-[40px] border border-white/60 backdrop-blur xl:grid-cols-[0.9fr_1.1fr]">
          <div className="relative overflow-hidden px-8 py-10 sm:px-10 sm:py-12">
            <div className="theme-auth-panel absolute inset-0" />
            <div className="relative flex h-full flex-col justify-between">
              <div className="space-y-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="theme-brand-badge flex size-16 items-center justify-center rounded-[22px]">
                      <img src="/admin/brand/logo-mark.png" alt="Virtuals Whale Radar" className="size-11 rounded-[14px] object-cover" />
                    </div>
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.24em] text-primary/80">
                        Virtuals Whale Radar
                      </div>
                      <div className="text-2xl font-semibold tracking-[-0.04em]">项目观察台</div>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="theme-toggle-button"
                    onClick={toggleTheme}
                    title={theme === "light" ? "切换到深色模式" : "切换到浅色模式"}
                  >
                    {theme === "light" ? <MoonStar className="size-4" /> : <SunMedium className="size-4" />}
                    {theme === "light" ? "深色模式" : "浅色模式"}
                  </Button>
                </div>

                <div className="space-y-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.24em] text-primary/80">
                    {eyebrow}
                  </div>
                  <h1 className="max-w-md text-4xl font-semibold tracking-[-0.06em] text-balance text-foreground">
                    {title}
                  </h1>
                  <p className="max-w-md text-base leading-7 text-muted-foreground">{description}</p>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-[24px] border border-border/80 bg-[color:var(--surface-soft)] px-5 py-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">看发射</div>
                  <div className="mt-2 text-sm leading-6 text-foreground">
                    盯正在发射的项目，快速看分钟消耗、税收和大户有没有进场。
                  </div>
                </div>
                <div className="rounded-[24px] border border-border/80 bg-[color:var(--surface-soft)] px-5 py-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">跟钱包</div>
                  <div className="mt-2 text-sm leading-6 text-foreground">
                    先加自己的钱包，再去挑项目。真正想盯的盘面再用积分解锁。
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="px-8 py-10 sm:px-10 sm:py-12">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, auth, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [verificationState, setVerificationState] = useState<{
    email: string;
    expired: boolean;
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

  const loginMutation = useMutation({
    mutationFn: () => login(email.trim(), password),
    onSuccess: (result) => {
      setVerificationState(null);
      toast.success("登录成功。");
      const redirectTo = new URLSearchParams(location.search).get("redirect");
      navigate(
        resolvePostAuthRedirect({
          role: result.user.role,
          homePath: result.home_path,
          redirectTo,
        }),
        { replace: true },
      );
    },
    onError: (error: Error) => {
      if (error instanceof ApiError && error.details && typeof error.details === "object") {
        const details = error.details as {
          code?: string;
          email?: string;
          expired?: boolean;
        };
        if (details.code === "email_not_verified") {
          setVerificationState({
            email: String(details.email || email).trim(),
            expired: Boolean(details.expired),
          });
          toast.error(details.expired ? "验证邮件已过期，请重新发送。" : "请先完成邮箱验证。");
          return;
        }
      }
      setVerificationState(null);
      toast.error(error.message);
    },
  });

  const resendMutation = useMutation({
    mutationFn: () => dashboardApi.auth.resendVerification(verificationState?.email || email.trim()),
    onSuccess: (result) => {
      setVerificationState({
        email: result.email,
        expired: false,
      });
      toast.success("验证邮件已重新发送。");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AuthFrame
      eyebrow="Login"
      title="继续盯你关心的项目"
      description="登录后可以继续看项目列表、跟踪自己的钱包，并解锁真正想长期盯的实时盘面。"
    >
      <div className="mx-auto flex h-full max-w-md flex-col justify-center">
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Account Access</div>
            <div className="text-3xl font-semibold tracking-[-0.05em]">欢迎回来</div>
            <p className="text-sm leading-6 text-muted-foreground">
              如果你已经加过钱包，登录后就能继续看自己关注的钱包有没有在项目里进场。
            </p>
          </div>

          <div className="space-y-4">
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
                  placeholder="输入密码"
                />
              </div>
            </label>
          </div>

          <Button className="h-12 w-full rounded-[18px]" onClick={() => void loginMutation.mutate()} disabled={!email.trim() || !password.trim()}>
            登录
            <ArrowRight className="size-4" />
          </Button>

          {verificationState ? (
            <div className="rounded-[24px] border border-border/80 bg-[color:var(--surface-soft)] px-5 py-4">
              <div className="text-sm font-medium text-foreground">
                {verificationState.expired ? "验证链接已过期" : "邮箱还没验证"}
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {verificationState.email} 还没有完成验证。重新发送后，点开邮箱里的链接即可完成注册并到账 20 积分。
              </p>
              <Button
                className="mt-4 h-10 rounded-[16px]"
                variant="outline"
                onClick={() => void resendMutation.mutate()}
                disabled={resendMutation.isPending}
              >
                重新发送验证邮件
              </Button>
            </div>
          ) : null}

          <div className="text-sm text-muted-foreground">
            没有账号？
            <Link className="ml-2 font-medium text-primary hover:underline" to={buildAuthSwitchHref("/auth/register", location.search)}>
              去注册
            </Link>
          </div>
        </div>
      </div>
    </AuthFrame>
  );
}
