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
const env = await readFile(new URL("../.env.local", import.meta.url), "utf8").catch(() => "");
const DATA = (process.env.VITE_DATA_URL ?? env.match(/^VITE_DATA_URL=(.+)$/m)?.[1]?.trim() ?? "https://clearhealthcareprices.com").replace(/\/$/, "");

const HEADERS = {
  "Content-Security-Policy": [
    "default-src 'self'", "connect-src 'self'", "img-src 'self' data:",
    "style-src 'self'", "script-src 'self'", "frame-ancestors 'none'",
  ].join("; "),
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

// The same rule as the CloudFront Function in infra/main/site.tf.
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
  const file = await resolve(req.url ?? "/");
  if (!file) {
    res.writeHead(404, HEADERS).end("Not found");
    return;
  }
  res.writeHead(200, { ...HEADERS, "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`build/client on http://localhost:${PORT} (data from ${DATA})`));
