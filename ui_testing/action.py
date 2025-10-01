# ui_testing/action.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

@dataclass
class Action:
    action_type: str
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    screenshot: Optional[str] = None
    delay: float = 0.0
    # NEW: persisted UIA meta so JSON contains automation info
    auto_id: Optional[str] = None
    control_type: Optional[str] = None
