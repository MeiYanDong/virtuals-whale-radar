import { useMutation } from "@tanstack/react-query";
import { ArrowRight, KeyRound, Mail, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

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
      toast.success("注册成功，20 积分已到账。");
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
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <AuthFrame
      eyebrow="Register"
      title="先领 20 积分，再开始看项目"
      description="注册后会自动登录。你可以先添加自己的钱包，再去挑项目，最后把积分用在真正想盯的实时盘面上。"
    >
      <div className="mx-auto flex h-full max-w-md flex-col justify-center">
        <div className="space-y-6">
          <div className="space-y-2">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-muted-foreground">Create Account</div>
            <div className="text-3xl font-semibold tracking-[-0.05em]">开始使用</div>
            <p className="text-sm leading-6 text-muted-foreground">
              新账号默认赠送 20 积分，足够你先体验项目列表、加钱包，并解锁前两个真正想看的盘面。
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
            disabled={!nickname.trim() || !email.trim() || !password.trim()}
          >
            注册并领取 20 积分
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
