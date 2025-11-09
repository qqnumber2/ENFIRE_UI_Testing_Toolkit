"""Runtime configuration loading helpers for the UI testing toolkit."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from .settings import AppSettings

_ENV_PREFIX = "UI_TESTING_"
_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


@dataclass(slots=True)
class RuntimeConfig:
    """Declarative overrides sourced from environment variables or config files."""

    config_source: Optional[Path] = None
    theme: Optional[str] = None
    default_delay: Optional[float] = None
    tolerance: Optional[float] = None
    ignore_recorded_delays: Optional[bool] = None
    use_automation_ids: Optional[bool] = None
    use_screenshots: Optional[bool] = None
    prefer_semantic_scripts: Optional[bool] = None
    use_ssim: Optional[bool] = None
    ssim_threshold: Optional[float] = None
    automation_backend: Optional[str] = None
    target_app_regex: Optional[str] = None
    semantic_wait_timeout: Optional[float] = None
    semantic_poll_interval: Optional[float] = None

    def apply_to_settings(self, settings: AppSettings) -> None:
        """Project runtime overrides onto persisted settings without destroying saved values."""

        if self.theme is not None:
            settings.theme = self.theme
        if self.default_delay is not None:
            settings.default_delay = self.default_delay
        if self.tolerance is not None:
            settings.tolerance = self.tolerance
        if self.ignore_recorded_delays is not None:
            settings.ignore_recorded_delays = self.ignore_recorded_delays
        if self.use_automation_ids is not None:
            settings.use_automation_ids = self.use_automation_ids
        if self.use_screenshots is not None:
            settings.use_screenshots = self.use_screenshots
        if self.prefer_semantic_scripts is not None:
            settings.prefer_semantic_scripts = self.prefer_semantic_scripts
        if self.use_ssim is not None:
            settings.use_ssim = self.use_ssim
        if self.ssim_threshold is not None:
            settings.ssim_threshold = self.ssim_threshold
        if self.automation_backend is not None:
            settings.automation_backend = self.automation_backend
        if self.target_app_regex is not None:
            settings.target_app_regex = self.target_app_regex
        if self.semantic_wait_timeout is not None:
            settings.semantic_wait_timeout = self.semantic_wait_timeout
        if self.semantic_poll_interval is not None:
            settings.semantic_poll_interval = self.semantic_poll_interval


def load_runtime_config(
    env: Mapping[str, str] | None = None,
    config_path: Optional[Path] = None,
) -> RuntimeConfig:
    """Load runtime configuration overrides from environment variables and optional INI files."""

    source_env = os.environ if env is None else env
    config_file = _determine_config_path(source_env, config_path)
    config = RuntimeConfig(config_source=config_file)

    if config_file is not None and config_file.is_file():
        parser = configparser.ConfigParser()
        try:
            parser.read(config_file, encoding="utf-8")
        except Exception:
            parser = None  # pragma: no cover - invalid file handled via env overrides only
        if parser and parser.has_section("runtime"):
            section = parser["runtime"]
            config.theme = section.get("theme", config.theme)
            config.default_delay = _get_float(section, "default_delay", config.default_delay)
            config.tolerance = _get_float(section, "tolerance", config.tolerance)
            config.ignore_recorded_delays = _get_bool(section, "ignore_recorded_delays", config.ignore_recorded_delays)
            config.use_automation_ids = _get_bool(section, "use_automation_ids", config.use_automation_ids)
            config.use_screenshots = _get_bool(section, "use_screenshots", config.use_screenshots)
            config.prefer_semantic_scripts = _get_bool(section, "prefer_semantic_scripts", config.prefer_semantic_scripts)
            config.use_ssim = _get_bool(section, "use_ssim", config.use_ssim)
            config.ssim_threshold = _get_float(section, "ssim_threshold", config.ssim_threshold)
            config.automation_backend = section.get("automation_backend", config.automation_backend)
            config.target_app_regex = section.get("target_app_regex", config.target_app_regex)
            config.semantic_wait_timeout = _get_float(section, "semantic_wait_timeout", config.semantic_wait_timeout)
            config.semantic_poll_interval = _get_float(section, "semantic_poll_interval", config.semantic_poll_interval)

    _apply_env_overrides(config, source_env)
    return config


def _determine_config_path(env: Mapping[str, str], explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit
    env_override = env.get(f"{_ENV_PREFIX}CONFIG_FILE")
    if env_override:
        return Path(env_override).expanduser()
    candidates = (
        Path(env.get("UI_TESTING_ROOT", "")) / "ui_testing.ini" if env.get("UI_TESTING_ROOT") else None,
        Path.cwd() / "ui_testing.ini",
        Path.cwd() / "ui-testing.ini",
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    return None


def _apply_env_overrides(config: RuntimeConfig, env: Mapping[str, str]) -> None:
    config.theme = env.get(f"{_ENV_PREFIX}THEME", config.theme)
    config.default_delay = _get_float(env, f"{_ENV_PREFIX}DEFAULT_DELAY", config.default_delay)
    config.tolerance = _get_float(env, f"{_ENV_PREFIX}TOLERANCE", config.tolerance)
    config.ignore_recorded_delays = _get_bool(env, f"{_ENV_PREFIX}IGNORE_RECORDED_DELAYS", config.ignore_recorded_delays)
    config.use_automation_ids = _get_bool(env, f"{_ENV_PREFIX}USE_AUTOMATION_IDS", config.use_automation_ids)
    config.use_screenshots = _get_bool(env, f"{_ENV_PREFIX}USE_SCREENSHOTS", config.use_screenshots)
    config.prefer_semantic_scripts = _get_bool(env, f"{_ENV_PREFIX}PREFER_SEMANTIC", config.prefer_semantic_scripts)
    config.use_ssim = _get_bool(env, f"{_ENV_PREFIX}USE_SSIM", config.use_ssim)
    config.ssim_threshold = _get_float(env, f"{_ENV_PREFIX}SSIM_THRESHOLD", config.ssim_threshold)
    config.automation_backend = env.get(f"{_ENV_PREFIX}AUTOMATION_BACKEND", config.automation_backend)
    config.target_app_regex = env.get(f"{_ENV_PREFIX}TARGET_APP_REGEX", config.target_app_regex)
    config.semantic_wait_timeout = _get_float(env, f"{_ENV_PREFIX}SEMANTIC_WAIT_TIMEOUT", config.semantic_wait_timeout)
    config.semantic_poll_interval = _get_float(env, f"{_ENV_PREFIX}SEMANTIC_POLL_INTERVAL", config.semantic_poll_interval)


def _get_float(source: Mapping[str, str], key: str, default: Optional[float]) -> Optional[float]:
    raw = source.get(key)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _get_bool(source: Mapping[str, str], key: str, default: Optional[bool]) -> Optional[bool]:
    raw = source.get(key)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    return default
