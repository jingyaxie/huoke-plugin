# Install Windows 10/11 SDK silently (needed for Rust MSVC link.exe -> kernel32.lib).
$ErrorActionPreference = "Stop"

function Test-IsAdmin {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-Admin {
  if (Test-IsAdmin) { return }
  Write-Host "Re-launching installer with administrator privileges (approve UAC if prompted)..."
  $args = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $PSCommandPath
  )
  $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $args -Wait -PassThru
  if ($proc.ExitCode -ne 0) {
    throw "Elevated Windows SDK install failed with exit code $($proc.ExitCode)"
  }
  exit 0
}

function Write-InstallLog {
  param([string]$Message)
  $logFile = Join-Path $PSScriptRoot "..\install-sdk.log"
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Write-Host $line
  Add-Content -Path $logFile -Value $line -Encoding UTF8
}

function Test-Kernel32Lib {
  return Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\Lib" -Recurse -Filter "kernel32.lib" -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Install-WindowsSdkFeatures {
  param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string[]]$Features,
    [Parameter(Mandatory = $true)][string]$Label
  )
  $logDir = Join-Path $env:TEMP "huoke-winsdk-logs"
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  $logFile = Join-Path $logDir ("{0}.log" -f ($Label -replace '\s+', '-'))
  $featureArgs = @("/features") + $Features + @("/quiet", "/norestart", "/log", $logFile)
  Write-InstallLog "Trying $Label ..."
  Write-InstallLog "Command: $Installer $($featureArgs -join ' ')"
  $proc = Start-Process -FilePath $Installer -ArgumentList $featureArgs -Wait -PassThru
  Write-InstallLog "$Label exit code: $($proc.ExitCode) log: $logFile"
  if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) {
    $kernel = Test-Kernel32Lib
    if ($kernel) {
      Write-InstallLog "Windows SDK ready: $($kernel.FullName)"
      exit 0
    }
  }
}

Ensure-Admin

$kernel = Test-Kernel32Lib
if ($kernel) {
  Write-InstallLog "Windows SDK already present: $($kernel.FullName)"
  exit 0
}

$vsSetup = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\setup.exe"
$vsPath = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
if (Test-Path $vsSetup) {
  foreach ($component in @(
      "Microsoft.VisualStudio.Component.Windows11SDK.22621",
      "Microsoft.VisualStudio.Component.Windows10SDK.19041"
    )) {
    Write-InstallLog "VS modify add $component ..."
    $proc = Start-Process -FilePath $vsSetup -ArgumentList @(
      "modify",
      "--installPath", $vsPath,
      "--add", $component,
      "--passive",
      "--norestart",
      "--force"
    ) -Wait -PassThru
    Write-InstallLog "VS modify ($component) exit code: $($proc.ExitCode)"
    $kernel = Test-Kernel32Lib
    if ($kernel) {
      Write-InstallLog "Windows SDK ready via VS: $($kernel.FullName)"
      exit 0
    }
  }
}

$sdkInstaller = Join-Path $env:TEMP "winsdksetup-huoke.exe"
if (Test-Path $sdkInstaller) {
  Remove-Item $sdkInstaller -Force
}
Write-InstallLog "Downloading fresh Windows SDK installer..."
Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/?linkid=2317808" -OutFile $sdkInstaller -UseBasicParsing
if (-not (Test-Path $sdkInstaller) -or (Get-Item $sdkInstaller).Length -lt 1MB) {
  throw "Windows SDK installer download looks invalid"
}

Install-WindowsSdkFeatures -Installer $sdkInstaller -Label "desktop cpp x64 minimal" -Features @(
  "OptionId.DesktopCPPx64",
  "OptionId.WindowsDesktopDebuggers"
)
Install-WindowsSdkFeatures -Installer $sdkInstaller -Label "full sdk" -Features @("+")

throw "All Windows SDK install attempts failed. See logs under $env:TEMP\huoke-winsdk-logs and install-sdk.log"
