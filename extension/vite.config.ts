import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        service_worker: resolve(__dirname, "background/service_worker.ts"),
        sidebar: resolve(__dirname, "sidebar/index.html"),
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
    target: "es2022",
    sourcemap: true,
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "."),
    },
  },
});
