# Generate RUNTIME_MANIFEST.json with SHA256 fingerprints for critical runtime files.
param(
  [Parameter(Mandatory = $true)][string]$BundleDir
)

$ErrorActionPreference = "Stop"

function Get-HuokeFileFingerprint {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) { return $null }
  $item = Get-Item $Path
  if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
    $hash = (Get-FileHash -Algorithm SHA256 -Path $Path).Hash
  } else {
    $hash = ("size:{0}:ticks:{1}" -f $item.Length, $item.LastWriteTimeUtc.Ticks)
  }
  return @{
    path = $Path
    size = $item.Length
    sha256 = $hash
  }
}

function New-HuokeRuntimeManifest {
  param([Parameter(Mandatory = $true)][string]$BundleDir)

  if (-not (Test-Path $BundleDir)) {
    throw "Bundle directory not found: $BundleDir"
  }

  $entries = [System.Collections.Generic.List[object]]::new()

  function Add-ManifestEntry {
    param([string]$RelativePath)
    $fullPath = Join-Path $BundleDir $RelativePath
    $fp = Get-HuokeFileFingerprint -Path $fullPath
    if ($fp) {
      $entries.Add(@{
          relative = ($RelativePath -replace '\\', '/')
          size = $fp.size
          sha256 = $fp.sha256
        })
    }
  }

  function Add-ManifestGlob {
    param([string]$Pattern)
    $resolved = Join-Path $BundleDir $Pattern
    $parent = Split-Path $resolved -Parent
    $filter = Split-Path $resolved -Leaf
    if (-not (Test-Path $parent)) { return }
    Get-ChildItem -Path $parent -Filter $filter -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
      $rel = $_.FullName.Substring($BundleDir.Length).TrimStart('\', '/')
      $fp = Get-HuokeFileFingerprint -Path $_.FullName
      if ($fp) {
        $entries.Add(@{
            relative = ($rel -replace '\\', '/')
            size = $fp.size
            sha256 = $fp.sha256
          })
      }
    }
  }

  foreach ($rel in @(
      "BUNDLE_MANIFEST.json",
      "backend/app/main.py",
      "backend/storage/skills/global.json",
      "frontend-dist/index.html",
      "runtime/python/python.exe",
      "runtime/python/python312.dll",
      "runtime/python/vcruntime140.dll",
      "runtime/python/vcruntime140_1.dll",
      "runtime/msvc/vcruntime140.dll",
      "runtime/msvc/vcruntime140_1.dll"
    )) {
    Add-ManifestEntry -RelativePath $rel
  }

  Add-ManifestGlob -Pattern "runtime/python/Lib/site-packages/greenlet/_greenlet*.pyd"
  Add-ManifestGlob -Pattern "runtime/python/Lib/site-packages/cryptography/**/*.pyd"
  Add-ManifestGlob -Pattern "runtime/python/Lib/site-packages/pydantic_core/*.pyd"
  Add-ManifestGlob -Pattern "runtime/python/Lib/site-packages/sqlalchemy/cyextension/*.pyd"
  Add-ManifestGlob -Pattern "runtime/python/Lib/site-packages/playwright/driver/node.exe"

  $bundleManifest = Join-Path $BundleDir "BUNDLE_MANIFEST.json"
  $bundleFingerprint = $null
  if (Test-Path $bundleManifest) {
    $bundleFingerprint = (Get-HuokeFileFingerprint -Path $bundleManifest).sha256
  }

  $manifest = @{
    kind = "huoke-runtime-manifest"
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    bundle_fingerprint = $bundleFingerprint
    files = $entries
  }

  $outFile = Join-Path $BundleDir "RUNTIME_MANIFEST.json"
  $manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $outFile -Encoding UTF8
  Write-Host "RUNTIME_MANIFEST.json written ($($entries.Count) files): $outFile"
  return $outFile
}

New-HuokeRuntimeManifest -BundleDir $BundleDir | Out-Null
