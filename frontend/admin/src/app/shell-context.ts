import { createContext, useContext } from "react";

import type {
  AppMetaResponse,
  AuthUser,
  HealthResponse,
  MetaResponse,
  RefreshMode,
  SignalHubResponse,
} from "@/types/api";

export type WorkspaceViewer = "admin" | "user";

export interface ShellContextValue {
  viewer: WorkspaceViewer;
  authUser?: AuthUser;
  meta?: MetaResponse | AppMetaResponse;
  health?: HealthResponse;
  signalHubPreview?: SignalHubResponse;
  projectOptions: string[];
  selectedProject: string;
  setSelectedProject: (project: string) => void;
  refreshMode: RefreshMode;
  setRefreshMode: (mode: RefreshMode) => void;
  refreshAll: () => Promise<void>;
  lastRefreshAt: number;
  isRefreshing: boolean;
  toggleRuntimePause: () => Promise<void>;
  isRuntimeMutating: boolean;
  logout: () => Promise<void>;
}

export const ShellContext = createContext<ShellContextValue | null>(null);

export function useShell() {
  const context = useContext(ShellContext);
  if (!context) {
    throw new Error("useShell must be used inside AdminShell");
  }
  return context;
}
