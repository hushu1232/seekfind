/**
 * 构建 Content Scripts 为 IIFE 格式
 * Chrome content scripts 不支持 ES modules
 *
 * 用法: node scripts/build-content.js
 */

import { execSync } from "child_process";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

const scripts = [
  "snapshot",
  "observer",
  "highlight",
  "particle",
  "privacy",
  "screenshot",
  "float-ball",
];

for (const name of scripts) {
  console.log(`Building content/${name}.ts → IIFE...`);
  execSync(
    `npx vite build --config vite.content.single.config.ts`,
    {
      cwd: root,
      stdio: "inherit",
      env: { ...process.env, CS_NAME: name },
    }
  );
}

console.log("All content scripts built.");
