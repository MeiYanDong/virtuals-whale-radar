import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

export function ensureArray<T>(value: T[] | undefined | null) {
  return Array.isArray(value) ? value : [];
}

export function compareText(a: string, b: string) {
  return a.localeCompare(b, "zh-CN", { sensitivity: "base" });
}
