function Invoke-HuokePython {
  param(
    [Parameter(Mandatory = $true)][string]$Candidate,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs
  )
  if ($Candidate -match "^py\s+-(\d+\.\d+)$") {
    $ver = $Matches[1]
    & py "-$ver" @PythonArgs
  } elseif ($Candidate -match "^py\s+(-\S+)$") {
    $flag = $Matches[1]
    & py $flag @PythonArgs
  } else {
    & $Candidate @PythonArgs
  }
}

function Test-WindowsPythonStub {
  param([string]$Path)
  if (-not $Path) { return $false }
  return $Path -match "(\\|/)WindowsApps(\\|/)python(\.exe)?$"
}

function Test-HuokePythonVersion {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  $check = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
  if ($Candidate -match "^py\s+-(\d+\.\d+)$") {
    & py "-$($Matches[1])" -c $check
  } elseif ($Candidate -match "^py\s+(-\S+)$") {
    & py $Matches[1] -c $check
  } else {
    & $Candidate -c $check
  }
  return ($LASTEXITCODE -eq 0)
}

function Test-HuokePythonCandidate {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  if (Test-WindowsPythonStub $Candidate) { return $null }
  if ($Candidate -notmatch "^py\s") {
    if ($Candidate -match "^[A-Za-z]:\\") {
      if (-not (Test-Path -LiteralPath $Candidate)) { return $null }
    } elseif ($Candidate -ne "python" -and $Candidate -notmatch "^python3") {
      return $null
    }
  }
  try {
    if (Test-HuokePythonVersion $Candidate) {
      return $Candidate
    }
  } catch {}
  return $null
}

function Find-HuokePython {
  $preferred = @()
  if ($env:HUOKE_PYTHON) { $preferred += $env:HUOKE_PYTHON }
  if ($env:PYTHON) { $preferred += $env:PYTHON }
  if ($env:pythonLocation) {
    $preferred += (Join-Path $env:pythonLocation "python.exe")
  }
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd -and $pythonCmd.Source) {
    $preferred += $pythonCmd.Source
  }

  $seen = @{}
  foreach ($candidate in $preferred) {
    if (-not $candidate -or $seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    $found = Test-HuokePythonCandidate $candidate
    if ($found) { return $found }
  }

  foreach ($candidate in @("py -3.12", "py -3.11", "python3.12", "python3.11", "python")) {
    if ($seen.ContainsKey($candidate)) { continue }
    $seen[$candidate] = $true
    $found = Test-HuokePythonCandidate $candidate
    if ($found) { return $found }
  }
  return $null
}

function Resolve-HuokePythonExe {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  if ($Candidate -match "^py\s") {
    $exe = $null
    if ($Candidate -match "^py\s+-(\d+\.\d+)$") {
      $exe = & py "-$($Matches[1])" -c "import sys; print(sys.executable)"
    } elseif ($Candidate -match "^py\s+(-\S+)$") {
      $exe = & py $Matches[1] -c "import sys; print(sys.executable)"
    }
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($exe | Out-String).Trim()
  }
  if (Test-Path -LiteralPath $Candidate) { return $Candidate }
  $cmd = Get-Command $Candidate -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source) { return $cmd.Source }
  return $Candidate
}

function Set-HuokePythonEnv {
  param([Parameter(Mandatory = $true)][string]$Candidate)
  $exe = Resolve-HuokePythonExe $Candidate
  if (-not $exe -or -not (Test-Path -LiteralPath $exe)) {
    throw "Failed to resolve Python executable from candidate: $Candidate"
  }
  if (-not (Test-HuokePythonVersion $exe)) {
    throw "Python 3.11+ required, but resolved executable failed version check: $exe"
  }
  $env:HUOKE_PYTHON = $exe
  $env:PYTHON = $exe
  return $exe
}

function Write-HuokePythonDiagnostics {
  Write-Host "Python diagnostics:"
  Write-Host "  HUOKE_PYTHON=$($env:HUOKE_PYTHON)"
  Write-Host "  PYTHON=$($env:PYTHON)"
  Write-Host "  pythonLocation=$($env:pythonLocation)"
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if ($cmd) {
    Write-Host "  Get-Command python -> $($cmd.Source)"
  } else {
    Write-Host "  Get-Command python -> (not found)"
  }
  foreach ($probe in @($env:HUOKE_PYTHON, $env:PYTHON, $(if ($cmd) { $cmd.Source }))) {
    if (-not $probe) { continue }
    $ok = $false
    try { $ok = Test-HuokePythonVersion $probe } catch {}
    Write-Host "  version-check $probe -> $ok"
  }
}
