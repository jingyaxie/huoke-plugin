import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const manifestPath = path.join(dist, "manifest.json");

function fail(msg) {
  console.error(`[verify-dist] FAIL: ${msg}`);
  process.exit(1);
}

if (!fs.existsSync(dist)) fail("dist/ missing — run: npm run build");
if (!fs.existsSync(manifestPath)) fail("dist/manifest.json missing");

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const sw = manifest.background?.service_worker;
if (!sw) fail("manifest.background.service_worker missing");
if (sw.endsWith(".ts")) {
  fail(`loaded source manifest — Chrome cannot run ${sw}. Load extension/dist only.`);
}

const swPath = path.join(dist, sw);
if (!fs.existsSync(swPath)) fail(`service worker file missing: ${sw}`);

const popup = manifest.action?.default_popup;
if (popup) {
  const popupHtml = path.join(dist, popup);
  if (!fs.existsSync(popupHtml)) fail(`popup html missing: ${popup}`);
  const html = fs.readFileSync(popupHtml, "utf8");
  if (html.includes('src="/assets/')) {
    fail("popup uses absolute /assets paths — rebuild with base: './'");
  }
}

const csFiles = manifest.content_scripts?.flatMap((entry) => entry.js ?? []) ?? [];
const loaderRel = csFiles.find((rel) => rel.includes("loader") || rel.includes("index.ts"));
if (!loaderRel) fail("manifest content_scripts missing index loader");

const loaderPath = path.join(dist, loaderRel);
if (!fs.existsSync(loaderPath)) fail(`content loader missing: ${loaderRel}`);

const loader = fs.readFileSync(loaderPath, "utf8");
const match = loader.match(/getURL\("([^"]+)"\)/);
if (!match) fail(`content loader has no getURL target: ${loaderRel}`);
const chunkRel = match[1];
const chunkPath = path.join(dist, chunkRel);
if (!fs.existsSync(chunkPath)) fail(`content chunk missing: ${chunkRel}`);

fs.writeFileSync(
  loaderPath,
  `(function () {
  'use strict';
  (async () => {
    await import(chrome.runtime.getURL("${chunkRel}"));
  })().catch((error) => console.error('[huoke-ext] content import failed', error));
})();
`,
);

const bootstrapRel = csFiles.find((rel) => rel.includes("bootstrap"));
if (bootstrapRel) {
  const bootstrapDist = path.join(dist, bootstrapRel);
  const bootstrapSrc = fs.readFileSync(path.join(root, "src/content/bootstrap.js"), "utf8");
  fs.writeFileSync(
    bootstrapDist,
    bootstrapSrc.replace("__HUOKE_CONTENT_CHUNK__", chunkRel),
  );
}

const warEntry = manifest.web_accessible_resources?.[0];
if (warEntry) {
  const required = new Set([
    "src/injected/network-hook.js",
    chunkRel,
    `${chunkRel}.map`,
    ...fs
      .readdirSync(path.join(dist, "assets"))
      .filter((name) => /^(constants|protocol|logger|runtime)-.*\.js$/.test(name))
      .map((name) => `assets/${name}`),
  ]);
  const existing = new Set(warEntry.resources ?? []);
  for (const item of required) {
    if (!existing.has(item) && fs.existsSync(path.join(dist, item))) {
      existing.add(item);
    }
  }
  warEntry.resources = [...existing];
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
}

console.log("[verify-dist] OK");
console.log(`Load this folder in chrome://extensions → ${dist}`);
console.log(`Service worker: ${sw}`);
console.log(`content chunk: ${chunkRel}`);
