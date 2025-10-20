from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List

import pytest

from ui_testing.automation.player import Player, PlayerConfig
from ui_testing.automation.semantic.context import SemanticContext
from ui_testing.automation.semantic.registry import ControlEntry


class _FakeRegistry:
    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, ControlEntry]] = {}

    def add_group(self, group: str, names: List[str]) -> None:
        group_entries: Dict[str, ControlEntry] = {}
        for index, name in enumerate(names):
            automation_id = f"{group}.{name}.{index}"
            group_entries[name] = ControlEntry(
                automation_id=automation_id,
                group=group,
                name=name,
                control_type="Text",
            )
        self._entries[group] = group_entries

    def find_by_name(self, group: str, name: str) -> ControlEntry | None:
        return self._entries.get(group, {}).get(name)


class _FakeControl:
    def __init__(self, spec) -> None:  # type: ignore[no-untyped-def]
        self.spec = spec

    def click(self) -> None:
        pass

    def set_value(self, value: str) -> None:
        self.value = value

    def get_value(self) -> str:
        return getattr(self, "value", self.spec.automation_id)


@pytest.fixture(autouse=True)
def _patch_control_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    from ui_testing.automation.semantic.screens import base

    monkeypatch.setattr(base, "resolve_control", lambda session, spec: _FakeControl(spec))


@pytest.fixture
def semantic_context(monkeypatch: pytest.MonkeyPatch) -> SemanticContext:
    fake_registry = _FakeRegistry()
    fake_registry.add_group(
        "MapControlIds",
        [
            "RadialMenuButton",
            "CustomZoomButton",
            "MapScaleCombo",
            "MapScaleDisplay",
            "CoordinateLabel",
            "GoToToggle",
            "BasemapToggle",
        ],
    )
    monkeypatch.setattr(
        "ui_testing.automation.semantic.context.load_registry",
        lambda manifest_path: fake_registry,
    )
    ctx = SemanticContext()
    ctx._session = SimpleNamespace()
    ctx._registry = fake_registry  # type: ignore[assignment]
    return ctx


@pytest.mark.semantic
def test_resolve_screen_for_group_caches_instances(semantic_context: SemanticContext) -> None:
    first = semantic_context.resolve_screen_for_group("MapControlIds")
    assert first is not None
    second = semantic_context.resolve_screen_for_group("MapControlIds")
    assert second is first


@pytest.mark.semantic
def test_player_semantic_template_records_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = PlayerConfig(
        scripts_dir=tmp_path / "scripts",
        images_dir=tmp_path / "images",
        results_dir=tmp_path / "results",
    )
    config.scripts_dir.mkdir()
    config.images_dir.mkdir()
    config.results_dir.mkdir()

    monkeypatch.setattr("ui_testing.automation.player.pyautogui.size", lambda: (1920, 1080))

    player = Player(config)
    player._current_script = "dummy"
    calls: List[str] = []
    monkeypatch.setattr(player, "_record_failure", lambda identifier: calls.append(identifier))

    class _Screen:
        def assert_name(self, expected: str) -> None:
            raise AssertionError(f"bad value: {expected}")

    player._semantic_context = SimpleNamespace(resolve_screen_for_group=lambda group: _Screen())

    with pytest.raises(AssertionError) as exc:
        player._run_semantic_template({"group": "TerrainIds", "name": "TerrainName"}, "abc")
    assert "semantic:TerrainIds.TerrainName" in str(exc.value)
    assert calls == ["semantic:TerrainIds.TerrainName"]
