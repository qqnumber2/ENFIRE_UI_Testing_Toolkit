"""Semantic screen for bridge route reports."""

from __future__ import annotations

from ...driver import AutomationSession
from ..registry import AutomationRegistry
from .base import BaseScreen

_BRIDGE_GROUP = "BridgeIds"


class BridgeReportScreen(BaseScreen):
    """Helpers for interacting with bridge report controls."""

    def __init__(self, session: AutomationSession, registry: AutomationRegistry) -> None:
        super().__init__(session, registry)
        self.bind(name="BridgeType", group=_BRIDGE_GROUP, control_type="ComboBox")
        self.bind(name="BridgeRemarks", group=_BRIDGE_GROUP, control_type="Edit")
        self.bind(name="BypassDifficulty", group=_BRIDGE_GROUP, control_type="ComboBox")
        self.bind(name="BypassRemarks", group=_BRIDGE_GROUP, control_type="Edit")
        self.bind(name="BridgeMlcResults", group=_BRIDGE_GROUP, control_type="Text")

    def select_bridge_type(self, value: str) -> None:
        self.control("BridgeType").set_value(value)

    def set_bridge_remarks(self, value: str) -> None:
        self.control("BridgeRemarks").set_value(value)

    def select_bypass_difficulty(self, value: str) -> None:
        self.control("BypassDifficulty").set_value(value)

    def set_bypass_remarks(self, value: str) -> None:
        self.control("BypassRemarks").set_value(value)

    def read_mlc_results(self) -> str:
        return str(self.control("BridgeMlcResults").get_value() or "")

    def assert_mlc(self, expected: str) -> None:
        actual = self.read_mlc_results()
        if actual != expected:
            raise AssertionError(f"Expected MLC '{expected}' but found '{actual}'")
