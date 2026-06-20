# Sync desktop bundle to an ASCII-only cache when Unicode install paths break portable Python.
$ErrorActionPreference = "Stop"

function Test-HuokePathHasNonAscii {
  param([string]$Path)
  if (-not $Path) { return $false }
  foreach ($ch in $Path.ToCharArray()) {
    if ([int][char]$ch -gt 127) { return $true }
  }
  return $false
}

function Find-PortablePythonExe {
  param([Parameter(Mandatory = $true)][string]$BundleDir)
  foreach ($candidate in @(
      (Join-Path $BundleDir "runtime/python/python.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python3.exe"),
      (Join-Path $BundleDir "runtime/python/bin/python3.12.exe")
    )) {
    if (Test-Path $candidate) { return $candidate }
  }
  return $null
}

function Get-PortablePythonRoot {
  param([Parameter(Mandatory = $true)][string]$PythonExe)
  $pythonRoot = Split-Path $PythonExe -Parent
  if ((Split-Path $pythonRoot -Leaf) -eq "bin") {
    $pythonRoot = Split-Path $pythonRoot -Parent
  }
  return $pythonRoot
}

function Set-PortablePythonEnv {
  param([Parameter(Mandatory = $true)][string]$PythonExe)
  $pythonRoot = Get-PortablePythonRoot -PythonExe $PythonExe
  # Do not set PYTHONHOME: with python-build-standalone it can break Windows
  # DLL lookup for native wheels such as greenlet/playwright.
  Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
  $env:PYTHONUTF8 = "1"
  $runtimeRoot = Split-Path $pythonRoot -Parent
  $dllDirs = @(
    $pythonRoot,
    (Join-Path $pythonRoot "DLLs"),
    (Join-Path $runtimeRoot "msvc")
  )
  $prefix = (($dllDirs | Where-Object { Test-Path $_ }) -join ";")
  if ($prefix) {
    $env:PATH = "$prefix;$env:PATH"
  }
}

function Invoke-PortablePythonProbe {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$BackendDir,
    [string]$Code = "import uvicorn; print('portable python probe ok')"
  )
  if (-not (Test-Path $PythonExe)) {
    return @{ Ok = $false; Output = "python exe missing: $PythonExe" }
  }
  if (-not (Test-Path $BackendDir)) {
    return @{ Ok = $false; Output = "backend dir missing: $BackendDir" }
  }

  $prevPythonPath = $env:PYTHONPATH
  $prevPath = $env:PATH
  $prevPythonHome = $env:PYTHONHOME
  $prevPythonUtf8 = $env:PYTHONUTF8
  $prevEap = $ErrorActionPreference
  $env:PYTHONPATH = $BackendDir
  Set-PortablePythonEnv -PythonExe $PythonExe
  $ErrorActionPreference = 'Continue'
  try {
    # Do NOT pipe to Out-Null: PowerShell 5.1 loses native $LASTEXITCODE after a pipeline.
    $output = & $PythonExe -c $Code 2>&1
    $exitCode = $LASTEXITCODE
    $text = if ($output) { ($output | ForEach-Object { "$_" }) -join "`n" } else { "" }
    return @{ Ok = ($exitCode -eq 0); Output = $text; ExitCode = $exitCode }
  } finally {
    $ErrorActionPreference = $prevEap
    if ($null -eq $prevPythonPath) {
      Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
      $env:PYTHONPATH = $prevPythonPath
    }
    if ($null -eq $prevPythonHome) {
      Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    } else {
      $env:PYTHONHOME = $prevPythonHome
    }
    if ($null -eq $prevPythonUtf8) {
      Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue
    } else {
      $env:PYTHONUTF8 = $prevPythonUtf8
    }
    if ($null -eq $prevPath) {
      Remove-Item Env:PATH -ErrorAction SilentlyContinue
    } else {
      $env:PATH = $prevPath
    }
  }
}

function Test-PortablePythonRunnable {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$BackendDir
  )
  $result = Invoke-PortablePythonProbe -PythonExe $PythonExe -BackendDir $BackendDir
  return $result.Ok
}

function Get-HuokeBundleFingerprint {
  param([Parameter(Mandatory = $true)][string]$BundleDir)
  $manifest = Join-Path $BundleDir "BUNDLE_MANIFEST.json"
  if (Test-Path $manifest) {
    if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
      return (Get-FileHash -Algorithm SHA256 -Path $manifest).Hash
    }
    $item = Get-Item $manifest
    return ("{0}:{1}" -f $item.Length, $item.LastWriteTimeUtc.Ticks)
  }
  $item = Get-Item $BundleDir
  return $item.LastWriteTimeUtc.Ticks.ToString()
}

function Clear-HuokeBundleCache {
  param([Parameter(Mandatory = $true)][string]$DataDir)
  $cacheRoot = Join-Path $DataDir "bundle-cache"
  if (Test-Path $cacheRoot) {
    Remove-Item -Recurse -Force $cacheRoot -ErrorAction SilentlyContinue
  }
}

function Sync-HuokeBundleCache {
  param(
    [Parameter(Mandatory = $true)][string]$SourceBundleDir,
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$Root = ""
  )

  if (-not (Test-Path (Join-Path $SourceBundleDir "runtime"))) {
    throw "Source bundle missing runtime: $SourceBundleDir"
  }

  $pathNeedsCache = (Test-HuokePathHasNonAscii $Root) -or (Test-HuokePathHasNonAscii $SourceBundleDir)
  if (-not $pathNeedsCache) {
    return $SourceBundleDir
  }

  $backendDir = Join-Path $SourceBundleDir "backend"
  $pythonExe = Find-PortablePythonExe -BundleDir $SourceBundleDir
  if (-not $pythonExe) {
    throw "Unicode install path but portable Python not found under $SourceBundleDir"
  }

  $cacheRoot = Join-Path $DataDir "bundle-cache"
  $cacheBundle = Join-Path $cacheRoot "current"
  $manifestFile = Join-Path $cacheRoot "CACHE_MANIFEST.json"
  $fingerprint = Get-HuokeBundleFingerprint -BundleDir $SourceBundleDir

  if (Test-Path $manifestFile) {
    try {
      $existing = Get-Content $manifestFile -Raw | ConvertFrom-Json
      if ($existing.fingerprint -eq $fingerprint -and (Test-Path (Join-Path $cacheBundle "runtime"))) {
        $cachedPython = Find-PortablePythonExe -BundleDir $cacheBundle
        if (Test-PortablePythonRunnable -PythonExe $cachedPython -BackendDir (Join-Path $cacheBundle "backend")) {
          Write-Host "Reusing bundle cache: $cacheBundle"
          return $cacheBundle
        }
      }
    } catch {}
  }

  Write-Host "Syncing bundle cache to ASCII path: $cacheBundle"
  if (Test-Path $cacheBundle) {
    Remove-Item -Recurse -Force $cacheBundle
  }
  New-Item -ItemType Directory -Force -Path $cacheBundle | Out-Null

  foreach ($name in @("runtime", "backend", "frontend-dist")) {
    $src = Join-Path $SourceBundleDir $name
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $cacheBundle $name
    robocopy $src $dst /E /SL /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    if ($LASTEXITCODE -ge 8) {
      Clear-HuokeBundleCache -DataDir $DataDir
      throw "Failed to cache bundle component '$name' (robocopy exit $LASTEXITCODE)"
    }
  }

  foreach ($name in @("BUNDLE_MANIFEST.json", "RUNTIME_MANIFEST.json")) {
    $src = Join-Path $SourceBundleDir $name
    if (Test-Path $src) {
      Copy-Item $src (Join-Path $cacheBundle $name) -Force
    }
  }
  @{
    fingerprint = $fingerprint
    source = $SourceBundleDir
    cached_at = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json | Set-Content -Path $manifestFile -Encoding UTF8

  $cachedPython = Find-PortablePythonExe -BundleDir $cacheBundle
  $probe = Invoke-PortablePythonProbe -PythonExe $cachedPython -BackendDir (Join-Path $cacheBundle "backend")
  if (-not $probe.Ok) {
    Clear-HuokeBundleCache -DataDir $DataDir
    $detail = if ($probe.Output) { $probe.Output } else { "(no output, exit $($probe.ExitCode))" }
    throw "Bundle cache sync completed but portable Python probe failed: $detail"
  }

  return $cacheBundle
}
