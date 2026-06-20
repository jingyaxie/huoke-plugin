# Verify Windows desktop bundle / installer layout before shipping to customers.
param(
  [string]$BundleDir = "",
  [string]$InstallRoot = "",
  [switch]$RequireChrome
)

$ErrorActionPreference = "Stop"

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

function Assert-PathExists {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if (-not (Test-Path $Path)) {
    throw "Missing $Label`: $Path"
  }
}

function Resolve-BundleDir {
  if ($BundleDir) {
    return (Resolve-Path $BundleDir).Path
  }
  if ($InstallRoot) {
    $candidate = Join-Path $InstallRoot "desktop/bundle"
    if (Test-Path $candidate) {
      return (Resolve-Path $candidate).Path
    }
  }
  $repoBundle = Join-Path $PSScriptRoot "..\desktop\bundle"
  if (Test-Path $repoBundle) {
    return (Resolve-Path $repoBundle).Path
  }
  throw "Bundle directory not found. Pass -BundleDir or -InstallRoot."
}

$resolvedBundle = Resolve-BundleDir
Write-Host "Verifying Windows bundle: $resolvedBundle"

foreach ($rel in @(
    "backend",
    "frontend-dist",
    "runtime/python",
    "runtime/repair-wheels",
    "runtime/msvc",
    "BUNDLE_MANIFEST.json",
    "RUNTIME_MANIFEST.json"
  )) {
  Assert-PathExists -Path (Join-Path $resolvedBundle $rel) -Label $rel
}

foreach ($rel in @(
    "backend/storage/skills/global.json",
    "backend/storage/rules/global.json"
  )) {
  Assert-PathExists -Path (Join-Path $resolvedBundle $rel) -Label $rel
}

foreach ($rel in @("backend/scripts", "backend/tests")) {
  $devPath = Join-Path $resolvedBundle $rel
  if (Test-Path $devPath) {
    throw "Dev-only path must not ship in desktop bundle: $devPath"
  }
}

foreach ($dll in @("vcruntime140.dll", "vcruntime140_1.dll")) {
  Assert-PathExists -Path (Join-Path $resolvedBundle "runtime/msvc/$dll") -Label $dll
}

. (Join-Path $PSScriptRoot "desktop-bundle-cache.ps1")
. (Join-Path $PSScriptRoot "desktop-runtime-workdir.ps1")

$pythonExe = Find-PortablePythonExe -BundleDir $resolvedBundle
if (-not $pythonExe) {
  throw "Portable python.exe missing under $resolvedBundle/runtime/python"
}

$backendDir = Join-Path $resolvedBundle "backend"
$probe = Invoke-PortablePythonProbe -PythonExe $pythonExe -BackendDir $backendDir -Code @"
import greenlet
from greenlet._greenlet import _C_API
import cryptography
import pydantic_core
from playwright.async_api import async_playwright
from app.main import app
print('bundle import ok')
"@
if (-not $probe.Ok) {
  throw "Portable Python import probe failed: $($probe.Output)"
}

$manifestCheck = Test-HuokeRuntimeManifest -BundleDir $resolvedBundle -ThrowOnMismatch
if (-not $manifestCheck.Ok) {
  throw ("RUNTIME_MANIFEST verification failed: " + ($manifestCheck.Issues -join "; "))
}

$repairCount = (Get-ChildItem (Join-Path $resolvedBundle "runtime/repair-wheels") -File -ErrorAction SilentlyContinue).Count
if ($repairCount -lt 1) {
  throw "repair-wheels directory is empty"
}

$pdbCount = (Get-ChildItem (Join-Path $resolvedBundle "runtime/python") -Recurse -Include "*.pdb", "*.ilk" -File -ErrorAction SilentlyContinue).Count
if ($pdbCount -gt 0) {
  throw "portable Python bundle still contains $pdbCount debug artifact(s); rebuild with install_portable_python_win.ps1"
}

$chrome = Find-ChromePath
if ($chrome) {
  Write-Host "Chrome detected: $chrome"
  $verifyScript = Join-Path $PSScriptRoot "verify_playwright_bundle.py"
  & $pythonExe $verifyScript 2>&1 | Out-Host
  if ($LASTEXITCODE -ne 0) {
    throw "system Chrome launch smoke test failed"
  }
} elseif ($RequireChrome) {
  throw "Google Chrome is required for verification (-RequireChrome)"
} else {
  Write-Warning "Google Chrome not installed on this machine. Bundle is complete, but customers must install Chrome to run browser automation."
}

Write-Host "Windows bundle verification passed ($repairCount repair wheels, python=$pythonExe)"
