// The data every state page starts from: the state, and its hospitals (its catalog).

import { data } from "react-router";

import { stateCatalog } from "~/lib/catalog";
import { stateFor } from "~/lib/states";

export async function stateData(code: string) {
  const state = stateFor(code);
  if (!state) throw data("Not found", { status: 404 });
  return { state, catalog: await stateCatalog(state.code) };
}
