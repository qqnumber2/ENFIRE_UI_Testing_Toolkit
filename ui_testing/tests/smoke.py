"""Quick smoke test to ensure core modules import and basic app wiring works."""

from __future__ import annotations

import contextlib

from ui_testing.app.environment import build_default_paths
from ui_testing.ui.app import TestRunnerApp


def run() -> None:
    paths = build_default_paths()
    print(f"Scripts dir: {paths.scripts_dir}")
    print(f"Images dir:  {paths.images_dir}")

    app = TestRunnerApp()
    with contextlib.suppress(Exception):
        app.ui_settings_save = False
    app._on_window_close()
    print("Smoke test passed: app constructed and torn down cleanly.")


if __name__ == "__main__":
    run()
