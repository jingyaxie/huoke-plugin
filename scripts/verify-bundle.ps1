# 验证 desktop/bundle 瘦壳产物（Windows）
param(
  [string]$BundleDir = (Join-Path (Split-Path -Parent $PSScriptRoot) "desktop/bundle")
)

$ErrorActionPreference = "Stop"
$resolved = Resolve-Path $BundleDir

Write-Host "==> verify bundle: $resolved"

$required = @(
  "BUNDLE_MANIFEST.json",
  "frontend-dist/index.html",
  "extension/manifest.json",
  "huoke-extension.zip"
)

foreach ($rel in $required) {
  $path = Join-Path $resolved $rel
  if (-not (Test-Path $path)) {
    throw "missing bundle file: $rel"
  }
  Write-Host "  ok $rel"
}

$runtimeExe = Join-Path $resolved "runtime/huoke-local-service.exe"
$runtimeBin = Join-Path $resolved "runtime/huoke-local-service"
if (-not (Test-Path $runtimeExe) -and -not (Test-Path $runtimeBin)) {
  throw "missing local-service binary under runtime/"
}
Write-Host "  ok local-service runtime"

Write-Host "bundle verification passed"
