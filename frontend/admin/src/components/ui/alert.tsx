import * as React from "react";

import { cn } from "@/lib/utils";

export function Alert({
  className,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: "default" | "warning" | "danger" }) {
  const styles =
    variant === "warning"
      ? "border-[color:var(--warning-soft)] bg-[color:var(--warning-soft)] text-[color:var(--warning-foreground)]"
      : variant === "danger"
        ? "border-[color:var(--danger-soft)] bg-[color:var(--danger-soft)] text-[color:var(--danger-foreground)]"
        : "border-border bg-[color:var(--surface-soft)] text-foreground";
  return (
    <div
      className={cn("rounded-[22px] border px-4 py-3 text-sm shadow-sm", styles, className)}
      {...props}
    />
  );
}
