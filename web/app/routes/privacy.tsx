// What the site collects (nothing of its own) and what its ads do. AdSense's program
// policies require a privacy policy that discloses Google's cookies.

import type { Route } from "./+types/privacy";

export const meta: Route.MetaFunction = () => [
  { title: "Privacy and ads | Clear Healthcare Prices" },
  { name: "description", content: "What this site collects about you (nothing of its own), and how the ads from Google work." },
];

export default function Privacy() {
  return (
    <article className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">Privacy and ads</h1>
      <div className="mt-6 space-y-4 text-pretty [&_a]:text-primary [&_a:hover]:underline">
        <h2 className="pt-4 text-xl font-semibold tracking-tight">What we collect</h2>
        <p>
          Nothing of our own. There are no accounts, the site sets no cookies of its own, and
          we don't keep a log of who visits. Searches run in your browser: what you search for
          isn't sent to us.
        </p>
        <h2 className="pt-4 text-xl font-semibold tracking-tight">Ads</h2>
        <p>
          Some pages show ads from Google AdSense, which pay for the site. They're labelled
          “Advertisement” and are kept apart from the prices. No advertiser can change a price,
          a ranking or a score.
        </p>
        <p>
          We ask Google for non-personalized ads: ads chosen from the page you're on, such as
          its state and procedure, not from what Google knows about you. Google and its partners
          still use cookies and similar technology to show those ads, limit how often you see
          the same one, measure them and stop fraud. That means Google can receive your IP
          address and the address of the page you're reading.
        </p>
        <ul className="list-disc space-y-2 pl-6">
          <li>
            <a href="https://policies.google.com/technologies/partner-sites">How Google uses information from sites that use its services</a>
          </li>
          <li>
            <a href="https://policies.google.com/technologies/ads">How Google uses cookies in advertising</a>
          </li>
          <li>
            <a href="https://myadcenter.google.com/">My Ad Center</a>, where you can turn off personalized ads from Google everywhere
          </li>
        </ul>
        <p>An ad blocker hides the ads; every page works the same without them.</p>
        <h2 className="pt-4 text-xl font-semibold tracking-tight">Health information</h2>
        <p>
          This site doesn't know who you are or what care you need, and never asks. A page about
          a procedure is a public page anyone can read. Google receives that page's address, as
          above, and isn't asked to use it to personalize the ads you see.
        </p>
      </div>
    </article>
  );
}
