"""Export AutomationId constants from the ENFIRE WPF solution.

This utility scans the Utility/AutomationIds folder inside the ENFIRE
source tree and emits a JSON manifest mapping class names to their
constants. The manifest is used by ui_testing to validate selectors and
is bundled with build artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def export_manifest(root: Path, output: Path) -> None:
    manifest: dict[str, dict[str, str]] = {}
    for cs_file in sorted(root.glob("*.cs")):
        try:
            content = cs_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        constants = re.findall(r'const\s+string\s+(\w+)\s*=\s*"([^"]+)"', content)
        manifest[cs_file.stem] = {name: value for name, value in constants}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    source_root = repo_root / "enfire" / "Source" / "Enfire.EsriRuntime.Wpf" / "Utility" / "AutomationIds"
    output = repo_root / "automation" / "automation_ids.json"
    if not source_root.exists():
        print(f"AutomationIds source folder not found: {source_root}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}", encoding="utf-8")
        return
    export_manifest(source_root, output)
    print(f"Wrote automation manifest to {output}")


if __name__ == "__main__":
    main()
