import { defineConfig } from "vite";
import { resolve } from "path";

const name = process.env.CS_NAME || "snapshot";
// IIFE name 不能含连字符，替换为下划线
const iifeName = `_qw_${name.replace(/-/g, "_")}`;

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    lib: {
      entry: resolve(__dirname, `content/${name}.ts`),
      formats: ["iife"],
      name: iifeName,
      fileName: () => `content/${name}.js`,
    },
    target: "es2022",
    sourcemap: true,
    minify: "esbuild",
  },
  resolve: {
    alias: { "@": resolve(__dirname, ".") },
  },
});
