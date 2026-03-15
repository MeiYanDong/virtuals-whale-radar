const zhDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const zhShortDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const compactNumberFormatter = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 2,
});

const integerFormatter = new Intl.NumberFormat("zh-CN");

export function formatCompactNumber(value: number | string | null | undefined) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "-";
  return compactNumberFormatter.format(num);
}

export function formatInteger(value: number | string | null | undefined) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "-";
  return integerFormatter.format(num);
}

export function formatDecimal(
  value: number | string | null | undefined,
  maximumFractionDigits = 4,
) {
  const num = Number(value ?? 0);
  if (!Number.isFinite(num)) return "-";
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits,
    minimumFractionDigits: num !== 0 && Math.abs(num) < 1 ? 2 : 0,
  }).format(num);
}

export function formatCurrency(value: number | string | null | undefined, symbol = "V") {
  const formatted = formatDecimal(value, 3);
  return formatted === "-" ? formatted : `${formatted} ${symbol}`;
}

export function formatDateTime(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "-";
  const date =
    typeof value === "number" || /^\d+$/.test(String(value))
      ? new Date(Number(value) * 1000)
      : new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return zhDateFormatter.format(date);
}

export function formatShortDateTime(value: number | string | null | undefined) {
  if (value === null || value === undefined || value === "") return "-";
  const date =
    typeof value === "number" || /^\d+$/.test(String(value))
      ? new Date(Number(value) * 1000)
      : new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return zhShortDateFormatter.format(date);
}

export function formatRelativeSeconds(value: number | null | undefined) {
  const seconds = Number(value ?? 0);
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${Math.max(seconds, 0)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时`;
  return `${Math.floor(seconds / 86400)} 天`;
}

export function formatCountdown(value: number | null | undefined) {
  const seconds = Number(value ?? 0);
  if (!Number.isFinite(seconds)) return "-";
  if (seconds <= 0) return "已到达";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} 天 ${h} 小时`;
  if (h > 0) return `${h} 小时 ${m} 分钟`;
  return `${m} 分钟`;
}

export function formatAddress(value: string | null | undefined, size = 6) {
  const text = String(value ?? "").trim();
  if (!text) return "-";
  if (text.length <= size * 2) return text;
  return `${text.slice(0, size)}...${text.slice(-size)}`;
}

export function toDatetimeLocalValue(timestamp: number) {
  const date = new Date(timestamp * 1000 + 8 * 3600 * 1000);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

export function parseDatetimeLocalValue(value: string) {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  return Math.floor(
    Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour) - 8,
      Number(minute),
      0,
      0,
    ) / 1000,
  );
}

export function toDatetimeLocalRange(hoursBack = 8) {
  const end = Math.floor(Date.now() / 1000);
  const start = end - hoursBack * 3600;
  return {
    start: toDatetimeLocalValue(start),
    end: toDatetimeLocalValue(end),
  };
}
