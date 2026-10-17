// Moves every inline <script> in the built HTML into its own file, so the site's Content
// Security Policy can stay `script-src 'self'` (no 'unsafe-inline').
//
// React Router writes small inline scripts into each pre-rendered page: the page's data for
// hydration, the module that starts the app, and scroll restoration. A classic script with
// `src` (no async/defer) runs at the same point in the page as the inline one did, and a
// module script with `src` is deferred, running after the page's data scripts as the app
// expects. `async` is removed from module scripts: React 19 treats `<script async src>` as a
// hoistable resource and skips it while hydrating, which shifts every later element and
// fails hydration (React error #418). Files are named by a hash of their content and cached
// like the other assets.

import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { join, relative } from "node:path";

const ROOT = new URL("../build/client/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const OUT = join(ROOT, "assets", "inline");
const INLINE = /<script(\s[^>]*)?>([\s\S]*?)<\/script>/g;

async function* htmlFiles(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* htmlFiles(path);
    else if (entry.name.endsWith(".html")) yield path;
  }
}

export function externalize(html, write) {
  return html.replace(INLINE, (tag, attrs = "", body) => {
    if (/\ssrc=/.test(attrs) || !body.trim()) return tag;
    const name = `${createHash("sha256").update(body).digest("hex").slice(0, 16)}.js`;
    write(name, body);
    const kept = /\stype=["']?module/.test(attrs) ? attrs.replace(/\sasync(=("[^"]*"|'[^']*'|\S+))?(?=\s|$)/, "") : attrs;
    return `<script${kept} src="/assets/inline/${name}"></script>`;
  });
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const files = new Map();
  let pages = 0;
  for await (const path of htmlFiles(ROOT)) {
    const html = await readFile(path, "utf8");
    const out = externalize(html, (name, body) => files.set(name, body));
    if (out !== html) {
      await writeFile(path, out);
      pages++;
    }
    if (/<script(?![^>]*\ssrc=)[^>]*>\s*\S/.test(out)) throw new Error(`inline script left in ${relative(ROOT, path)}`);
  }
  for (const [name, body] of files) await writeFile(join(OUT, name), body);
  console.log(`moved ${files.size} inline scripts out of ${pages} pages`);
}

if (process.argv[1]?.endsWith("externalize-inline-scripts.mjs")) await main();
