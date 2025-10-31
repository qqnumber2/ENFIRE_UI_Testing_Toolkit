# ui_testing/app/settings.py
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class AppSettings:
    theme: str = "cosmo"
    default_delay: float = 0.5
    tolerance: float = 0.01
    ignore_recorded_delays: bool = False
    use_automation_ids: bool = True
    use_screenshots: bool = True
    prefer_semantic_scripts: bool = True
    use_ssim: bool = False
    ssim_threshold: float = 0.99
    automation_backend: str = "uia"
    appium_server_url: Optional[str] = None
    appium_capabilities: Optional[Dict[str, Any]] = None
    normalize_script: Optional[str] = None
    window_geometry: Optional[str] = None
    window_state: Optional[str] = None
    target_app_regex: Optional[str] = r".*ENFIRE.*"
    semantic_wait_timeout: float = 1.0
    semantic_poll_interval: float = 0.05

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
            use_screenshots=bool(data.get("use_screenshots", cls.use_screenshots)),
            prefer_semantic_scripts=bool(data.get("prefer_semantic_scripts", cls.prefer_semantic_scripts)),
            use_ssim=bool(data.get("use_ssim", cls.use_ssim)),
            ssim_threshold=float(data.get("ssim_threshold", cls.ssim_threshold)),
            automation_backend=str(data.get("automation_backend", cls.automation_backend)).lower(),
            appium_server_url=data.get("appium_server_url"),
            appium_capabilities=data.get("appium_capabilities") if isinstance(data.get("appium_capabilities"), dict) else None,
            normalize_script=data.get("normalize_script"),
            window_geometry=data.get("window_geometry"),
            window_state=data.get("window_state"),
            target_app_regex=data.get("target_app_regex", cls.target_app_regex),
            semantic_wait_timeout=float(data.get("semantic_wait_timeout", cls.semantic_wait_timeout)),
            semantic_poll_interval=float(data.get("semantic_poll_interval", cls.semantic_poll_interval)),
        )

    def save(self, path: Path) -> None:
        try:
            path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except Exception:
            pass


