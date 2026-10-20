// Serves build/client the way CloudFront does in production, to check a build before it's
// deployed: a path's own file, else its folder's index.html (pre-rendered pages), else the app
// shell __spa-fallback.html; with the site's security headers, including its Content Security
// Policy (infra/main/site.tf), so a script or style the policy would block fails here too.
// /data/ (the data files, serving/export_static.py) is passed through to the live site.
//
//   node scripts/serve-build.mjs [port]

import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";

const ROOT = new URL("../build/client/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const PORT = Number(process.argv[2] ?? 4173);
const read = (name) => readFile(new URL(`../${name}`, import.meta.url), "utf8").catch(() => "");
const env = [await read(".env.local"), await read(".env.production")].join("\n");
const DATA = (process.env.VITE_DATA_URL ?? env.match(/^VITE_DATA_URL=(.+)$/m)?.[1]?.trim() ?? "https://clearhealthcareprices.com").replace(/\/$/, "");

// infra/main/site.tf's two policies: without ads, and with AdSense (var.adsense).
const GOOGLE_ADS = "https://*.googlesyndication.com https://*.doubleclick.net https://*.google.com https://*.adtrafficquality.google https://*.googleadservices.com https://*.gstatic.com";
const ADS = /^VITE_ADSENSE_CLIENT=\S/m.test(env) || Boolean(process.env.VITE_ADSENSE_CLIENT);
const CSP = ADS
  ? ["default-src 'self'", `connect-src 'self' ${GOOGLE_ADS}`, "img-src 'self' data: https:",
    "style-src 'self' 'unsafe-inline'", `script-src 'self' ${GOOGLE_ADS}`, `frame-src ${GOOGLE_ADS}`, "frame-ancestors 'none'"]
  : ["default-src 'self'", "connect-src 'self'", "img-src 'self' data:",
    "style-src 'self'", "script-src 'self'", "frame-ancestors 'none'"];

const HEADERS = {
  "Content-Security-Policy": CSP.join("; "),
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
};
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".svg": "image/svg+xml", ".woff2": "font/woff2", ".json": "application/json",
  ".data": "text/x-script", ".map": "application/json",
};

const isFile = (path) => stat(path).then((s) => s.isFile(), () => false);

// Arizona's pages from before every state had its own: their new address, as the CloudFront
// Function (infra/main/site_router.js) redirects them.
export function moved(urlPath) {
  const [path, search] = urlPath.split(/(?=\?)/);
  const old = path === "/services" || path === "/services/" || path.startsWith("/services/")
    || path === "/hospitals" || path === "/hospitals/";
  return old ? `/az${path}${search ?? ""}` : null;
}

// The same rule as the CloudFront Function in infra/main/site_router.js.
export async function resolve(urlPath) {
  const path = normalize(join(ROOT, decodeURIComponent(urlPath.split("?")[0])));
  if (!path.startsWith(normalize(ROOT))) return null;
  if (await isFile(path)) return path;
  if (await isFile(join(path, "index.html"))) return join(path, "index.html");
  return extname(path) ? null : join(ROOT, "__spa-fallback.html");
}

createServer(async (req, res) => {
  if (req.url?.startsWith("/data/")) {
    const upstream = await fetch(DATA + req.url); // fetch decompresses; send it plain
    const type = upstream.headers.get("content-type") ?? "application/octet-stream";
    res.writeHead(upstream.status, { ...HEADERS, "Content-Type": type });
    res.end(Buffer.from(await upstream.arrayBuffer()));
    return;
  }
  const location = moved(req.url ?? "/");
  if (location) {
    res.writeHead(301, { ...HEADERS, Location: location }).end();
    return;
  }
  const file = await resolve(req.url ?? "/");
  if (!file) {
    res.writeHead(404, HEADERS).end("Not found");
    return;
  }
  res.writeHead(200, { ...HEADERS, "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`build/client on http://localhost:${PORT} (data from ${DATA})`));
