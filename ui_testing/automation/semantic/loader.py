"""Utilities for loading semantic automation resources."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .registry import AutomationRegistry

DEFAULT_MANIFEST_PATH = Path("ui_testing/automation/manifest/automation_ids.json")


def load_registry(manifest_path: Optional[Path] = None) -> AutomationRegistry:
    """Load the AutomationId manifest into an AutomationRegistry instance."""
    registry = AutomationRegistry()
    path = manifest_path or DEFAULT_MANIFEST_PATH
    registry.load_from_file(path)
    return registry
