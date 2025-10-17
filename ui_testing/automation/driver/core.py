"""
Core driver utilities for interacting with the ENFIRE desktop UI via UI Automation.

This module currently exposes scaffolding that will be expanded as semantic
testing capabilities mature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class WindowSpec:
    """Describes the top-level window we want to attach to."""

    title_regex: Optional[str] = None
    class_name: Optional[str] = None


class WindowNotFoundError(RuntimeError):
    """Raised when the primary application window cannot be located."""


def attach_to_window(spec: WindowSpec) -> None:  # pragma: no cover - scaffold
    """
    Placeholder for logic that will attach the automation driver to ENFIRE.

    Parameters
    ----------
    spec:
        Criteria used to find the target window.
    """
    raise WindowNotFoundError("Window attachment not yet implemented.")

