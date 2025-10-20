"""Semantic screen object for the ENFIRE map toolbar."""

from __future__ import annotations

from ...driver import ControlSpec
from ..registry import AutomationRegistry
from .base import BaseScreen

_MAP_GROUP = "MapControlIds"


class MapToolbarScreen(BaseScreen):
    """Encapsulates interactions with the map toolbar controls."""

    def __init__(self, session, registry: AutomationRegistry) -> None:
        super().__init__(session, registry)
        self.bind(name="RadialMenuButton", group=_MAP_GROUP, control_type="Button")
        self.bind(name="CustomZoomButton", group=_MAP_GROUP, control_type="Button")
        self.bind(name="MapScaleCombo", group=_MAP_GROUP, control_type="ComboBox")
        self.bind(name="MapScaleDisplay", group=_MAP_GROUP, control_type="Text")
        self.bind(name="CoordinateLabel", group=_MAP_GROUP, control_type="Text")
        self.bind(name="GoToToggle", group=_MAP_GROUP, control_type="Button")
        self.bind(name="BasemapToggle", group=_MAP_GROUP, control_type="Button")

    def open_radial_menu(self) -> None:
        self.control("RadialMenuButton").click()

    def set_custom_zoom(self) -> None:
        self.control("CustomZoomButton").click()

    def select_map_scale(self, value: str) -> None:
        combo = self.control("MapScaleCombo")
        combo.set_value(value)

    def read_scale_display(self) -> str:
        return str(self.control("MapScaleDisplay").get_value() or "")

    def read_coordinates(self) -> str:
        return str(self.control("CoordinateLabel").get_value() or "")

    def toggle_basemap(self) -> None:
        self.control("BasemapToggle").click()

