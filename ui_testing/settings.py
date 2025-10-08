# ui_testing/settings.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AppSettings:
    theme: str = "cosmo"
    default_delay: float = 0.5
    tolerance: float = 0.01
    ignore_recorded_delays: bool = False
    use_automation_ids: bool = True
    normalize_script: Optional[str] = None
    window_geometry: Optional[str] = None
    window_state: Optional[str] = None
    target_app_regex: Optional[str] = r".*ENFIRE.*"

    @classmethod
    def load(cls, path: Path) -> AppSettings:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        return cls(
            theme=data.get("theme", cls.theme),
            default_delay=float(data.get("default_delay", cls.default_delay)),
            tolerance=float(data.get("tolerance", cls.tolerance)),
            ignore_recorded_delays=bool(data.get("ignore_recorded_delays", cls.ignore_recorded_delays)),
            use_automation_ids=bool(data.get("use_automation_ids", cls.use_automation_ids)),
            normalize_script=data.get("normalize_script"),
            window_geometry=data.get("window_geometry"),
            window_state=data.get("window_state"),
            target_app_regex=data.get("target_app_regex", cls.target_app_regex),
        )

    def save(self, path: Path) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            pass


