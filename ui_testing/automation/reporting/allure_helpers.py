"""Allure reporting helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import allure  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    allure = None  # type: ignore


def attach_image(name: str, path: Path, attachment_type: Optional[str] = None) -> None:
    if allure is None:
        return
    attachment_type = attachment_type or "image/png"
    try:
        allure.attach(path.read_bytes(), name=name, attachment_type=attachment_type)
    except Exception:
        pass


def attach_file(name: str, path: Path, attachment_type: Optional[str] = None) -> None:
    if allure is None:
        return
    if not path.exists():
        return
    attachment_type = attachment_type or "application/octet-stream"
    try:
        allure.attach(path.read_bytes(), name=name, attachment_type=attachment_type)
    except Exception:
        pass
