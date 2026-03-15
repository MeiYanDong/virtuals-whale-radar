import type { AuthUser } from "@/types/api";

export function resolvePostAuthRedirect(options: {
  role?: AuthUser["role"];
  homePath?: string | null;
  redirectTo?: string | null;
}) {
  const homePath = options.homePath?.trim() || (options.role === "admin" ? "/admin" : "/app");
  const redirectTo = options.redirectTo?.trim();

  if (!redirectTo || !redirectTo.startsWith("/") || redirectTo.startsWith("//")) {
    return homePath;
  }

  if (options.role === "admin" && redirectTo.startsWith("/admin")) {
    return redirectTo;
  }

  if (options.role === "user" && redirectTo.startsWith("/app")) {
    return redirectTo;
  }

  return homePath;
}

export function buildAuthSwitchHref(path: string, search: string) {
  const redirectTo = new URLSearchParams(search).get("redirect");
  if (!redirectTo) {
    return path;
  }
  return `${path}?redirect=${encodeURIComponent(redirectTo)}`;
}
