from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...driver import AutomationSession
from ..registry import AutomationRegistry
from .base import BaseScreen


def text_equals(screen: BaseScreen, control_name: str, expected: str, *, message: Optional[str] = None) -> None:
    control = screen.control(control_name)
    value = str(control.get_value() or "")
    if value != expected:
        raise AssertionError(message or f"Expected '{expected}' but found '{value}' for {control_name}")


def text_contains(screen: BaseScreen, control_name: str, expected_substring: str) -> None:
    control = screen.control(control_name)
    value = str(control.get_value() or "")
    if expected_substring not in value:
        raise AssertionError(f"Expected '{control_name}' to contain '{expected_substring}' but got '{value}'")


def toggle_state(screen: BaseScreen, control_name: str, expected: bool) -> None:
    control = screen.control(control_name)
    try:
        state = bool(control.wrapper.get_toggle_state())
    except Exception as exc:
        raise AssertionError(f"Control {control_name} does not expose toggle state: {exc}") from exc
    if state != expected:
        raise AssertionError(f"Expected toggle {control_name} to be {expected} but was {state}")


def dropdown_equals(screen: BaseScreen, control_name: str, expected: str) -> None:
    control = screen.control(control_name)
    value = str(control.get_value() or "")
    if value != expected:
        raise AssertionError(f"Expected selection '{expected}' but found '{value}' for {control_name}")
