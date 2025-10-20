"""Simple flake tracking using JSON persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass
class FlakeTracker:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                self._stats: Dict[str, Dict[str, int]] = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._stats = {}
        else:
            self._stats = {}

    def record_failure(self, script: str, identifier: str) -> None:
        script_stats = self._stats.setdefault(script, {})
        script_stats[identifier] = script_stats.get(identifier, 0) + 1
        self._flush()

    def _flush(self) -> None:
        try:
            self.path.write_text(json.dumps(self._stats, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            pass
