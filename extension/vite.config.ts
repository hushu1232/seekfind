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
        chunkFileNames: "assets/[name]-[hash].js",
        // Content scripts 单独用 IIFE 格式构建
        format: "es",
      },
    },
    target: "es2022",
    sourcemap: true,
    minify: "esbuild",
    chunkSizeWarningLimit: 500,
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "."),
    },
  },
});
