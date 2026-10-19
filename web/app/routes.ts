import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("methods", "routes/methods.tsx"),
  route("search", "routes/search.tsx"),
  route("hospitals/:ccn", "routes/hospital.tsx"),
  // Before every state had pages, Arizona's were at /services and /hospitals.
  route("services", "routes/legacy.tsx", { id: "legacy-services" }),
  route("services/:slug", "routes/legacy.tsx", { id: "legacy-service" }),
  route("hospitals", "routes/legacy.tsx", { id: "legacy-hospitals" }),
  route(":state", "routes/state.tsx"),
  route(":state/services", "routes/services.tsx"),
  route(":state/services/:slug", "routes/service.tsx"),
  route(":state/hospitals", "routes/hospitals.tsx"),
  route("*", "routes/not-found.tsx"),
] satisfies RouteConfig;
