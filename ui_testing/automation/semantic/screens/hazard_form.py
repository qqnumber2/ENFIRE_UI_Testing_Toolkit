"""Semantic screen object for the ENFIRE hazard form."""

from __future__ import annotations

from ...driver import AutomationSession
from ..registry import AutomationRegistry
from .base import BaseScreen

_EHSR_GROUP = "EhsrIds"


class HazardFormScreen(BaseScreen):
    """Semantic helpers for interacting with hazard (EHSR) forms."""

    def __init__(self, session: AutomationSession, registry: AutomationRegistry) -> None:
        super().__init__(session, registry)
        self.bind(name="ReportTitle", group=_EHSR_GROUP, control_type="Edit")
        self.bind(name="ReportType", group=_EHSR_GROUP, control_type="ComboBox")
        self.bind(name="ReportLocation", group=_EHSR_GROUP, control_type="Edit")
        self.bind(name="Description", group=_EHSR_GROUP, control_type="Edit")
        self.bind(name="ThreatsDescription", group=_EHSR_GROUP, control_type="Edit")
        self.bind(name="ProtectionPriority", group=_EHSR_GROUP, control_type="ComboBox")
        self.bind(name="ProtectionTaken", group=_EHSR_GROUP, control_type="Edit")

    def set_title(self, value: str) -> None:
        self.control("ReportTitle").set_value(value)

    def select_type(self, value: str) -> None:
        self.control("ReportType").set_value(value)

    def set_location(self, value: str) -> None:
        self.control("ReportLocation").set_value(value)

    def set_description(self, value: str) -> None:
        self.control("Description").set_value(value)

    def set_threats(self, value: str) -> None:
        self.control("ThreatsDescription").set_value(value)

    def select_priority(self, value: str) -> None:
        self.control("ProtectionPriority").set_value(value)

    def set_measures(self, value: str) -> None:
        self.control("ProtectionTaken").set_value(value)
