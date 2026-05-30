import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        service_worker: resolve(__dirname, "background/service_worker.ts"),
        sidebar: resolve(__dirname, "sidebar/index.html"),
        // Content scripts
        "content/snapshot": resolve(__dirname, "content/snapshot.ts"),
        "content/observer": resolve(__dirname, "content/observer.ts"),
        "content/highlight": resolve(__dirname, "content/highlight.ts"),
        "content/particle": resolve(__dirname, "content/particle.ts"),
        "content/privacy": resolve(__dirname, "content/privacy.ts"),
        "content/screenshot": resolve(__dirname, "content/screenshot.ts"),
      },
      output: {
        entryFileNames: "[name].js",
        chunkFileNames: "assets/[name]-[hash].js",
        // 分离大型依赖为独立 chunk（优化缓存）
        manualChunks: {
          "three": ["three"],
        },
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
