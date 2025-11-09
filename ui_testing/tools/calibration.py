"""Coordinate calibration utilities for ENFIRE UI automation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import pyautogui

try:
    from ui_testing.automation.driver import DEFAULT_WINDOW_SPEC, WindowSpec
except Exception:  # pragma: no cover - fallback when driver optional
    WindowSpec = None  # type: ignore
    DEFAULT_WINDOW_SPEC = None  # type: ignore

try:
    from pywinauto import Desktop  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Desktop = None  # type: ignore


@dataclass(slots=True)
class CalibrationProfile:
    """Represents a stored calibration anchor for coordinate playback."""

    name: str
    anchor_x: int
    anchor_y: int
    width: Optional[int] = None
    height: Optional[int] = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationProfile":
        return cls(
            name=str(data["name"]),
            anchor_x=int(data["anchor_x"]),
            anchor_y=int(data["anchor_y"]),
            width=data.get("width"),
            height=data.get("height"),
            updated_at=str(data.get("updated_at", datetime.now(timezone.utc).isoformat())),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at
        return payload


def calibration_dir(data_root: Path) -> Path:
    directory = data_root / "calibration"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def profile_path(data_root: Path, name: str) -> Path:
    return calibration_dir(data_root) / f"{name}.json"


def save_profile(data_root: Path, profile: CalibrationProfile) -> Path:
    path = profile_path(data_root, profile.name)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return path


def load_profile(data_root: Path, name: str) -> Optional[CalibrationProfile]:
    path = profile_path(data_root, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CalibrationProfile.from_dict(data)
    except Exception:
        return None


def list_profiles(data_root: Path) -> List[str]:
    directory = calibration_dir(data_root)
    return sorted(p.stem for p in directory.glob("*.json"))


def capture_window_anchor(window_spec: Optional[WindowSpec] = None) -> Optional[Tuple[int, int, Optional[int], Optional[int]]]:
    """Capture the top-left coordinate and size of the ENFIRE window."""

    spec = window_spec or DEFAULT_WINDOW_SPEC
    if Desktop is not None and spec is not None:
        try:
            desktop = Desktop(backend="uia")
            window = desktop.window(**spec.to_query())
            window.wait("exists ready", timeout=2.0)
            rect = window.rectangle()
            return int(rect.left), int(rect.top), int(rect.width()), int(rect.height())
        except Exception:
            pass

    # Fallback to current active window via pyautogui (PyGetWindow)
    try:
        active = pyautogui.getActiveWindow()
    except Exception:
        active = None
    if active:
        try:
            return int(active.left), int(active.top), int(active.width), int(active.height)
        except Exception:
            return None
    return None


def compute_offset(profile: CalibrationProfile, current_anchor: Tuple[int, int]) -> Tuple[int, int]:
    px, py = current_anchor
    dx = int(px) - int(profile.anchor_x)
    dy = int(py) - int(profile.anchor_y)
    return dx, dy
