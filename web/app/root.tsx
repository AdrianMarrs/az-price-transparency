import { isRouteErrorResponse, Links, Meta, Outlet, Scripts, ScrollRestoration } from "react-router";

import type { Route } from "./+types/root";
import { SiteFooter, SiteHeader } from "~/components/site-chrome";
import { Skeleton } from "~/components/ui/skeleton";
import { TooltipProvider } from "~/components/ui/tooltip";
import "./app.css";

export const links: Route.LinksFunction = () => [
  { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
];

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#0f3b46" />
        <Meta />
        <Links />
      </head>
      <body className="min-h-dvh">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-4 focus:py-2 focus:shadow">
          Skip to content
        </a>
        <TooltipProvider delayDuration={200}>
          <SiteHeader />
          <main id="main">{children}</main>
          <SiteFooter />
        </TooltipProvider>
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

export default function App() {
  return <Outlet />;
}

// Shown while a page that wasn't pre-rendered loads its data in the browser.
export function HydrateFallback() {
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-12 sm:px-6" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-9 w-2/3" />
      <Skeleton className="h-5 w-1/3" />
      <Skeleton className="mt-8 h-64 w-full" />
    </div>
  );
}

export function ErrorBoundary({ error }: Route.ErrorBoundaryProps) {
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  return (
    <div className="mx-auto max-w-2xl px-4 py-24 text-center sm:px-6">
      <p className="text-sm font-medium text-primary">{notFound ? "404" : "Something went wrong"}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">
        {notFound ? "We couldn't find that page" : "This page didn't load"}
      </h1>
      <p className="mt-4 text-muted-foreground">
        {notFound
          ? "The link may be old, or the service or hospital isn't in our data."
          : error instanceof Error ? error.message : "Please try again in a moment."}
      </p>
      <a href="/" className="mt-8 inline-block text-primary underline-offset-4 hover:underline">Go to the home page</a>
    </div>
  );
}
