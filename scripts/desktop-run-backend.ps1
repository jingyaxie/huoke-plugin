# Windows desktop: start bundled FastAPI backend (stdout-only logging for Rust parent)
$ErrorActionPreference = "Stop"

function Resolve-HuokeDataDir {
  if ($env:HUOKE_DATA_DIR) { return $env:HUOKE_DATA_DIR }
  $appData = [Environment]::GetFolderPath("ApplicationData")
  return Join-Path $appData "com.huoke.desktop"
}

function Write-Log {
  param([string]$Message)
  $line = ("[backend] [{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
  try {
    Write-Output $line
  } catch {
    $logFile = $env:HUOKE_LOG_FILE
    if ($logFile) {
      Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    }
  }
}

function Set-HuokePythonProcessEnv {
  $env:PYTHONIOENCODING = "utf-8"
  $env:PYTHONUNBUFFERED = "1"
}

function Invoke-PythonScript {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [switch]$AllowFailure
  )
  Set-HuokePythonProcessEnv
  Write-Log $Label
  # Do NOT pipe & output: PS 5.1 loses $LASTEXITCODE after a pipeline.
  # Use Continue so native stderr does not terminate before we read $LASTEXITCODE.
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $output = & $PythonExe @ArgumentList 2>&1
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prevEap
  }
  foreach ($line in @($output)) {
    if ($null -eq $line) { continue }
    $text = if ($line -is [System.Management.Automation.ErrorRecord]) { "$line" } else { "$line" }
    if ($text.Length -gt 0) {
      try {
        Write-Output ("[backend] {0}" -f $text)
      } catch {
        $logFile = $env:HUOKE_LOG_FILE
        if ($logFile) {
          Add-Content -LiteralPath $logFile -Value ("[backend] {0}" -f $text) -Encoding UTF8 -ErrorAction SilentlyContinue
        }
      }
    }
  }
  if ($exitCode -ne 0) {
    if ($AllowFailure) {
      return $false
    }
    throw "$Label failed (exit $exitCode)"
  }
  return $true
}

function Start-PythonLauncherServer {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$LauncherScript,
    [int]$Port = 18765
  )
  Write-Log "starting backend launcher on port $Port"
  # Direct invocation streams Python stdout/stderr to Tauri without temp-file loss.
  Set-HuokePythonProcessEnv
  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & $PythonExe $LauncherScript --port $Port
    $exitCode = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prevEap
  }
  if ($exitCode -ne 0) {
    throw "backend launcher failed (exit $exitCode)"
  }
}

function Invoke-PythonProcess {
  param(
    [Parameter(Mandatory = $true)][string]$Label,
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string[]]$ArgumentList,
    [switch]$AllowFailure
  )
  return Invoke-PythonScript -Label $Label -PythonExe $PythonExe -ArgumentList $ArgumentList -AllowFailure:$AllowFailure
}

function Resolve-HuokeBundleDir {
  if ($env:HUOKE_BUNDLE_DIR -and (Test-Path (Join-Path $env:HUOKE_BUNDLE_DIR "runtime"))) {
    return $env:HUOKE_BUNDLE_DIR
  }
  $candidates = @(
    (Join-Path $script:Root "desktop/bundle"),
    (Join-Path $script:Root "bundle")
  )
  foreach ($dir in $candidates) {
    if (Test-Path (Join-Path $dir "runtime")) { return $dir }
  }
  throw "bundle runtime not found under HUOKE_ROOT=$($script:Root)"
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

function Test-PortInUse {
  param([int]$Port)
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { return $true }
  } catch {}
  try {
    $netstatMatches = netstat -ano | Select-String -Pattern ":[ ]*$Port[ ].*LISTENING"
    return [bool]$netstatMatches
  } catch {}
  return $false
}

function Invoke-HuokeNativeDiagnostics {
  param(
    [string]$PythonExe,
    [string]$BundleDir
  )
  $diagScript = Join-Path $script:ScriptDir "diagnose_portable_python.py"
  if (-not (Test-Path $diagScript)) {
    Write-Log "WARN: diagnose_portable_python.py missing"
    return
  }
  $env:HUOKE_BUNDLE_DIR = $BundleDir
  $env:HUOKE_PYTHON_EXE = $PythonExe
  Invoke-PythonProcess -Label "native diagnostics" -PythonExe $PythonExe -ArgumentList @($diagScript) -AllowFailure | Out-Null
}

function Invoke-HuokePortableDllBootstrap {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$ScriptDir
  )
  $pythonRoot = Get-PortablePythonRoot -PythonExe $PythonExe
  $bootstrap = Join-Path $pythonRoot "Lib\portable_dll_bootstrap.py"
  if (-not (Test-Path $bootstrap)) {
    $fallback = Join-Path $ScriptDir "portable_dll_bootstrap.py"
    if (Test-Path $fallback) {
      New-Item -ItemType Directory -Force -Path (Split-Path $bootstrap -Parent) | Out-Null
      Copy-Item $fallback $bootstrap -Force
      Write-Log "installed portable_dll_bootstrap.py into runtime Lib"
      $fallbackStdio = Join-Path $ScriptDir "desktop_stdio.py"
      if (Test-Path $fallbackStdio) {
        Copy-Item $fallbackStdio (Join-Path $pythonRoot "Lib\desktop_stdio.py") -Force
        Write-Log "installed desktop_stdio.py into runtime Lib"
      }
    }
  }
  if (-not (Test-Path $bootstrap)) {
    Write-Log "WARN: portable_dll_bootstrap.py missing"
    return $false
  }
  return Invoke-PythonScript -Label "portable dll bootstrap" -PythonExe $PythonExe -ArgumentList @($bootstrap, "--heal-only") -AllowFailure
}

function Repair-HuokeNativeRuntime {
  param(
    [string]$PythonExe,
    [string]$BundleDir,
    [string]$ScriptDir
  )
  $layoutOk = Invoke-HuokePortableDllBootstrap -PythonExe $PythonExe -ScriptDir $ScriptDir
  $repairWheels = Join-Path $BundleDir "runtime/repair-wheels"
  if (-not (Test-Path $repairWheels)) {
    Write-Log "WARN: repair-wheels directory missing: $repairWheels"
    return $layoutOk
  }
  Write-Log "attempting offline native repair from $repairWheels"
  $pipOk = Invoke-PythonScript -Label "native repair" -PythonExe $PythonExe -ArgumentList @(
    "-m", "pip", "install", "--disable-pip-version-check",
    "--no-index", "--find-links", $repairWheels,
    "--force-reinstall", "greenlet", "playwright", "cryptography", "pydantic-core"
  ) -AllowFailure
  return ($layoutOk -or $pipOk)
}

function Invoke-HuokeBackendLauncher {
  param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$LauncherScript,
    [int]$Port = 18765,
    [switch]$CheckOnly,
    [switch]$AllowFailure
  )
  $args = @($LauncherScript, "--port", "$Port")
  if ($CheckOnly) {
    $args += "--check-only"
  }
  $label = if ($CheckOnly) { "unified preflight" } else { "starting uvicorn on port $Port" }
  return Invoke-PythonProcess -Label $label -PythonExe $PythonExe -ArgumentList $args -AllowFailure:$AllowFailure
}

function Start-HuokeDesktopBackend {
  $DataDir = Resolve-HuokeDataDir
  $SourceBundleDir = Resolve-HuokeBundleDir
  $CachedBundleDir = Sync-HuokeBundleCache -SourceBundleDir $SourceBundleDir -DataDir $DataDir -Root $script:Root
  $BundleDir = Sync-HuokeRuntimeWorkdir -SourceBundleDir $CachedBundleDir -DataDir $DataDir
  $BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 18765 }
  $StorageDir = Join-Path $DataDir "storage"
  $EnvFile = Join-Path $DataDir ".env.desktop"
  $DbFile = Join-Path $StorageDir "huoke_desktop.db"

  New-Item -ItemType Directory -Force -Path $DataDir, $StorageDir, (Join-Path $StorageDir "douyin/profile") | Out-Null
  Write-Log "root=$($script:Root) sourceBundle=$SourceBundleDir cachedBundle=$CachedBundleDir workBundle=$BundleDir"

  $ExampleEnv = Join-Path $script:Root ".env.desktop.example"
  if (-not (Test-Path $ExampleEnv)) {
    $ExampleEnv = Join-Path $script:Root "resources/.env.desktop.example"
  }
  if (-not (Test-Path $EnvFile)) {
    if (Test-Path $ExampleEnv) {
      Copy-Item $ExampleEnv $EnvFile
      Add-Content $EnvFile "`nANTIBOT_FINGERPRINT_PLATFORM=win"
      Write-Log "created desktop config: $EnvFile"
    } else {
      Write-Log "WARN: .env.desktop.example missing, using defaults"
    }
  }

  $PortablePython = Find-PortablePythonExe -BundleDir $BundleDir
  $VenvPython = Join-Path $BundleDir "runtime/.venv/Scripts/python.exe"
  $Python = $null
  $BackendDir = $null
  if ($PortablePython) {
    $BackendDir = Join-Path $BundleDir "backend"
    $Python = $PortablePython
  } elseif (Test-Path $VenvPython) {
    $BackendDir = Join-Path $BundleDir "backend"
    $Python = $VenvPython
  } else {
    . (Join-Path $script:ScriptDir "_python_win.ps1")
    $BackendDir = Join-Path $script:Root "backend"
    $DevVenv = Join-Path $BackendDir ".venv/Scripts/python.exe"
    if (Test-Path $DevVenv) {
      $Python = $DevVenv
    } else {
      $candidate = Find-HuokePython
      if ($candidate) {
        $Python = Resolve-HuokePythonExe $candidate
      }
    }
  }

  if (-not $Python -or -not (Test-Path $Python)) {
    throw "Python runtime not found (bundle=$BundleDir)"
  }

  if ($PortablePython) {
    Set-PortablePythonEnv -PythonExe $Python
    Write-Log "Python: $Python (portable root=$(Get-PortablePythonRoot -PythonExe $Python))"
  } else {
    Write-Log "Python: $Python"
  }

  if (Test-PortInUse -Port $BackendPort) {
    throw "port $BackendPort is already in use"
  }

  Set-Location $BackendDir

  $env:DESKTOP_MODE = "true"
  $env:HUOKE_BUNDLE_DIR = $BundleDir
  $env:HUOKE_PYTHON_EXE = $Python
  $FrontendDist = Join-Path $BundleDir "frontend-dist"
  if (Test-Path $FrontendDist) {
    $env:FRONTEND_DIST_DIR = $FrontendDist
  } else {
    $env:FRONTEND_DIST_DIR = Join-Path $script:Root "frontend/dist"
  }
  $env:STORAGE_ROOT = $StorageDir
  $env:FRONTEND_ORIGIN = "http://127.0.0.1:$BackendPort"
  $env:DATABASE_URL = "sqlite+pysqlite:///$($DbFile -replace '\\', '/')"
  $env:DOUYIN_PROFILE_DIR = Join-Path $StorageDir "douyin/profile"
  $env:PYTHONPATH = $BackendDir
  $env:ANTIBOT_FINGERPRINT_PLATFORM = "win"

  if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
      $line = $_.Trim()
      if ($line -and -not $line.StartsWith("#") -and $line -match '^([^=]+)=(.*)$') {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim().Trim('"')
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
      }
    }
  }

  $env:DESKTOP_MODE = "true"
  $env:FRONTEND_ORIGIN = "http://127.0.0.1:$BackendPort"
  $env:ANTIBOT_FINGERPRINT_PLATFORM = "win"

  $Chrome = Find-ChromePath
  if (-not $Chrome) {
    Write-Log "Google Chrome is required for browser automation. Install Chrome and restart the app."
    throw "Google Chrome not installed"
  }
  Write-Log "Chrome: $Chrome"

  $LauncherScript = Join-Path $script:ScriptDir "desktop_uvicorn_launcher.py"
  if (-not (Test-Path $LauncherScript)) {
    throw "desktop_uvicorn_launcher.py missing under $($script:ScriptDir)"
  }

  if ($PortablePython) {
    $null = Invoke-HuokePortableDllBootstrap -PythonExe $Python -ScriptDir $script:ScriptDir
  }

  try {
    Start-PythonLauncherServer -PythonExe $Python -LauncherScript $LauncherScript -Port $BackendPort
  } catch {
    $startError = $_.Exception.Message
    Write-Log "backend launcher failed: $startError"
    Invoke-HuokeNativeDiagnostics -PythonExe $Python -BundleDir $BundleDir
    $repaired = Repair-HuokeNativeRuntime -PythonExe $Python -BundleDir $BundleDir -ScriptDir $script:ScriptDir
    if ($repaired) {
      Write-Log "native repair completed; retrying launcher"
    }
    if ($PortablePython) {
      $null = Invoke-HuokePortableDllBootstrap -PythonExe $Python -ScriptDir $script:ScriptDir
    }
    $preflightOk = Invoke-HuokeBackendLauncher -PythonExe $Python -LauncherScript $LauncherScript -Port $BackendPort -CheckOnly -AllowFailure
    if (-not $preflightOk) {
      throw "native repair completed but preflight still failed; see diagnose output above"
    }
    Start-PythonLauncherServer -PythonExe $Python -LauncherScript $LauncherScript -Port $BackendPort
  }
}

$script:ScriptDir = $PSScriptRoot
$script:Root = if ($env:HUOKE_ROOT) { $env:HUOKE_ROOT } else { Split-Path -Parent $script:ScriptDir }
. (Join-Path $script:ScriptDir "desktop-bundle-cache.ps1")
. (Join-Path $script:ScriptDir "desktop-runtime-workdir.ps1")

try {
  Write-Log "desktop-run-backend starting"
  Start-HuokeDesktopBackend
} catch {
  $msg = $_.Exception.Message
  if ($msg -match 'greenlet|native|DLL|vcruntime') {
    $msg = "$msg`n`nSuggestions: 1) Add install dir to antivirus allowlist 2) Fully uninstall and reinstall 3) If vcruntime is missing, install VC++ 2015-2022 x64: https://aka.ms/vs/17/release/vc_redist.x64.exe"
  }
  Write-Log ("FATAL: {0}" -f $msg)
  if ($_.ScriptStackTrace) {
    Write-Log $_.ScriptStackTrace
  }
  exit 1
}
