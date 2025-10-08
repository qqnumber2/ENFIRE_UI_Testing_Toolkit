<#  UI Testing — Setup & Deploy (PS 5.1 compatible, absolute paths + proper quoting)
    - Builds PyInstaller EXE
    - Uses venv in .\venv (no need to activate)
    - Installs deps (online or from .\wheels\ with -Offline)
    - Places Desktop shortcut (with icon if present)
    - Keeps images/scripts/results next to EXE (OneDir recommended)
#>

param(
  [switch]$OneFile = $false,       # default: onedir
  [switch]$Offline = $false,       # install from .\wheels\
  [switch]$Debug   = $false,       # console window
  [switch]$ForceRebuild = $false   # remove dist/ before build
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "UI Testing — Setup & Deploy"

# -------- Config --------
$AppName      = "UI_Testing"                 # exe name (no spaces is safer)
$EntryScript  = "ui_testing\gui.py"
$IconPathRel  = "assets\app.ico"
$DistDirRel   = "dist"
$BuildDirRel  = "build"
$VenvDirRel   = "venv"
$WheelsDirRel = "wheels"
$ShortcutName = "UI Testing.lnk"

# -------- Resolve absolute paths --------
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host ("Project root: {0}" -f $Root) -ForegroundColor Cyan

$VenvDir   = Join-Path $Root $VenvDirRel
$BuildDir  = Join-Path $Root $BuildDirRel
$DistDir   = Join-Path $Root $DistDirRel
$WheelsDir = Join-Path $Root $WheelsDirRel
$IconPath  = Join-Path $Root $IconPathRel
$EntryAbs  = Join-Path $Root $EntryScript

# -------- Python detection --------
function Find-Python {
  try {
    $py = & py -3 -c "import sys;print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $py) { return $py.Trim() }
  } catch {}
  try {
    $py = & python -c "import sys;print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $py) { return $py.Trim() }
  } catch {}
  throw "Python not found. Install Python 3.x and ensure 'py' or 'python' is on PATH."
}
$SystemPython = Find-Python
Write-Host ("System Python: {0}" -f $SystemPython)

# -------- Ensure venv --------
if (-not (Test-Path $VenvDir)) {
  Write-Host "Creating venv..." -ForegroundColor Yellow
  & "$SystemPython" -m venv "$VenvDir"
}

$Py  = Join-Path $VenvDir "Scripts\python.exe"
$Pip = Join-Path $VenvDir "Scripts\pip.exe"
if (-not (Test-Path $Py))  { throw "venv creation failed — missing: $Py" }
if (-not (Test-Path $Pip)) { throw "venv creation failed — missing: $Pip" }

# Upgrade pip when online
if (-not $Offline) {
  try { & "$Pip" install --upgrade pip setuptools wheel | Out-Host } catch { Write-Warning "Pip upgrade failed (continuing). $_" }
}

# -------- Install dependencies --------
$Req = Join-Path $Root "requirements.txt"
if (-not (Test-Path $Req)) { throw "requirements.txt not found at: $Req" }

if ($Offline) {
  if (-not (Test-Path $WheelsDir)) { throw "Offline mode requested, but wheels folder not found: $WheelsDir" }
  Write-Host "Installing from local wheels..." -ForegroundColor Yellow
  & "$Pip" install --no-index --find-links="$WheelsDir" -r "$Req" | Out-Host
} else {
  Write-Host "Installing from PyPI..." -ForegroundColor Yellow
  & "$Pip" install -r "$Req" | Out-Host
}

# Ensure PyInstaller exists even if requirements missed it
& "$Py" -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing PyInstaller explicitly..." -ForegroundColor Yellow
  if ($Offline) {
    & "$Pip" install --no-index --find-links="$WheelsDir" pyinstaller | Out-Host
  } else {
    & "$Pip" install pyinstaller | Out-Host
  }
  if ($LASTEXITCODE -ne 0) { throw "Failed to install PyInstaller." }
}

# -------- Clean build --------
if (Test-Path $BuildDir) { Remove-Item "$BuildDir" -Recurse -Force }
if ($ForceRebuild -and (Test-Path $DistDir)) { Remove-Item "$DistDir" -Recurse -Force }

# -------- Compose flags (PS 5.1-safe) --------
$WindowFlag = "--windowed"
if ($Debug) { $WindowFlag = "--console" }

$BundleFlag = "--onedir"
if ($OneFile) { $BundleFlag = "--onefile" }

$IconArgs = @()
if (Test-Path $IconPath) { $IconArgs = @("--icon", $IconPath) }

$Hidden = @(
  "--hidden-import","pynput.keyboard",
  "--hidden-import","pynput.mouse",
  "--hidden-import","win32timezone"
)

# -------- Build --------
Write-Host ("Building EXE with PyInstaller ({0})..." -f $BundleFlag) -ForegroundColor Yellow
& "$Py" -m PyInstaller `
  --noconfirm `
  --clean `
  $BundleFlag `
  $WindowFlag `
  --name "$AppName" `
  @IconArgs `
  @Hidden `
  "$EntryAbs"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

# -------- Detect EXE path based on mode --------
$ExePath = $null
if ($OneFile) {
  $ExePath = Join-Path $DistDir "$AppName.exe"
} else {
  $ExeDir  = Join-Path $DistDir $AppName
  $ExePath = Join-Path $ExeDir "$AppName.exe"
}
if (-not (Test-Path $ExePath)) { throw ("PyInstaller did not produce expected executable: {0}" -f $ExePath) }

# -------- Ensure runtime data dirs (OneDir) --------
if (-not $OneFile) {
  $AppDir = Split-Path -Parent $ExePath
  foreach ($d in @("images","scripts","results")) {
    $p = Join-Path $AppDir $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
  }
}

# -------- Desktop shortcut --------
$Desktop      = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop $ShortcutName

Write-Host ("Creating/Updating Desktop shortcut: {0}" -f $ShortcutPath) -ForegroundColor Yellow
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = (Get-Item $ExePath).FullName
$Shortcut.WorkingDirectory = (Get-Item (Split-Path -Parent $ExePath)).FullName
if (Test-Path $IconPath) { $Shortcut.IconLocation = (Get-Item $IconPath).FullName }
$Shortcut.Save()

Write-Host ""
Write-Host ("✅ Build complete.") -ForegroundColor Green
Write-Host ("EXE: {0}" -f (Get-Item $ExePath).FullName)
if ($OneFile) { Write-Host "Mode: OneFile" -ForegroundColor Cyan } else { Write-Host "Mode: OneDir" -ForegroundColor Cyan; Write-Host "Dirs beside EXE: images/, scripts/, results/" }
Write-Host ("Shortcut: {0}" -f $ShortcutPath)
Write-Host ""
Write-Host "Re-run anytime; it only updates what changed."
