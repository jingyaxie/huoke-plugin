import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../..");
const RELEASE_DIR = path.join(ROOT, "dist", "releases");
const MANIFEST_PATH = path.join(RELEASE_DIR, "RELEASES.json");
const INDEX_PATH = path.join(RELEASE_DIR, "index.html");

function readJson(filePath, fallback = null) {
  if (!fs.existsSync(filePath)) return fallback;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

export function getVersions(root = ROOT) {
  const appVersion = readJson(path.join(root, "package.json"))?.version ?? "0.0.0";
  const extVersion = readJson(path.join(root, "extension/manifest.json"))?.version ?? "0.0.0";
  const cargoToml = fs.readFileSync(path.join(root, "local-service/Cargo.toml"), "utf8");
  const lsMatch = cargoToml.match(/^version\s*=\s*"([^"]+)"/m);
  const localServiceVersion = lsMatch?.[1] ?? "0.0.0";
  const desktopVersion = readJson(path.join(root, "desktop/src-tauri/tauri.conf.json"))?.version ?? appVersion;
  return {
    app_version: appVersion,
    desktop_version: desktopVersion,
    extension_version: extVersion,
    local_service_version: localServiceVersion,
  };
}

function ensureReleaseDir() {
  fs.mkdirSync(RELEASE_DIR, { recursive: true });
}

function fileSize(filePath) {
  return fs.statSync(filePath).size;
}

function copyArtifact(srcPath, destName) {
  ensureReleaseDir();
  const destPath = path.join(RELEASE_DIR, destName);
  fs.copyFileSync(srcPath, destPath);
  return {
    filename: destName,
    path: destPath,
    size_bytes: fileSize(destPath),
  };
}

function loadManifest(versions) {
  const existing = readJson(MANIFEST_PATH);
  return {
    kind: "huoke-releases",
    generated_at: new Date().toISOString(),
    ...versions,
    artifacts: Array.isArray(existing?.artifacts) ? [...existing.artifacts] : [],
  };
}

const STANDALONE_LOCAL_SERVICE_IDS = new Set(["local-service-macos", "local-service-windows"]);
const RELEASE_META_FILES = new Set(["index.html", "RELEASES.json"]);

function upsertArtifact(manifest, artifact) {
  const index = manifest.artifacts.findIndex((item) => item.id === artifact.id);
  if (index >= 0) manifest.artifacts[index] = artifact;
  else manifest.artifacts.push(artifact);
  manifest.artifacts.sort((a, b) => a.id.localeCompare(b.id));
}

/** 对外发布只保留「桌面客户端 + 插件」；local-service 已内置于安装包，不再单独列出。 */
function pruneStandaloneLocalServiceArtifacts(manifest) {
  manifest.artifacts = manifest.artifacts.filter((item) => !STANDALONE_LOCAL_SERVICE_IDS.has(item.id));
}

/** 删除 dist/releases 中不在清单内的旧文件（如 standalone local-service、解压目录等）。 */
function pruneReleaseDir(manifest) {
  if (!fs.existsSync(RELEASE_DIR)) return;
  const allowed = new Set([
    ...manifest.artifacts.map((item) => item.filename),
    ...RELEASE_META_FILES,
  ]);
  for (const name of fs.readdirSync(RELEASE_DIR)) {
    if (allowed.has(name)) continue;
    const fullPath = path.join(RELEASE_DIR, name);
    fs.rmSync(fullPath, { recursive: true, force: true });
    console.log(`[release] 已清理: ${name}`);
  }
}

function writeManifest(manifest) {
  pruneStandaloneLocalServiceArtifacts(manifest);
  ensureReleaseDir();
  fs.writeFileSync(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`);
  writeIndexHtml(manifest);
  pruneReleaseDir(manifest);
}

function freshManifest(versions) {
  return {
    kind: "huoke-releases",
    generated_at: new Date().toISOString(),
    ...versions,
    artifacts: [],
  };
}

function extensionArtifact(copied, versions) {
  return {
    id: "extension",
    label: "Chrome 插件（手动加载/更新）",
    filename: copied.filename,
    platform: "chrome",
    version: versions.extension_version,
    size_bytes: copied.size_bytes,
  };
}

function windowsDesktopArtifact(copied, versions) {
  return {
    id: "desktop-windows-setup",
    label: "盈小蚁 Windows 轻量安装包",
    filename: copied.filename,
    platform: "windows",
    version: versions.desktop_version,
    size_bytes: copied.size_bytes,
  };
}

function windowsOfflineDesktopArtifact(copied, versions) {
  return {
    id: "desktop-windows-offline-setup",
    label: "盈小蚁 Windows 离线完整安装包",
    filename: copied.filename,
    platform: "windows",
    version: versions.desktop_version,
    size_bytes: copied.size_bytes,
  };
}

function macosDesktopArtifact(copied, versions) {
  return {
    id: "desktop-macos-dmg",
    label: "盈小蚁 macOS 安装包",
    filename: copied.filename,
    platform: "macos",
    version: versions.desktop_version,
    size_bytes: copied.size_bytes,
  };
}

function formatSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function writeIndexHtml(manifest) {
  const rows = manifest.artifacts
    .map((item) => {
      const meta = [item.platform, item.version ? `v${item.version}` : null, formatSize(item.size_bytes)]
        .filter(Boolean)
        .join(" · ");
      return `<li><a href="./${item.filename}" download>${item.label}</a><span>${meta}</span></li>`;
    })
    .join("\n        ");

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Huoke 安装包下载</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 720px; margin: 48px auto; padding: 0 20px; color: #1f2937; }
    h1 { font-size: 24px; margin-bottom: 8px; }
    p { color: #6b7280; line-height: 1.6; }
    ul { list-style: none; padding: 0; margin: 24px 0 0; }
    li { display: flex; justify-content: space-between; gap: 16px; padding: 14px 0; border-bottom: 1px solid #e5e7eb; align-items: baseline; }
    a { color: #2563eb; text-decoration: none; font-weight: 600; }
    a:hover { text-decoration: underline; }
    span { color: #6b7280; font-size: 13px; white-space: nowrap; }
    code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
  </style>
</head>
<body>
  <h1>Huoke 安装包下载</h1>
  <p>应用 <code>v${manifest.app_version}</code> · 插件 <code>v${manifest.extension_version}</code></p>
  <p><strong>1.</strong> 安装桌面客户端（.exe / .dmg）→ 打开「盈小蚁」即可，本地服务已内置。</p>
  <p><strong>2.</strong> 插件 zip 仅在手动更新或 chrome://extensions 重新加载时需要。</p>
  <p>更新时间：${manifest.generated_at}</p>
  <ul>
        ${rows}
  </ul>
</body>
</html>
`;
  fs.writeFileSync(INDEX_PATH, html);
}

function requireFile(filePath, label) {
  if (!filePath || !fs.existsSync(filePath)) {
    throw new Error(`${label} 不存在: ${filePath || "(未指定)"}`);
  }
}

export function publishExtensionZip(srcPath, versions = getVersions()) {
  requireFile(srcPath, "extension zip");
  const destName = `huoke-extension-v${versions.extension_version}.zip`;
  const copied = copyArtifact(srcPath, destName);
  const manifest = loadManifest(versions);
  upsertArtifact(manifest, extensionArtifact(copied, versions));
  writeManifest(manifest);
  return copied.path;
}

/** Windows 桌面完整发布：仅保留 setup.exe + 插件 zip */
export function publishWindowsDesktopRelease(extensionZipPath, setupOptions, versions = getVersions()) {
  const setupPath = typeof setupOptions === "string" ? setupOptions : setupOptions?.setupPath;
  const offlineSetupPath = typeof setupOptions === "object" ? setupOptions?.offlineSetupPath : null;
  requireFile(extensionZipPath, "extension zip");
  if (!setupPath && !offlineSetupPath) {
    throw new Error("至少需要指定一个 Windows 安装包");
  }
  if (setupPath) requireFile(setupPath, "Windows 轻量安装包");
  if (offlineSetupPath) requireFile(offlineSetupPath, "Windows 离线完整安装包");

  const extCopied = copyArtifact(
    extensionZipPath,
    `huoke-extension-v${versions.extension_version}.zip`,
  );
  const setupCopied = setupPath
    ? copyArtifact(
        setupPath,
        `huoke-desktop-v${versions.desktop_version}-windows-setup.exe`,
      )
    : null;
  const offlineSetupCopied = offlineSetupPath
    ? copyArtifact(
        offlineSetupPath,
        `huoke-desktop-v${versions.desktop_version}-windows-offline-setup.exe`,
      )
    : null;

  const manifest = freshManifest(versions);
  manifest.artifacts = [extensionArtifact(extCopied, versions)];
  if (setupCopied) manifest.artifacts.push(windowsDesktopArtifact(setupCopied, versions));
  if (offlineSetupCopied) manifest.artifacts.push(windowsOfflineDesktopArtifact(offlineSetupCopied, versions));
  writeManifest(manifest);
  return [extCopied.path, setupCopied?.path, offlineSetupCopied?.path].filter(Boolean);
}

/** macOS 桌面完整发布：仅保留 dmg + 插件 zip */
export function publishMacosDesktopRelease(extensionZipPath, dmgPath, versions = getVersions()) {
  requireFile(extensionZipPath, "extension zip");
  requireFile(dmgPath, "macOS DMG");

  const extCopied = copyArtifact(
    extensionZipPath,
    `huoke-extension-v${versions.extension_version}.zip`,
  );
  const dmgCopied = copyArtifact(
    dmgPath,
    `huoke-desktop-v${versions.desktop_version}-macos.dmg`,
  );

  const manifest = freshManifest(versions);
  manifest.artifacts = [
    extensionArtifact(extCopied, versions),
    macosDesktopArtifact(dmgCopied, versions),
  ];
  writeManifest(manifest);
  return [extCopied.path, dmgCopied.path];
}

export function publishMacDmg(srcPath, versions = getVersions()) {
  requireFile(srcPath, "macOS DMG");
  const destName = `huoke-desktop-v${versions.desktop_version}-macos.dmg`;
  const copied = copyArtifact(srcPath, destName);
  const manifest = loadManifest(versions);
  upsertArtifact(manifest, macosDesktopArtifact(copied, versions));
  writeManifest(manifest);
  return copied.path;
}

export function publishWindowsSetup(srcPath, versions = getVersions()) {
  requireFile(srcPath, "Windows 安装包");
  const destName = `huoke-desktop-v${versions.desktop_version}-windows-setup.exe`;
  const copied = copyArtifact(srcPath, destName);
  const manifest = loadManifest(versions);
  upsertArtifact(manifest, windowsDesktopArtifact(copied, versions));
  writeManifest(manifest);
  return copied.path;
}

export function getReleaseDir() {
  return RELEASE_DIR;
}
