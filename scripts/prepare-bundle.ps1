# Tauri 桌面打包资源（Windows）
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$ExtensionDir = Join-Path $Root "extension"
$BundleDir = Join-Path $Root "desktop/bundle"
$LocalServiceDir = Join-Path $Root "local-service"

Write-Host "=== Huoke Desktop Bundle (Windows) ==="

Write-Host ">>> 构建 Chrome 插件"
Push-Location $ExtensionDir
try {
  if (-not (Test-Path "node_modules")) { npm install }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "extension build failed" }
} finally {
  Pop-Location
}

Write-Host ">>> 构建 local-service (release)"
Push-Location $LocalServiceDir
try {
  cargo build --release
  if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }
} finally {
  Pop-Location
}

Write-Host ">>> 构建前端"
Push-Location $FrontendDir
try {
  if (-not (Test-Path "node_modules")) {
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
  }
  $env:VITE_LOCAL_SERVICE_URL = "http://127.0.0.1:18766"
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
} finally {
  Pop-Location
}

$IndexHtml = Join-Path $FrontendDir "dist/index.html"
if (-not (Test-Path $IndexHtml)) {
  throw "frontend dist missing: $IndexHtml"
}

Write-Host ">>> 组装 desktop/bundle"
if (Test-Path $BundleDir) {
  Remove-Item $BundleDir -Recurse -Force
}
New-Item -ItemType Directory -Path (Join-Path $BundleDir "runtime") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BundleDir "frontend-dist") -Force | Out-Null

$ServiceExe = Join-Path $LocalServiceDir "target/release/huoke-local-service.exe"
if (-not (Test-Path $ServiceExe)) {
  throw "local-service binary missing: $ServiceExe"
}
Copy-Item $ServiceExe (Join-Path $BundleDir "runtime/huoke-local-service.exe") -Force

Copy-Item (Join-Path $FrontendDir "dist/*") (Join-Path $BundleDir "frontend-dist") -Recurse -Force

New-Item -ItemType Directory -Path (Join-Path $BundleDir "extension") -Force | Out-Null
Copy-Item (Join-Path $ExtensionDir "dist/*") (Join-Path $BundleDir "extension") -Recurse -Force

$ZipPath = Join-Path $BundleDir "huoke-extension.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $ExtensionDir "dist/*") -DestinationPath $ZipPath -Force

$AppVersion = node -p "require('$Root/package.json').version"
$ExtVersion = node -p "require('$ExtensionDir/manifest.json').version"
$LsVersion = (Select-String -Path (Join-Path $LocalServiceDir "Cargo.toml") -Pattern '^version' | Select-Object -First 1).Line -replace '.*"(.*)".*', '$1'

@{
  kind = "huoke-desktop-bundle"
  app_version = $AppVersion
  extension_version = $ExtVersion
  local_service_version = $LsVersion
  runtime = "runtime/huoke-local-service.exe"
  frontend = "frontend-dist"
  extension = "extension"
  extension_zip = "huoke-extension.zip"
  static_port = 18765
  local_service_port = 18766
  notes = "Vue static + Rust local-service + Chrome extension (auto-loaded on first run)."
} | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $BundleDir "BUNDLE_MANIFEST.json") -Encoding UTF8

Write-Host "bundle 就绪: $BundleDir"
Write-Host "  - runtime/huoke-local-service.exe"
Write-Host "  - frontend-dist/"
Write-Host "  - extension/"
Write-Host "  - huoke-extension.zip"
Write-Host "（对外发布请运行 npm run build:win 或 npm run build:mac）"
