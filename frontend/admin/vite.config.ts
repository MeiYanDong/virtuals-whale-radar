import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiRoutes = [
  "/api",
  "/meta",
  "/health",
  "/signalhub",
  "/launch-configs",
  "/wallet-configs",
  "/wallet-recalc",
  "/runtime",
  "/scan-range",
  "/scan-jobs",
  "/mywallets",
  "/minutes",
  "/leaderboard",
  "/event-delays",
  "/project-tax",
  "/favicon",
  "/favicon.ico",
  "/favicon-vpulse.svg",
];

export default defineConfig({
  base: "/admin/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: Object.fromEntries(
      apiRoutes.map((route) => [
        route,
        {
          target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8080",
          changeOrigin: true,
        },
      ]),
    ),
  },
});
