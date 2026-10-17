// The price transparency rules ingest/hospitals/compliance.py checks, in plain language.
// Keep in step with RULES there.

export const RULES: Record<string, { title: string; why: string }> = {
  cms_hpt_lists_hospital: {
    title: "Its website lists the price file",
    why: "A cms-hpt.txt file at the website's root must point to the hospital's price file, so programs can find it.",
  },
  cms_hpt_machine_readable: {
    title: "That listing is machine-readable",
    why: "cms-hpt.txt must follow CMS's format so a program can read it.",
  },
  price_file_downloads: {
    title: "The price file can be downloaded",
    why: "The file must be free to download without an account, password or personal details, and by automated programs, not just a browser.",
  },
  price_file_parses: {
    title: "The file follows CMS's template",
    why: "Since July 2024 hospitals must use one of CMS's templates (CSV or JSON).",
  },
  version_stated: {
    title: "The file says which template version it uses",
    why: "The version tells a reader which columns and rules apply.",
  },
  header_fields_present: {
    title: "Every required header field is filled in",
    why: "Hospital name, address, license number, last-updated date and an attestation that the file is accurate.",
  },
  payer_prices_present: {
    title: "It lists what each insurer pays",
    why: "Payer-specific negotiated charges are the heart of the rule.",
  },
  mostly_dollar_prices: {
    title: "Insurer prices are mostly dollar amounts",
    why: "Prices given only as percentages or formulas can't be compared; we expect at least half to be dollars.",
  },
  updated_within_12_months: {
    title: "The file was updated in the last year",
    why: "Hospitals must update the file at least once a year.",
  },
};

export function failedRules(failed: string | undefined): string[] {
  return (failed ?? "").split(/[,;]\s*/).map((r) => r.trim()).filter((r) => r in RULES);
}
