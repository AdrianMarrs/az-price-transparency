import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchWithRetry } from "./api";

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
