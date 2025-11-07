# ENFIRE UI Testing Toolkit

An enterprise-grade automation workbench for exercising the ENFIRE desktop application. The toolkit records mouse/keyboard interactions (with semantic metadata, screenshots, and calibration-aware coordinates), replays them through deterministic pipelines, and emits the evidence (Excel, screenshots, logs, Allure attachments) needed to certify a release. The same codebase powers both a Tk/ttk GUI and a fully scriptable CLI so QA engineers, developers, and CI systems can share identical workflows.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Repository Map](#repository-map)
3. [Runtime Configuration & Settings](#runtime-configuration--settings)
4. [Coordinate Calibration System](#coordinate-calibration-system)
5. [GUI User Guide](#gui-user-guide)
6. [Command-Line Interface](#command-line-interface)
7. [Recording Pipeline](#recording-pipeline)
8. [Playback Pipeline](#playback-pipeline)
9. [Automation Manifest & Semantic Metadata](#automation-manifest--semantic-metadata)
10. [Artifacts, Reporting, and Evidence](#artifacts-reporting-and-evidence)
11. [Developer Guide (Architecture, Coding Standards, Tests)](#developer-guide-architecture-coding-standards-tests)
12. [ENFIRE Integration Checklist](#enfire-integration-checklist)
13. [Troubleshooting](#troubleshooting)
14. [Glossary](#glossary)

---

## Quick Start

### Prerequisites

- Windows 10/11, PowerShell 5.1+, Python 3.12 (or use `setup_and_deploy.ps1` which bootstraps everything)
- ENFIRE installed locally (or accessible via Appium/WinAppDriver)
- Optional: Allure CLI for report attachment, Node.js/NPM for Appium scenarios

### Install & Run (developer flow)

```powershell
git clone <repo>
cd ENFIRE_UI_Testing_Toolkit
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m ui_testing.gui             # launches the Tk GUI
```

### Record & Play (GUI)

1. Launch `python -m ui_testing.gui`
2. Click **Record New**, fill in Procedure/Section/Test names → press **Start Recording**
3. Interact with ENFIRE. Use the hotkeys:
   - `p` – capture screenshot (primary monitor, taskbar cropped)
   - `F` – stop recording
4. Recorded script lands in `ui_testing/data/scripts/<proc>/<section>/<test>.json` with screenshots under `../images/...`
5. Select the script in the left tree → **Run Selected** to replay

### Record & Play (CLI)

```powershell
# Capture a calibration profile (anchored to the current ENFIRE window)
python -m ui_testing.cli calibrate --name lab --set-default

# Headless recording (press F inside ENFIRE to stop)
python -m ui_testing.cli record 12_EBS/6/6.7_ATTACHMENTS_TAB --calibration lab

# Headless playback with semantic assertions + screenshots
python -m ui_testing.cli play 12_EBS/6/6.7_ATTACHMENTS_TAB --calibration lab --semantic --screenshots
```

---

## Repository Map

| Path | Description |
| --- | --- |
| `ui_testing/gui.py` | CLI entry point for the Tk/ttk GUI (`python -m ui_testing.gui`) |
| `ui_testing/ui/app.py` | `TestRunnerApp` – orchestrates Tk panels, settings, recorder/player lifecycles |
| `ui_testing/automation/recorder.py` | Recorder engine (pynput hooks, semantic metadata, calibration-aware actions) |
| `ui_testing/automation/player.py` | Player facade (uses locator, calibration, metrics, screenshot components) |
| `ui_testing/automation/player_components/` | Modular helpers (`metrics.py`, `screenshots.py`) |
| `ui_testing/automation/locator.py` | Manifest normalization + semantic metadata helper used by recorder/player/inspector |
| `ui_testing/app/configuration.py` | Runtime config loader (INI/env overrides) |
| `ui_testing/app/settings.py` | Persisted GUI settings dataclass (`ui_settings.json`) |
| `ui_testing/tools/calibration.py` | Capture/store calibration profiles and compute offsets |
| `ui_testing/cli/` | Headless CLI implementation (`python -m ui_testing.cli …`) |
| `ui_testing/tests/` | Pytest suites (unit/API/semantic) |
| `automation/export_automation_ids.py` | Standalone script to regenerate `automation_ids.json` from ENFIRE sources |
| `docs/refactor_cli_calibration_plan.md` | Living design doc for ongoing refactors (module split, CLI convergence) |

---

## Runtime Configuration & Settings

Every entry point (GUI, CLI, headless recorder/player) flows through two layers:

1. **Runtime overrides** – loaded via `ui_testing/app/configuration.py`
   - INI (default search order: `<repo>/ui_testing.ini`, `<repo>/automation/ui_testing.ini`, current working dir)
   - Env vars prefixed with `UI_TESTING_` (e.g., `UI_TESTING_THEME=darkly`, `UI_TESTING_DEFAULT_DELAY=0.75`)
2. **Persisted settings** – `ui_testing/data/ui_settings.json` (loaded/saved by `AppSettings`)

Common keys:

| Key | INI / Env Variable | Meaning |
| --- | --- | --- |
| Theme | `theme` / `UI_TESTING_THEME` | ttkbootstrap theme (e.g., `cosmo`, `flatly`) |
| Default delay | `default_delay` / `UI_TESTING_DEFAULT_DELAY` | Base pacing between recorded actions |
| Tolerance | `tolerance` / `UI_TESTING_TOLERANCE` | Screenshot diff tolerance (0–1%) |
| Ignore recorded delays | `ignore_recorded_delays` / `UI_TESTING_IGNORE_RECORDED_DELAYS` | Force constant pacing |
| Use AutomationIds | `use_automation_ids` / `UI_TESTING_USE_AUTOMATION_IDS` | Toggle semantic navigation |
| Use screenshots | `use_screenshots` / `UI_TESTING_USE_SCREENSHOTS` | Toggle screenshot checkpoints |
| Prefer semantic scripts | `prefer_semantic_scripts` / `UI_TESTING_PREFER_SEMANTIC` | Evaluate `assert.property` steps |
| Use SSIM | `use_ssim` / `UI_TESTING_USE_SSIM` | Enable Structural Similarity comparison |
| SSIM threshold | `ssim_threshold` / `UI_TESTING_SSIM_THRESHOLD` | Score (0.0–1.0) for SSIM pass/fail |
| Automation backend | `automation_backend` / `UI_TESTING_AUTOMATION_BACKEND` | `uia` or `appium` |
| Target regex | `target_app_regex` / `UI_TESTING_TARGET_APP_REGEX` | Regex used to attach to ENFIRE |
| Calibration profile | `calibration_profile` / `UI_TESTING_CALIBRATION_PROFILE` | Default profile name |
| Semantic wait/poll | `semantic_wait_timeout`, `semantic_poll_interval` | UIA wait intervals |

When running headless (CLI), the command-line arguments override both persisted settings and runtime config (e.g., `--semantic/--no-semantic`, `--screenshots/--no-screenshots`, `--calibration <name>`).

---

## Coordinate Calibration System

The toolkit treats calibration as a first-class concept:

1. `python -m ui_testing.cli calibrate --name lab --set-default` captures the ENFIRE top-left coordinate (window origin) and dimensions. Profiles are stored under `ui_testing/data/calibration/<name>.json`.
2. Recorder embeds both absolute (`x`, `y`) and relative (`rel_x`, `rel_y`, `rel_path`) coordinates when a profile is active. The JSON also records which profile was used.
3. Player resolves coordinates in three tiers:
   - **Relative**: if `rel_x`/`rel_y` (or `rel_path`) exist and the requested profile is available on the current machine, the player recreates the human click in the new coordinate space.
   - **Calibration offset**: if only absolute coordinates exist but a profile is active, the recorded position is shifted by `current_anchor - recorded_anchor`.
   - **Raw coordinates**: fallback when no calibration data exists.
4. Logs clearly indicate when calibration offsets are applied (e.g., `Playback: click at (120, 340) -> calibrated (140, 360)`), making it easy to diagnose environment drift.
5. CLI `--calibration` flag and GUI settings point to the same profile, so workflows remain consistent regardless of entry point.

---

## GUI User Guide

### Layout

| Region | Description |
| --- | --- |
| Toolbar | Record/Stop, Run Selected/Run All, Normalize, Semantic Helper, Automation Inspector, Instructions, Settings, Logs |
| Actions Panel | Real-time log of the recorder (mouse/keyboard events) |
| Tests Panel | Tree grouped by Procedure/Section/Test; context menu includes “Open”, “Reveal in Explorer”, “Delete” |
| Results Panel | Live replay output (status, notes, attachments) |
| Preview Panel | Baseline/test/diff/highlight images for screenshot checkpoints |
| Log Panel | Tails `ui_testing/data/logs/ui_testing.log` with severity filters |

### Recording Workflow

1. **Record New**
   - Enter Procedure/Section/Test names (these map to folders under `ui_testing/data/scripts`).
   - When prompted, confirm overwriting existing artifacts.
2. **Hotkeys**
   - `p`: screenshot (cropped to hide the Windows taskbar via `taskbar_crop_px`)
   - `F`: stop recorder (also refreshes the Available Tests tree)
3. **Semantic Metadata**
   - Recorder resolves AutomationIds via pywinauto (`Desktop().from_point`) and the manifest. Generic IDs (`Window`, `Pane`, `MainWindowControl`) are ignored.
   - When a semantic control is found, the recorder writes an accompanying `assert.property` action.
4. **Calibration**
   - If a profile is selected in settings, every mouse action stores `rel_x`, `rel_y`, and `calibration_profile` so the script remains portable.

### Playback Workflow

1. Select one or more scripts in the Tests tree.
2. Configure toggles (Ignore recorded delays, Use AutomationIds, Prefer semantic assertions, Compare screenshots, Use SSIM, Automation backend).
3. Click **Run Selected**. Results panel will show statuses; summary line includes semantic/UIA/coordinate counts and screenshot totals.
4. All artifacts (Excel, diff images, logs) land in `ui_testing/data/results/<script>/…`.

### Automation Inspector

Live overlay (pywinauto) that displays the AutomationId, control type, manifest group/name, and bounding rectangle under the mouse pointer. Useful for discovering missing AutomationIds before recording or when enhancing the manifest.

---

## Command-Line Interface

```
python -m ui_testing.cli --help
```

| Command | Description |
| --- | --- |
| `calibrate --name NAME [--set-default] [--overwrite]` | Capture ENFIRE window anchor and store (optionally set as default in `ui_settings.json`) |
| `calibration-list` | List saved calibration profiles with anchors & timestamps |
| `record SCRIPT_NAME [--calibration NAME]` | Headless recorder (press **F** inside ENFIRE to stop). Respects runtime settings + manifest |
| `play SCRIPT [SCRIPT ...] [--calibration NAME] [--semantic/--no-semantic] [--screenshots/--no-screenshots]` | Headless playback pipeline |

Both commands use the same paths as the GUI:

- Scripts: `ui_testing/data/scripts`
- Images: `ui_testing/data/images`
- Results: `ui_testing/data/results`

The CLI loads runtime overrides (`ui_testing.ini`, env vars) and merges them with `ui_settings.json`, so toggles behave identically across GUI and headless runs.

---

## Recording Pipeline

Key module: `ui_testing/automation/recorder.py`

### Dependencies

- `pynput` – global mouse/keyboard hooks
- `pyautogui` – screenshot capture
- `pywinauto` – AutomationId resolution (`Desktop().from_point`)
- `Pillow` – image handling

### Action structure (`ui_testing/automation/action.py`)

```python
Action(
    action_type="click",                # click, mouse_down, mouse_up, drag, key, hotkey, scroll, type, screenshot
    x=960, y=540,                       # absolute coordinates
    rel_x=120, rel_y=80,                # relative to calibration anchor (optional)
    rel_path=[[0,0],[120,40],...],      # relative drag path (optional)
    button="left",
    delay=0.327,
    auto_id="AppBarSave",
    control_type="Button",
    semantic={"group": "AppBarIds", "name": "AppBarSave", ...},
    property_name="name",
    expected="Save",
    calibration_profile="lab"
)
```

### Behavior

1. **Mouse events** – The recorder tracks down/up, accumulates drag paths (downsampled), and captures property snapshots for asserts.
2. **Keyboard events** – Printable characters are buffered, function keys/hotkeys emit discrete actions.
3. **Screenshots** – Stored as `0_000O.png` (baseline) / `0_000T.png` (test) with optional diff/highlight generated during playback.
4. **Semantic metadata** – `_make_semantic_metadata` consults `LocatorService` + manifest registry to populate `semantic` blocks.
5. **Calibration** – If an anchor is available, all actions record relative coordinates; the calibration profile is saved back to disk (allowing multiple machines to share a profile name and keep scripts portable).

---

## Playback Pipeline

Key module: `ui_testing/automation/player.py` (facade) + `player_components/metrics.py`, `player_components/screenshots.py`.

### Click Resolution Order

1. **Semantic session** (`AutomationSession.resolve_control`)
2. **UIA search** (`Desktop(backend="uia").window(...)`)
3. **Coordinates**
   - If `rel_x`/`rel_y` exist and the requested calibration profile is present → reconstruct absolute point.
   - Else apply the stored calibration offset (anchor difference).
   - Else use recorded absolute coordinates.

### Metrics

- `PlaybackMetrics` tracks counts/history for semantic/UIA/coordinate clicks and drag paths. Results panel and logs surface these to diagnose fallback causes.

### Screenshots

- `ScreenshotComparator` handles pixel diff + optional SSIM, saving `*_D.png` (difference) and `*_H.png` (highlight overlay).
- Tolerance: `config.diff_tolerance_percent` (defaults to `tolerance` setting). SSIM is optional and auto-disables when `scikit-image` is not installed.

### Artifacts generated per run

- Excel summary (`results/<script>/<timestamp>.xlsx`)
- Screenshot diff/highlight images
- Bug notes (if AI summarizer is configured)
- Flake statistics (`data/flake_stats.json`)
- Allure attachments (Excel + images) when enabled

### Headless vs GUI parity

The CLI and GUI construct the same `PlayerConfig`. The CLI simply bypasses the Tk front-end and streams status to stdout/logs, ensuring deterministic behavior regardless of entry point.

### Recorder & Player Configuration Reference

#### RecorderConfig (fields in `ui_testing/automation/recorder.py`)

| Field | Type | Description |
| --- | --- | --- |
| `scripts_dir`, `images_dir`, `results_dir` | `Path` | Storage locations for JSON, PNG, Excel artifacts |
| `script_name` | `str` | e.g., `12_EBS/6/6.7_ATTACHMENTS_TAB` (used to build directory structure) |
| `taskbar_crop_px` | `int` | Crops screenshot height to hide Windows taskbar |
| `gui_hwnd` | `Optional[int]` | HWND of the recorder window (used to ignore clicks on the GUI) |
| `always_record_text` | `bool` | Whether printable characters are always emitted as `type` actions |
| `default_delay` | `float` | Baseline delay between actions (when `Ignore recorded delays` is on) |
| `calibration_profile` | `Optional[str]` | Active profile name; stored on every action (`calibration_profile`) |
| `calibration_dir` | `Optional[Path]` | Where calibration JSON files live |
| `window_spec` | `Optional[WindowSpec]` | pywinauto spec for ENFIRE’s top-level window |
| `automation_manifest` | `Optional[dict]` | Preloaded manifest (falls back to on-disk JSON when `None`) |

#### PlayerConfig (fields in `ui_testing/automation/player.py`)

| Field | Type | Description |
| --- | --- | --- |
| `scripts_dir`, `images_dir`, `results_dir`, `taskbar_crop_px`, `wait_between_actions` | Identical to recorder |
| `diff_tolerance`, `diff_tolerance_percent` | `float` | Pixel diff threshold (% of mismatched pixels) |
| `use_default_delay_always` | `bool` | If `True`, recorded delays are ignored |
| `use_automation_ids`, `use_screenshots`, `prefer_semantic_scripts` | `bool` | Main playback toggles |
| `use_ssim`, `ssim_threshold` | `bool/float` | Structural Similarity settings |
| `automation_backend` | `str` | `"uia"` or `"appium"` |
| `appium_server_url`, `appium_capabilities` | `Optional[str/dict]` | Only used when backend is `appium` |
| `enable_allure` | `bool` | Controls Allure attachment helpers |
| `flake_stats_path` | `Optional[Path]` | JSON file that tracks flaky assertions |
| `state_snapshot_dir` | `Optional[Path]` | Where CSV state exports live (optional Great Expectations checks) |
| `semantic_wait_timeout`, `semantic_poll_interval` | `float` | UIA wait semantics |
| `calibration_profile`, `calibration_dir` | `Optional[str/Path]` | Same as recorder; used to resolve relative coords |
| `window_spec` | `Optional[WindowSpec]` | ENFIRE window spec (defaults to `DEFAULT_WINDOW_SPEC`) |

When writing custom tooling (e.g., script that pre-processes JSON actions), refer to these dataclasses to ensure compatibility with the GUI/CLI.

---

## Automation Manifest & Semantic Metadata

- Manifest path: `ui_testing/automation/manifest/automation_ids.json`
- Regenerate via:
  ```powershell
  python automation/export_automation_ids.py
  # or more advanced options:
  python -m ui_testing.tools.automation_ids.export_ids --cs-root external/enfire/... --output ui_testing/automation/manifest/automation_ids.json
  ```
- `LocatorService` normalizes the manifest into `groups` + lookup dictionaries, filters generic AutomationIds, stores descriptions/control types, and provides helper APIs (`contains`, `manifest_entry`, `semantic_metadata`).
- Recorder + player + automation inspector all peg off this service, guaranteeing consistent behavior across components.

---

## Artifacts, Reporting, and Evidence

| Artifact | Location | Description |
| --- | --- | --- |
| Scripts | `ui_testing/data/scripts/<proc>/<section>/<test>.json` | Recorded action sequences (with semantic & calibration metadata) |
| Screenshots | `ui_testing/data/images/<proc>/<section>/<test>/0_000O.png` etc. | Baseline/test images and diff/highlight outputs |
| Results | `ui_testing/data/results/<script>/<timestamp>/` | Excel summary, JSON logs, bug notes |
| Logs | `ui_testing/data/logs/ui_testing.log` | Rotating log captured by the GUI (also viewable via in-app Log panel) |
| Flake stats | `ui_testing/data/flake_stats.json` | Aggregated failures per script/assertion |
| Calibration profiles | `ui_testing/data/calibration/<name>.json` | Anchors for coordinate normalization |

When Allure is enabled (toggle in Settings or CLI), each failing checkpoint attaches the relevant evidence (Excel, screenshots, diff/highlight, flake stats) so CI pipelines can display everything without remoting into the test VM.

---

## Settings Reference (GUI Toggles & Fields)

| Control | Stored In | Description |
| --- | --- | --- |
| Theme dropdown | `AppSettings.theme` | ttkbootstrap theme |
| Default delay | `default_delay` | Seconds between actions when “Ignore recorded delays” is enabled |
| Screenshot tolerance slider | `tolerance` | Pixel diff threshold |
| Ignore recorded delays | `ignore_recorded_delays` | Force `default_delay` everywhere |
| Use Automation IDs | `use_automation_ids` | Enables semantic navigation |
| Prefer semantic assertions | `prefer_semantic_scripts` | Executes inline `assert.property` actions |
| Compare screenshots | `use_screenshots` | Toggle screenshot checkpoints |
| Use SSIM | `use_ssim` | Enables structural similarity; threshold stored in `ssim_threshold` |
| Automation backend | `automation_backend` | `"uia"` (pywinauto) or `"appium"` |
| Target application regex | `target_app_regex` | pywinauto attach filter for ENFIRE window |
| Calibration profile | `calibration_profile` | Name from `ui_testing/data/calibration` (CLI `--set-default` updates this too) |
| Semantic wait timeout / poll interval | `semantic_wait_timeout`, `semantic_poll_interval` | Sensible defaults: 1.0s and 0.05s |

All settings are persisted to `ui_testing/data/ui_settings.json` and merged with runtime overrides at startup.

---

## Developer Guide (Architecture, Coding Standards, Tests)

### Architecture Snapshot

- **UI layer** (`ui_testing/ui/*`): Tk/ttk panels, dialogs, background animation, notes, settings dialog.
- **Automation layer** (`ui_testing/automation/*`):
  - `recorder.py` – handles pynput hooks, semantic registry access, calibration-aware action serialization.
  - `player.py` – orchestration (instantiates locator, calibration, metrics, screenshot comparator, Explorer integration, flake tracker, state snapshots).
  - `player_components/metrics.py` – semantics/UIA/coordinate stats.
  - `player_components/screenshots.py` – diff/SSIM/highlight logic.
  - `locator.py` – manifest normalization/lookup, generic ID filtering.
  - `driver/` – pywinauto session helpers (`AutomationSession`, `WindowSpec`, caching).
- **Tooling**:
  - `ui_testing/cli` – single entry point for headless automation (record/play/calibrate).
  - `ui_testing/tools/calibration.py` – profile capture, load/save, offset computations.
  - `automation/export_automation_ids.py` – manifest generation from ENFIRE C# sources.
- **Docs**:
  - `README.md` (this file) – user/dev guide.
  - `docs/refactor_cli_calibration_plan.md` – living design doc for upcoming refactors.

### Coding Standards

- Python 3.12, follow `pyproject.toml` (black, isort, ruff, mypy).
- Prefer dataclasses for configs/structs (`Action`, `RecorderConfig`, `PlayerConfig`, `CalibrationProfile`).
- Keep modules ASCII unless there’s a compelling reason otherwise.
- Extract reusable logic into helper modules (e.g., metrics, screenshots) so CLI/GUI share the same code paths.
- Use dependency injection / `try/except` imports to keep packaged EXEs resilient when optional dependencies are missing.

### Testing

- Unit tests: `python -m pytest ui_testing/tests/unit`
  - `test_config/` – runtime config loader
  - `test_locator/` – manifest normalization semantics
  - `test_calibration/` – profile serialization + offset math
- Semantic tests: `pytest -m semantic --maxfail=1` (requires pywinauto + ENFIRE)
- Packaging script (`setup_and_deploy.ps1`) runs `compileall` + `pytest -m semantic` before building the PyInstaller exe.

### Roadmap (see `docs/refactor_cli_calibration_plan.md`)

- Extract playback executor + screenshot pipeline into dedicated modules (so CLI and GUI call the same entry point).
- Modularize recorder (event hooks, semantic metadata, action serialization).
- Continue to build out CLI options (e.g., JSON result summaries, manifest validation commands).
- Expand unit coverage to include the new executor and screenshot components.
- Investigate advanced scripts (e.g., multi-script playlists, conditional waits) once the executor is extracted.
- Provide hooks for custom assertions (user-defined functions triggered by manifest metadata).

---

## ENFIRE Integration Checklist

1. **AutomationIds**
   - When new controls are added to ENFIRE, declare AutomationIds in `Enfire.EsriRuntime.Wpf/Utility/AutomationIds/*.cs` and reference them in XAML as `{x:Static automation:FooIds.Bar}`.
   - Regenerate `automation_ids.json` and commit the new manifest alongside UI changes.
2. **State Reset Hooks**
   - Expose lightweight entry points (command-line flags, IPC, dedicated menu item) that reset ENFIRE to a known state. The CLI can call these between runs to minimize flaky behavior.
3. **Test Data**
   - Provide deterministic datasets (e.g., sample workspaces) that can be restored before each run.
4. **Calibration**
   - Capture a profile on the target hardware (per lab). Share the `ui_testing/data/calibration/<name>.json` across machines so coordinate scripts stay reliable.
5. **Permissions**
   - Ensure UI Testing runs with the same elevation context as ENFIRE (pywinauto cannot interact with higher-privilege windows).

---

## Troubleshooting

| Symptom | Likely Cause / Fix |
| --- | --- |
| GUI fails to launch (`SyntaxError`, packaging mismatch) | Reinstall dependencies (`pip install -r requirements.txt`), ensure `pywinauto` and `pyautogui` are installed, verify `ui_testing/app/settings.py` is valid JSON |
| CLI complains about calibration profile | Run `python -m ui_testing.cli calibrate --name <profile>` on the current machine or remove `calibration_profile` from `ui_settings.json` |
| Semantic clicks fall back to coordinates | Verify `Use Automation IDs` + `Prefer semantic assertions` toggles, `automation_ids.json` is up-to-date, ENFIRE window title matches regex, and UI Testing matches ENFIRE elevation |
| Recorder ignores clicks | Ensure the recorder window isn’t in focus (GUI suppresses clicks when you click on itself), confirm `pynput` hooks are functioning (some antivirus tools block global hooks) |
| Screenshots always fail | Check `ui_testing/data/images/<script>` for baseline (`*_O.png`). Re-record screenshots or disable screenshot comparisons temporarily |
| pywinauto errors (`Access is denied`) | Run both ENFIRE and UI Testing as admin (or both as standard user). UIA requires matching elevation |
| Packaging script fails | Review `build_log.txt`, rerun `setup_and_deploy.ps1 -ForceRebuild`, ensure semantic tests pass (`pytest -m semantic --maxfail=1`) |

---

## Glossary

- **AutomationId manifest** – JSON describing known controls (`ui_testing/automation/manifest/automation_ids.json`)
- **Semantic assertion** – `assert.property` action generated when the recorder resolves a semantic control
- **Calibration profile** – Captured anchor describing ENFIRE’s window origin/size; used to normalize coordinates
- **Checkpoint** – Validation step (assert/property or screenshot) recorded in the Results panel & Excel summary
- **Flake tracker** – JSON stats for flaky assertions (`ui_testing/data/flake_stats.json`)
- **UIA** – Microsoft UI Automation backend (used via pywinauto)
- **Appium** – Alternative automation backend (WinAppDriver flavor) for remote or sandboxed sessions
- **SSIM** – Structural Similarity Index Measure (0–1), used to compare screenshot similarity in a perceptual way

---

With this guide, a QA engineer or developer can install, operate, extend, and maintain the ENFIRE UI Testing Toolkit with confidence. For deeper architectural notes and refactor plans, consult `docs/refactor_cli_calibration_plan.md` and keep the `README` in sync with ongoing work. Happy testing!
