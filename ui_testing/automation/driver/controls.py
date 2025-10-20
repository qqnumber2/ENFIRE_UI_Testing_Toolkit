"""
Control-level helpers for semantic automation of ENFIRE.

This module wraps pywinauto control handles with a consistent API that the
recorder/player can use without worrying about backend specifics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Optional

from .core import AutomationSession
from .exceptions import ControlNotFoundError, AutomationError

try:
    from pywinauto.base_wrapper import BaseWrapper  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BaseWrapper = object  # type: ignore


class ControlHandle(Protocol):  # pragma: no cover - interface only
    """Protocol describing the minimal surface we expect from concrete handles."""

    def set_value(self, value: Any) -> None:
        ...

    def get_value(self) -> Any:
        ...

    def click(self) -> None:
        ...


@dataclass(slots=True)
class ControlSpec:
    """Descriptor tying an AutomationId to a control type."""

    automation_id: str
    control_type: str | None = None


@dataclass(slots=True)
class UIControl(ControlHandle):
    """Concrete implementation of ControlHandle backed by a pywinauto wrapper."""

    wrapper: BaseWrapper

    def click(self) -> None:  # pragma: no cover - UI interaction
        self.wrapper.click_input()

    def set_value(self, value: Any) -> None:  # pragma: no cover - UI interaction
        if hasattr(self.wrapper, "set_edit_text"):
            self.wrapper.set_edit_text(str(value))
        elif hasattr(self.wrapper, "select"):
            self.wrapper.select(str(value))
        elif hasattr(self.wrapper, "set_value"):
            self.wrapper.set_value(value)
        else:
            raise ControlNotFoundError(
                f"Control {self.wrapper} does not support setting value."
            )

    def get_value(self) -> Any:
        if hasattr(self.wrapper, "get_value"):
            return self.wrapper.get_value()
        if hasattr(self.wrapper, "window_text"):
            return self.wrapper.window_text()
        if hasattr(self.wrapper, "texts"):
            texts = self.wrapper.texts()
            return texts[0] if texts else ""
        return None

    def toggle(self, *, state: Optional[bool] = None) -> None:  # pragma: no cover - UI interaction
        if not hasattr(self.wrapper, "get_toggle_state"):
            raise AutomationError("Control does not expose toggle state.")
        current = self.wrapper.get_toggle_state()
        target = 1 if state else 0
        if state is None or current != target:
            if hasattr(self.wrapper, "toggle"):
                self.wrapper.toggle()
            else:
                self.wrapper.click_input()

    def type_text(self, text: str, clear_first: bool = True) -> None:  # pragma: no cover - UI interaction
        if hasattr(self.wrapper, "set_edit_text"):
            if clear_first:
                self.wrapper.set_edit_text("")
            self.wrapper.type_keys(text, with_spaces=True, set_foreground=True)
        elif hasattr(self.wrapper, "type_keys"):
            if clear_first and hasattr(self.wrapper, "set_edit_text"):
                self.wrapper.set_edit_text("")
            self.wrapper.type_keys(text, with_spaces=True, set_foreground=True)
        else:
            raise AutomationError("Control does not support typing text.")


def resolve_control(session: AutomationSession, spec: ControlSpec, timeout: float = 5.0) -> UIControl:
    """Resolve a control spec into a UIControl wrapper using the session."""
    try:
        wrapper = session.resolve_control(
            automation_id=spec.automation_id,
            control_type=spec.control_type,
            timeout=timeout,
        )
    except Exception as exc:  # pragma: no cover - wrapper around core exception
        raise ControlNotFoundError(
            f"Unable to resolve control {spec.automation_id}"
        ) from exc
    return UIControl(wrapper=wrapper)
