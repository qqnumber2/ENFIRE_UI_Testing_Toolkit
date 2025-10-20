"""Semantic screen object for the ENFIRE app bar."""

from __future__ import annotations

from ...driver import AutomationSession
from ..registry import AutomationRegistry
from .base import BaseScreen

_APPBAR_GROUP = "AppBarIds"


class AppBarScreen(BaseScreen):
    """Encapsulates common app bar actions."""

    def __init__(self, session: AutomationSession, registry: AutomationRegistry) -> None:
        super().__init__(session, registry)
        self.bind(name="AppBarAdd", group=_APPBAR_GROUP, control_type="Button")
        self.bind(name="AppBarSave", group=_APPBAR_GROUP, control_type="Button")
        self.bind(name="AppBarDelete", group=_APPBAR_GROUP, control_type="Button")
        self.bind(name="AppBarReport", group=_APPBAR_GROUP, control_type="Button")
        self.bind(name="AppBarMenu", group=_APPBAR_GROUP, control_type="Button")

    def click_add(self) -> None:
        self.control("AppBarAdd").click()

    def click_save(self) -> None:
        self.control("AppBarSave").click()

    def click_delete(self) -> None:
        self.control("AppBarDelete").click()

    def open_report(self) -> None:
        self.control("AppBarReport").click()

    def open_menu(self) -> None:
        self.control("AppBarMenu").click()
