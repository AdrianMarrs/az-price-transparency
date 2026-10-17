import { data } from "react-router";

// Any unknown path: the root ErrorBoundary renders the 404 page.
export async function clientLoader() {
  throw data("Not found", { status: 404 });
}

export default function NotFound() {
  return null;
}
