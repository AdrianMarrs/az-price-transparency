import { redirect } from "react-router";

import type { Route } from "./+types/legacy";

// Arizona's pages from before every state had its own: /services/cpt-73721 is now
// /az/services/cpt-73721. CloudFront answers these with a 301 (infra/main/site_router.js);
// this covers the app's own links and anywhere that doesn't.
export async function clientLoader({ request }: Route.ClientLoaderArgs) {
  const url = new URL(request.url);
  throw redirect(`/az${url.pathname}${url.search}${url.hash}`);
}

export default function Legacy() {
  return null;
}
