# Windows 桌面应用打包（Tauri NSIS）
param(
  [ValidateSet("both", "light", "offline")]
  [string]$Mode = "both"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$DesktopDir = Join-Path $Root "desktop"
$StagingDir = Join-Path $Root "dist/windows-build"
$BuiltInstallers = @{}

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

function Get-LatestInstaller {
  param(
    [Parameter(Mandatory = $true)][string]$NsisDir,
    [Parameter(Mandatory = $true)][datetime]$Since
  )
  $installers = Get-ChildItem $NsisDir -Filter "*.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -ge $Since } |
    Sort-Object LastWriteTime -Descending
  if (-not $installers) {
    throw "No NSIS installer found in $NsisDir"
  }
  return $installers[0]
}

function Invoke-NsisBuild {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string]$OutputName,
    [string[]]$ExtraArgs = @()
  )
  Write-Host ""
  Write-Host "==> Building NSIS installer: $Name"
  $startedAt = Get-Date
  npm run build -- --bundles nsis @ExtraArgs
  if ($LASTEXITCODE -ne 0) { throw "npm run build failed: $Name" }
  $installer = Get-LatestInstaller -NsisDir (Join-Path $DesktopDir "src-tauri/target/release/bundle/nsis") -Since $startedAt
  New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null
  $stagedPath = Join-Path $StagingDir $OutputName
  Copy-Item $installer.FullName $stagedPath -Force
  return Get-Item $stagedPath
}

Write-Host "==> Huoke Windows desktop build"
Write-Host "Mode: $Mode"
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

  if ($Mode -eq "both" -or $Mode -eq "light") {
    $BuiltInstallers["light"] = Invoke-NsisBuild -Name "light (downloads WebView2 only when needed)" -OutputName "huoke-windows-light-setup.exe"
  }
  if ($Mode -eq "both" -or $Mode -eq "offline") {
    $BuiltInstallers["offline"] = Invoke-NsisBuild -Name "offline (embeds WebView2 installer)" -OutputName "huoke-windows-offline-setup.exe" -ExtraArgs @("--config", "src-tauri/tauri.windows.offline.conf.json")
  }
} finally {
  Pop-Location
}

$BundleDir = Join-Path $DesktopDir "bundle"
& (Join-Path $PSScriptRoot "verify-bundle.ps1") -BundleDir $BundleDir
if ($LASTEXITCODE -ne 0) { throw "verify-bundle.ps1 failed" }

Write-Host ""
Write-Host "==> 发布到 dist/releases（setup.exe + 插件 zip）"
$PublishScript = Join-Path $Root "scripts/publish-release-artifacts.mjs"
$ExtensionZip = Join-Path $BundleDir "huoke-extension.zip"
$publishArgs = @("--windows-release", "--extension-zip", $ExtensionZip)
if ($BuiltInstallers.ContainsKey("light")) {
  $publishArgs += @("--setup", $BuiltInstallers["light"].FullName)
}
if ($BuiltInstallers.ContainsKey("offline")) {
  $publishArgs += @("--offline-setup", $BuiltInstallers["offline"].FullName)
}
node $PublishScript @publishArgs
if ($LASTEXITCODE -ne 0) { throw "publish-release-artifacts failed" }

$ReleaseDir = Join-Path $Root "dist/releases"
Write-Host ""
Write-Host "发布目录: $ReleaseDir"
Get-ChildItem $ReleaseDir -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.Name)" }
$BuiltInstallers.GetEnumerator() | ForEach-Object { Write-Host "  Tauri [$($_.Key)]: $($_.Value.FullName)" }
