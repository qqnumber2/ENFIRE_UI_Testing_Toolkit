# ui_testing/tests/smoke.py
from __future__ import annotations

from ui_testing.ui.app import TestRunnerApp


def main() -> None:
    """Instantiate and tear down the GUI quickly to verify imports and layout."""
    app = TestRunnerApp()
    app.root.update_idletasks()
    app.root.update()
    app.root.destroy()
    print("Smoke test completed: GUI instantiated successfully.")


if __name__ == "__main__":
    main()
