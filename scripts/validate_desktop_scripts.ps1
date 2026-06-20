# Fast local/CI validation for Windows desktop packaging scripts.
# Run on Windows before pushing tags: pwsh ./scripts/validate_desktop_scripts.ps1
$ErrorActionPreference = "Stop"

function Test-PowerShellScriptSyntax {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path $Path)) {
    throw "missing script: $Path"
  }
  $tokens = $null
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path $Path),
    [ref]$tokens,
    [ref]$errors
  )
  if ($errors -and $errors.Count -gt 0) {
    $details = ($errors | ForEach-Object { $_.ToString() }) -join "`n"
    throw "PowerShell syntax error in ${Path}:`n$details"
  }
  Write-Host "syntax ok: $Path"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
  foreach ($script in @(
      "scripts/desktop-run-backend.ps1",
      "scripts/desktop-bundle-cache.ps1",
      "scripts/desktop-runtime-workdir.ps1",
      "scripts/generate_runtime_manifest.ps1",
      "scripts/verify_installed_startup.ps1",
      "scripts/verify_nsis_installed.ps1",
      "scripts/verify_windows_bundle.ps1",
      "scripts/_python_win.ps1"
    )) {
    Test-PowerShellScriptSyntax -Path $script
  }

  $pythonScripts = @(
    "desktop_uvicorn_launcher.py",
    "desktop_run_backend.py",
    "desktop_bundle_runtime.py",
    "desktop_stdio.py",
    "portable_dll_bootstrap.py"
  )
  foreach ($name in $pythonScripts) {
    $path = Join-Path $repoRoot "scripts/$name"
    if (-not (Test-Path $path)) {
      throw "missing script: scripts/$name"
    }
  }

  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    $py = Get-Command python3 -ErrorAction SilentlyContinue
  }
  if ($py) {
    foreach ($name in $pythonScripts) {
      $path = Join-Path $repoRoot "scripts/$name"
      & $py.Source -m py_compile $path
      if ($LASTEXITCODE -ne 0) {
        throw "Python syntax error in scripts/$name"
      }
      Write-Host "syntax ok: scripts/$name"
    }
  } else {
    Write-Host "WARN: python not found; skipped desktop python script syntax checks"
  }

  $config = Get-Content "desktop/src-tauri/tauri.conf.json" -Raw | ConvertFrom-Json
  $expectedMainUrl = "about:blank"
  if ($config.app.windows[0].url -ne $expectedMainUrl) {
    throw "main window must start at $expectedMainUrl until backend is ready, got: $($config.app.windows[0].url)"
  }
  foreach ($required in @(
      "../../scripts/desktop-runtime-workdir.ps1",
      "../../scripts/diagnose_portable_python.py",
      "../../scripts/desktop_uvicorn_launcher.py",
      "../../scripts/desktop_run_backend.py",
      "../../scripts/desktop_bundle_runtime.py",
      "../../scripts/desktop_stdio.py",
      "../../scripts/portable_dll_bootstrap.py"
    )) {
    if (-not $config.bundle.resources.$required) {
      throw "missing bundle resource: $required"
    }
  }
  Write-Host "tauri.conf.json ok"

  if (Test-Path "desktop/bundle/runtime") {
    . (Join-Path $repoRoot "scripts/desktop-bundle-cache.ps1")
    . (Join-Path $repoRoot "scripts/desktop-runtime-workdir.ps1")
    $bundleDir = (Resolve-Path "desktop/bundle").Path
    $asciiData = Join-Path $env:TEMP ("huoke-validate-cache-{0}" -f ([guid]::NewGuid().ToString('N')))
    $asciiRoot = Join-Path $env:TEMP "huoke-validate-ascii-root"
    try {
      $resolved = Sync-HuokeBundleCache -SourceBundleDir $bundleDir -DataDir $asciiData -Root $asciiRoot
      if ($resolved -ne $bundleDir) {
        throw "ASCII install path must not trigger bundle cache sync (got: $resolved)"
      }
      $py = Find-PortablePythonExe -BundleDir $bundleDir
      $probe = Invoke-PortablePythonProbe -PythonExe $py -BackendDir (Join-Path $bundleDir "backend")
      if (-not $probe.Ok) {
        throw "portable python probe failed under ASCII path: $($probe.Output)"
      }
      Write-Host "bundle-cache ASCII guard ok"

      $workData = Join-Path $env:TEMP ("huoke-validate-work-{0}" -f ([guid]::NewGuid().ToString('N')))
      try {
        foreach ($rel in @(
            "backend/app/main.py",
            "backend/storage/skills/global.json",
            "frontend-dist/index.html"
          )) {
          if (-not (Test-Path (Join-Path $bundleDir $rel))) {
            throw "bundle missing $rel (run prepare_desktop_bundle.ps1)"
          }
        }
        $workBundle = Sync-HuokeRuntimeWorkdir -SourceBundleDir $bundleDir -DataDir $workData
        if (-not (Test-HuokeRuntimeWorkBackendReady -WorkBundle $workBundle)) {
          throw "runtime-work bundle incomplete after sync"
        }
        $workCheck = Test-HuokeRuntimeManifest -BundleDir $workBundle
        if (-not $workCheck.Ok) {
          throw ("runtime-work manifest failed: " + ($workCheck.Issues -join "; "))
        }
        Write-Host "runtime-work sync ok"
      } finally {
        if (Test-Path $workData) {
          Remove-Item -Recurse -Force $workData -ErrorAction SilentlyContinue
        }
      }
    } finally {
      if (Test-Path $asciiData) {
        Remove-Item -Recurse -Force $asciiData -ErrorAction SilentlyContinue
      }
    }

    Write-Host "bundle present, running installed-layout smoke (ASCII, powershell.exe)..."
    $asciiInstall = Join-Path $env:TEMP "huoke-validate-ascii"
    & (Join-Path $repoRoot "scripts/verify_installed_startup.ps1") `
      -RepoRoot $repoRoot `
      -InstallRoot $asciiInstall `
      -BackendPort 18766 `
      -Shell "powershell.exe" `
      -AssertNoBundleCacheSync
    Write-Host "installed-layout smoke ok (powershell.exe)"
  } else {
    Write-Host "desktop/bundle missing; syntax-only validation passed (run prepare_desktop_bundle.ps1 for full smoke)"
  }

  Write-Host "validate_desktop_scripts: all checks passed"
  exit 0
} finally {
  Pop-Location
}
