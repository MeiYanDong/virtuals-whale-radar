interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status: number, details: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

function buildUrl(
  path: string,
  params: Record<string, string | number | boolean | null | undefined> | undefined,
) {
  const base = (import.meta.env.VITE_API_BASE as string | undefined)?.trim();
  const url = base ? new URL(path, base) : new URL(path, window.location.origin);

  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    url.searchParams.set(key, String(value));
  });

  return base ? url.toString() : `${url.pathname}${url.search}`;
}

export async function requestJson<T>(path: string, options: RequestOptions = {}) {
  const response = await fetch(buildUrl(path, options.params), {
    method: options.method ?? "GET",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
    cache: "no-store",
  });

  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "string"
        ? payload.error
        : `${response.status} ${response.statusText}`;

    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}
