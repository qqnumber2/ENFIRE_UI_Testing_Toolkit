# ui_testing/action.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

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
    button: Optional[str] = None
    scroll_dx: Optional[int] = None
    scroll_dy: Optional[int] = None
    keys: Optional[List[str]] = None
    key: Optional[str] = None






