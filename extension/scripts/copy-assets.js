/**
 * Copy static assets to dist/
 * - icons/
 * - manifest.json
 */

import { cpSync, copyFileSync, mkdirSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const dist = resolve(root, "dist");

// Copy icons
const iconsSrc = resolve(root, "icons");
const iconsDest = resolve(dist, "icons");
if (existsSync(iconsSrc)) {
  mkdirSync(iconsDest, { recursive: true });
  cpSync(iconsSrc, iconsDest, { recursive: true });
  console.log("Copied: icons/");
}

// Copy manifest.json
const manifestSrc = resolve(root, "manifest.json");
const manifestDest = resolve(dist, "manifest.json");
if (existsSync(manifestSrc)) {
  copyFileSync(manifestSrc, manifestDest);
  console.log("Copied: manifest.json");
}

console.log("Static assets copied to dist/");
