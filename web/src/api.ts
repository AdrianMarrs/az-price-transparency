// Client for the price API (api/handler.py), through CloudFront.

const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export type Service = {
  id: string;
  key: string;
  code: string;
  code_type: string;
  description: string;
  cms_shoppable_id?: number;
  cms_description?: string;
  hospitals: number;
};

export type Price = {
  payer?: string;
  plan?: string;
  group?: string;
  market?: string;
  setting?: string;
  type: string;
  method?: string;
  amount?: number;
  algorithm?: string;
  bundled?: boolean;
  n: number;
};

export type Hospital = {
  ccn: string;
  name?: string;
  city?: string;
  county?: string;
  score_pct?: number;
  hospital_type?: string;
};

export type HospitalPrices = {
  hospital: Hospital;
  plans: number;
  standard: Price[];
  prices: Price[];
};

export type Compare = {
  service: Service;
  hospitals: HospitalPrices[];
  note: string;
};

export type Profile = Hospital & {
  address?: string;
  zip?: string;
  ownership?: string;
  mrf_url?: string;
  rules_checked?: number;
  rules_passed?: number;
  failed_rules?: string;
  services?: number;
  price_file_status?: string;
  note: string;
};

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, { signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error ?? `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const searchServices = (q: string, signal?: AbortSignal) =>
  get<{ services: Service[] }>(`/services?q=${encodeURIComponent(q)}`, signal).then(
    (r) => r.services,
  );

// Filters are applied in the browser so one cached response serves every filter choice.
export const comparePrices = (serviceId: string, signal?: AbortSignal) =>
  get<Compare>(`/services/${serviceId}/prices`, signal); // ids are [a-z0-9:-], safe in a path

export const hospitalProfile = (ccn: string, signal?: AbortSignal) =>
  get<Profile>(`/providers/${ccn}`, signal);
