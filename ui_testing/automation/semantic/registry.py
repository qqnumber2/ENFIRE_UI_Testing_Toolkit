"""
Registry mapping AutomationIds to higher-level semantic control abstractions.

In the initial phase this module keeps a simple in-memory registry populated
from generated manifests. It will later expose convenience lookups for recorder
and playback components.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional
import json

ControlMap = Dict[str, "ControlEntry"]


@dataclass(slots=True)
class ControlEntry:
    """Represents metadata for a single AutomationId."""

    automation_id: str
    group: str
    name: str
    control_type: Optional[str] = None
    description: Optional[str] = None


class AutomationRegistry:
    """Loads and provides read-only access to AutomationId metadata."""

    def __init__(self) -> None:
        self._entries: ControlMap = {}
        self._groups: Dict[str, Dict[str, ControlEntry]] = {}

    def load(self, manifest: Mapping[str, Mapping[str, Dict[str, str]]]) -> None:
        """Populate the registry from a nested manifest structure."""
        self._entries.clear()
        self._groups.clear()
        for group, items in manifest.items():
            if not isinstance(items, dict):
                continue
            group_entries: Dict[str, ControlEntry] = {}
            self._groups[group] = group_entries
            for name, payload in items.items():
                automation_id = payload.get("id") or payload.get("automation_id")
                if not automation_id:
                    continue
                entry = ControlEntry(
                    automation_id=automation_id,
                    group=group,
                    name=str(name),
                    control_type=payload.get("control_type"),
                    description=payload.get("description"),
                )
                self._entries[automation_id] = entry
                group_entries[name] = entry

    def get(self, automation_id: str) -> Optional[ControlEntry]:
        """Return the registry entry for an AutomationId, if present."""
        return self._entries.get(automation_id)

    def all(self) -> Mapping[str, ControlEntry]:
        """Expose a snapshot of the registry contents."""
        return dict(self._entries)

    def by_group(self, group: str) -> Mapping[str, ControlEntry]:
        """Return entries for a specific AutomationId group/class."""
        return dict(self._groups.get(group, {}))

    def groups(self) -> Iterable[str]:
        """Return all known groups."""
        return tuple(self._groups.keys())

    def find_by_name(self, group: str, name: str) -> Optional[ControlEntry]:
        """Retrieve the entry represented by the C# constant name."""
        return self._groups.get(group, {}).get(name)

    def load_from_file(self, path: Path) -> None:
        """Load manifest metadata from a JSON file on disk."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            manifest = data.get("groups") if "groups" in data else data
            if isinstance(manifest, dict):
                self.load(manifest)
                return
        raise ValueError(f"Unsupported manifest format in {path}")
