"""
Core driver utilities for interacting with the ENFIRE desktop UI via UI Automation.

This module provides a thin shim around pywinauto's UIA backend, supplying
retry-aware window attachment and helper methods that downstream code can use
without depending directly on pywinauto primitives.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from pywinauto import Desktop  # type: ignore
    from pywinauto.application import Application  # type: ignore
    from pywinauto.base_wrapper import BaseWrapper  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Desktop = None  # type: ignore
    Application = None  # type: ignore
    BaseWrapper = object  # type: ignore


@dataclass(slots=True)
class WindowSpec:
    """Describes the top-level window we want to attach to."""

    title_regex: Optional[str] = None
    class_name: Optional[str] = None

    def to_query(self) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        if self.title_regex:
            query["title_re"] = self.title_regex
        if self.class_name:
            query["class_name"] = self.class_name
        return query


DEFAULT_WINDOW_SPEC = WindowSpec(title_regex=r".*ENFIRE.*", class_name=None)


class WindowNotFoundError(RuntimeError):
    """Raised when the primary application window cannot be located."""


class PywinautoUnavailableError(RuntimeError):
    """Raised when pywinauto is not installed but semantic automation is requested."""


@dataclass(slots=True)
class AutomationSession:
    """Represents an attached ENFIRE window and provides lookup helpers."""

    window: BaseWrapper
    spec: WindowSpec

    def resolve_control(
        self, *, automation_id: str, control_type: Optional[str] = None, timeout: float = 5.0
    ) -> BaseWrapper:
        """Locate a control by AutomationId, optionally constrained by control type."""
        deadline = time.monotonic() + max(timeout, 0.1)
        last_exc: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                query: Dict[str, Any] = {"auto_id": automation_id}
                if control_type:
                    query["control_type"] = control_type
                spec = self.window.child_window(**query)
                spec.wait("exists ready", timeout=0.5)
                return spec.wrapper_object()
            except Exception as exc:  # pragma: no cover - UI timing dependent
                last_exc = exc
                time.sleep(0.25)
        raise WindowNotFoundError(
            f"Control with AutomationId='{automation_id}'"
            f"{' and control_type=' + control_type if control_type else ''} not found."
        ) from last_exc


def attach_to_window(
    spec: WindowSpec = DEFAULT_WINDOW_SPEC,
    *,
    timeout: float = 12.0,
    retry_interval: float = 0.5,
) -> AutomationSession:
    """
    Attach to the ENFIRE UI using the supplied spec and return an AutomationSession.

    Parameters
    ----------
    spec:
        Criteria used to find the target window (title regex/class name).
    timeout:
        Overall timeout in seconds when searching for the window.
    retry_interval:
        Delay between successive search attempts.
    """
    if Desktop is None:
        raise PywinautoUnavailableError(
            "pywinauto is required for semantic automation but is not installed."
        )

    deadline = time.monotonic() + max(timeout, 0.1)
    last_exc: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            desktop = Desktop(backend="uia")
            window = desktop.window(**spec.to_query())
            window.wait("exists ready", timeout=retry_interval)
            return AutomationSession(window=window, spec=spec)
        except Exception as exc:  # pragma: no cover - UI timing dependent
            last_exc = exc
            time.sleep(retry_interval)
    raise WindowNotFoundError(
        f"Unable to locate ENFIRE window using spec={spec}"
    ) from last_exc


_SESSION_CACHE: Optional[AutomationSession] = None


def get_session(spec: WindowSpec = DEFAULT_WINDOW_SPEC, *, timeout: float = 12.0) -> AutomationSession:
    """
    Return a cached AutomationSession or attach to a new one if needed.

    The session is cached globally to minimize repeated window lookups during a
    test run. Call ``reset_session`` if the underlying ENFIRE instance restarts.
    """
    global _SESSION_CACHE
    if _SESSION_CACHE is not None:
        # If the spec differs, reattach to honour the new criteria.
        if _SESSION_CACHE.spec == spec:
            return _SESSION_CACHE
    _SESSION_CACHE = attach_to_window(spec=spec, timeout=timeout)
    return _SESSION_CACHE


def reset_session() -> None:
    """Clear any cached automation session."""
    global _SESSION_CACHE
    _SESSION_CACHE = None
