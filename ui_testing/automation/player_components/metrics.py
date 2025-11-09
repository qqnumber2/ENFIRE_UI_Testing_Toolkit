from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..locator import is_generic_automation_id


@dataclass
class PlaybackMetrics:
    """Tracks semantic/UIA/coordinate fallback usage and drag metadata."""

    click_counts: Dict[str, int] = field(default_factory=lambda: {"semantic": 0, "uia": 0, "coordinate": 0})
    click_history: List[str] = field(default_factory=list)
    drag_count: int = 0
    drag_history: List[str] = field(default_factory=list)

    def note_click(self, mode: str, auto_id: Optional[str], control_type: Optional[str], coords: Tuple[int, int]) -> None:
        """Record a click mode usage."""
        if mode not in self.click_counts:
            self.click_counts[mode] = 0
        self.click_counts[mode] += 1
        detail = mode
        if mode in {"semantic", "uia"}:
            if auto_id:
                detail += f":{auto_id}"
            if control_type:
                detail += f"[{control_type}]"
        else:
            detail += f":({coords[0]},{coords[1]})"
            if auto_id and not is_generic_automation_id(auto_id):
                detail += f" from {auto_id}"
        self.click_history.append(detail)

    def note_drag(self, button: str, point_count: int) -> None:
        self.drag_count += 1
        self.drag_history.append(f"{button}:{point_count}pts")

    def reset(self) -> None:
        self.click_counts = {k: 0 for k in ["semantic", "uia", "coordinate"]}
        self.click_history.clear()
        self.drag_count = 0
        self.drag_history.clear()
