"""Custom exception types for the automation driver layer."""

from __future__ import annotations


class AutomationError(RuntimeError):
    """Base class for automation-related failures."""


class ControlNotFoundError(AutomationError):
    """Raised when a control cannot be located via its AutomationId."""


class ActionTimeoutError(AutomationError):
    """Raised when an operation exceeds the allotted wait interval."""

