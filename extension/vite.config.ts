import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.json";

const buildId = Date.now().toString(36);

export default defineConfig({
  base: "./",
  define: {
    __HUOKE_BUILD_ID__: JSON.stringify(buildId),
  },
  plugins: [crx({ manifest })],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      input: {
        popup: "src/popup/index.html",
        offscreen: "src/offscreen/offscreen.html",
      },
    },
  },
});
