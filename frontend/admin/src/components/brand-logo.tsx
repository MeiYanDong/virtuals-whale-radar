import { useState } from "react";

import { buildBrandLogoCandidates } from "@/lib/brand-assets";
import { cn } from "@/lib/utils";

export function BrandLogo({
  className,
  alt = "Virtuals Whale Radar",
}: {
  className?: string;
  alt?: string;
}) {
  const [sourceIndex, setSourceIndex] = useState(0);
  const candidates = buildBrandLogoCandidates();
  const src = candidates[Math.min(sourceIndex, candidates.length - 1)];

  return (
    <img
      src={src}
      alt={alt}
      className={cn("object-cover", className)}
      onError={() => setSourceIndex((index) => Math.min(index + 1, candidates.length - 1))}
    />
  );
}
