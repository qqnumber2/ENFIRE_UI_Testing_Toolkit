# UI Testing Toolkit

This repository packages an interactive Windows UI automation harness for ENFIRE workflows. It lets you:

- record pixel-perfect UI test scripts with optional AutomationID metadata
- replay selected tests in batch, collect screenshots, and mark pass/fail in the ENFIRE Excel test plan
- review results, preview diffs, and capture bug draft notes for failed runs

## Quick start

1. Clone or copy the repository to the target machine.
2. Open PowerShell in the project root and run:

   ```powershell
   .\setup_and_deploy.ps1 [-Offline] [-OneFile] [-Debug] [-ForceRebuild]
   ```

   (Prefer to double-click something? `setup_and_deploy.bat` is just a thin wrapper that forwards to the PowerShell entry point above.)

   With no flags the script creates a `.venv` virtual environment, installs dependencies from PyPI (including OpenCV for the animated background), builds the OneDir bundle, and prepares redistributable packages in `dist\`.

3. Launch `dist\UI_Testing-Package\UI_Testing.exe`, or run `dist\UI_Testing-Installer\Install_UI_Testing.bat` on a target machine for a hands-off install.

### Script options

```powershell
.\setup_and_deploy.ps1 [-Offline] [-OneFile] [-Debug] [-ForceRebuild]
```

- `-Offline` installs packages from `.\wheels\` (no internet required).
- `-OneFile` produces a single self-contained EXE (skips the side-by-side folders).
- `-Debug` keeps a console window attached to the UI for troubleshooting.
- `-ForceRebuild` wipes the existing `dist\` folder before rebuilding.

Only the PowerShell script is maintained; the batch wrapper exists purely as a convenience shim.

### Distribution artifacts

Every run refreshes the following inside `dist\`:

- `UI_Testing\` (or `UI_Testing.exe` when `-OneFile`): raw PyInstaller output.
- `UI_Testing-Package\` and `UI_Testing-Package.zip`: ready-to-copy runtime folder with scripts/images/settings.
- `UI_Testing-Installer\` and `UI_Testing-Installer.zip`: includes the package plus `Install_UI_Testing.bat` for a simple desktop deployment.
- A refreshed desktop shortcut pointing at the latest EXE.

Reuse the generated zip files for offline distribution; they contain everything needed for a fresh machine.

## GUI highlights

- **Toolbar toggles**
  - Ignore recorded delays enforces the default pacing between steps.
  - Use Automation IDs enables pywinauto / UIA lookups; turn it off for image-only playback.
  - Compare screenshots lets you disable image checkpoints when your scripts rely purely on AutomationId-based assertions.
  - Open Logs opens the latest ui_testing.log for quick inspection.
  - Settings (gear icon) opens a dialog where you can change theme, default delay, tolerance, and toggle automation/screenshot behaviour.
- **Available Tests panel** shows scripts as procedure/section/test (e.g. 4/1/1). The badge counter reflects the selection count and recolors with the current theme.
- **Instructions** now appear as notebook tabs (Overview, Recording, Playback, Results, Tips) and explain all major features and shortcuts.
- **Test plan integration**: after each run, the ENFIRE workbook receives a PASS/FAIL update on the matching sheet (procedure.section). A toast (and log fallback) confirms the update.

## Automation IDs & Semantic Assertions

- A build step now exports `automation_ids.json` from the ENFIRE solution so selectors stay in sync across runs. The manifest is bundled with the packaged EXE.
- Recorder collapses press/release pairs into single `click` actions (capturing `auto_id` / `control_type`) and omits empty fields, keeping JSON compact.
- Recorder automatically appends `assert.property` steps (using UI Automation text) for controls with AutomationIds, so new runs rely on semantic checks by default.
- Playback understands `assert.property` actions: provide an `auto_id`, optional `property` (defaults to `name`), an `expected` value, and optional `compare` mode (`equals`/`contains`). The player resolves the control via UI Automation and logs pass/fail without relying on screenshots.
- Screenshot checkpoints remain available, but you can toggle them off from the toolbar (or set `use_screenshots` in `ui_settings.json`) once a workflow is covered by semantic checks.

## Repository layout

```
ui_testing/
  app/          environment + settings loader
  automation/   recorder/player engines, action model, explorer helper, util
  services/     AI summariser, test-plan reporter
  ui/           Tk/ttk views, panels, dialogs, video background
  data/         scripts, images, logs, results, ui_settings.json
  tests/        (smoke tests / fixtures)
assets/         application icon + background.mp4
automation/     helper scripts (e.g., export automation IDs)
dist/           build outputs (created by setup_and_deploy.ps1)
external/       archived payloads (ignored)
```

## Animated background

If `assets/background.mp4` is present and OpenCV (`opencv-python`) is installed, the UI renders the video beneath the widgets with a subtle transparency overlay. If the asset or OpenCV is unavailable the app falls back to the standard static theme automatically.

## Test plan detection

At startup the app looks for an `.xlsm` workbook in the project root whose filename contains “Test Procedure”. When the file is found the log shows a “Detected test plan: …” message and subsequent runs push PASS/FAIL updates into that workbook. Replace the sample workbook in the root (or ship your own alongside the EXE) to wire in a different plan.

## Smoke test

Run a quick import/build sanity check with:

```powershell
python -m ui_testing.tests.smoke
```

It exercises `build_default_paths`, constructs/tears down the `TestRunnerApp`, and logs the script/image directories in use.

## Development tips

- Run python -m ui_testing.tests.smoke inside .venv to sanity-check GUI imports after changes.
- AutomationID lookups come from pywinauto; when disabled, playback falls back to recorded screen coordinates.
- The ENFIRE workbook is discovered automatically (*.xlsm in the app directory). Replace the sample plan with your own if needed.

