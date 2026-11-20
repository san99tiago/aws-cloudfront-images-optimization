import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Local development: `make dev` writes public/config.json and .env.local (VITE_API_PROXY) from the stack
// outputs, so /api/* is proxied to the deployed CloudFront distribution (same path as in production).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: env.VITE_API_PROXY ? { "/api": { target: env.VITE_API_PROXY, changeOrigin: true, secure: true } } : undefined,
    },
    build: {
      target: "es2022",
      sourcemap: false,
      // Hashed file names (immutable assets): safe to cache for one year at the edge and in the browser
      assetsDir: "assets",
    },
  };
});
