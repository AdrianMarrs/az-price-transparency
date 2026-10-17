import type { Config } from "@react-router/dev/config";

import hospitals from "./app/data/hospitals.json" with { type: "json" };
import services from "./app/data/featured-services.json" with { type: "json" };

// A static site: no server at request time. Every page below is rendered to HTML at build
// time (so search engines and link previews see real content); any other URL loads the app
// shell from __spa-fallback.html and renders in the browser.
export default {
  ssr: false,
  async prerender() {
    return [
      "/",
      "/services",
      "/hospitals",
      "/methods",
      ...hospitals.map((h) => `/hospitals/${h.ccn}`),
      ...services.map((s) => `/services/${s.slug}`),
    ];
  },
} satisfies Config;
