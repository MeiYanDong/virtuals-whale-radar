import * as React from "react";

import { cn } from "@/lib/utils";

export function Alert({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "warning" | "danger" }) {
  const styles =
    variant === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : variant === "danger"
        ? "border-rose-200 bg-rose-50 text-rose-900"
        : "border-border bg-white/70 text-foreground";
  return (
    <div
      className={cn("rounded-[22px] border px-4 py-3 text-sm shadow-sm", styles, className)}
      {...props}
    />
  );
}
