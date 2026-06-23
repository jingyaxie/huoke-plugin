#!/usr/bin/env node
import {
  getReleaseDir,
  getVersions,
  publishExtensionZip,
  publishLocalServiceMac,
  publishLocalServiceWindows,
  publishMacDmg,
  publishWindowsSetup,
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
  --extension <path>              发布 Chrome 插件 zip
  --local-service-macos <path>    发布 macOS local-service 二进制
  --local-service-windows <path>  发布 Windows local-service 二进制
  --macos-dmg <path>              发布 macOS DMG 安装包
  --windows-setup <path>          发布 Windows NSIS 安装包
`);
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const hasAction = ["extension", "local-service-macos", "local-service-windows", "macos-dmg", "windows-setup"].some(
    (key) => options[key],
  );
  if (!hasAction) {
    usage();
    process.exit(1);
  }

  const versions = getVersions();
  const published = [];

  if (options.extension) published.push(publishExtensionZip(options.extension, versions));
  if (options["local-service-macos"]) published.push(publishLocalServiceMac(options["local-service-macos"], versions));
  if (options["local-service-windows"]) {
    published.push(publishLocalServiceWindows(options["local-service-windows"], versions));
  }
  if (options["macos-dmg"]) published.push(publishMacDmg(options["macos-dmg"], versions));
  if (options["windows-setup"]) published.push(publishWindowsSetup(options["windows-setup"], versions));

  console.log("[release] 版本:", versions);
  for (const filePath of published) {
    console.log(`[release] 已发布: ${filePath}`);
  }
  console.log(`[release] 下载入口: ${getReleaseDir()}/index.html`);
}

main();
