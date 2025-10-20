# UI Testing Toolkit

An automation workbench for ENFIRE that records rich UI interactions, replays them through multiple validation channels, and ships as a turnkey desktop app. The toolkit captures semantic automation metadata, screenshots, and runtime diagnostics so teams can regression-test ENFIRE without sacrificing fidelity.

---

## Table of Contents

1. [Purpose and Scope](#purpose-and-scope)
2. [Feature Highlights](#feature-highlights)
3. [Architecture Overview](#architecture-overview)
4. [Technology Stack](#technology-stack)
5. [Repository Layout](#repository-layout)
6. [Data Lifecycle](#data-lifecycle)
7. [Validation Modes](#validation-modes)
8. [Results & Reporting](#results--reporting)
9. [Build & Distribution Workflow](#build--distribution-workflow)
10. [Using the GUI](#using-the-gui)
11. [Developer Quick Start](#developer-quick-start)
12. [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)
13. [Glossary & Further Reading](#glossary--further-reading)

---

## Purpose and Scope

The toolkit exists to automate ENFIRE test procedures without locking the team into a single validation strategy. It supports:

- Manual recording of exploratory or scripted runs.
- Semantic validation via AutomationIds (pywinauto UIA backend).
- Coordinate-based playback when semantic metadata is unavailable.
- Screenshot comparison and SSIM-based visual diffs.
- Automated summarisation of failures and flake tracking.
- Turnkey packaging so QA can install and run tests on disconnected laptops.

The project targets Windows 10/11 workstations. Packaging, dependency resolution, and verification are fully scripted to minimise manual setup (“plug and play” installs).

---

## Feature Highlights

- **Recorder** captures clicks, drags, key presses, screenshots, and semantic metadata. It filters out non-actionable AutomationIds (for example, `"Window"` and `"Pane"`) and cross-references controls against the ENFIRE manifest to keep scripts resilient.
- **Player** replays scripts with a deterministic delay model and a three-tier targeting strategy (semantic session → UIA search → raw coordinates). Each run reports how many clicks were executed in each mode.
- **Semantic Helper** retrofits older scripts with assert-based validations that leverage the manifest without losing screenshot checkpoints.
- **Bug note generator** diff analyses failing screenshots, produces cropped evidence, and writes structured markdown notes alongside heuristic recommendations.
- **Packaging pipeline** (PowerShell) creates a virtual environment, installs pinned dependencies, runs `compileall` and `pytest -m semantic`, bundles the PyInstaller build, and emits redistributable zips with deployment instructions.
- **Allure & flake integration** tracks flaky assertions per script and attaches run artifacts (Excel summaries, screenshot diffs) to test reports when enabled.

---

## Architecture Overview

```
┌───────────────────────────────────────────────────────────────────┐
│                         UI Testing Toolkit                        │
├───────────────────────┬───────────────────────────────────────────┤
│ UI layer (tk/ttk +    │ Automation layer (Python)                 │
│ ttkbootstrap)         │                                           │
│  • actions_panel      │  • recorder.py                            │
│  • tests/results/log  │  • player.py                              │
│  • preview + video    │  • automation.driver.* (pywinauto shim)   │
│  • settings dialog    │  • semantic.* (contexts, manifests)       │
│  • instructions tabs  │  • services.ai_summarizer (bug notes)     │
│  • hotkeys + helpers  │  • reporting.allure_helpers               │
├───────────────────────┴───────────────────────────────────────────┤
│ Data folders: scripts/, images/, results/, logs/, automation_ids  │
│ Packaging: setup_and_deploy.ps1 → PyInstaller, installer zip      │
└───────────────────────────────────────────────────────────────────┘
```

- **Recorder ↔ Player** communicate via JSON action files and PNG artefacts stored in `ui_testing/data`.
- **Automation manifest** (`automation/manifest/automation_ids.json`) maps AutomationIds to semantic group/name and control types exported from the ENFIRE solution.
- **SemanticContext** caches pywinauto sessions and manifest lookups, giving both recorder and player consistent automation access.
- **Packaging** lives outside of the UI code. Invoking `setup_and_deploy.ps1` is the canonical way to set up environments, run verification, and ship binaries.

---

## Technology Stack

| Library / Tool | Purpose |
| --- | --- |
| `pyautogui` | Low-level mouse/keyboard interaction and screenshot capture. |
| `pynput` | Global hotkey listeners (recording stop, screenshot capture). |
| `pywinauto` | UI Automation (UIA) backend for locating controls by AutomationId. |
| `ttkbootstrap` | Themed widgets on top of Tkinter. |
| `Pillow (PIL)` | Image processing for screenshots and diff crops. |
| `numpy` | Efficient array manipulation for diff masks. |
| `scikit-image` / `opencv-python(-headless)` | SSIM comparisons and background video playback. |
| `pandas` | Data summarisation for scripts and results. |
| `openpyxl` | Excel result export (results_summary.xlsx). |
| `great_expectations` | State snapshot validations and data-quality checks. |
| `sumy` | Lightweight text summarisation for bug drafts (optional). |
| `pytest` / `pytest-xdist` | Test automation; `pytest -m semantic` validates semantic helpers. |
| `allure-pytest` | Optional reporting – attaches Excel, screenshots, and flake stats. |
| `PyInstaller` | Builds the distributable Windows executable. |
| `PowerShell` (`setup_and_deploy.ps1`) | Automates environment provisioning and packaging. |

All versions are pinned in `requirements.txt` to guarantee deterministic builds.

---

## Repository Layout

```
ui_testing/
  app/                # Settings loader, persisted config dataclasses
  automation/         # Recorder/player engines, helpers, semantic support
    driver/           # pywinauto session shims (AutomationSession)
    manifest/         # Exported AutomationId metadata
    reporting/        # Allure integration
    semantic/         # Context, registry, screen objects
    services/         # AI summariser, test-plan integration
    vision/           # SSIM comparison helpers
  data/
    scripts/          # Recorded JSON scripts (procedure/section/test folders)
    images/           # Screenshot checkpoints (O/T naming)
    results/          # Bug drafts, diff crops, Excel output
    logs/             # ui_testing.log + historical runs
  tests/              # Smoke, semantic, and data-quality suites
assets/               # Icons, video background
automation/           # Ancillary scripts (manifest exporter)
dist/                 # Build output (created by setup_and_deploy.ps1)
setup_and_deploy.ps1  # Packaging entry point
README.md             # You are here
```

---

## Data Lifecycle

### Recording Pipeline

1. Operator selects **Record New** and provides procedure/section/test metadata.
2. `recorder.py` starts listeners for mouse/keyboard, resolves the current ENFIRE window, and loads the automation manifest.
3. Every click is analysed:
   - If a manifest control encloses the pointer, its AutomationId + group/name metadata are recorded.
   - Otherwise, the recorder stores raw coordinates only.
4. Keystrokes are buffered and flushed as `type` actions; `p` captures screenshot checkpoints (cropped to hide the Windows taskbar).
5. Companion semantic `assert.property` actions are generated for manifest-backed clicks, keeping scripts self-validating.
6. Output is written to `data/scripts/...json`, with PNG assets under `data/images/...`.

### Playback Pipeline

1. Player loads JSON actions and the matching manifest.
2. For each click:
   - Attempt semantic session resolution (`AutomationSession.resolve_control`).
   - Fall back to a UIA lookup via Desktop().
   - Finally, use recorded coordinates.
3. Assertions use semantic metadata first (prefer manifest group/name), fall back to UIA property reads, or report “not found” failures.
4. Screenshot checkpoints compare test vs. golden images (optional SSIM). Failures attach diff/highlight artefacts and raise bug drafts.
5. Each run appends to the results grid and rewrites Excel/flake stats.

---

## Validation Modes

- **Semantic:** Manifest-backed AutomationIds resolved through the cached pywinauto session. Logged as `Playback(Semantic)`; the run summary reports how many clicks used this path.
- **UIA Search:** Direct lookup via `Desktop(backend="uia")` when the semantic session is unavailable or raises. Logged as `Playback(UIA)`.
- **Coordinate:** Fallback when no manifest entry exists. Logged as `Playback: click at ... [coordinate fallback]`.
- **Screenshot Differences:** Controlled via the “Compare screenshots” toggle. Produces diff and highlight PNGs plus SSIM percentages when enabled.
- **State Snapshots:** Optional hook running `ui_testing/automation/state_snapshots.validate_exports` to validate exported CSVs with Great Expectations.
- **Semantic Assertions:** Assert the text/value/enabled state of manifest controls. Automatically suppressed for non-manifest AutomationIds to avoid false positives.

---

## Results & Reporting

- **Results grid** displays each checkpoint with timestamp, diff percentage, and pass/fail status. Summary rows include validation counts and click mode breakdowns.
- **Excel workbook** (`results_summary.xlsx`) consolidates assertions/screenshot counts per procedure/section/test. Outdated rows are pruned before new results append.
- **Bug drafts** (markdown + cropped PNGs) are generated for failing screenshot checkpoints. Heuristics propose likely causes and remediation tips.
- **Flake statistics** capture repeated failures per script + assertion when `flake_stats_path` is configured, aiding triage of intermittent issues.
- **Allure attachments** (optional) upload Excel summaries, screenshot artefacts, and flake stats for CI/CD visibility.
- **Logs** live in `data/logs/ui_testing.log` and include semantic fallbacks, AutomationId mismatches, and packaging diagnostics.

---

## Build & Distribution Workflow

1. **Run `setup_and_deploy.ps1`** from the repo root. Parameters:
   - `-Offline`: install from `.\wheels\` instead of PyPI.
   - `-OneFile`: build a single-file EXE (PyInstaller `--onefile`).
   - `-Debug`: keep a console attached to the GUI for troubleshooting.
   - `-ForceRebuild`: delete existing `dist\` output before building.
2. The script performs:
   - Virtual environment creation (`.venv`) if missing.
   - Deterministic dependency installation (pinned `requirements.txt`).
   - Preflight verification: `python -m compileall ui_testing` and `python -m pytest ui_testing/tests -m semantic --maxfail=1`.
   - PyInstaller build (default: one-folder).
   - Packaging into `dist\UI_Testing-Package\` and `dist\UI_Testing-Installer\` + matching zip archives.
   - Generation of a desktop shortcut pointing at the fresh EXE.
3. **Deploy** by copying `UI_Testing-Package` or running `Install_UI_Testing.bat` from the installer folder. The latter copies the package to `%USERPROFILE%\Desktop\UI_Testing` and makes a shortcut.
4. **Usage instructions** are bundled as `README.txt` inside each package to guide offline installs.

---

## Using the GUI

1. **Launch** `UI_Testing.exe` (or use the packaged shortcut). The app automatically loads the most recent settings (`ui_settings.json`) and scans `data/scripts` for available tests.
2. **Toolbar Controls**
   - Record New / Stop Recording (mouse/keyboard capture).
   - Run Selected / Run All (queue execution).
   - Normalize (run, choose, clear).
   - Semantic Helper (retrofit selected scripts).
   - **Automation Inspector** (new): opens a live overlay that displays AutomationId, control type, name, framework, and manifest group/name for the element under the mouse pointer—perfect for discovering new AutomationId opportunities in ENFIRE.
   - Instructions / Settings / Logs quick links.
3. **Playback Toggles & Backends** (toolbar + Settings dialog):
   - **Ignore Recorded Delays** – replace every recorded delay with the default pacing value. Disable this to replay human think-time exactly as captured.
   - **Use Automation IDs** – enable semantic navigation. When checked, the player resolves controls via the manifest/pywinauto session before falling back to coordinates.
   - **Prefer Semantic Assertions** – load `*.semantic.json` variants that include assert.property steps; uncheck to stick with the original coordinate-only recordings.
   - **Compare Screenshots** – toggle visual diffs. Pair with semantic playback to mix assertions and image validation as needed.
   - **Use SSIM** – switch screenshot comparisons to Structural Similarity (SSIM) instead of raw pixel diff. Combined with the **SSIM Threshold** slider (0.0–1.0) this handles minor rendering drift; 1.0 requires identical images.
   - **Automation Backend** – choose **UIA** (pywinauto + Microsoft UI Automation, default) or **Appium** (WinAppDriver/Appium Server). UIA is lightweight and works when ENFIRE exposes AutomationIds locally. Appium is useful for remote sessions or when the test rig connects to a dedicated WinAppDriver instance.
   - Theme, normalize script, and other environment toggles live in the same dialog.
4. **Available Tests Tree**: organised as procedure/section/test; right-click nodes to open, reveal on disk, or delete scripts/images/results.
5. **Results Panel**: live view of checkpoints; summary row includes counts and semantic/UIA/coordinate distribution.
6. **Preview Panel**: displays baseline/test/diff/highlight images for screenshot checkpoints.
7. **Log Panel**: tail of `ui_testing.log`. Double-click to open full file or use `Ctrl+L` for the standalone viewer.
8. **Instructions**: the in-app “Instructions” button opens a notebook that documents toolbar buttons, validation logic, packaging flow, and keyboard shortcuts.

---

## Developer Quick Start

1. **Prerequisites**: Windows 10/11, PowerShell 5.1+, Python 3.12 (or run `setup_and_deploy.ps1` which bootstraps everything), optional Allure CLI for report attachment, Node.js + npm if Appium support is required.
2. **Clone & Install**:
   ```powershell
   git clone <repo>
   cd ENFIRE_UI_Testing_Toolkit
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. **Run Tests**:
   ```powershell
   python -m compileall ui_testing
   python -m pytest ui_testing/tests -m semantic --maxfail=1
   python -m ui_testing.tests.smoke  # optional GUI smoke
   ```
4. **Launch GUI** (dev mode):
   ```powershell
   python -m ui_testing.gui
   ```
5. **Update manifest** when ENFIRE adds AutomationIds by regenerating `automation_ids.json` (see `automation/` helper scripts) and re-running the Semantic Helper on existing scripts.

---

## Troubleshooting & Diagnostics

- **AutomationIds appear as “Window”**: ensure `automation/manifest/automation_ids.json` is up to date. The recorder intentionally discards generic ids; if none remain, playback reverts to coordinates. See the log for `Semantic metadata skipped` messages.
- **Semantic playback falls back to coordinates**: confirm `Use Automation IDs` and `Prefer semantic assertions` toggles are enabled, pywinauto is installed, and the ENFIRE window matches the regex configured in Settings.
- **Bug note generation reports missing files**: check that the underlying screenshots exist (e.g., `images/.../0_000O.png`). The summariser skips drafts when evidence is absent.
- **Packaging fails preflight**: review the console output for compile/test errors. Fix the underlying issue before distributing the installer.
- **Appium backend**: if switching to Appium in Settings, make sure `appium` is available on PATH and the capabilities JSON is configured (see `docs/tools/appium_capabilities.py`). The semantic context will fall back to UIA if attachment fails.
- **Upgrade Python dependencies**: update `requirements.txt` with pinned versions, regenerate `.\wheels\` if offline installs are required, then rerun `setup_and_deploy.ps1`.

---

## Glossary & Further Reading

- **AutomationId manifest**: JSON exported from the ENFIRE codebase describing control identifiers. Located at `ui_testing/automation/manifest/automation_ids.json`.
- **Semantic script**: `*.semantic.json` file containing the same actions as the baseline script but decorated with semantic assertions.
- **Checkpoint**: Individual validation step (assertion or screenshot) recorded in the Results grid and Excel summary.
- **State snapshot**: CSV export validated by Great Expectations to confirm non-UI state (if configured).
- **Flake Tracker**: JSON statistics per script/action stored at the configured `flake_stats_path` (defaults to `data/flake_stats.json`).
- **UIA**: Microsoft’s UI Automation framework; pywinauto’s UIA backend is used for in-process semantic control resolution.
- **Appium**: Cross-platform automation server (WinAppDriver flavour) used when tests must drive ENFIRE through a remote or sandboxed session. Configure server URL and capabilities in Settings.
- **SSIM (Structural Similarity Index Measure)**: Image metric that captures perceived visual differences (luminance/contrast/structure) rather than pixel identity. Thresholds closer to 1.0 are stricter.

For ENFIRE-specific AutomationId definitions, refer to the upstream `MapControlIds.cs`, `AppBarIds.cs`, and related files within the ENFIRE repository (mirrored under `external/enfire/...`). Those constants feed the manifest used by this toolkit.

---

With the documentation above—even an entry-level engineer can clone the repository, understand the architectural decisions, reproduce the build, and confidently operate the recording/playback workflows. Dive into the in-app Instructions for a guided tour once the GUI is running. Happy testing!
