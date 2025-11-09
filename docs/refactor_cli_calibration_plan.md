# Toolkit Modernisation: CLI, Calibration, and Engine Refactor

## Goals

1. Provide first-class command-line tooling so automation can be scripted (record, play, inspect) without launching the GUI.
2. Introduce coordinate calibration so coordinate-mode playback adapts to window offsets/resolution changes.
3. Decompose the current monolithic `player.py` / `recorder.py` into testable modules with clear responsibilities.
4. Enrich playback metrics (semantic/UIA/coordinate counts, calibration usage) while isolating screenshot/result orchestration.
5. Prepare for ENFIRE-side improvements (additional AutomationIds, reset hooks) by defining manifest & reset expectations.

## CLI Design

Package: `ui_testing.cli`

- Entry point (`python -m ui_testing.cli` / console script `ui-testing`).
- Click-like subcommands (using `argparse` initially for zero deps):
  - `record`: launch recorder in headless mode (optional manifest, calibration profile, output path).
  - `play`: run scripts with overrides (use manifest/calibration, toggle semantic/screenshots, results folder).
  - `inspect`: dump AutomationId metadata for point/rect or list manifest entries.
- Shared configuration loader reuses `load_runtime_config` + new CLI arg parsing. GUI and CLI both write to the same `AppSettings` if requested (`--persist` flag).

## Coordinate Calibration

Concept: per-script calibration profile stored as JSON (e.g., `ui_testing/data/calibration/<profile>.json`).

- Calibration captures window origin, DPI scaling factors, optional anchor points.
- Recorder:
  - Allows tagging a recording with a calibration profile (CLI flag / GUI future toggle).
  - Stores coordinates relative to calibrated origin when profile provided (falls back to absolute otherwise).
- Player:
  - Applies calibration offsets before coordinate fallback clicks.
  - Tracks drift statistics (difference between expected vs. actual window origin) and logs adjustments.
- Utilities:
  - `ui_testing.tools.calibration` module with helpers to capture current window rect, compute offsets, save profile.
  - CLI subcommand `calibrate` prompts the user to select the ENFIRE window and saves a profile.

## Engine Refactor Outline

Structure under `ui_testing/automation/`:

- `player/`
  - `config.py`: dataclasses, runtime config merging, CLI integration.
  - `executor.py`: orchestration of action playback (semantic/UIA/coordinate decision) with injected services.
  - `screenshot.py`: capture + diff utilities (reused by GUI and CLI).
  - `results.py`: Excel/Allure/flake reporting (abstracted behind interface for CLI/GUI reuse).
  - `metrics.py`: track click/drag/assert counts, calibration usage, fallback reasons.
- `recorder/`
  - `core.py`: event listeners, state machines, writes actions.
  - `actions.py`: dataclasses / serialization helpers.
  - `semantic.py`: manifest + locator integration, assert.property generation.
  - `cli.py`: wrappers invoked by `ui_testing.cli record`.

Implementation approach:
1. Introduce new modules with thin wrappers that delegate from the existing monolithic classes.
2. Gradually move logic into helpers while keeping backwards-compatible APIs (`Recorder`/`Player` act as facades).
3. Add unit tests targeting the new modules before deleting old code paths.

## Metrics & Screenshot Isolation

- Metrics collector object tracks totals and exposes structured data (used for GUI summaries + CLI JSON output).
- Screenshot diff helper takes config + paths and returns `ScreenshotResult` dataclass (status, diff image path, metrics).
- Recorder stores more metadata for drags, double-clicks, etc., enabling richer analytics downstream.

## ENFIRE Collaboration Notes

- Manifest: define required groups and naming conventions (e.g., `RoadCollectorIds.*`, `CrossfireIds.*`). Provide script to fail CI when new controls lack AutomationIds.
- Reset hooks: propose surface-level API (command-line flag/IPC) that resets ENFIRE state (close dialogs, load default workspace, clear temp files). Document expected behaviour so player CLI can call it before runs.

## Next Implementation Steps

1. Scaffold `ui_testing/cli/__init__.py` with `argparse` entry point + placeholder subcommands.
2. Create calibration helper module and wire basic profile loading/saving (player consumes offsets but keeps current behaviour when absent).
3. Extract screenshot logic into dedicated module and redirect `Player` methods to use it.
4. Move action playback loops into `executor.py` with minimal API change.
5. Backfill unit tests for calibration + metrics modules.
