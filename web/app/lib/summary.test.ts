import { describe, expect, it } from "vitest";

import type { HospitalPrices } from "./api";
import { compareRows, median, moneyRange, sortRows, summarize, titleCase, type Filters } from "./summary";

const ALL: Filters = { county: "", setting: "any", market: "", payer: "" };

const row: HospitalPrices = {
  hospital: { ccn: "030006", name: "TUCSON MEDICAL CENTER", county: "PIMA", score_pct: 100 },
  plans: 3,
  standard: [
    { setting: "outpatient", type: "gross", amount: 2500, n: 1 },
    { setting: "outpatient", type: "discounted_cash", amount: 900, n: 1 },
    { setting: "inpatient", type: "discounted_cash", amount: 1200, n: 1 },
  ],
  prices: [
    { payer: "Aetna", plan: "PPO", group: "Aetna", market: "commercial", setting: "outpatient", type: "negotiated_dollar", amount: 1421.79, n: 1 },
    { payer: "AHCCCS", plan: "Banner UFC", group: "AHCCCS", market: "medicaid", setting: "both", type: "negotiated_dollar", amount: 167, n: 1 },
    { payer: "Aetna", plan: "PPO", group: "Aetna", market: "commercial", setting: "inpatient", type: "negotiated_algorithm", algorithm: "Bundled into the DRG", n: 1 },
  ],
};

describe("summarize", () => {
  it("summarizes every price with no filters", () => {
    const s = summarize(row, ALL);
    expect(s.cash).toEqual({ low: 900, high: 1200 });
    expect(s.gross).toEqual({ low: 2500, high: 2500 });
    expect(s.insurerMedian).toBeCloseTo((1421.79 + 167) / 2);
    expect(s.dollarPrices).toBe(2);
    expect(s.otherPrices).toBe(1);
  });

  it("counts a 'both' price in either setting", () => {
    const s = summarize(row, { ...ALL, setting: "inpatient" });
    expect(s.insurerMedian).toBe(167);
    expect(s.otherPrices).toBe(1);
    expect(s.cash).toEqual({ low: 1200, high: 1200 });
  });

  it("filters by market and by payer, plan or parent company", () => {
    expect(summarize(row, { ...ALL, market: "medicaid" }).insurerMedian).toBe(167);
    expect(summarize(row, { ...ALL, payer: "aet", setting: "outpatient" }).insurerMedian).toBe(1421.79);
    expect(summarize(row, { ...ALL, payer: "cigna" }).insurerMedian).toBeNull();
  });
});

describe("placeholders", () => {
  it("leaves $1 stand-ins out of the median and range but keeps them in the list", () => {
    const withOnes: HospitalPrices = {
      ...row,
      prices: [
        ...row.prices,
        ...[1, 1, 0.01].map((amount) => ({ payer: "UHC", plan: "Commercial", group: "UnitedHealthcare", market: "commercial", setting: "outpatient", type: "negotiated_dollar", amount, n: 1 })),
      ],
    };
    const s = summarize(withOnes, ALL);
    expect(s.insurerMedian).toBeCloseTo((1421.79 + 167) / 2);
    expect(s.insurerRange).toEqual({ low: 167, high: 1421.79 });
    expect(s.dollarPrices).toBe(2);
    expect(s.placeholders).toBe(3);
    expect(s.otherPrices).toBe(1);
    expect(s.prices).toHaveLength(6);
  });
});

describe("helpers", () => {
  it("takes the median of odd and even counts", () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([])).toBeNull();
  });

  it("puts hospitals with insurer prices first, cheapest first", () => {
    const none = { ...row, hospital: { ccn: "1", name: "A" }, prices: [] };
    const rows = [none, row].map((r) => ({ row: r, summary: summarize(r, ALL) }));
    expect(rows.sort(compareRows)[0].row.hospital.ccn).toBe("030006");
  });

  it("formats ranges and names", () => {
    expect(moneyRange({ low: 900, high: 1200 })).toBe("$900–$1,200");
    expect(moneyRange(null)).toBe("—");
    expect(titleCase("TUCSON MEDICAL CENTER")).toBe("Tucson Medical Center");
    expect(titleCase("ST JOSEPH'S HOSPITAL")).toBe("St Joseph's Hospital");
    expect(titleCase("BANNER-UNIVERSITY MEDICAL CENTER")).toBe("Banner-University Medical Center");
  });
});

describe("sortRows", () => {
  const make = (ccn: string, cash: number | null, insurer: number, score?: number): HospitalPrices => ({
    hospital: { ccn, name: ccn, score_pct: score },
    plans: 1,
    standard: cash == null ? [] : [{ setting: "outpatient", type: "discounted_cash", amount: cash, n: 1 }],
    prices: [{ payer: "Aetna", plan: "PPO", setting: "outpatient", type: "negotiated_dollar", amount: insurer, n: 1 }],
  });
  const rows = [make("a", 900, 300, 82), make("b", null, 100, 100), make("c", 400, 200)]
    .map((row) => ({ row, summary: summarize(row, ALL) }));
  const order = (key: Parameters<typeof sortRows>[1]["key"], dir: "asc" | "desc") =>
    sortRows(rows, { key, dir }).map((r) => r.row.hospital.ccn);

  it("sorts either way, keeping hospitals without the number last", () => {
    expect(order("cash", "asc")).toEqual(["c", "a", "b"]);
    expect(order("cash", "desc")).toEqual(["a", "c", "b"]);
    expect(order("median", "desc")).toEqual(["a", "c", "b"]);
    expect(order("score", "desc")).toEqual(["b", "a", "c"]);
  });
});
