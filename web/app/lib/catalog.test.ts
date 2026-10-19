import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { citiesOf, matches, searchCities, searchHospitals, serviceApiId, serviceSlug, type StateCatalog } from "./catalog";
import { searchStates, stateFor, stateOfCcn, statePath } from "./states";

// Arizona's catalog as scripts/build-data.mjs writes it.
const az: StateCatalog = JSON.parse(readFileSync("public/catalog/az.json", "utf8"));

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
    expect(searchHospitals(az.hospitals, "tucson medical").map((h) => h.ccn)).toContain("030006");
    expect(searchHospitals(az.hospitals, "flagstaff").length).toBeGreaterThan(0);
    expect(searchHospitals(az.hospitals, "t")).toEqual([]);
  });

  it("ranks cities with more hospitals first", () => {
    const cities = citiesOf(az.hospitals);
    expect(searchCities(cities, "p")).toEqual([]); // too short
    expect(searchCities(cities, "phoenix")[0].city).toBe("PHOENIX");
    expect(cities[0].hospitals).toBeGreaterThanOrEqual(cities[1].hospitals);
  });
});

describe("states", () => {
  it("finds a state by its code in a URL, in any case", () => {
    expect(stateFor("tx")?.name).toBe("Texas");
    expect(stateFor("TX")?.code).toBe("TX");
    expect(stateFor("zz")).toBeUndefined();
    expect(stateFor(undefined)).toBeUndefined();
  });

  it("knows a hospital's state from its CCN", () => {
    expect(stateOfCcn("030006")?.code).toBe("AZ");
    expect(stateOfCcn("450358")?.code).toBe("TX");
    expect(stateOfCcn("990001")).toBeUndefined();
  });

  it("makes lowercase paths", () => {
    expect(statePath("TX")).toBe("/tx");
    expect(statePath(stateFor("az")!)).toBe("/az");
  });

  it("searches state names and codes", () => {
    expect(searchStates("new").map((s) => s.code)).toEqual(expect.arrayContaining(["NH", "NJ"]));
    expect(searchStates("tx").map((s) => s.code)).toEqual(["TX"]);
    expect(searchStates("caro", 5).map((s) => s.code).sort()).toEqual(["NC", "SC"]);
    expect(searchStates("t")).toEqual([]);
  });
});
