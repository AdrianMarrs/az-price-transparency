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

import { useEffect, useRef, useSyncExternalStore } from "react";
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

// A page's ads: a wide banner where the component is placed (below the page's content), and,
// on screens wide enough to have room beside the content, a tall ad that stays in view in
// the right margin. Each is remounted on each page change (the key), because AdSense fills
// an <ins> once. Google's script loads after hydration, so it can't change the
// pre-rendered markup before React has hydrated it.
export function AdSlot({ className }: { className?: string }) {
  const { pathname } = useLocation();
  const rail = useMediaQuery(RAIL_FITS);
  if (!adsOn) return null;
  return (
    <>
      <aside aria-label="Advertisement" className={cn("mx-auto max-w-6xl px-4 sm:px-6", className)}>
        <Label />
        <Ad key={pathname} format="horizontal" className="block min-h-[90px] w-full" />
      </aside>
      {rail && (
        // Centered in the right margin: (margin - 160px) / 2 from the edge, where the
        // margin is (100vw - 72rem) / 2 (the content is max-w-6xl, 72rem).
        <aside aria-label="Advertisement" className="fixed top-24 right-[calc((100vw-72rem-160px*2)/4)] z-30 w-[160px]">
          <Label />
          <Ad key={`rail${pathname}`} className="block h-[600px] w-[160px]" />
        </aside>
      )}
    </>
  );
}

// The rail is 160px wide and 600px tall (a "wide skyscraper"). It's shown only when it fits
// in the margin beside the 72rem (1152px) content with room to spare, and the window is tall
// enough for it below the header; otherwise it's not rendered at all (AdSense can't fill a
// hidden slot).
const RAIL_FITS = "(min-width: 1536px) and (min-height: 760px)";

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false, // pre-rendered without it, so hydration matches
  );
}

const Label = () => <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Advertisement</p>;

// format "horizontal" asks for a wide ad that fits the slot's width; with no format, the
// slot's own CSS size is the ad's size (AdSense's way to fix a responsive unit's size).
function Ad({ format, className }: { format?: "horizontal"; className: string }) {
  const ref = useRef<HTMLModElement>(null);
  const requested = useRef(false); // effects run twice in development (StrictMode)
  useEffect(() => {
    if (!ref.current || requested.current || ref.current.dataset.adsbygoogleStatus) return;
    requested.current = true;
    try {
      (window.adsbygoogle ??= []).push({});
    } catch {
      // An ad blocker or an unfilled slot: the page works the same without it.
    }
  }, []);
  return (
    <ins
      ref={ref}
      className={cn("adsbygoogle", className)}
      data-ad-client={ADSENSE_CLIENT}
      data-ad-slot={SLOT}
      data-ad-format={format}
      data-full-width-responsive={format ? "true" : undefined}
    />
  );
}
