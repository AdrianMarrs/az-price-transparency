import { useSyncExternalStore } from "react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const noSubscription = () => () => {};

// False while React hydrates a pre-rendered page, true after (and on any page rendered in
// the browser from the start). A page pre-rendered without a query string (filters) must
// first render without it too, or hydrating fails (React error #418).
export function useHydrated(): boolean {
  return useSyncExternalStore(noSubscription, () => true, () => false);
}
