import { describe, expect, it } from "vitest";

import { matches, searchCities, searchHospitals, serviceApiId, serviceSlug } from "./catalog";

describe("service URLs", () => {
  it("round-trips API ids", () => {
    expect(serviceSlug("cpt-hcpcs:73721")).toBe("cpt-73721");
    expect(serviceSlug("ms-drg:470")).toBe("drg-470");
    expect(serviceApiId("cpt-73721")).toBe("cpt-hcpcs:73721");
    expect(serviceApiId("drg-470")).toBe("ms-drg:470");
    expect(serviceApiId("cpt-g0121")).toBe("cpt-hcpcs:g0121");
  });

  it("rejects anything else", () => {
    expect(serviceApiId("cpt-hcpcs:73721")).toBeNull();
    expect(serviceApiId("../etc")).toBeNull();
  });
});

describe("search", () => {
  it("matches word prefixes in any order", () => {
    expect(matches("st jo", "ST JOSEPHS HOSPITAL")).toBe(true);
    expect(matches("hospital joseph", "ST JOSEPHS HOSPITAL")).toBe(true);
    expect(matches("osep", "ST JOSEPHS HOSPITAL")).toBe(false);
  });

  it("finds hospitals by name or city", () => {
    expect(searchHospitals("tucson medical").map((h) => h.ccn)).toContain("030006");
    expect(searchHospitals("flagstaff").length).toBeGreaterThan(0);
    expect(searchHospitals("t")).toEqual([]);
  });

  it("ranks cities with more hospitals first", () => {
    const [first] = searchCities("p");
    expect(first).toBeUndefined(); // too short
    expect(searchCities("phoenix")[0].city).toBe("PHOENIX");
  });
});
