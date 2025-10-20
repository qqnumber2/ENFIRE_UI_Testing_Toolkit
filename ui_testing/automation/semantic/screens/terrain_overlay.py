"""Semantic screen for terrain overlay map controls."""

from __future__ import annotations

from ...driver import AutomationSession
from ..registry import AutomationRegistry
from .base import BaseScreen

_TERRAIN_GROUP = "TerrainIds"


class TerrainOverlayScreen(BaseScreen):
    """Helpers for editing terrain overlay information."""

    def __init__(self, session: AutomationSession, registry: AutomationRegistry) -> None:
        super().__init__(session, registry)
        self.bind(name="TerrainName", group=_TERRAIN_GROUP, control_type="Edit")
        self.bind(name="Description", group=_TERRAIN_GROUP, control_type="Edit")
        self.bind(name="ManMade", group=_TERRAIN_GROUP, control_type="Button")
        self.bind(name="Natural", group=_TERRAIN_GROUP, control_type="Button")

    def set_name(self, value: str) -> None:
        self.control("TerrainName").set_value(value)

    def set_description(self, value: str) -> None:
        self.control("Description").set_value(value)

    def toggle_man_made(self, state: bool = True) -> None:
        control = self.control("ManMade")
        control.toggle(state=state)

    def toggle_natural(self, state: bool = True) -> None:
        control = self.control("Natural")
        control.toggle(state=state)

    def assert_name(self, expected: str) -> None:
        value = str(self.control("TerrainName").get_value() or "")
        if value != expected:
            raise AssertionError(f"Expected terrain name '{expected}' but found '{value}'")
