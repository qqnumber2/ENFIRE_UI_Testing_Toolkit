"""Shared locator utilities used by automation components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

_GENERIC_AUTOMATION_IDS = {"", "window", "pane", "mainwindowcontrol"}


def is_generic_automation_id(value: Optional[str]) -> bool:
    """Return True when an AutomationId is empty or represents a generic container."""

    if not value:
        return True
    lowered = str(value).strip().lower()
    return lowered in _GENERIC_AUTOMATION_IDS


@dataclass(slots=True)
class ManifestIndex:
    """Normalized manifest lookup table."""

    groups: Dict[str, Dict[str, Dict[str, Any]]]
    lookup: Dict[str, Tuple[str, str]]

    def get(self, automation_id: str) -> Optional[Tuple[str, str]]:
        """Return (group, name) for an AutomationId if present."""

        return self.lookup.get(str(automation_id))

    def contains(self, automation_id: str) -> bool:
        """Return True when an AutomationId exists in the manifest."""

        return str(automation_id) in self.lookup


def normalize_manifest(manifest: Mapping[str, Mapping[str, Any]] | None) -> ManifestIndex:
    """Normalize manifest data into deterministic dictionaries and lookup tables."""

    structured: Dict[str, Dict[str, Dict[str, Any]]] = {}
    lookup: Dict[str, Tuple[str, str]] = {}
    if not isinstance(manifest, Mapping):
        return ManifestIndex(groups=structured, lookup=lookup)
    for group, mapping in manifest.items():
        if not isinstance(mapping, Mapping):
            continue
        group_key = str(group)
        group_entries: Dict[str, Dict[str, Any]] = {}
        for name, payload in mapping.items():
            auto_id: Optional[str] = None
            metadata: Dict[str, Any]
            if isinstance(payload, Mapping):
                auto_id = payload.get("automation_id") or payload.get("id")
                if auto_id:
                    metadata = dict(payload)
                    metadata["automation_id"] = str(auto_id)
                else:
                    continue
            else:
                auto_id = str(payload)
                if not auto_id:
                    continue
                metadata = {"automation_id": auto_id}
            name_key = str(name)
            group_entries[name_key] = metadata
            lookup[str(auto_id)] = (group_key, name_key)
        if group_entries:
            structured[group_key] = group_entries
    return ManifestIndex(groups=structured, lookup=lookup)


class LocatorService:
    """Helper that centralises manifest indexing and semantic metadata generation."""

    def __init__(self, manifest: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.update_manifest(manifest)

    def update_manifest(self, manifest: Mapping[str, Mapping[str, Any]] | None) -> None:
        self._index = normalize_manifest(manifest or {})

    @property
    def manifest(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        return self._index.groups

    @property
    def lookup(self) -> Dict[str, Tuple[str, str]]:
        return self._index.lookup

    def contains(self, automation_id: Optional[str]) -> bool:
        if automation_id is None:
            return False
        return self._index.contains(str(automation_id))

    def manifest_entry(self, automation_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if automation_id is None:
            return None
        key = self._index.get(str(automation_id))
        if not key:
            return None
        group, name = key
        return self._index.groups.get(group, {}).get(name)

    def semantic_metadata(
        self,
        automation_id: Optional[str],
        control_type: Optional[str] = None,
        registry: Any = None,
    ) -> Optional[Dict[str, Any]]:
        if not automation_id or is_generic_automation_id(automation_id):
            return None
        payload: Dict[str, Any] = {"automation_id": str(automation_id)}
        if control_type:
            payload["control_type"] = str(control_type)

        entry = None
        if registry is not None and hasattr(registry, "get"):
            try:
                entry = registry.get(str(automation_id))
            except Exception:
                entry = None

        if entry is not None:
            payload["group"] = getattr(entry, "group", None) or payload.get("group")
            payload["name"] = getattr(entry, "name", None) or payload.get("name")
            entry_control_type = getattr(entry, "control_type", None)
            if entry_control_type and "control_type" not in payload:
                payload["control_type"] = entry_control_type
            description = getattr(entry, "description", None)
            if description:
                payload["description"] = description
        else:
            manifest_key = self._index.get(str(automation_id))
            if manifest_key:
                group, name = manifest_key
                payload["group"] = group
                payload["name"] = name
                metadata = self.manifest_entry(automation_id)
                if metadata:
                    description = metadata.get("description")
                    if description:
                        payload["description"] = description
                    manifest_ctrl = metadata.get("control_type")
                    if manifest_ctrl and "control_type" not in payload:
                        payload["control_type"] = manifest_ctrl
        return payload
