"""
Export AutomationId constants from the ENFIRE source tree into a JSON manifest.

Usage
-----
python -m ui_testing.tools.automation_ids.export_ids \
    --cs-root external/enfire/Source/Enfire.EsriRuntime.Wpf/Utility/AutomationIds \
    --output ui_testing/automation/manifest/automation_ids.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

CLASS_PATTERN = re.compile(r"class\s+(?P<name>[A-Za-z0-9_]+)")
CONST_PATTERN = re.compile(
    r"\b(?:public|internal|protected|private)\s+const\s+string\s+"
    r"(?P<name>[A-Za-z0-9_]+)\s*=\s*\"(?P<value>[^\"\\]*(?:\\.[^\"\\]*)*)\""
)
SUMMARY_PATTERN = re.compile(r"^\s*///\s*(?P<text>.+?)\s*$")


@dataclass(slots=True)
class ConstantEntry:
    name: str
    value: str
    description: Optional[str]
    source: Path
    line: int


def extract_constants(path: Path) -> Dict[str, List[ConstantEntry]]:
    """Parse a C# file and return constants keyed by containing class."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    class_name = None
    classes: Dict[str, List[ConstantEntry]] = {}

    for idx, line in enumerate(lines):
        class_match = CLASS_PATTERN.search(line)
        if class_match:
            class_name = class_match.group("name")
            classes.setdefault(class_name, [])
            continue

        const_match = CONST_PATTERN.search(line)
        if const_match and class_name:
            name = const_match.group("name")
            value = bytes(const_match.group("value"), "utf-8").decode("unicode_escape")
            description = _collect_summary(lines, idx)
            entry = ConstantEntry(
                name=name,
                value=value,
                description=description,
                source=path,
                line=idx + 1,
            )
            classes.setdefault(class_name, []).append(entry)
    return classes


def _collect_summary(lines: List[str], index: int) -> Optional[str]:
    """Collect contiguous XML summary lines preceding a constant definition."""
    summaries: List[str] = []
    i = index - 1
    while i >= 0:
        match = SUMMARY_PATTERN.match(lines[i])
        if not match:
            break
        summaries.append(match.group("text").strip())
        i -= 1
    summaries.reverse()
    if not summaries:
        return None
    # strip XML tags if present (simple heuristic)
    text = " ".join(summaries)
    text = re.sub(r"<.*?>", "", text).strip()
    return text or None


def build_manifest(constants: Dict[str, List[ConstantEntry]]) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Convert parsed constants into the manifest structure."""
    manifest: Dict[str, Dict[str, Dict[str, str]]] = {}
    for cls, entries in constants.items():
        if not entries:
            continue
        group = manifest.setdefault(cls, {})
        for entry in entries:
            group[entry.name] = {
                "id": entry.value,
                "description": entry.description or "",
                "source": str(entry.source.as_posix()),
                "line": entry.line,
            }
    return manifest


def gather_constants(cs_root: Path) -> Dict[str, List[ConstantEntry]]:
    """Walk the C# AutomationIds directory and parse each file."""
    aggregated: Dict[str, List[ConstantEntry]] = {}
    for file_path in sorted(cs_root.glob("*.cs")):
        parsed = extract_constants(file_path)
        for cls, entries in parsed.items():
            aggregated.setdefault(cls, []).extend(entries)
    return aggregated


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ENFIRE AutomationIds to JSON.")
    parser.add_argument(
        "--cs-root",
        type=Path,
        default=Path("external/enfire/Source/Enfire.EsriRuntime.Wpf/Utility/AutomationIds"),
        help="Directory containing AutomationIds C# files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ui_testing/automation/manifest/automation_ids.json"),
        help="Destination JSON manifest file.",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path("ui_testing/automation/manifest/schema.json"),
        help="Optional schema path to include reference in output metadata.",
    )
    args = parser.parse_args()

    if not args.cs_root.exists():
        parser.error(f"Source directory not found: {args.cs_root}")

    constants = gather_constants(args.cs_root)
    manifest = build_manifest(constants)
    output_data = {
        "$schema": str(args.schema.as_posix()) if args.schema.exists() else None,
        "generated_from": str(args.cs_root.as_posix()),
        "groups": manifest,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote manifest with {sum(len(v) for v in manifest.values())} ids to {args.output}")


if __name__ == "__main__":
    main()

