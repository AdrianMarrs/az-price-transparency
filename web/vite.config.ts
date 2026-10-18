import { fileURLToPath } from "node:url";

import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [tailwindcss(), reactRouter()],
  resolve: { alias: { "~": fileURLToPath(new URL("./app", import.meta.url)) } },
  build: { sourcemap: true },
  server: {
    // The data files live next to the live site (serving/export_static.py); in development
    // they're fetched from there, as if same-origin.
    proxy: { "/data": { target: process.env.VITE_DATA_URL ?? "https://clearhealthcareprices.com", changeOrigin: true } },
    // In the Docker dev container the source is a bind mount from Windows, where file
    // change events don't cross into the container; poll instead.
    watch: process.env.VITE_POLL ? { usePolling: true, interval: 300 } : undefined,
  },
});
