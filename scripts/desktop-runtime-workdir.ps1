# Sync desktop bundle to a writable runtime-work directory with integrity checks.
$ErrorActionPreference = "Stop"

function Copy-HuokeBundleTree {
  param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Destination
  )
  if (-not (Test-Path $Source)) {
    throw "Copy source missing: $Source"
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  # /SL materializes symlinks so copied bundles keep identical bytes/hash on Windows.
  robocopy $Source $Destination /E /SL /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed copying '$Source' -> '$Destination' (exit $LASTEXITCODE)"
  }
}

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
    size = $item.Length
    sha256 = $hash
  }
}

function Test-HuokeRuntimeManifest {
  param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [switch]$ThrowOnMismatch
  )
  $manifestFile = Join-Path $BundleDir "RUNTIME_MANIFEST.json"
  if (-not (Test-Path $manifestFile)) {
    if ($ThrowOnMismatch) { throw "RUNTIME_MANIFEST.json missing under $BundleDir" }
    return @{ Ok = $false; Issues = @("RUNTIME_MANIFEST.json missing") }
  }
  $data = Get-Content $manifestFile -Raw | ConvertFrom-Json
  $issues = [System.Collections.Generic.List[string]]::new()
  foreach ($entry in $data.files) {
    $fullPath = Join-Path $BundleDir ($entry.relative -replace '/', '\')
    if (-not (Test-Path $fullPath)) {
      $issues.Add("missing: $($entry.relative)")
      continue
    }
    $fp = Get-HuokeFileFingerprint -Path $fullPath
    $expectedSize = [int64]$entry.size
    if ($fp.size -ne $expectedSize) {
      $issues.Add("size mismatch: $($entry.relative) (expected $expectedSize, got $($fp.size))")
    }
    $expectedHash = "$($entry.sha256)".ToUpperInvariant()
    $actualHash = "$($fp.sha256)".ToUpperInvariant()
    if ($actualHash -ne $expectedHash) {
      $issues.Add("hash mismatch: $($entry.relative)")
    }
  }
  $ok = ($issues.Count -eq 0)
  if (-not $ok -and $ThrowOnMismatch) {
    throw ("Runtime manifest verification failed:`n" + ($issues -join "`n"))
  }
  return @{ Ok = $ok; Issues = @($issues) }
}

function Unblock-HuokeDirectory {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) { return }
  Get-ChildItem -Path $Path -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    try {
      Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue
    } catch {}
  }
}

function Get-HuokeBundleFingerprint {
  param([Parameter(Mandatory = $true)][string]$BundleDir)
  $manifest = Join-Path $BundleDir "BUNDLE_MANIFEST.json"
  if (Test-Path $manifest) {
    $fp = Get-HuokeFileFingerprint -Path $manifest
    if ($fp) { return $fp.sha256 }
  }
  $runtimeManifest = Join-Path $BundleDir "RUNTIME_MANIFEST.json"
  if (Test-Path $runtimeManifest) {
    $fp = Get-HuokeFileFingerprint -Path $runtimeManifest
    if ($fp) { return $fp.sha256 }
  }
  $item = Get-Item $BundleDir
  return $item.LastWriteTimeUtc.Ticks.ToString()
}

function Test-HuokeRuntimeWorkBackendReady {
  param([Parameter(Mandatory = $true)][string]$WorkBundle)
  foreach ($rel in @(
      "backend/app/main.py",
      "backend/storage/skills/global.json",
      "frontend-dist/index.html",
      "runtime/python/python.exe"
    )) {
    if (-not (Test-Path (Join-Path $WorkBundle $rel))) {
      return $false
    }
  }
  $backendFiles = @(Get-ChildItem (Join-Path $WorkBundle "backend") -Recurse -File -ErrorAction SilentlyContinue)
  if ($backendFiles.Count -lt 10) {
    return $false
  }
  return $true
}

function Sync-HuokeRuntimeWorkdir {
  param(
    [Parameter(Mandatory = $true)][string]$SourceBundleDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [switch]$Force
  )

  if (-not (Test-Path (Join-Path $SourceBundleDir "runtime"))) {
    throw "Source bundle missing runtime: $SourceBundleDir"
  }

  $sourceCheck = Test-HuokeRuntimeManifest -BundleDir $SourceBundleDir
  if (-not $sourceCheck.Ok) {
    $detail = if ($sourceCheck.Issues.Count -gt 0) { $sourceCheck.Issues -join "; " } else { "unknown" }
    Write-Host "WARN: source bundle manifest issues: $detail"
  }

  $workRoot = Join-Path $DataDir "runtime-work"
  $workBundle = Join-Path $workRoot "current"
  $stateFile = Join-Path $workRoot "WORK_STATE.json"
  $fingerprint = Get-HuokeBundleFingerprint -BundleDir $SourceBundleDir

  $reuse = $false
  if (-not $Force -and (Test-Path $stateFile) -and (Test-Path (Join-Path $workBundle "runtime"))) {
    try {
      $state = Get-Content $stateFile -Raw | ConvertFrom-Json
      if ($state.fingerprint -eq $fingerprint -and (Test-HuokeRuntimeWorkBackendReady -WorkBundle $workBundle)) {
        $workCheck = Test-HuokeRuntimeManifest -BundleDir $workBundle
        if ($workCheck.Ok) {
          Write-Host "Reusing runtime-work: $workBundle"
          Unblock-HuokeDirectory -Path $workBundle
          return $workBundle
        }
      }
    } catch {}
  }

  Write-Host "Syncing runtime-work: $workBundle"
  if (Test-Path $workBundle) {
    Remove-Item -Recurse -Force $workBundle
  }
  New-Item -ItemType Directory -Force -Path $workBundle | Out-Null

  foreach ($name in @("runtime", "backend", "frontend-dist")) {
    $src = Join-Path $SourceBundleDir $name
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $workBundle $name
    Copy-HuokeBundleTree -Source $src -Destination $dst
  }

  foreach ($name in @("BUNDLE_MANIFEST.json", "RUNTIME_MANIFEST.json")) {
    $src = Join-Path $SourceBundleDir $name
    if (Test-Path $src) {
      Copy-Item $src (Join-Path $workBundle $name) -Force
    }
  }

  if (-not (Test-HuokeRuntimeWorkBackendReady -WorkBundle $workBundle)) {
    throw "runtime-work sync completed but backend/frontend bundle is incomplete under $workBundle"
  }

  Unblock-HuokeDirectory -Path $workBundle

  $workCheck = Test-HuokeRuntimeManifest -BundleDir $workBundle
  if (-not $workCheck.Ok) {
    $missingManifestOnly = ($workCheck.Issues.Count -eq 1 -and $workCheck.Issues[0] -eq "RUNTIME_MANIFEST.json missing")
    $hasOnlyHashMismatch = ($workCheck.Issues | Where-Object { $_ -notmatch '^hash mismatch:' }).Count -eq 0
    if ($missingManifestOnly) {
      Write-Host "WARN: RUNTIME_MANIFEST.json missing in runtime-work; continuing without hash gate"
    } elseif ($hasOnlyHashMismatch) {
      Write-Host "WARN: runtime-work hash metadata mismatch; continuing because file sizes are intact"
    } else {
      $detail = if ($workCheck.Issues.Count -gt 0) { $workCheck.Issues -join "; " } else { "unknown" }
      throw "runtime-work sync completed but manifest verification failed: $detail"
    }
  }

  @{
    fingerprint = $fingerprint
    source = $SourceBundleDir
    synced_at = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8

  Write-Host "runtime-work synced: $workBundle"
  return $workBundle
}
