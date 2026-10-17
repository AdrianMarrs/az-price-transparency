// A styled native <select>: the phone's own picker, fully accessible, and no inline styles
// (Radix's Select renders a hidden <select style="…">, which the site's CSP blocks).

import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "~/lib/utils";

export function NativeSelect({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <div className={cn("relative", className)}>
      <select
        data-slot="native-select"
        className={cn(
          "h-9 w-full appearance-none rounded-md border border-input bg-card pl-3 pr-9 text-sm shadow-xs outline-none transition",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:opacity-50",
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown aria-hidden className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
