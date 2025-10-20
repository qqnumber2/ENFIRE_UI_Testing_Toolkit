"""Public exports for the ENFIRE automation driver."""

from .core import (
    DEFAULT_WINDOW_SPEC,
    AutomationSession,
    WindowNotFoundError,
    WindowSpec,
    attach_to_window,
    get_session,
    PywinautoUnavailableError,
    reset_session,
)
from .controls import ControlSpec, UIControl, resolve_control
from .exceptions import ActionTimeoutError, AutomationError, ControlNotFoundError
from .appium import AppiumSession, attach_appium_session

__all__ = [
    "DEFAULT_WINDOW_SPEC",
    "AutomationSession",
    "WindowNotFoundError",
    "WindowSpec",
    "attach_to_window",
    "get_session",
    "PywinautoUnavailableError",
    "reset_session",
    "ControlSpec",
    "UIControl",
    "resolve_control",
    "ActionTimeoutError",
    "AutomationError",
    "ControlNotFoundError",
    "AppiumSession",
    "attach_appium_session",
]
