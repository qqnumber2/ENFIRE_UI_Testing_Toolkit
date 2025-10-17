"""
Assertion utilities for semantic ENFIRE automation.

These helpers bridge recorded metadata to driver operations. The current module
contains scaffolding that will evolve alongside the semantic rollout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(slots=True)
class AssertionContext:
    """Contextual information that accompanies a semantic assertion."""

    script_name: str
    action_index: int
    description: Optional[str] = None


class AssertionFailure(AssertionError):
    """Raised when a semantic assertion does not hold."""


def assert_equals(expected: Any, actual: Any, context: AssertionContext) -> None:
    """
    Placeholder equality assertion that will later call into the driver layer.

    Parameters
    ----------
    expected / actual:
        Values to compare.
    context:
        Additional metadata to enrich error messages/logging.
    """
    if expected != actual:
        raise AssertionFailure(
            f"Expected {expected!r} but found {actual!r} "
            f"(script={context.script_name}, action={context.action_index})"
        )

