
"""
Base screen abstraction for semantic ENFIRE automation.

Screen objects encapsulate common control lookups and interactions for a given
area of the ENFIRE UI, keeping tests concise and resilient to layout changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ...driver import AutomationSession, ControlSpec, UIControl, resolve_control
from ..registry import AutomationRegistry, ControlEntry


@dataclass(slots=True)
class ControlBinding:
    """Binding between a manifest entry and a control spec."""

    entry: ControlEntry
    spec: ControlSpec


class BaseScreen:
    """Common functionality for semantic screen/page objects."""

    def __init__(
        self,
        session: AutomationSession,
        registry: AutomationRegistry,
    ) -> None:
        self._session = session
        self._registry = registry
        self._bindings: Dict[str, ControlBinding] = {}

    def bind(self, *, name: str, group: str, control_type: Optional[str] = None) -> None:
        """
        Register a control from the manifest for later use.

        Parameters
        ----------
        name:
            Name of the constant within the manifest group.
        group:
            Manifest group (C# class name).
        control_type:
            Optional UIA control type to narrow resolution.
        """
        entry = self._registry.find_by_name(group, name)
        if entry is None:
            raise KeyError(f"AutomationId {group}.{name} not found in manifest.")
        spec = ControlSpec(automation_id=entry.automation_id, control_type=control_type)
        self._bindings[name] = ControlBinding(entry=entry, spec=spec)

    def control(self, name: str) -> UIControl:
        """Resolve a previously bound control."""
        binding = self._bindings.get(name)
        if binding is None:
            raise KeyError(f"No control bound for {name}.")
        return resolve_control(self._session, binding.spec)

    @property
    def session(self) -> AutomationSession:
        """Expose the underlying session for advanced operations."""
        return self._session
