// A garbled dash on the hospitals page was a "—" saved as UTF-8 and read back as
// Windows-1252 by an edit script. This catches the next one before it ships. (The patterns
// are escaped so this file doesn't match itself.)
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, it } from "vitest";

const APP = join(__dirname, "..");
const MOJIBAKE = new RegExp(["\\u00e2\\u20ac", "\\u00c3[\\u0080-\\u00bf]", "\\u00c2[\\u00a0-\\u00bf]"].join("|"));

function* sources(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* sources(path);
    else if (/\.(tsx?|css|json)$/.test(entry.name)) yield path;
  }
}

it("has no text garbled by a wrong encoding", () => {
  const garbled = [...sources(APP)].filter((f) => MOJIBAKE.test(readFileSync(f, "utf8")));
  expect(garbled).toEqual([]);
});
