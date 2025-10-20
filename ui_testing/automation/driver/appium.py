"""Appium driver scaffolding for ENFIRE automation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    from appium import webdriver
except Exception:  # pragma: no cover - optional dependency
    webdriver = None  # type: ignore


@dataclass
class AppiumSession:
    """Lightweight wrapper around an Appium WebDriver session."""

    driver: "webdriver.Remote"

    def resolve_control(self, automation_id: str, control_type: Optional[str] = None):  # pragma: no cover - placeholder
        locator = {"automationId": automation_id}
        if control_type:
            locator["className"] = control_type
        return self.driver.find_element("windows_uiautomation", locator)


def attach_appium_session(server_url: str, capabilities: Dict[str, Any]) -> AppiumSession:
    if webdriver is None:
        raise RuntimeError("Appium Python client not available. Install Appium-Python-Client.")
    driver = webdriver.Remote(command_executor=server_url, desired_capabilities=capabilities)
    return AppiumSession(driver=driver)
