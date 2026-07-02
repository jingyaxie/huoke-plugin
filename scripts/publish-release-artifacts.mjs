#!/usr/bin/env node
import {
  getReleaseDir,
  getVersions,
  publishExtensionZip,
  publishMacosDesktopRelease,
  publishWindowsDesktopRelease,
} from "./lib/release-artifacts.mjs";

function parseArgs(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) {
      options[key] = true;
      continue;
    }
    options[key] = value;
    i += 1;
  }
  return options;
}

function usage() {
  console.log(`用法:
  node scripts/publish-release-artifacts.mjs [选项]

选项:
  --windows-release               发布 Windows 完整包（setup.exe + 插件 zip，并清理旧产物）
    --extension-zip <path>
    --setup <path>                 Windows 安装包
  --macos-release                 发布 macOS 完整包（dmg + 插件 zip，并清理旧产物）
    --extension-zip <path>
    --dmg <path>
  --extension <path>              仅更新插件 zip（保留已有桌面安装包）
`);
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const versions = getVersions();
  const published = [];

  if (options["windows-release"]) {
    if (!options["extension-zip"] || !options.setup) {
      usage();
      process.exit(1);
    }
    published.push(
      ...publishWindowsDesktopRelease(options["extension-zip"], {
        setupPath: options.setup,
      }, versions),
    );
  } else if (options["macos-release"]) {
    if (!options["extension-zip"] || !options.dmg) {
      usage();
      process.exit(1);
    }
    published.push(
      ...publishMacosDesktopRelease(options["extension-zip"], options.dmg, versions),
    );
  } else if (options.extension) {
    published.push(publishExtensionZip(options.extension, versions));
  } else {
    usage();
    process.exit(1);
  }

  console.log("[release] 版本:", versions);
  for (const filePath of published) {
    console.log(`[release] 已发布: ${filePath}`);
  }
  console.log(`[release] 下载入口: ${getReleaseDir()}/index.html`);
}

main();
