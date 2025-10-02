# UI Testing Toolkit

This repository packages an interactive Windows UI automation harness for ENFIRE workflows. It lets you:

- record pixel-perfect UI test scripts with optional AutomationID metadata
- replay selected tests in batch, collect screenshots, and mark pass/fail in the ENFIRE Excel test plan
- review results, preview diffs, and capture bug draft notes for failed runs

## Quick start

1. **Clone or copy the repository** to the target machine.
2. Open PowerShell in the project root and run:

   `powershell
   .\setup_and_deploy.ps1
   `

   The script creates a .venv virtual environment, installs dependencies, runs a smoke test, and builds a UI Testing.exe package inside dist/.

3. Launch dist/UI Testing-Package/UI Testing.exe (or the copy placed on your Desktop).

### Script options

`powershell
./setup_and_deploy.ps1 [-Python <path>] [-RecreateVenv] [-SkipBuild] [-AppName <name>]
`

- -RecreateVenv removes and rebuilds .venv from scratch.
- -SkipBuild only prepares the virtual environment (useful for development).
- -Python lets you point at a specific interpreter.
- -AppName controls the executable name.

The legacy setup_and_deploy.bat now forwards to the PowerShell script, so you can still double-click it if PowerShell scripts are allowed on your system.

## GUI highlights

- **Toolbar toggles**
  - Ignore recorded delays enforces the default pacing between steps.
  - Use Automation IDs enables pywinauto / UIA lookups; turn it off for image-only playback.
  - Open Logs opens the latest ui_testing.log for quick inspection.
- **Available Tests panel** shows scripts as procedure/section/test (e.g. 4/1/1). The badge counter reflects the selection count and recolors with the current theme.
- **Instructions** now appear as notebook tabs (Overview, Recording, Playback, Results, Tips) and explain all major features and shortcuts.
- **Test plan integration**: after each run, the ENFIRE workbook receives a PASS/FAIL update on the matching sheet (procedure.section). A toast (and log fallback) confirms the update.

## Repository layout

`
ui_testing/
  action.py, recorder.py, player.py    # recording / playback engines
  environment.py, settings.py          # path discovery & persisted options
  testplan.py                          # Excel reporter
  ui/                                  # Tk UI panels and helpers
  tests/                               # smoke test harness
results/, scripts/, images/            # default working directories
ENFIRE 11.0 Test Procedure ... .xlsm   # sample test plan detected automatically
`

## Development tips

- Run python -m ui_testing.tests.smoke inside .venv to sanity-check GUI imports after changes.
- AutomationID lookups come from pywinauto; when disabled, playback falls back to recorded screen coordinates.
- The ENFIRE workbook is discovered automatically (*.xlsm in the app directory). Replace the sample plan with your own if needed.

