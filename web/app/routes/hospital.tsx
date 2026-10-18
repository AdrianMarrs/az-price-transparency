import { CircleCheck, CircleX, ExternalLink, MapPin } from "lucide-react";
import { data, Link } from "react-router";

import type { Route } from "./+types/hospital";
import { ScoreBadge } from "~/components/score-badge";
import { Badge } from "~/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "~/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "~/components/ui/table";
import { hospitalProfile, type Profile } from "~/lib/api";
import { hospital as summaryOf, serviceSlug } from "~/lib/catalog";
import { failedRules, RULES } from "~/lib/rules";
import { money, titleCase } from "~/lib/summary";

async function load(ccn: string): Promise<Profile> {
  if (!summaryOf(ccn)) throw data("Not found", { status: 404 });
  try {
    return await hospitalProfile(ccn);
  } catch {
    throw data("Not found", { status: 404 });
  }
}

// At build time (the pre-rendered page), then again in the browser for the latest numbers.
export const loader = ({ params }: Route.LoaderArgs) => load(params.ccn);
export const clientLoader = ({ params }: Route.ClientLoaderArgs) => load(params.ccn);
clientLoader.hydrate = true as const;

export const meta: Route.MetaFunction = ({ loaderData }) => {
  if (!loaderData) return [{ title: "Hospital not found | Clear Healthcare Prices" }];
  const name = titleCase(loaderData.name);
  return [
    { title: `${name} prices and price transparency | Clear Healthcare Prices` },
    { name: "description", content: `Published prices at ${name} in ${titleCase(loaderData.city)}, AZ: cash, list and insurer prices for common services, and how well it follows the price transparency rules.` },
  ];
};

const slugFromKey = (key: string) => serviceSlug(key.replace("CPT/HCPCS:", "cpt-hcpcs:").replace("MS-DRG:", "ms-drg:").toLowerCase());

export default function Hospital({ loaderData: p }: Route.ComponentProps) {
  const failed = failedRules(p.failed_rules);
  const passed = p.rules_passed ?? (p.rules_checked != null ? p.rules_checked - failed.length : null);
  const shoppable = [...(p.shoppable ?? [])].sort((a, b) => a.cms_shoppable_id - b.cms_shoppable_id);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link to="/hospitals" className="hover:text-foreground">Hospitals</Link>
        <span aria-hidden className="mx-2">/</span>
        <span className="text-foreground">{titleCase(p.name)}</span>
      </nav>

      <header className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-balance">{titleCase(p.name)}</h1>
          <p className="mt-2 flex items-center gap-1.5 text-muted-foreground">
            <MapPin aria-hidden className="size-4" />
            {titleCase(p.address)}, {titleCase(p.city)}, AZ {p.zip}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Badge variant="secondary">{p.hospital_type}</Badge>
            {p.ownership && <Badge variant="outline">{p.ownership}</Badge>}
          </div>
        </div>
        <ScoreBadge score={p.score_pct} className="self-start text-sm" />
      </header>

      <div className="mt-8 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Price transparency</CardTitle>
            <CardDescription>
              {passed != null && p.rules_checked
                ? `Meets ${passed} of the ${p.rules_checked} rules we can check.`
                : "We couldn't check this hospital's file."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {failed.length > 0 && (
              <ul className="space-y-3">
                {failed.map((r) => (
                  <li key={r} className="flex gap-2.5">
                    <CircleX aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
                    <span>
                      <span className="block text-sm font-medium">{RULES[r].title}</span>
                      <span className="block text-sm text-muted-foreground">{RULES[r].why}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {passed != null && passed > 0 && (
              <p className="flex items-center gap-2.5 text-sm text-muted-foreground">
                <CircleCheck aria-hidden className="size-4 shrink-0 text-success" />
                {failed.length ? `Meets the other ${passed}.` : "Meets every rule we check."}
              </p>
            )}
            {p.mrf_url && (
              <a href={p.mrf_url} className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline" rel="noopener">
                The hospital's own price file <ExternalLink aria-hidden className="size-3.5" />
              </a>
            )}
          </CardContent>
        </Card>

        <Card className="py-0 lg:col-span-2">
          <CardHeader className="pt-6">
            <CardTitle>Common services</CardTitle>
            <CardDescription>
              {shoppable.length
                ? `${shoppable.length} of CMS's shoppable services. The insurer price is the median across every plan the hospital lists.`
                : "This hospital's file has no prices we could read for CMS's shoppable services."}
            </CardDescription>
          </CardHeader>
          {shoppable.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-6">Service</TableHead>
                  <TableHead className="text-right">Insurer median</TableHead>
                  <TableHead className="text-right">Cash price</TableHead>
                  <TableHead className="hidden pr-6 text-right sm:table-cell">Plans</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shoppable.map((s) => (
                  <TableRow key={s.service_key}>
                    <TableCell className="whitespace-normal pl-6">
                      <Link to={`/services/${slugFromKey(s.service_key)}`} className="hover:text-primary hover:underline">
                        {s.description}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular">{money(s.negotiated_median)}</TableCell>
                    <TableCell className="text-right tabular">{s.cash != null ? money(s.cash) : <span className="text-xs text-muted-foreground">Unpublished</span>}</TableCell>
                    <TableCell className="hidden pr-6 text-right tabular text-muted-foreground sm:table-cell">{s.plans}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
      </div>
      <p className="mt-6 text-sm text-muted-foreground">{p.note}</p>
    </div>
  );
}
