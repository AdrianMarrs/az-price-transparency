// Google AdSense. Off unless the build sets VITE_ADSENSE_CLIENT (the publisher ID,
// "ca-pub-…"): then every page names the account and loads Google's script, which is what
// AdSense checks when it reviews the site. Ads appear once VITE_ADSENSE_SLOT is set too (a
// display ad unit's ID, made in AdSense after the site is approved). Without either,
// nothing renders and no Google script loads.
//
// Ads are placed by hand, never inside a price table, and are labelled. They're asked to be
// non-personalized: the site is about people's health care, so ads follow the page (its
// state and procedure, which AdSense reads from the page itself), not the visitor.
// See /privacy.

import { useEffect, useRef } from "react";
import { useLocation } from "react-router";

import { cn } from "~/lib/utils";

export const ADSENSE_CLIENT = import.meta.env.VITE_ADSENSE_CLIENT as string | undefined;
const SLOT = import.meta.env.VITE_ADSENSE_SLOT as string | undefined;
export const adsenseOn = Boolean(ADSENSE_CLIENT);
const adsOn = Boolean(ADSENSE_CLIENT && SLOT);

type AdsQueue = unknown[] & { requestNonPersonalizedAds?: number };
declare global {
  interface Window { adsbygoogle?: AdsQueue }
}

// Loads Google's script once, in the browser: added after hydration, so pre-rendered pages
// and the app shell stay identical whether ads are on or not.
export function useAdSense() {
  useEffect(() => {
    if (!adsenseOn || document.getElementById("adsbygoogle-js")) return;
    const queue: AdsQueue = (window.adsbygoogle ??= []);
    queue.requestNonPersonalizedAds = 1;
    const script = document.createElement("script");
    script.id = "adsbygoogle-js";
    script.async = true;
    script.crossOrigin = "anonymous";
    script.src = `https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=${ADSENSE_CLIENT}`;
    document.head.appendChild(script);
  }, []);
}

// One responsive display ad, remounted on each page change (the key), because AdSense
// fills an <ins> once. Google's script loads after hydration, so it can't change the
// pre-rendered markup before React has hydrated it.
export function AdSlot({ className }: { className?: string }) {
  const { pathname } = useLocation();
  return adsOn ? <Ad key={pathname} className={className} /> : null;
}

function Ad({ className }: { className?: string }) {
  const ref = useRef<HTMLModElement>(null);
  useEffect(() => {
    if (!ref.current || ref.current.dataset.adsbygoogleStatus) return;
    try {
      (window.adsbygoogle ??= []).push({});
    } catch {
      // An ad blocker or an unfilled slot: the page works the same without it.
    }
  }, []);
  return (
    <aside aria-label="Advertisement" className={cn("mx-auto max-w-6xl px-4 sm:px-6", className)}>
      <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Advertisement</p>
      <ins
        ref={ref}
        className="adsbygoogle block min-h-[100px]"
        data-ad-client={ADSENSE_CLIENT}
        data-ad-slot={SLOT}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </aside>
  );
}
