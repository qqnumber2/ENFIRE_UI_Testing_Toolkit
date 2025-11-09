from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from ui_testing.app.configuration import RuntimeConfig, load_runtime_config
from ui_testing.app.settings import AppSettings


@pytest.fixture
def temp_ini(tmp_path: Path) -> Path:
    ini = tmp_path / "ui_testing.ini"
    ini.write_text(
        "[runtime]\n"
        "theme = flatly\n"
        "default_delay = 0.2\n"
        "use_automation_ids = false\n"
        "semantic_wait_timeout = 2.5\n",
        encoding="utf-8",
    )
    return ini


def test_load_runtime_config_prefers_explicit_path(temp_ini: Path) -> None:
    cfg = load_runtime_config({}, config_path=temp_ini)
    assert cfg.theme == "flatly"
    assert cfg.default_delay == pytest.approx(0.2)
    assert cfg.use_automation_ids is False
    assert cfg.semantic_wait_timeout == pytest.approx(2.5)
    # Config source should reflect the file used
    assert cfg.config_source == temp_ini


def test_env_overrides_ini(temp_ini: Path) -> None:
    env: Dict[str, str] = {
        "UI_TESTING_THEME": "darkly",
        "UI_TESTING_DEFAULT_DELAY": "0.75",
        "UI_TESTING_USE_AUTOMATION_IDS": "1",
    }
    cfg = load_runtime_config(env, config_path=temp_ini)
    assert cfg.theme == "darkly"
    assert cfg.default_delay == pytest.approx(0.75)
    assert cfg.use_automation_ids is True


def test_runtime_config_applies_to_settings(temp_ini: Path) -> None:
    cfg = load_runtime_config({}, config_path=temp_ini)
    settings = AppSettings()
    cfg.apply_to_settings(settings)
    assert settings.theme == "flatly"
    assert settings.default_delay == pytest.approx(0.2)
    assert settings.use_automation_ids is False
    assert settings.semantic_wait_timeout == pytest.approx(2.5)


def test_load_runtime_config_handles_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.ini"
    cfg = load_runtime_config({}, config_path=missing)
    assert cfg.theme is None
    assert cfg.config_source == missing
