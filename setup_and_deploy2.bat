param(
    [string]$Python = "python",
    [switch]$RecreateVenv,
    [switch]$SkipBuild,
    [switch]$RefreshDependencies,
    [string]$VenvDir = "venv",
    [string]$AppName = "UI Testing"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPath = Join-Path $root $VenvDir
if ($RecreateVenv -and (Test-Path $venvPath)) {
    Write-Host "Removing existing virtual environment..."
    Remove-Item $venvPath -Recurse -Force
}
if (!(Test-Path $venvPath)) {
    if (-not $RecreateVenv) {
        Write-Host "Virtual environment not found at $venvPath. Creating a new one..."
    }
    & $Python -m venv $venvPath
}
$venvPython = Join-Path $venvPath 'Scripts/python.exe'
if (!(Test-Path $venvPython)) {
    throw "Virtual environment appears corrupted. Expected interpreter at $venvPython"
}

if ($RefreshDependencies) {
    Write-Host "Refreshing dependencies inside virtual environment..."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    & $venvPython -m pip install pyinstaller
} else {
    Write-Host "Using existing virtual environment dependencies (pass -RefreshDependencies to reinstall)."
    try {
        & $venvPython -m PyInstaller --version | Out-Null
    } catch {
        throw "PyInstaller is not available in the virtual environment. Re-run with -RefreshDependencies while online."
    }
}

if (-not $SkipBuild) {
    Write-Host "Running smoke test..."
    & $venvPython -m ui_testing.tests.smoke

    $distRoot = Join-Path $root 'dist'
    $buildRoot = Join-Path $root 'build'
    Remove-Item $distRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $buildRoot -Recurse -Force -ErrorAction SilentlyContinue

    $pyInstallerArgs = @(
        '--noconfirm',
        '--clean',
        '--windowed',
        '--name', $AppName,
        '--collect-data', 'ttkbootstrap',
        '--collect-metadata', 'ttkbootstrap',
        '--hidden-import', 'ui_testing.dialogs',
        '--hidden-import', 'ui_testing.environment',
        '--hidden-import', 'ui_testing.testplan',
        '--hidden-import', 'ui_testing.settings',
        '--hidden-import', 'ui_testing.ui.notes',
        '--hidden-import', 'openpyxl',
        '--hidden-import', 'pynput.keyboard',
        '--hidden-import', 'pynput.mouse',
        '--hidden-import', 'pywinauto',
        '--hidden-import', 'pywinauto.controls',
        '--hidden-import', 'pywinauto.win32functions',
        '--hidden-import', 'pywinauto.win32structures',
        '--hidden-import', 'pyautogui',
        '--hidden-import', 'numpy',
        '--hidden-import', 'PIL.Image',
        '--hidden-import', 'PIL.ImageTk',
        '--hidden-import', 'PIL.ImageChops',
        '--add-data', 'ui_testing\ui_settings.json;ui_testing',
        '--add-data', 'ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm;.'
    )

    Write-Host "Building executable via PyInstaller..."
    & $venvPython -m PyInstaller @pyInstallerArgs 'ui_testing\gui.py'

    $exePath = Join-Path $distRoot ("$AppName.exe")
    if (!(Test-Path $exePath)) {
        throw "PyInstaller did not produce expected executable: $exePath"
    }

    $packageDir = Join-Path $distRoot ("$AppName-Package")
    Remove-Item $packageDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $packageDir | Out-Null

    Copy-Item $exePath $packageDir -Force

    foreach ($sub in 'scripts', 'images') {
        $source = Join-Path $root ('ui_testing/' + $sub)
        if (Test-Path $source) {
            Copy-Item $source (Join-Path $packageDir $sub) -Recurse -Force
        }
    }
    $resultsDir = Join-Path $packageDir 'results'
    if (!(Test-Path $resultsDir)) {
        New-Item -ItemType Directory -Path $resultsDir | Out-Null
    }
    Copy-Item 'ui_testing/ui_settings.json' $packageDir -Force -ErrorAction SilentlyContinue
    if (Test-Path 'ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm') {
        Copy-Item 'ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm' $packageDir -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Package created at: $packageDir"
    Write-Host ("Executable: {0}" -f (Join-Path $packageDir ("$AppName.exe")))

    $desktop = [Environment]::GetFolderPath('Desktop')
    if ($desktop) {
        $desktopPackage = Join-Path $desktop ("$AppName-Package")
        if (!(Test-Path $desktopPackage)) {
            New-Item -ItemType Directory -Path $desktopPackage -Force | Out-Null
        }
        Copy-Item (Join-Path $packageDir '*') $desktopPackage -Recurse -Force
        Write-Host "Desktop package refreshed at: $desktopPackage"
    } else {
        Write-Warning "Could not resolve Desktop path; skipping desktop package copy."
    }
}
