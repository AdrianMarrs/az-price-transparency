import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchWithRetry, findServices } from "./api";

const respond = (...statuses: number[]) => {
  const fetch = vi.fn();
  for (const status of statuses) fetch.mockResolvedValueOnce(new Response("{}", { status }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
};

afterEach(() => vi.unstubAllGlobals());

describe("fetchWithRetry", () => {
  it("retries a throttled answer until it succeeds", async () => {
    const fetch = respond(503, 429, 200);
    expect((await fetchWithRetry("https://api/x", undefined, [0, 0, 0])).status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("gives up after the last pause and returns the busy answer", async () => {
    const fetch = respond(503, 503, 503);
    expect((await fetchWithRetry("https://api/x", undefined, [0, 0])).status).toBe(503);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("doesn't retry a real answer, including a 404", async () => {
    const fetch = respond(404);
    expect((await fetchWithRetry("https://api/x", undefined, [0])).status).toBe(404);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("findServices", () => {
  const list = [
    { id: "cpt-hcpcs:73721", key: "CPT/HCPCS:73721", code: "73721", code_type: "CPT/HCPCS", description: "MRI EXT LOWER JT", terms: "knee mri", hospitals: 40, cms_shoppable_id: 34 },
    { id: "cpt-hcpcs:73722", key: "CPT/HCPCS:73722", code: "73722", code_type: "CPT/HCPCS", description: "MRI EXT LOWER JT W/DYE", terms: "knee mri", hospitals: 60 },
    { id: "cpt-hcpcs:70450", key: "CPT/HCPCS:70450", code: "70450", code_type: "CPT/HCPCS", description: "CT HEAD W/O DYE", hospitals: 70, cms_shoppable_id: 1 },
  ];

  it("needs every word, and puts CMS shoppable services first", () => {
    expect(findServices(list, "knee MRI").map((s) => s.code)).toEqual(["73721", "73722"]);
    expect(findServices(list, "73722").map((s) => s.code)).toEqual(["73722"]);
    expect(findServices(list, "  ")).toEqual([]);
  });
});
