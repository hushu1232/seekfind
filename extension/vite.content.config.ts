import { defineConfig } from "vite";
import { resolve } from "path";

// Content scripts 专用配置 — 每个文件独立 IIFE 构建
// Chrome content scripts 不支持 ES modules，必须用 IIFE 格式

const contentScripts = [
  "snapshot",
  "observer",
  "highlight",
  "particle",
  "privacy",
  "screenshot",
];

// 为每个 content script 生成独立配置
export default contentScripts.map((name) =>
  defineConfig({
    build: {
      outDir: "dist",
      emptyOutDir: false,
      lib: {
        entry: resolve(__dirname, `content/${name}.ts`),
        formats: ["iife"],
        name: `qiuwen_${name.replace(/-/g, "_")}`,
        fileName: () => `content/${name}.js`,
      },
      rollupOptions: {
        output: {
          // IIFE 格式，无 export
          exports: "none",
        },
      },
      target: "es2022",
      sourcemap: true,
      minify: "esbuild",
    },
    resolve: {
      alias: {
        "@": resolve(__dirname, "."),
      },
    },
  })
);
