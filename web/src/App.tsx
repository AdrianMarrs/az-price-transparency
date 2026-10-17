import { useEffect, useMemo, useState } from "react";

import {
  comparePrices,
  hospitalProfile,
  searchServices,
  type Compare,
  type HospitalPrices,
  type Profile,
  type Service,
} from "./api";
import {
  compareRows,
  MARKETS,
  money,
  moneyRange,
  summarize,
  titleCase,
  type Filters,
  type Setting,
  type Summary,
} from "./summary";

// The page state lives in the URL (?service=cpt-hcpcs:73721&county=PIMA), so links can be shared.
function readUrl(): { serviceId: string; filters: Filters } {
  const p = new URLSearchParams(window.location.search);
  return {
    serviceId: p.get("service") ?? "",
    filters: {
      county: p.get("county") ?? "PIMA",
      setting: (p.get("setting") as Setting) ?? "any",
      market: p.get("market") ?? "",
      payer: p.get("payer") ?? "",
    },
  };
}

function writeUrl(serviceId: string, f: Filters) {
  const p = new URLSearchParams();
  if (serviceId) p.set("service", serviceId);
  if (f.county !== "PIMA") p.set("county", f.county);
  if (f.setting !== "any") p.set("setting", f.setting);
  if (f.market) p.set("market", f.market);
  if (f.payer) p.set("payer", f.payer);
  const query = p.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

export default function App() {
  const initial = useMemo(readUrl, []);
  const [serviceId, setServiceId] = useState(initial.serviceId);
  const [filters, setFilters] = useState<Filters>(initial.filters);

  useEffect(() => writeUrl(serviceId, filters), [serviceId, filters]);

  return (
    <div className="page">
      <header>
        <h1>
          <a href="/" onClick={(e) => { e.preventDefault(); setServiceId(""); }}>
            Arizona hospital prices
          </a>
        </h1>
        <p className="lede">
          What hospitals publish for a service: cash price, list price and what each insurer pays,
          with how well each hospital follows the price transparency rules.
        </p>
      </header>
      <Search onPick={(s) => setServiceId(s.id)} />
      {serviceId && <Prices serviceId={serviceId} filters={filters} setFilters={setFilters} />}
      <footer>
        <p>
          <strong>These are published prices, not quotes.</strong> What you pay depends on your plan,
          deductible and the care you actually get. Ask your insurer and the hospital for an estimate.
        </p>
        <p>
          Data from each hospital's machine-readable price file, checked weekly.{" "}
          <a href="https://github.com/AdrianMarrs/az-price-transparency">Source and method</a>
        </p>
      </footer>
    </div>
  );
}

function Search({ onPick }: { onPick: (s: Service) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Service[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchServices(q.trim(), controller.signal)
        .then((r) => { setResults(r); setError(""); })
        .catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [q]);

  return (
    <section className="search">
      <label htmlFor="q">Find a service</label>
      <input
        id="q"
        type="search"
        placeholder="knee mri, colonoscopy, office visit, 73721…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        autoComplete="off"
      />
      {error && <p className="error">{error}</p>}
      {results.length > 0 && (
        <ul className="results">
          {results.map((s) => (
            <li key={s.id}>
              <button onClick={() => { onPick(s); setQ(""); setResults([]); }}>
                <span className="desc">{s.cms_description ?? s.description}</span>
                <span className="meta">
                  {s.code_type === "MS-DRG" ? "DRG" : "CPT"} {s.code} · {s.hospitals} hospitals
                  {s.cms_shoppable_id != null && <span className="tag">CMS shoppable</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.trim().length >= 2 && results.length === 0 && !error && (
        <p className="hint">No matches yet. Try a simpler word or the billing code.</p>
      )}
    </section>
  );
}

function Prices({ serviceId, filters, setFilters }: {
  serviceId: string;
  filters: Filters;
  setFilters: (f: Filters) => void;
}) {
  const [data, setData] = useState<Compare | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    comparePrices(serviceId, controller.signal)
      .then(setData)
      .catch((e) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [serviceId]);

  if (error) return <p className="error">Couldn't load prices: {error}</p>;
  if (!data) return <p className="loading">Loading prices…</p>;

  const counties = [...new Set(data.hospitals.map((h) => h.hospital.county ?? ""))].filter(Boolean).sort();
  const markets = [...new Set(data.hospitals.flatMap((h) => h.prices.map((p) => p.market ?? "")))]
    .filter((m) => m in MARKETS);
  const inCounty = data.hospitals.filter((h) => !filters.county || h.hospital.county === filters.county);
  const rows = inCounty.map((row) => ({ row, summary: summarize(row, filters) })).sort(compareRows);
  const s = data.service;
  const set = (patch: Partial<Filters>) => setFilters({ ...filters, ...patch });

  return (
    <section className="prices">
      <h2>{s.cms_description ?? titleCase(s.description)}</h2>
      <p className="meta">
        {s.code_type === "MS-DRG" ? "MS-DRG" : "CPT/HCPCS"} {s.code}
        {s.cms_description && <> · hospitals bill it as “{s.description}”</>}
      </p>

      <div className="filters">
        <label>
          Area
          <select value={filters.county} onChange={(e) => set({ county: e.target.value })}>
            <option value="">All of Arizona</option>
            {counties.map((c) => <option key={c} value={c}>{titleCase(c)} County</option>)}
          </select>
        </label>
        <label>
          Setting
          <select value={filters.setting} onChange={(e) => set({ setting: e.target.value as Setting })}>
            <option value="any">Any</option>
            <option value="outpatient">Outpatient</option>
            <option value="inpatient">Inpatient</option>
          </select>
        </label>
        <label>
          Insurance type
          <select value={filters.market} onChange={(e) => set({ market: e.target.value })}>
            <option value="">All</option>
            {markets.map((m) => <option key={m} value={m}>{MARKETS[m]}</option>)}
          </select>
        </label>
        <label>
          Insurer or plan
          <input
            type="search"
            placeholder="e.g. Aetna, BCBS"
            value={filters.payer}
            onChange={(e) => set({ payer: e.target.value })}
          />
        </label>
      </div>

      {rows.length === 0 ? (
        <p className="hint">
          No hospital {filters.county ? `in ${titleCase(filters.county)} County ` : ""}publishes a
          price for this service. Try all of Arizona.
        </p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Hospital</th>
                <th className="num">Insurer median</th>
                <th className="num">Insurer range</th>
                <th className="num">Cash price</th>
                <th className="num">List price</th>
                <th>Transparency</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ row, summary }) => (
                <HospitalRow key={row.hospital.ccn} row={row} summary={summary} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="note">{data.note}</p>
    </section>
  );
}

function Badge({ score }: { score?: number }) {
  if (score == null) return <span className="badge">Not scored</span>;
  const level = score >= 100 ? "good" : score >= 70 ? "fair" : "poor";
  const label = score >= 100 ? "Passes every rule" : `${Math.round(score)}% of rules`;
  return <span className={`badge ${level}`}>{label}</span>;
}

function HospitalRow({ row, summary }: { row: HospitalPrices; summary: Summary }) {
  const [open, setOpen] = useState(false);
  const h = row.hospital;
  return (
    <>
      <tr className={open ? "open" : ""}>
        <td>
          <button className="expand" aria-expanded={open} onClick={() => setOpen(!open)}>
            <span className="name">{titleCase(h.name)}</span>
            <span className="meta">{titleCase(h.city)}</span>
          </button>
        </td>
        <td className="num">
          {money(summary.insurerMedian)}
          {summary.dollarPrices > 0 && <span className="meta"> {summary.dollarPrices} prices</span>}
        </td>
        <td className="num">{moneyRange(summary.insurerRange)}</td>
        <td className="num">{moneyRange(summary.cash)}</td>
        <td className="num">{moneyRange(summary.gross)}</td>
        <td><Badge score={h.score_pct} /></td>
      </tr>
      {open && (
        <tr className="detail">
          <td colSpan={6}>
            <PlanPrices summary={summary} />
            <HospitalDetails ccn={h.ccn} />
          </td>
        </tr>
      )}
    </>
  );
}

function PlanPrices({ summary }: { summary: Summary }) {
  if (summary.prices.length === 0) {
    return <p className="hint">No insurer prices match these filters.</p>;
  }
  return (
    <table className="plans">
      <thead>
        <tr><th>Insurer</th><th>Plan</th><th>Type</th><th>Setting</th><th className="num">Price</th></tr>
      </thead>
      <tbody>
        {summary.prices.map((p, i) => (
          <tr key={i}>
            <td>{p.payer}</td>
            <td>{p.plan}</td>
            <td>{MARKETS[p.market ?? ""] ?? ""}</td>
            <td>{p.setting}</td>
            <td className="num">
              {p.type === "negotiated_dollar"
                ? money(p.amount)
                : p.type === "negotiated_percentage"
                  ? `${p.amount ?? "?"}% of charges`
                  : <span className="meta">{p.algorithm ?? "formula"}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function HospitalDetails({ ccn }: { ccn: string }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    hospitalProfile(ccn, controller.signal).then(setProfile).catch(() => {});
    return () => controller.abort();
  }, [ccn]);
  if (!profile) return null;
  return (
    <div className="hospital">
      <p>
        {titleCase(profile.address)}, {titleCase(profile.city)} {profile.zip} ·{" "}
        {profile.hospital_type}
      </p>
      <p>
        Price transparency: passes {profile.rules_passed} of {profile.rules_checked} rules we can
        check{profile.failed_rules ? `; fails: ${profile.failed_rules.replaceAll("_", " ")}` : ""}.
        {profile.mrf_url && <> <a href={profile.mrf_url}>The hospital's price file</a>.</>}
      </p>
    </div>
  );
}
