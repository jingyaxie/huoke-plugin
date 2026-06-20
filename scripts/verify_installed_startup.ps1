# CI: simulate installed layout (ASCII + Unicode paths) and verify backend startup.
param(
  [Parameter(Mandatory = $true)][string]$RepoRoot,
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [int]$BackendPort = 18765,
  [string]$Shell = "",
  [switch]$AssertNoBundleCacheSync
)

$ErrorActionPreference = "Stop"

function Copy-InstalledLayout {
  param(
    [string]$SourceRoot,
    [string]$TargetRoot
  )
  if (Test-Path $TargetRoot) {
    Remove-Item -Recurse -Force $TargetRoot
  }
  New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
  robocopy (Join-Path $SourceRoot "scripts") (Join-Path $TargetRoot "scripts") /E /SL /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "scripts copy failed ($LASTEXITCODE)" }
  robocopy (Join-Path $SourceRoot "desktop/bundle") (Join-Path $TargetRoot "desktop/bundle") /E /SL /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "bundle copy failed ($LASTEXITCODE)" }
  $exampleEnv = Join-Path $SourceRoot ".env.desktop.example"
  if (Test-Path $exampleEnv) {
    Copy-Item $exampleEnv (Join-Path $TargetRoot ".env.desktop.example")
  }
}

function Wait-BackendHealth {
  param([int]$Port, [int]$TimeoutSec = 120)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 -UseBasicParsing
      if ($r.StatusCode -eq 200) { return }
    } catch {}
    Start-Sleep -Seconds 1
  }
  throw "health check timed out for port $Port"
}

function Show-SmokeFailureLogs {
  param(
    [string]$StdoutFile,
    [string]$StderrFile
  )
  Write-Host "--- backend stdout ---"
  if (Test-Path $StdoutFile) {
    Get-Content $StdoutFile -Tail 80 | ForEach-Object { Write-Host $_ }
  }
  Write-Host "--- backend stderr ---"
  if (Test-Path $StderrFile) {
    Get-Content $StderrFile -Tail 80 | ForEach-Object { Write-Host $_ }
  }
}

Copy-InstalledLayout -SourceRoot $RepoRoot -TargetRoot $InstallRoot

$dataDir = Join-Path $env:TEMP "huoke-smoke-data-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

$stdoutFile = Join-Path $env:TEMP "huoke-smoke-stdout-$BackendPort.log"
$stderrFile = Join-Path $env:TEMP "huoke-smoke-stderr-$BackendPort.log"
if (Test-Path $stdoutFile) { Remove-Item $stdoutFile -Force }
if (Test-Path $stderrFile) { Remove-Item $stderrFile -Force }

$backendScript = Join-Path $InstallRoot "scripts/desktop-run-backend.ps1"
if (-not $Shell) {
  $Shell = if (Get-Command pwsh.exe -ErrorAction SilentlyContinue) { "pwsh.exe" } else { "powershell.exe" }
}
Write-Host "startup smoke shell: $Shell installRoot=$InstallRoot"
$proc = Start-Process -FilePath $Shell -PassThru -WindowStyle Hidden -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $backendScript
) -WorkingDirectory $InstallRoot -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile -Environment @{
  HUOKE_ROOT = $InstallRoot
  HUOKE_BUNDLE_DIR = (Join-Path $InstallRoot "desktop/bundle")
  HUOKE_DATA_DIR = $dataDir
  BACKEND_PORT = "$BackendPort"
}

try {
  $deadline = (Get-Date).AddSeconds(120)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
      break
    }
    try {
      Wait-BackendHealth -Port $BackendPort -TimeoutSec 2
      $healthy = $true
      break
    } catch {
      Start-Sleep -Seconds 1
    }
  }

  if (-not $healthy) {
    Show-SmokeFailureLogs -StdoutFile $stdoutFile -StderrFile $stderrFile
    if ($proc.HasExited) {
      throw "backend exited early with code $($proc.ExitCode) for install root: $InstallRoot"
    }
    throw "backend startup timed out for install root: $InstallRoot"
  }

  if (-not (Test-Path $stdoutFile)) {
    throw "missing backend stdout log for install root: $InstallRoot"
  }
  $backendLines = Get-Content $stdoutFile | Where-Object { $_ -match '\[backend\]' }
  if (-not $backendLines -or $backendLines.Count -lt 1) {
    Show-SmokeFailureLogs -StdoutFile $stdoutFile -StderrFile $stderrFile
    throw "backend stdout missing [backend] log lines for install root: $InstallRoot"
  }

  if ($AssertNoBundleCacheSync) {
    $stdoutText = Get-Content $stdoutFile -Raw
    if ($stdoutText -match 'Syncing bundle cache') {
      Show-SmokeFailureLogs -StdoutFile $stdoutFile -StderrFile $stderrFile
      throw "ASCII install must not sync bundle cache (install root: $InstallRoot)"
    }
  }

  Write-Host "startup smoke ok: $InstallRoot ($($backendLines.Count) [backend] lines, shell=$Shell)"
} finally {
  if (-not $proc.HasExited) {
    try {
      & taskkill.exe /PID $proc.Id /T /F | Out-Null
    } catch {
      Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
  }
  Start-Sleep -Seconds 1
  if (Test-Path $dataDir) {
    Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
  }
}

exit 0
