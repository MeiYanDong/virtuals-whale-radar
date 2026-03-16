import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { AdminShell, UserShell } from "@/app/shell";
import { ThemeProvider } from "@/app/theme-provider";
import { AuthProvider } from "@/auth/auth-context";
import { resolvePostAuthRedirect } from "@/auth/redirect";
import { useAuth } from "@/auth/use-auth";
import { LoadingState } from "@/components/app-primitives";
import { InboxPage } from "@/pages/InboxPage";
import { BillingPage } from "@/pages/BillingPage";
import { LoginPage } from "@/pages/LoginPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { ProjectsPage } from "@/pages/ProjectsPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { UsersPage } from "@/pages/UsersPage";
import { VerifyEmailPage } from "@/pages/VerifyEmailPage";
import { WalletsPage } from "@/pages/WalletsPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
});

function RootRedirect() {
  const { auth, isLoading } = useAuth();
  if (isLoading) {
    return <LoadingState label="正在解析登录状态..." />;
  }
  if (auth?.authenticated && auth.home_path) {
    return <Navigate to={auth.home_path} replace />;
  }
  return <Navigate to="/auth/login" replace />;
}

function AdminDefaultRoute() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projectScheduler,
    queryFn: dashboardApi.admin.getProjectSchedulerStatus,
  });
  if (isLoading) {
    return <LoadingState label="正在解析管理员默认入口..." />;
  }
  const hasActiveProject = (data?.items ?? []).some((item) =>
    ["live", "prelaunch"].includes(String(item.projectedStatus)),
  );
  return <Navigate to={hasActiveProject ? "/admin/overview" : "/admin/projects"} replace />;
}

function AppDefaultRoute() {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.appMeta,
    queryFn: dashboardApi.app.getMeta,
  });
  if (isLoading) {
    return <LoadingState label="正在解析用户默认入口..." />;
  }
  return <Navigate to={data?.default_path || "/app/projects"} replace />;
}

function AuthRoute() {
  const { auth, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return <LoadingState label="正在检查登录状态..." />;
  }
  if (auth?.authenticated && auth.home_path && auth.user) {
    const redirectTo = new URLSearchParams(location.search).get("redirect");
    return (
      <Navigate
        to={resolvePostAuthRedirect({
          role: auth.user.role,
          homePath: auth.home_path,
          redirectTo,
        })}
        replace
      />
    );
  }
  return <Outlet />;
}

function ProtectedRoute({ role }: { role: "admin" | "user" }) {
  const { auth, isLoading } = useAuth();
  const location = useLocation();
  if (isLoading) {
    return <LoadingState label="正在验证访问权限..." />;
  }
  if (!auth?.authenticated || !auth.user) {
    const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
    return <Navigate to={`/auth/login?redirect=${redirect}`} replace />;
  }
  if (role === "admin" && auth.user.role !== "admin") {
    return <Navigate to="/app" replace />;
  }
  if (role === "user" && auth.user.role !== "user") {
    return <Navigate to="/admin" replace />;
  }
  return <Outlet />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<RootRedirect />} />

              <Route element={<AuthRoute />}>
                <Route path="/auth/login" element={<LoginPage />} />
                <Route path="/auth/register" element={<RegisterPage />} />
              </Route>
              <Route path="/auth/verify-email" element={<VerifyEmailPage />} />

              <Route element={<ProtectedRoute role="admin" />}>
                <Route path="/admin" element={<AdminShell />}>
                  <Route index element={<AdminDefaultRoute />} />
                  <Route path="overview" element={<OverviewPage />} />
                  <Route path="projects" element={<ProjectsPage />} />
                  <Route path="projects/:projectId" element={<OverviewPage />} />
                  <Route path="signalhub" element={<InboxPage />} />
                  <Route path="wallets" element={<WalletsPage />} />
                  <Route path="users" element={<UsersPage />} />
                  <Route path="operations" element={<Navigate to="../users" replace />} />
                  <Route path="settings" element={<SettingsPage />} />
                  <Route path="inbox" element={<Navigate to="../signalhub" replace />} />
                </Route>
              </Route>

              <Route element={<ProtectedRoute role="user" />}>
                <Route path="/app" element={<UserShell />}>
                  <Route index element={<AppDefaultRoute />} />
                  <Route path="overview" element={<OverviewPage />} />
                  <Route path="projects" element={<ProjectsPage />} />
                  <Route path="projects/:projectId" element={<OverviewPage />} />
                  <Route path="signalhub" element={<InboxPage />} />
                  <Route path="wallets" element={<WalletsPage />} />
                  <Route path="billing" element={<BillingPage />} />
                </Route>
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
          <Toaster
            position="top-right"
            richColors
            closeButton
            toastOptions={{
              style: {
                background: "var(--popover-elevated)",
                border: "1px solid var(--border-strong)",
                color: "var(--foreground)",
                boxShadow: "var(--shadow-soft)",
                backdropFilter: "blur(18px)",
              },
            }}
          />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
