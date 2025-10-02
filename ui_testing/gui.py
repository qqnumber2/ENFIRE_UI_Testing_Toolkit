# ui_testing/gui.py
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure package root is importable when running this file directly
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from ui_testing.ui.app import TestRunnerApp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    app = TestRunnerApp()
    app.run()


if __name__ == "__main__":
    main()
