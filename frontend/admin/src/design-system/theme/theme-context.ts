import { createContext } from "react";

export type DesignThemeMode = "light" | "dark";

export type DesignThemeContextValue = {
  theme: DesignThemeMode;
  setTheme: (theme: DesignThemeMode) => void;
  toggleTheme: () => void;
};

export const DesignThemeContext = createContext<DesignThemeContextValue | null>(null);
