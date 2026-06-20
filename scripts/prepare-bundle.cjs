#!/usr/bin/env node
/** Tauri beforeBuildCommand — 组装 desktop/bundle */
const { spawnSync } = require("child_process");
const path = require("path");

const root = path.resolve(__dirname, "..");

function run(cmd, args) {
  const result = spawnSync(cmd, args, {
    stdio: "inherit",
    cwd: root,
    shell: false,
    env: process.env,
  });
  process.exit(result.status ?? 1);
}

if (process.platform === "win32") {
  const shell =
    ["pwsh.exe", "powershell.exe"].find((name) => {
      const probe = spawnSync(name, ["-NoLogo", "-Command", "$PSVersionTable.PSVersion.Major"], {
        encoding: "utf8",
      });
      return probe.status === 0;
    }) ?? "powershell.exe";
  run(shell, [
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    path.join(root, "scripts", "prepare-bundle.ps1"),
  ]);
} else {
  run("bash", [path.join(root, "scripts", "prepare-bundle.sh")]);
}
