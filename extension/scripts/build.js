/**
 * 求问 — 构建脚本
 * 支持 Chrome / Edge / Firefox 三目标构建
 *
 * 用法：
 *   node scripts/build.js           # 默认 Edge（核心面向）
 *   node scripts/build.js edge      # Microsoft Edge
 *   node scripts/build.js chrome    # Chrome
 *   node scripts/build.js firefox   # Firefox
 */

import { cpSync, copyFileSync, mkdirSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const dist = resolve(root, "dist");

const target = process.argv[2] || "edge";  // 默认 Edge

if (!["chrome", "edge", "firefox"].includes(target)) {
  console.error(`Unknown target: ${target}. Use 'edge', 'chrome' or 'firefox'.`);
  process.exit(1);
}

console.log(`Building for: ${target}`);

// Copy manifest（Edge 和 Chrome 共用同一个 manifest）
const manifestFile = target === "firefox" ? "manifest.firefox.json" : "manifest.chrome.json";
const manifestSrc = resolve(root, manifestFile);
const manifestDest = resolve(dist, "manifest.json");
if (existsSync(manifestSrc)) {
  copyFileSync(manifestSrc, manifestDest);
  console.log(`Copied: ${manifestFile} -> dist/manifest.json`);
} else {
  console.error(`Manifest not found: ${manifestSrc}`);
  process.exit(1);
}

// Copy icons
const iconsSrc = resolve(root, "icons");
const iconsDest = resolve(dist, "icons");
if (existsSync(iconsSrc)) {
  mkdirSync(iconsDest, { recursive: true });
  cpSync(iconsSrc, iconsDest, { recursive: true });
  console.log("Copied: icons/");
}

console.log(`\nBuild complete for ${target}!`);
if (target === "edge") {
  console.log("Load dist/ folder in Edge: edge://extensions -> 开发者模式 -> 加载已解压");
} else if (target === "firefox") {
  console.log("Load dist/ folder in Firefox: about:debugging -> 此 Firefox -> 加载临时附加组件");
} else {
  console.log("Load dist/ folder in Chrome: chrome://extensions -> 开发者模式 -> 加载已解压");
}
