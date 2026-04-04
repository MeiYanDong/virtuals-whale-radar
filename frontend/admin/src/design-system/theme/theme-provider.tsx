import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  DesignThemeContext,
  type DesignThemeMode,
} from "@/design-system/theme/theme-context";

const STORAGE_KEY = "vwr_design_system_theme_mode";

function resolveInitialTheme(): DesignThemeMode {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    return "light";
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function DesignThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<DesignThemeMode>(resolveInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = theme;
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      setTheme: setThemeState,
      toggleTheme: () => setThemeState((current) => (current === "light" ? "dark" : "light")),
    }),
    [theme],
  );

  return <DesignThemeContext.Provider value={value}>{children}</DesignThemeContext.Provider>;
}
