# ui_testing/app/environment.py
from __future__ import annotations

import sys
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Paths:
    """Resolved filesystem locations used by the UI tester."""

    root: Path
    data_root: Path
    scripts_dir: Path
    images_dir: Path
    results_dir: Path
    logs_dir: Path
    tolerance: float = 0.01
    test_plan: Optional[Path] = None


def resource_path(relative: str) -> str:
    """Return an absolute path that works both from source and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return str((base / relative).resolve())


def build_default_paths() -> Paths:
    """Create the default Paths collection and ensure directories exist."""
    module_path = Path(__file__).resolve()
    project_root = Path(getattr(sys, "_MEIPASS", module_path.parents[2]))
    package_root = Path(getattr(sys, "_MEIPASS", module_path.parents[1]))
    data_root = package_root / "data"
    paths = Paths(
        root=package_root,
        data_root=data_root,
        scripts_dir=data_root / "scripts",
        images_dir=data_root / "images",
        results_dir=data_root / "results",
        logs_dir=data_root / "logs",
    )
    _ensure_dirs(paths.data_root, paths.scripts_dir, paths.images_dir, paths.results_dir, paths.logs_dir)
    if not hasattr(sys, "_MEIPASS"):
        _migrate_legacy_data(project_root / "data", paths.data_root)
    paths.test_plan = _find_default_test_plan(project_root)
    return paths


def _ensure_dirs(*directories: Path) -> None:
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_data(legacy_root: Path, target_root: Path) -> None:
    """Move data from the historical `<repo>/data` folder into `ui_testing/data`."""
    if legacy_root == target_root or not legacy_root.exists():
        return
    try:
        if not any(legacy_root.iterdir()):
            return
    except Exception:
        return

    logger = logging.getLogger(__name__)
    moved_any = False
    for item in legacy_root.iterdir():
        destination = target_root / item.name
        if destination.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
            moved_any = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not migrate '%s' to '%s': %s", item, destination, exc)
    if moved_any:
        note_path = legacy_root / "README_LEGACY.txt"
        try:
            note_path.write_text(
                "Data has been copied to ui_testing/data. This legacy folder is no longer used "
                "and can be removed once you verify the new location.",
                encoding="utf-8",
            )
        except Exception:
            pass
        logger.info("Legacy data copied from '%s' to '%s'. You may delete the old folder after verifying.", legacy_root, target_root)


def _find_default_test_plan(root: Path) -> Optional[Path]:
    candidates = sorted(root.glob("*.xlsm"))
    if not candidates:
        return None
    prioritized = [
        candidate
        for candidate in candidates
        if "Test Procedure" in candidate.name
    ]
    selected = prioritized[0] if prioritized else candidates[0]
    return selected if selected.is_file() else None
