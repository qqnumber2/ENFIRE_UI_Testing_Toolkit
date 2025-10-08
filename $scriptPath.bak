param(
    [string]$Python = "python",
    [switch]$RecreateVenv,
    [switch]$SkipBuild,
    [string]$AppName = "UI Testing"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venvPath = Join-Path $root '.venv'
if ($RecreateVenv -and (Test-Path $venvPath)) {
    Write-Host "Removing existing virtual environment..."
    Remove-Item $venvPath -Recurse -Force
}
if (!(Test-Path $venvPath)) {
    Write-Host "Creating virtual environment at $venvPath"
    & $Python -m venv $venvPath
}
$venvPython = Join-Path $venvPath 'Scripts/python.exe'

Write-Host "Upgrading pip and installing requirements..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt
& $venvPython -m pip install pyinstaller

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

    Copy-Item $exePath $packageDir

    foreach ($sub in 'scripts','images') {
        $source = Join-Path $root ('ui_testing/' + $sub)
        if (Test-Path $source) {
            Copy-Item $source (Join-Path $packageDir $sub) -Recurse
        }
    }
    $resultsDir = Join-Path $packageDir 'results'
    if (!(Test-Path $resultsDir)) { New-Item -ItemType Directory -Path $resultsDir | Out-Null }
    Copy-Item 'ui_testing/ui_settings.json' $packageDir -ErrorAction SilentlyContinue
    if (Test-Path 'ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm') {
        Copy-Item 'ENFIRE 11.0 Test Procedure 04 - Explosive Hazard Spot Report.xlsm' $packageDir -ErrorAction SilentlyContinue
    }

    Write-Host "Package created at: $packageDir"
    Write-Host ("Executable: {0}" -f (Join-Path $packageDir ("$AppName.exe")))
}
