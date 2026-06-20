# Build Huoke Windows desktop installer (Tauri NSIS + bundled Python backend)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot/_python_win.ps1"

$Root = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $Root "desktop"

function Assert-Command {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [string]$Hint = ""
  )
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    $suffix = if ($Hint) { " $Hint" } else { "" }
    throw "$Name not found in PATH.$suffix"
  }
}

function Find-ChromePath {
  $paths = @(
    (Join-Path ${env:ProgramFiles} "Google/Chrome/Application/chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google/Chrome/Application/chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google/Chrome/Application/chrome.exe")
  )
  foreach ($p in $paths) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

Write-Host "==> Huoke Windows build preflight"
Assert-Command node
Assert-Command npm
Assert-Command rustc "Install from https://rustup.rs/"

$nodeVersion = (& node --version | Out-String).Trim()
$npmVersion = (& npm --version | Out-String).Trim()
$rustVersion = (& rustc --version | Out-String).Trim()
Write-Host "Node: $nodeVersion"
Write-Host "npm: $npmVersion"
Write-Host "Rust: $rustVersion"

$Chrome = Find-ChromePath
if (-not $Chrome) {
  Write-Warning "Google Chrome not found. Build can continue, but browser automation requires Chrome on target machines."
} else {
  Write-Host "Chrome: $Chrome"
}

$Python = Find-HuokePython
if ($Python) {
  $PythonExe = Set-HuokePythonEnv $Python
  Write-Host "Python: $PythonExe"
  & $PythonExe --version
  if ($LASTEXITCODE -ne 0) { throw "Python executable is not runnable: $PythonExe" }
} else {
  Write-Host "System Python not required for packaging; portable runtime will be downloaded into the bundle."
}

Push-Location $DesktopDir
try {
  if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") {
      npm ci
    } else {
      npm install
    }
    if ($LASTEXITCODE -ne 0) { throw "npm dependency install failed" }
  }

  Write-Host ""
  Write-Host "==> Building Windows NSIS installer"
  Write-Host "First build may take 10-20 minutes (deps + Rust compile + Python packages)..."
  Write-Host ""

  # NSIS only — MSI (WiX light.exe) needs VBScript, which is often missing on CI runners.
  npm run build -- --bundles nsis
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }
} finally {
  Pop-Location
}

$BundleDir = Join-Path $DesktopDir "src-tauri/target/release/bundle/nsis"
Write-Host ""
Write-Host "Build finished. Output directory:"
Write-Host "  $BundleDir"
if (-not (Test-Path $BundleDir)) {
  throw "NSIS output directory not found: $BundleDir"
}

$installers = Get-ChildItem $BundleDir -Filter "*.exe" -ErrorAction SilentlyContinue
if (-not $installers -or $installers.Count -eq 0) {
  throw "No NSIS installer exe found in $BundleDir"
}
$installers | ForEach-Object {
  Write-Host "  Installer: $($_.FullName)"
}

Write-Host ""
Write-Host "==> Verifying bundled runtime in desktop/bundle"
$preparedBundle = Join-Path $DesktopDir "bundle"
if (-not (Test-Path $preparedBundle)) {
  throw "Prepared bundle missing: $preparedBundle (prepare_desktop_bundle.ps1 should run before Tauri build)"
}
& (Join-Path $PSScriptRoot "verify_windows_bundle.ps1") -BundleDir $preparedBundle
if ($LASTEXITCODE -ne 0) { throw "verify_windows_bundle.ps1 failed" }
