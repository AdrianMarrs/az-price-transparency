import { describe, expect, it } from "vitest";

import type { HospitalPrices } from "./api";
import { compareRows, median, moneyRange, summarize, titleCase, type Filters } from "./summary";

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
