import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("services", "routes/services.tsx"),
  route("services/:slug", "routes/service.tsx"),
  route("hospitals", "routes/hospitals.tsx"),
  route("hospitals/:ccn", "routes/hospital.tsx"),
  route("search", "routes/search.tsx"),
  route("methods", "routes/methods.tsx"),
  route("*", "routes/not-found.tsx"),
] satisfies RouteConfig;
