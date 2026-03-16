import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { dashboardApi } from "@/api/dashboard-api";
import { queryKeys } from "@/api/query-keys";
import { AuthContext, type AuthContextValue } from "@/auth/auth-context-value";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const authQuery = useQuery({
    queryKey: queryKeys.authMe,
    queryFn: dashboardApi.auth.me,
    staleTime: 10_000,
    retry: 0,
    refetchOnWindowFocus: false,
  });

  const invalidateAuth = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.authMe }),
      queryClient.invalidateQueries({ queryKey: queryKeys.meta }),
      queryClient.invalidateQueries({ queryKey: queryKeys.appMeta }),
    ]);
  };

  const loginMutation = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      dashboardApi.auth.login(email, password),
    onSuccess: async () => {
      await invalidateAuth();
    },
  });

  const registerMutation = useMutation({
    mutationFn: ({ nickname, email, password }: { nickname: string; email: string; password: string }) =>
      dashboardApi.auth.register(nickname, email, password),
  });

  const logoutMutation = useMutation({
    mutationFn: dashboardApi.auth.logout,
    onSuccess: async () => {
      await invalidateAuth();
      queryClient.removeQueries({ queryKey: queryKeys.appMeta });
      queryClient.removeQueries({ queryKey: queryKeys.meta });
    },
  });

  const value: AuthContextValue = {
    auth: authQuery.data,
    user: authQuery.data?.user,
    isAuthenticated: Boolean(authQuery.data?.authenticated && authQuery.data?.user),
    isAdmin: authQuery.data?.user?.role === "admin",
    isUser: authQuery.data?.user?.role === "user",
    isLoading: authQuery.isLoading,
    login: async (email: string, password: string) =>
      loginMutation.mutateAsync({ email, password }),
    register: async (nickname: string, email: string, password: string) =>
      registerMutation.mutateAsync({ nickname, email, password }),
    logout: async () => {
      await logoutMutation.mutateAsync();
    },
    refresh: async () => {
      const result = await authQuery.refetch();
      return result.data ?? { authenticated: false };
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
