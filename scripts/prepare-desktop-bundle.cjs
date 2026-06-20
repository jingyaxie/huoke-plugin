#!/usr/bin/env node
/**
 * Tauri beforeBuildCommand entrypoint.
 * macOS/Linux use bash; Windows uses pwsh so CI PATH/pythonLocation are preserved.
 */
const { spawnSync } = require("child_process");
const path = require("path");

const root = path.resolve(__dirname, "..");

function resolveWindowsShell() {
  const candidates = [
    process.env.PWSH,
    "pwsh.exe",
    "powershell.exe",
  ].filter(Boolean);
  for (const shell of candidates) {
    const probe = spawnSync(shell, ["-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"], {
      encoding: "utf8",
    });
    if (probe.status === 0) {
      return shell;
    }
  }
  return "powershell.exe";
}

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
  const shell = resolveWindowsShell();
  const useThin = process.env.HUOKE_DESKTOP_LEGACY !== "1";
  const script = useThin
    ? path.join(root, "scripts", "prepare_desktop_thin_bundle.sh")
    : path.join(root, "scripts", "prepare_desktop_bundle.ps1");
  if (useThin) {
    run("bash", [script]);
  } else {
    run(shell, [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      script,
    ]);
  }
} else {
  const useThin = process.env.HUOKE_DESKTOP_LEGACY !== "1";
  const script = useThin
    ? path.join(root, "scripts", "prepare_desktop_thin_bundle.sh")
    : path.join(root, "scripts", "prepare_desktop_bundle.sh");
  run("bash", [script]);
}
