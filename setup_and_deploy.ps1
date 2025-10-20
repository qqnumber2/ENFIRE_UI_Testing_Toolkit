<#  UI Testing - Setup & Deploy (PS 5.1 compatible, absolute paths + proper quoting)
    - Builds PyInstaller EXE
    - Uses virtual environment in .\.venv (no need to activate manually)
    - Installs deps (online or from .\wheels\ with -Offline)
    - Produces ready-to-copy Package and Installer folders (and zip archives)
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
$Host.UI.RawUI.WindowTitle = "UI Testing - Setup & Deploy"

# -------- Config --------
$AppName      = "UI_Testing"                 # exe name (no spaces is safer)
$EntryScript  = "ui_testing\gui.py"
$IconPathRel  = "assets\app.ico"
$AssetsDirRel = "assets"
$DataRootRel  = "ui_testing\data"
$UiSettingsRel = "ui_testing\data\ui_settings.json"
$DistDirRel   = "dist"
$BuildDirRel  = "build"
$VenvDirRel   = ".venv"
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
$AssetsDir = Join-Path $Root $AssetsDirRel
$DataRoot  = Join-Path $Root $DataRootRel
$UiSettingsPath = Join-Path $Root $UiSettingsRel
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
if (-not (Test-Path $Py))  { throw "venv creation failed - missing: $Py" }
if (-not (Test-Path $Pip)) { throw "venv creation failed - missing: $Pip" }

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

Write-Host "Running bytecode compilation (compileall)..." -ForegroundColor Yellow
& "$Py" "-m" "compileall" "ui_testing" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "compileall failed; aborting build." }

Write-Host "Running semantic pytest suite..." -ForegroundColor Yellow
& "$Py" "-m" "pytest" "ui_testing/tests" "-m" "semantic" "--maxfail=1" | Out-Host
if ($LASTEXITCODE -ne 0) { throw "pytest -m semantic failed; aborting build." }

function Ensure-Appium {
  if (Get-Command appium -ErrorAction SilentlyContinue) {
    Write-Host "Appium already installed." -ForegroundColor Green
    return
  }
  if ($Offline) {
    Write-Warning "Appium not installed (offline mode). Install manually or rerun setup online."
    return
  }
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Installing Appium via npm..." -ForegroundColor Yellow
    try {
      npm install -g appium | Out-Host
      Write-Host "Appium installation attempted; verify with 'appium --version'." -ForegroundColor Green
    } catch {
      Write-Warning "Failed to install Appium via npm. $_"
    }
  } else {
    Write-Warning "npm not found; unable to install Appium automatically. Install Node.js + Appium manually."
  }
}

function Ensure-WinAppDriver {
  if (Get-Command WinAppDriver.exe -ErrorAction SilentlyContinue) {
    Write-Host "WinAppDriver already available." -ForegroundColor Green
    return
  }
  if ($Offline) {
    Write-Warning "WinAppDriver not installed (offline mode). Install manually from Microsoft."
    return
  }
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing WinAppDriver via winget..." -ForegroundColor Yellow
    try {
      winget install --id=Microsoft.WinAppDriver -e --source winget | Out-Host
      Write-Host "WinAppDriver installation attempted; verify by running WinAppDriver.exe." -ForegroundColor Green
    } catch {
      Write-Warning "Failed to install WinAppDriver via winget. $_"
    }
  } else {
    Write-Warning "winget not found; install WinAppDriver manually from https://github.com/microsoft/WinAppDriver/releases."
  }
}

Ensure-Appium
Ensure-WinAppDriver

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

$DataArgs = @()
if (Test-Path $AssetsDir) {
  $DataSpec = "{0};{1}" -f $AssetsDir, $AssetsDirRel
  $DataArgs += @("--add-data", $DataSpec)
}
if (Test-Path $DataRoot) {
  foreach ($sub in @("scripts","images","results","logs")) {
    $src = Join-Path $DataRoot $sub
    if (Test-Path $src) {
      $rel = Join-Path $DataRootRel $sub
      $DataArgs += @("--add-data", ("{0};{1}" -f $src,$rel))
    }
  }
}
if (-not (Test-Path $UiSettingsPath) -and (Test-Path (Join-Path $DataRoot "ui_settings.json"))) {
  $UiSettingsPath = Join-Path $DataRoot "ui_settings.json"
}
if (Test-Path $UiSettingsPath) {
  $DataArgs += @("--add-data", ("{0};{1}" -f $UiSettingsPath, $UiSettingsRel))
}

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
  @DataArgs `
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

# -------- Automation manifest --------
$AutomationScript = Join-Path $Root "automation\export_automation_ids.py"
if (Test-Path $AutomationScript) {
  Write-Host "Exporting automation ID manifest..." -ForegroundColor Yellow
  try {
    & "$Py" $AutomationScript | Out-Host
  } catch {
    Write-Warning ("Automation manifest export failed: {0}" -f $_)
  }
}
$AutomationManifest = Join-Path $Root "automation\automation_ids.json"

# -------- Ensure runtime data dirs (OneDir) --------
if (-not $OneFile) {
  $AppDir = Split-Path -Parent $ExePath
  foreach ($d in @("scripts","images","results","logs")) {
    $p = Join-Path $AppDir $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null }
  }
}

# -------- Offline-friendly package bundle --------
$PackageRoot = Join-Path $DistDir ("{0}-Package" -f $AppName)
Remove-Item $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $PackageRoot | Out-Null

if ($OneFile) {
  Copy-Item $ExePath $PackageRoot -Force
  $AppBundleDir = $PackageRoot
} else {
  $ExeDir = Split-Path -Parent $ExePath
  $AppBundleDir = Join-Path $PackageRoot (Split-Path $ExeDir -Leaf)
  Copy-Item $ExeDir $AppBundleDir -Recurse -Force
}

foreach ($sub in @("scripts","images","logs")) {
  $src = Join-Path $DataRoot $sub
  if (Test-Path $src) {
    $dest = Join-Path $AppBundleDir $sub
    Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item $src $dest -Recurse -Force
  }
}

if (Test-Path $AutomationManifest) {
  Copy-Item $AutomationManifest (Join-Path $AppBundleDir "automation_ids.json") -Force
}

if (Test-Path $AssetsDir) {
  $assetsDest = Join-Path $AppBundleDir $AssetsDirRel
  Remove-Item $assetsDest -Recurse -Force -ErrorAction SilentlyContinue
  Copy-Item $AssetsDir $assetsDest -Recurse -Force
}

$resultsDest = Join-Path $AppBundleDir "results"
Remove-Item $resultsDest -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $resultsDest | Out-Null

$settingsDest = Join-Path $AppBundleDir "ui_settings.json"
$settingsSource = if (Test-Path $UiSettingsPath) { $UiSettingsPath } else { Join-Path $DataRoot "ui_settings.json" }
if (Test-Path $settingsSource) {
  Copy-Item $settingsSource $settingsDest -Force
} else {
  New-Item -ItemType File -Path $settingsDest -Force | Out-Null
}
$xlsmSrc = Join-Path $Root "ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm"
if (Test-Path $xlsmSrc) {
  Copy-Item $xlsmSrc (Join-Path $AppBundleDir (Split-Path $xlsmSrc -Leaf)) -Force
}

$readmeText = @"
UI Testing Package
==================

Contents
--------
- {0}\           : application files, automation manifest, and bundled dependencies
- ui_settings.json : default playback configuration (theme, timings, toggles)
- ENFIRE *.xlsm    : optional reference workbook for PASS/FAIL updates
- results\         : empty folder for bug drafts, diff images, and Excel exports
- logs\            : ui_testing.log persists run history per workstation

Before You Start
----------------
1. Ensure ENFIRE is installed on the target machine and that you can launch it manually.
2. Verify that the Windows account has permission to write to `%USERPROFILE%` (the installer copies files to the Desktop).
3. Optional but recommended: close any background automation tools that may conflict with global hotkeys (`p` / `F`).

Install & Launch
----------------
1. Copy the `{0}-Package` folder (or unzip `{0}-Package.zip`) to the target machine.
2. Recommended: run `Install_UI_Testing.bat` from the `{0}-Installer` folder (or the matching zip).  
   This creates `%USERPROFILE%\Desktop\UI_Testing`, copies the package, and drops a desktop shortcut.
   Manual alternative: run `{1}.exe` directly from inside `{0}-Package`.
3. Launch UI Testing via the desktop shortcut (or `{1}.exe`). Open the **Instructions** button in the toolbar for a full tour of the GUI.

Daily Workflow
--------------
- **Record New** captures AutomationIds, coordinates, keystrokes, and screenshots. Press `p` for checkpoints, `F` (or the Stop button) to finish.
- **Run Selected / Run All** replays tests and logs whether semantic automation, UIA search, or coordinates were used.
- **Automation Inspector** reveals the AutomationId/control type/name under the mouse pointer so you can confirm manifest coverage before recording.
- **Settings** lets you toggle automation modes, screenshot comparisons, normalize scripts, SSIM thresholds, and themes.
- Results flow into `data/results`, `data/logs`, and `results_summary.xlsx`. Failed screenshots produce bug drafts with cropped evidence.

Support
-------
- Logs: `%USERPROFILE%\Desktop\UI_Testing\data\logs\ui_testing.log`
- Scripts & images: `%USERPROFILE%\Desktop\UI_Testing\data\scripts` / `data\images`
- Packaging verification: each installer is built with `compileall` + `pytest -m semantic` preflight checks.
"@ -f $AppName, $AppName
Set-Content (Join-Path $PackageRoot "README.txt") -Value $readmeText -Encoding UTF8

$InstallerRoot = Join-Path $DistDir ("{0}-Installer" -f $AppName)
Remove-Item $InstallerRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $InstallerRoot | Out-Null
Copy-Item $PackageRoot (Join-Path $InstallerRoot ("{0}-Package" -f $AppName)) -Recurse -Force

$installScript = @"
@echo off
setlocal
set "TARGET=%USERPROFILE%\Desktop\{0}"
set "EXE_NAME={1}.exe"
set "PACKAGE_ROOT=%~dp0{0}-Package"
set "DESKTOP_LINK=%USERPROFILE%\Desktop\{1}.lnk"
echo Installing UI Testing to "%TARGET%"
if exist "%TARGET%" (
  echo Removing previous copy...
  rmdir /S /Q "%TARGET%"
)
mkdir "%TARGET%" >nul 2>&1
xcopy "%PACKAGE_ROOT%" "%TARGET%" /E /I /Y >nul
echo Creating desktop shortcut...
powershell -NoProfile -Command ^
  "$shell = New-Object -ComObject WScript.Shell; ^
   $shortcut = $shell.CreateShortcut('%DESKTOP_LINK%'); ^
   $shortcut.TargetPath = '%TARGET%\%EXE_NAME%'; ^
   $shortcut.WorkingDirectory = '%TARGET%'; ^
   $shortcut.Save()"
echo Installation complete. Launch via the desktop shortcut.
pause
"@ -f $AppName, $AppName
Set-Content (Join-Path $InstallerRoot "Install_UI_Testing.bat") -Value $installScript -Encoding ASCII

$PackageZip = Join-Path $DistDir ("{0}-Package.zip" -f $AppName)
try {
  if (Test-Path $PackageZip) { Remove-Item $PackageZip -Force }
  Compress-Archive -Path $PackageRoot -DestinationPath $PackageZip -Force
} catch {
  Write-Warning ("Failed to create package zip: {0}" -f $_)
}

$InstallerZip = Join-Path $DistDir ("{0}-Installer.zip" -f $AppName)
try {
  if (Test-Path $InstallerZip) { Remove-Item $InstallerZip -Force }
  Compress-Archive -Path $InstallerRoot -DestinationPath $InstallerZip -Force
} catch {
  Write-Warning ("Failed to create installer zip: {0}" -f $_)
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
Write-Host "Build complete." -ForegroundColor Green
$modeLabel = if ($OneFile) { "OneFile" } else { "OneDir" }
Write-Host ("Mode: {0}" -f $modeLabel) -ForegroundColor Cyan
Write-Host ("Executable:    {0}" -f (Get-Item $ExePath).FullName)
Write-Host ("Package dir:   {0}" -f $PackageRoot)
Write-Host ("Package zip:   {0}" -f $PackageZip)
Write-Host ("Installer dir: {0}" -f $InstallerRoot)
Write-Host ("Installer zip: {0}" -f $InstallerZip)
Write-Host ("Shortcut:      {0}" -f $ShortcutPath)
Write-Host ""
Write-Host "Re-run anytime; it only updates what changed."


