import { Link } from "react-router";

import type { Route } from "./+types/services";
import { SearchBox } from "~/components/search-box";
import { Card, CardContent } from "~/components/ui/card";
import { categories, featuredServices } from "~/lib/catalog";

export const meta: Route.MetaFunction = () => [
  { title: "Services: compare prices for common procedures | Clear Healthcare Prices" },
  { name: "description", content: "CMS's shoppable services by category, from office visits and lab tests to imaging, surgery and childbirth, with prices at every Arizona hospital." },
];

const anchor = (category: string) => category.toLowerCase().replace(/[^a-z0-9]+/g, "-");

export default function Services() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Services</h1>
      <p className="mt-2 max-w-2xl text-muted-foreground">
        These are the {featuredServices.length} services CMS calls “shoppable”: care you can
        schedule ahead, so you can compare. Hospitals price thousands more; search for any
        procedure or billing code.
      </p>
      <div className="mt-6 max-w-xl"><SearchBox size="sm" /></div>

      <nav aria-label="Categories" className="mt-8 flex flex-wrap gap-2">
        {categories.map((c) => (
          <a key={c} href={`#${anchor(c)}`} className="rounded-full border px-3 py-1 text-sm text-muted-foreground hover:border-primary hover:text-primary">
            {c}
          </a>
        ))}
      </nav>

      <div className="mt-8 space-y-10">
        {categories.map((c) => (
          <section key={c} id={anchor(c)} className="scroll-mt-24" aria-labelledby={`${anchor(c)}-h`}>
            <h2 id={`${anchor(c)}-h`} className="text-lg font-semibold">{c}</h2>
            <Card className="mt-3 py-1">
              <CardContent className="px-0">
                <ul className="divide-y">
                  {featuredServices.filter((s) => s.category === c).map((s) => (
                    <li key={s.slug}>
                      <Link to={`/services/${s.slug}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/50">
                        <span>{s.description}</span>
                        <span className="shrink-0 font-mono text-xs text-muted-foreground">
                          {s.code_type === "MS-DRG" ? "DRG" : "CPT"} {s.code}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </section>
        ))}
      </div>
    </div>
  );
}
