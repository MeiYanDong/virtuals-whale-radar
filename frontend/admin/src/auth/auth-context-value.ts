import { createContext } from "react";

import type { AuthMeResponse, AuthSuccessResponse, AuthUser } from "@/types/api";

export interface AuthContextValue {
  auth?: AuthMeResponse;
  user?: AuthUser;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isUser: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<AuthSuccessResponse>;
  register: (nickname: string, email: string, password: string) => Promise<AuthSuccessResponse>;
  logout: () => Promise<void>;
  refresh: () => Promise<AuthMeResponse>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
