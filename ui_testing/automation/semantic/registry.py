"""
Registry mapping AutomationIds to higher-level semantic control abstractions.

In the initial phase this module keeps a simple in-memory registry populated
from generated manifests. It will later expose convenience lookups for recorder
and playback components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

ControlMap = Dict[str, "ControlEntry"]


@dataclass(slots=True)
class ControlEntry:
    """Represents metadata for a single AutomationId."""

    automation_id: str
    group: str
    control_type: Optional[str] = None
    description: Optional[str] = None


class AutomationRegistry:
    """Loads and provides read-only access to AutomationId metadata."""

    def __init__(self) -> None:
        self._entries: ControlMap = {}

    def load(self, manifest: Mapping[str, Mapping[str, Dict[str, str]]]) -> None:
        """Populate the registry from a nested manifest structure."""
        self._entries.clear()
        for group, items in manifest.items():
            for name, payload in items.items():
                automation_id = payload.get("id") or payload.get("automation_id")
                if not automation_id:
                    continue
                self._entries[automation_id] = ControlEntry(
                    automation_id=automation_id,
                    group=group,
                    control_type=payload.get("control_type"),
                    description=payload.get("description"),
                )

    def get(self, automation_id: str) -> Optional[ControlEntry]:
        """Return the registry entry for an AutomationId, if present."""
        return self._entries.get(automation_id)

    def all(self) -> Mapping[str, ControlEntry]:
        """Expose a snapshot of the registry contents."""
        return dict(self._entries)

