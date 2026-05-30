/**
 * 求问 — 构建脚本
 * 支持 Chrome 和 Firefox 双目标构建
 *
 * 用法：
 *   node scripts/build.js           # 默认 Chrome
 *   node scripts/build.js chrome    # Chrome/Edge
 *   node scripts/build.js firefox   # Firefox
 */

import { cpSync, copyFileSync, mkdirSync, existsSync, readFileSync, writeFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const dist = resolve(root, "dist");

const target = process.argv[2] || "chrome";

if (!["chrome", "firefox"].includes(target)) {
  console.error(`Unknown target: ${target}. Use 'chrome' or 'firefox'.`);
  process.exit(1);
}

console.log(`Building for: ${target}`);

// Copy manifest
const manifestSrc = resolve(root, `manifest.${target}.json`);
const manifestDest = resolve(dist, "manifest.json");
if (existsSync(manifestSrc)) {
  copyFileSync(manifestSrc, manifestDest);
  console.log(`Copied: manifest.${target}.json -> dist/manifest.json`);
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
console.log(`Load dist/ folder as unpacked extension in ${target === "firefox" ? "Firefox" : "Chrome/Edge"}.`);
