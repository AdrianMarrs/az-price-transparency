import { Link } from "react-router";

import type { Route } from "./+types/methods";
import { Card, CardContent } from "~/components/ui/card";
import { hospitals } from "~/lib/catalog";
import { RULES } from "~/lib/rules";

export const meta: Route.MetaFunction = () => [
  { title: "How it works, and its limits | Arizona Hospital Prices" },
  { name: "description", content: "Where the prices come from, how often they're refreshed, how hospitals are scored, and what published prices can't tell you." },
];

export default function Methods() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">How it works, and its limits</h1>
      <p className="mt-4 text-lg text-muted-foreground text-pretty">
        Two federal rules make hospitals and insurers publish their prices. This site reads those
        files for Arizona and puts the numbers side by side.
      </p>

      <Section title="Where the prices come from">
        <p>
          <strong>Hospitals.</strong> Since 2021 every hospital must post a machine-readable file of
          its standard charges: the list price, the discounted cash price, and the price it has
          negotiated with each insurer and plan. We find each of Arizona's {hospitals.length} non-federal
          hospitals' files through the <code>cms-hpt.txt</code> file the rule requires on its website,
          download it every week, and read it in CMS's template format.
        </p>
        <p>
          <strong>Insurers.</strong> The Transparency in Coverage rule makes insurers publish the
          rates they've agreed with every provider in their networks. These files are enormous
          (one insurer's are about 30 GB compressed, hundreds of gigabytes as text), so they're
          streamed once a month and only the rates for Arizona hospitals are kept. We start with
          Cigna.
        </p>
      </Section>

      <Section title="How the numbers are compared">
        <ul>
          <li>Prices are matched by billing code (CPT, HCPCS or MS-DRG), by setting (inpatient or outpatient) and by type of charge. A hospital's facility fee is never compared with a physician's fee.</li>
          <li>The “insurer median” on each page is the middle of the dollar prices a hospital lists across its insurers and plans. Filters narrow it to one insurance type or insurer.</li>
          <li>Some prices are a percentage of billed charges or a formula. They're shown as written, but can't be turned into a dollar amount.</li>
        </ul>
      </Section>

      <Section title="How hospitals are scored">
        <p>We check each file against the rules a program can verify. The score is the share it meets.</p>
        <Card className="not-prose mt-4 py-2">
          <CardContent className="px-0">
            <ol className="divide-y">
              {Object.entries(RULES).map(([key, r], i) => (
                <li key={key} className="flex gap-4 px-5 py-3">
                  <span className="w-5 shrink-0 text-right text-sm tabular text-muted-foreground">{i + 1}</span>
                  <span>
                    <span className="block text-sm font-medium">{r.title}</span>
                    <span className="block text-sm text-muted-foreground">{r.why}</span>
                  </span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
        <p>
          A file that can't be downloaded or read can't be checked for the rest, so those rules
          count as unchecked, not passed.
        </p>
      </Section>

      <Section title="What this can't tell you">
        <ul>
          <li><strong>What you'll pay.</strong> Your cost depends on your plan's deductible, copays and coinsurance, and on the care you actually receive. Ask your insurer and the hospital for an estimate.</li>
          <li><strong>Every fee for a visit.</strong> A procedure often has separate bills: the hospital, the doctor, anesthesia, imaging. A page shows the charge for one billing code.</li>
          <li><strong>Whether a file is right.</strong> We show what hospitals and insurers publish. When the two disagree about the same price, both are shown.</li>
        </ul>
      </Section>

      <Section title="Open source">
        <p>
          Every step, from downloading files to this page, is in the{" "}
          <a href="https://github.com/AdrianMarrs/az-price-transparency">project's repository</a>.
          Found a problem? <Link to="/hospitals">Hospital pages</Link> link to each hospital's own
          file, so you can check any number against its source.
        </p>
      </Section>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 space-y-4 text-pretty leading-relaxed text-foreground/90 [&_a]:text-primary [&_a]:underline-offset-4 hover:[&_a]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:text-sm [&_li]:pl-1 [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5">
        {children}
      </div>
    </section>
  );
}
