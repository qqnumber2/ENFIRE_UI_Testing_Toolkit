"""
Control-level helpers for semantic automation of ENFIRE.

The current implementation deliberately stays minimal; it will grow as we map
AutomationIds to typed control wrappers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ControlHandle(Protocol):  # pragma: no cover - interface only
    """Protocol describing the minimal surface we expect from concrete handles."""

    def set_value(self, value: Any) -> None:
        ...

    def get_value(self) -> Any:
        ...

    def click(self) -> None:
        ...


@dataclass(slots=True)
class ControlSpec:
    """Descriptor tying an AutomationId to a control type."""

    automation_id: str
    control_type: str | None = None

