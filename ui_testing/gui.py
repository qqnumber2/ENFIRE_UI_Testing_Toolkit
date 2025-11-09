# ui_testing/gui.py
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure package root is importable when running this file directly
package_root = Path(__file__).resolve().parent.parent
if str(package_root) not in sys.path:
    sys.path.insert(0, str(package_root))

from ui_testing.app.configuration import load_runtime_config
from ui_testing.ui.app import TestRunnerApp


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    runtime_config = load_runtime_config()
    if runtime_config.config_source:
        logging.info("Loaded runtime config from %s", runtime_config.config_source)
    app = TestRunnerApp(runtime_config=runtime_config)
    app.run()


if __name__ == "__main__":
    main()
