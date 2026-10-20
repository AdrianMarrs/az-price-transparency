import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv, type Plugin } from "vite";

// ads.txt names who may sell the site's ad space: with AdSense on (app/components/ad-slot.tsx),
// Google, for this publisher ID; f08c47fec0942fa0 is Google's own ID in that file.
function adsTxt(): Plugin {
  let client: string | undefined;
  return {
    name: "ads-txt",
    apply: "build",
    configResolved(config) {
      if (!config.build.ssr) client = loadEnv(config.mode, config.root, "VITE_").VITE_ADSENSE_CLIENT;
    },
    writeBundle(options) {
      if (client && options.dir) {
        writeFileSync(join(options.dir, "ads.txt"), `google.com, ${client.replace(/^ca-/, "")}, DIRECT, f08c47fec0942fa0\n`);
      }
    },
  };
}

export default defineConfig({
  plugins: [tailwindcss(), reactRouter(), adsTxt()],
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
