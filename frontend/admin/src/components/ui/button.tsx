import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "@radix-ui/react-slot";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-55 [&_svg]:pointer-events-none [&_svg]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-[0_12px_24px_rgba(36,142,147,0.18)] hover:bg-[color:var(--primary-strong)]",
        secondary:
          "bg-white/75 text-foreground ring-1 ring-border hover:bg-white",
        ghost: "text-muted-foreground hover:bg-white/70 hover:text-foreground",
        outline:
          "border border-border bg-white/55 text-foreground hover:bg-white/85",
        destructive:
          "bg-[color:var(--danger)] text-white shadow-[0_10px_20px_rgba(190,75,78,0.22)] hover:bg-[#a13b3d]",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-11 px-5",
        icon: "h-10 w-10 rounded-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
      />
    );
  },
);

Button.displayName = "Button";
