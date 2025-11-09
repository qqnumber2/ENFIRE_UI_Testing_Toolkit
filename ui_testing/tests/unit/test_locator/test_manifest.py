from __future__ import annotations

from typing import Dict

import pytest

from ui_testing.automation.locator import LocatorService, is_generic_automation_id, normalize_manifest


def test_is_generic_automation_id_handles_common_cases() -> None:
    assert is_generic_automation_id(None) is True
    assert is_generic_automation_id("") is True
    assert is_generic_automation_id("Window") is True
    assert is_generic_automation_id("pane") is True
    assert is_generic_automation_id("MainWindowControl") is True
    assert is_generic_automation_id("SubmitButton") is False


def test_normalize_manifest_builds_lookup() -> None:
    raw_manifest: Dict[str, Dict[str, Dict[str, str]]] = {
        "AppBarIds": {
            "AppBarSave": {"id": "Save", "description": "Save button"},
            "AppBarOpen": "Open",
        }
    }
    index = normalize_manifest(raw_manifest)
    assert index.groups["AppBarIds"]["AppBarSave"]["automation_id"] == "Save"
    assert index.groups["AppBarIds"]["AppBarOpen"]["automation_id"] == "Open"
    assert index.contains("Save") is True
    assert index.contains("Missing") is False
    assert index.get("Save") == ("AppBarIds", "AppBarSave")


def test_locator_service_semantic_metadata_prefers_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    locator = LocatorService(
        {
            "AppBarIds": {
                "AppBarSave": {
                    "automation_id": "Save",
                    "description": "Save the record",
                    "control_type": "Button",
                }
            }
        }
    )

    class FakeEntry:
        automation_id = "Save"
        group = "AppBarIds"
        name = "AppBarSave"
        control_type = "Button"
        description = "Registry description"

    class FakeRegistry:
        def get(self, automation_id: str):  # type: ignore[no-untyped-def]
            if automation_id == "Save":
                return FakeEntry()
            return None

    metadata = locator.semantic_metadata("Save", "Button", FakeRegistry())
    assert metadata == {
        "automation_id": "Save",
        "control_type": "Button",
        "group": "AppBarIds",
        "name": "AppBarSave",
        "description": "Registry description",
    }


def test_locator_service_semantic_metadata_falls_back_to_manifest() -> None:
    locator = LocatorService(
        {
            "AppBarIds": {
                "AppBarOpen": {
                    "automation_id": "Open",
                    "description": "Open the record",
                    "control_type": "Button",
                }
            }
        }
    )
    metadata = locator.semantic_metadata("Open", "Button", registry=None)
    assert metadata == {
        "automation_id": "Open",
        "control_type": "Button",
        "group": "AppBarIds",
        "name": "AppBarOpen",
        "description": "Open the record",
    }


def test_locator_service_filters_generic_ids() -> None:
    locator = LocatorService(
        {
            "Generic": {
                "Window": {
                    "automation_id": "window",
                }
            }
        }
    )
    assert locator.semantic_metadata("window", "Pane", registry=None) is None
