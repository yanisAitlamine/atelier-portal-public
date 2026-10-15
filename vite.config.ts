import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
export default defineConfig({
  base: "/portal/",
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/portal/api": {
        target: "http://127.0.0.1:4180",
        rewrite: (p) => p.replace(/^\/portal/, ""),
      },
      "/portal/logout": {
        target: "http://127.0.0.1:4180",
        rewrite: (p) => p.replace(/^\/portal/, ""),
      },
    },
  },
});
