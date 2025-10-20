"""Semantic automation context utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, Union

from ..driver import (
    AppiumSession,
    AutomationSession,
    attach_appium_session,
    get_session,
    reset_session,
)
from .loader import DEFAULT_MANIFEST_PATH, load_registry
from .registry import AutomationRegistry

TScreen = TypeVar("TScreen")


@dataclass
class SemanticContext:
    """Container that manages shared session/registry for semantic tests."""

    manifest_path: Path = DEFAULT_MANIFEST_PATH
    backend: str = field(default_factory=lambda: os.getenv("UI_TESTING_AUTOMATION_BACKEND", "uia"))
    appium_server_url: Optional[str] = None
    appium_capabilities: Dict[str, Any] = field(default_factory=dict)
    _session: Optional[Union[AutomationSession, AppiumSession]] = field(default=None, init=False, repr=False)
    _registry: Optional[AutomationRegistry] = field(default=None, init=False, repr=False)
    _screen_cache: Dict[Type[Any], Any] = field(default_factory=dict, init=False, repr=False)

    @property
    def session(self) -> Union[AutomationSession, AppiumSession]:
        if self._session is None:
            backend = self.backend.lower()
            if backend == "appium":
                if self.appium_server_url is None:
                    raise RuntimeError("Appium backend selected but no server URL provided.")
                self._session = attach_appium_session(self.appium_server_url, self.appium_capabilities)
            else:
                self._session = get_session()
        return self._session

    @property
    def registry(self) -> AutomationRegistry:
        if self._registry is None:
            self._registry = load_registry(self.manifest_path)
        return self._registry

    def screen(self, screen_cls: Type[TScreen]) -> TScreen:
        if screen_cls not in self._screen_cache:
            self._screen_cache[screen_cls] = screen_cls(self.session, self.registry)
        return self._screen_cache[screen_cls]

    def resolve_screen_for_group(self, group: str):
        try:
            from .screens import (
                AppBarScreen,
                BridgeReportScreen,
                HazardFormScreen,
                MapToolbarScreen,
                TerrainOverlayScreen,
            )
        except Exception:
            return None
        mapping = {
            "MapControlIds": MapToolbarScreen,
            "AppBarIds": AppBarScreen,
            "EhsrIds": HazardFormScreen,
            "BridgeIds": BridgeReportScreen,
            "TerrainIds": TerrainOverlayScreen,
        }
        screen_cls = mapping.get(group)
        if screen_cls is None:
            return None
        return self.screen(screen_cls)

    def reset(self) -> None:
        self._screen_cache.clear()
        sess = self._session
        if sess is not None and hasattr(sess, "driver"):
            try:
                sess.driver.quit()
            except Exception:
                pass
        self._session = None
        self._registry = None
        if self.backend.lower() != "appium":
            reset_session()


_GLOBAL_CONTEXT: Optional[SemanticContext] = None


def get_semantic_context(manifest_path: Optional[Path] = None, **kwargs: Any) -> SemanticContext:
    """Return a global semantic context instance."""
    global _GLOBAL_CONTEXT
    effective_manifest = manifest_path or DEFAULT_MANIFEST_PATH
    backend = kwargs.get("backend")
    if _GLOBAL_CONTEXT is None:
        _GLOBAL_CONTEXT = SemanticContext(
            manifest_path=effective_manifest,
            **{k: v for k, v in kwargs.items() if k != "manifest_path"},
        )
    else:
        needs_rebuild = False
        if effective_manifest != _GLOBAL_CONTEXT.manifest_path:
            needs_rebuild = True
        if backend and backend.lower() != _GLOBAL_CONTEXT.backend.lower():
            needs_rebuild = True
        if needs_rebuild:
            _GLOBAL_CONTEXT.reset()
            _GLOBAL_CONTEXT = SemanticContext(
                manifest_path=effective_manifest,
                **{k: v for k, v in kwargs.items() if k != "manifest_path"},
            )
        else:
            if manifest_path is not None:
                _GLOBAL_CONTEXT.manifest_path = effective_manifest
    return _GLOBAL_CONTEXT


def reset_semantic_context() -> None:
    """Clear the cached semantic context."""
    global _GLOBAL_CONTEXT
    if _GLOBAL_CONTEXT is not None:
        _GLOBAL_CONTEXT.reset()
    _GLOBAL_CONTEXT = None
