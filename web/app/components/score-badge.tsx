// How well a hospital follows the federal price transparency rules we can check.

import { CircleCheck, CircleAlert, CircleX, CircleHelp } from "lucide-react";

import { cn } from "~/lib/utils";

export function scoreLevel(score: number | null | undefined) {
  if (score == null) return "unknown" as const;
  return score >= 100 ? ("good" as const) : score >= 70 ? ("fair" as const) : ("poor" as const);
}

const STYLES = {
  good: { icon: CircleCheck, className: "text-success bg-success/10 ring-success/25" },
  fair: { icon: CircleAlert, className: "text-warning bg-warning/10 ring-warning/30" },
  poor: { icon: CircleX, className: "text-destructive bg-destructive/10 ring-destructive/25" },
  unknown: { icon: CircleHelp, className: "text-muted-foreground bg-muted ring-border" },
};

export function ScoreBadge({ score, className }: { score: number | null | undefined; className?: string }) {
  const level = scoreLevel(score);
  const { icon: Icon, className: style } = STYLES[level];
  const label = score == null ? "Not scored" : score >= 100 ? "Meets every rule" : `Meets ${Math.round(score)}% of rules`;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", style, className)}>
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}
