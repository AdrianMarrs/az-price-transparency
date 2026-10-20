// Ways to help the site, for readers who block ads: the "custom choice" in AdSense's ad
// blocker message links here.

import { Link } from "react-router";

import type { Route } from "./+types/support";

export const meta: Route.MetaFunction = () => [
  { title: "Support the site | Clear Healthcare Prices" },
  { name: "description", content: "Clear Healthcare Prices is free, with no accounts. Here's how to help keep it that way." },
];

export default function Support() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Support the site</h1>
      <p className="mt-4 text-lg text-muted-foreground text-pretty">
        Clear Healthcare Prices is free to use, with no accounts and no paywall. Ads pay for it.
      </p>
      <div className="mt-6 space-y-4 text-pretty [&_a]:text-primary [&_a:hover]:underline">
        <h2 className="pt-4 text-xl font-semibold tracking-tight">Allow ads on this site</h2>
        <p>
          If you use an ad blocker, you can allow ads on clearhealthcareprices.com only. Most ad
          blockers have a button for this in their menu, such as “Pause on this site” or “Don't
          run on this site”. Then reload the page.
        </p>
        <p>
          The ads are labelled, kept apart from the prices, and are not personalized: they're
          chosen from the page you're reading, not from what Google knows about you. No
          advertiser can change a price, a ranking or a score.{" "}
          <Link to="/privacy">More about the ads and your privacy</Link>.
        </p>
        <h2 className="pt-4 text-xl font-semibold tracking-tight">Share it</h2>
        <p>
          A price is most useful before someone books. If you know someone comparing what a
          procedure costs, send them the page for it.
        </p>
        <h2 className="pt-4 text-xl font-semibold tracking-tight">Tell us what's wrong</h2>
        <p>
          If a price looks wrong or a hospital is missing, say so in an{" "}
          <a href="https://github.com/AdrianMarrs/az-price-transparency/issues">issue on GitHub</a>.
          Hospitals' files are often hard to read, and reports help find the ones we read
          wrongly.
        </p>
      </div>
    </article>
  );
}
