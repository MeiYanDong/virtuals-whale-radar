import * as React from "react";

import { cn } from "@/lib/utils";

const controlClasses =
  "flex h-11 w-full rounded-2xl border border-border bg-[color:var(--surface-soft)] px-4 py-2 text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(controlClasses, className)} {...props} />
  ),
);

Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.ComponentProps<"textarea">
>(({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "min-h-[110px] w-full rounded-[22px] border border-border bg-[color:var(--surface-soft)] px-4 py-3 text-sm text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] transition placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    {...props}
  />
));

Textarea.displayName = "Textarea";

export function Select(props: React.ComponentProps<"select">) {
  const { className, children, ...rest } = props;
  return (
    <select className={cn(controlClasses, "appearance-none pr-10", className)} {...rest}>
      {children}
    </select>
  );
}
