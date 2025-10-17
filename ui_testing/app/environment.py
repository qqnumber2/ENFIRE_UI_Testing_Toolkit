# ui_testing/app/environment.py
from __future__ import annotations

import sys
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
    paths.test_plan = _find_default_test_plan(project_root)
    return paths


def _ensure_dirs(*directories: Path) -> None:
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


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
