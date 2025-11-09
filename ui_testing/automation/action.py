# ui_testing/automation/action.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

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
    drag_duration: Optional[float] = None
    path: Optional[List[List[int]]] = None
    items: Optional[List[str]] = None
    explorer: Optional[Dict[str, Any]] = None
    property_name: Optional[str] = None
    expected: Optional[Any] = None
    compare: Optional[str] = None
    semantic: Optional[Dict[str, Any]] = None
    rel_x: Optional[int] = None
    rel_y: Optional[int] = None
    rel_path: Optional[List[List[int]]] = None
    calibration_profile: Optional[str] = None






