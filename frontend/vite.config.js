import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_PROXY_TARGET || "http://127.0.0.1:18000";

  return {
    base: "/",
    plugins: [vue()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      allowedHosts: ["localhost", "127.0.0.1"],
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  };
});
