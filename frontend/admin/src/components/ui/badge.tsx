import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold tracking-[0.02em]",
  {
    variants: {
      variant: {
        default: "bg-primary/12 text-primary ring-1 ring-primary/15",
        secondary: "bg-muted text-muted-foreground ring-1 ring-border",
        success: "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200",
        warning: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
        danger: "bg-rose-100 text-rose-700 ring-1 ring-rose-200",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
