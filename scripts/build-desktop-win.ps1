# Windows 桌面应用打包（Tauri NSIS）
$ErrorActionPreference = "Stop"

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

Write-Host "==> Huoke Windows desktop build"
Assert-Command node
Assert-Command npm
Assert-Command rustc "Install from https://rustup.rs/"

Write-Host "Node: $((node --version).Trim())"
Write-Host "npm: $((npm --version).Trim())"
Write-Host "Rust: $((rustc --version).Trim())"

$Chrome = Find-ChromePath
if (-not $Chrome) {
  Write-Warning "Google Chrome not found. Users must install Chrome and load huoke-extension.zip."
} else {
  Write-Host "Chrome: $Chrome"
}

Push-Location $DesktopDir
try {
  if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
  }

  Write-Host ""
  Write-Host "==> Building NSIS installer (prepare-bundle runs via Tauri beforeBuildCommand)"
  npm run build -- --bundles nsis
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
  Pop-Location
}

$BundleDir = Join-Path $DesktopDir "bundle"
& (Join-Path $PSScriptRoot "verify-bundle.ps1") -BundleDir $BundleDir
if ($LASTEXITCODE -ne 0) { throw "verify-bundle.ps1 failed" }

$NsisDir = Join-Path $DesktopDir "src-tauri/target/release/bundle/nsis"
Write-Host ""
Write-Host "Build finished: $NsisDir"
$installers = Get-ChildItem $NsisDir -Filter "*.exe" -ErrorAction SilentlyContinue
if (-not $installers) {
  throw "No NSIS installer found in $NsisDir"
}

Write-Host ""
Write-Host "==> 发布版本化安装包到 dist/releases"
$PublishScript = Join-Path $Root "scripts/publish-release-artifacts.mjs"
foreach ($installer in $installers) {
  node $PublishScript --windows-setup $installer.FullName
  if ($LASTEXITCODE -ne 0) { throw "publish-release-artifacts failed" }
}

$ReleaseDir = Join-Path $Root "dist/releases"
Write-Host ""
Write-Host "发布目录: $ReleaseDir"
Get-ChildItem $ReleaseDir -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.Name)" }
$installers | ForEach-Object { Write-Host "  Tauri: $($_.FullName)" }
