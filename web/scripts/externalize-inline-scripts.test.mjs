import { describe, expect, it } from "vitest";

import { externalize } from "./externalize-inline-scripts.mjs";

const run = (html) => {
  const files = {};
  return { html: externalize(html, (name, body) => { files[name] = body; }), files };
};

describe("externalize", () => {
  it("moves inline scripts to files and keeps their attributes", () => {
    const { html, files } = run('<head></head><script id="_R_">window.x = 1</script>');
    const [name] = Object.keys(files);
    expect(files[name]).toBe("window.x = 1");
    expect(html).toBe(`<head></head><script id="_R_" src="/assets/inline/${name}"></script>`);
  });

  it("drops async from module scripts so React can hydrate", () => {
    const { html } = run('<script type="module" async="">import "/a.js"</script>');
    expect(html).toMatch(/^<script type="module" src="\/assets\/inline\/[0-9a-f]{16}\.js"><\/script>$/);
  });

  it("leaves scripts that already have a src, and empty ones", () => {
    const html = '<script src="/x.js"></script><script> </script>';
    expect(run(html).html).toBe(html);
  });

  it("names a file by its content, so identical scripts share one", () => {
    const { files } = run("<script>a()</script><script>a()</script><script>b()</script>");
    expect(Object.keys(files)).toHaveLength(2);
  });
});
