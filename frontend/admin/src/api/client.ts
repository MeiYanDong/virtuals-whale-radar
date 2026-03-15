interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  params?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown | FormData;
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
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const requestBody: BodyInit | null | undefined =
    options.body === undefined
      ? undefined
      : isFormData
        ? (options.body as FormData)
        : JSON.stringify(options.body);
  const response = await fetch(buildUrl(path, options.params), {
    method: options.method ?? "GET",
    credentials: "include",
    headers: isFormData
      ? undefined
      : {
          "Content-Type": "application/json",
        },
    body: requestBody,
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
