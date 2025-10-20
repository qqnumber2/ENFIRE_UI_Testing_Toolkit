from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import pyautogui
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

try:
    from pywinauto import Desktop  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Desktop = None  # type: ignore

logger = logging.getLogger(__name__)

_GENERIC_AUTOMATION_IDS = {"", "window", "pane", "mainwindowcontrol"}


def _is_generic_automation_id(value: Optional[str]) -> bool:
    if not value:
        return True
    lowered = str(value).strip().lower()
    return lowered in _GENERIC_AUTOMATION_IDS


@dataclass(frozen=True)
class ManifestEntry:
    group: str
    name: str
    control_type: Optional[str] = None
    description: Optional[str] = None


class AutomationInspector:
    """Live window that displays AutomationId metadata under the mouse pointer."""

    POLL_MS = 250

    def __init__(
        self,
        root: tk.Misc,
        manifest: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None,
        automation_lookup: Optional[Dict[str, Tuple[str, str]]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        if Desktop is None:
            messagebox.showwarning(
                "Automation Inspector",
                "pywinauto is not available, so the Automation Inspector cannot run.\n\n"
                "Install pywinauto (or enable the automation backend) and try again.",
            )
            raise RuntimeError("Automation inspector unavailable (pywinauto missing).")
        self._root = root
        self._manifest_entries = self._build_manifest_index(manifest, automation_lookup)
        self._window = tk.Toplevel(root)
        self._window.title("Automation Inspector")
        self._window.geometry("520x360")
        try:
            self._window.iconbitmap("assets/app.ico")  # optional
        except Exception:
            pass
        self._window.transient(root)
        self._window.grab_set()
        self._window.protocol("WM_DELETE_WINDOW", self.close)
        self._on_close = on_close

        self._values: Dict[str, tk.StringVar] = {
            "coordinates": tk.StringVar(value="(0, 0)"),
            "automation_id": tk.StringVar(value=""),
            "manifest": tk.StringVar(value=""),
            "control_type": tk.StringVar(value=""),
            "name": tk.StringVar(value=""),
            "class_name": tk.StringVar(value=""),
            "framework": tk.StringVar(value=""),
            "rectangle": tk.StringVar(value=""),
        }
        self._status_var = tk.StringVar(
            value="Move the cursor over ENFIRE controls to inspect AutomationIds."
        )
        self._paused = tk.BooleanVar(value=False)
        self._create_widgets()
        self._running = True
        self._poll()

    def _build_manifest_index(
        self,
        manifest: Optional[Dict[str, Dict[str, Dict[str, Any]]]],
        automation_lookup: Optional[Dict[str, Tuple[str, str]]],
    ) -> Dict[str, ManifestEntry]:
        index: Dict[str, ManifestEntry] = {}
        if manifest:
            for group, mapping in manifest.items():
                if not isinstance(mapping, dict):
                    continue
                for name, payload in mapping.items():
                    auto_id: Optional[str] = None
                    ctrl = None
                    desc = None
                    if isinstance(payload, dict):
                        auto_id = payload.get("id") or payload.get("automation_id")
                        ctrl = payload.get("control_type")
                        desc = payload.get("description")
                    elif isinstance(payload, str):
                        auto_id = payload
                    if auto_id:
                        index[str(auto_id)] = ManifestEntry(
                            group=group,
                            name=name,
                            control_type=ctrl,
                            description=desc,
                        )
        if automation_lookup:
            for auto_id, (group, name) in automation_lookup.items():
                if auto_id not in index:
                    index[auto_id] = ManifestEntry(group=group, name=name)
        return index

    def _create_widgets(self) -> None:

        frame = ttk.Frame(self._window, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        header = ttk.Label(
            frame,
            text="Automation metadata under the cursor",
            font="-size 11 -weight bold",
        )
        header.grid(row=0, column=0, columnspan=3, sticky="w")

        ttk.Checkbutton(
            frame,
            text="Pause updates",
            variable=self._paused,
        ).grid(row=0, column=3, sticky="e")

        row = 1
        self._add_row(frame, row, "Coordinates", "coordinates")
        row += 1
        self._add_row(frame, row, "AutomationId", "automation_id", add_copy=True)
        row += 1
        self._add_row(frame, row, "Manifest group/name", "manifest", add_copy=True)
        row += 1
        self._add_row(frame, row, "Control type", "control_type")
        row += 1
        self._add_row(frame, row, "Name", "name")
        row += 1
        self._add_row(frame, row, "Framework", "framework")
        row += 1
        self._add_row(frame, row, "Class name", "class_name")
        row += 1
        self._add_row(frame, row, "Bounding rect", "rectangle")

        status = ttk.Label(
            frame,
            textvariable=self._status_var,
            wraplength=480,
            bootstyle="secondary",
        )
        status.grid(row=row + 1, column=0, columnspan=4, sticky="we", pady=(12, 0))

        frame.grid_columnconfigure(1, weight=1)

    def _add_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        key: str,
        *,
        add_copy: bool = False,
    ) -> None:
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
        entry = ttk.Entry(parent, textvariable=self._values[key], state="readonly")
        entry.grid(row=row, column=1, columnspan=2, sticky="we", pady=4)
        if add_copy:
            ttk.Button(
                parent,
                text="Copy",
                command=lambda k=key: self._copy_value(k),
                bootstyle="secondary",
            ).grid(row=row, column=3, sticky="e", padx=(8, 0))

    def _copy_value(self, key: str) -> None:
        value = self._values.get(key)
        if value is None:
            return
        try:
            text = value.get()
            self._window.clipboard_clear()
            self._window.clipboard_append(text)
            self._status_var.set(f"Copied {key} to clipboard.")
        except Exception as exc:  # pragma: no cover - UI only
            logger.debug("Clipboard copy failed: %s", exc)

    def _lookup_element(self) -> Dict[str, str]:
        try:
            pos = pyautogui.position()
        except Exception as exc:  # pragma: no cover - UI only
            logger.debug("Unable to read cursor position: %s", exc)
            return {}
        x, y = int(pos.x), int(pos.y)
        data: Dict[str, str] = {"coordinates": f"({x}, {y})"}
        try:
            wrapper = Desktop(backend="uia").from_point(x, y)
        except Exception:
            wrapper = None
        if wrapper is None:
            return data
        target_wrapper, auto_id = self._select_preferred_wrapper(wrapper)
        element = target_wrapper.element_info if target_wrapper is not None else wrapper.element_info
        control_type = getattr(element, "control_type", "") or ""
        name = getattr(element, "name", "") or ""
        framework = getattr(element, "framework_id", "") or ""
        class_name = getattr(element, "class_name", "") or ""
        try:
            rect = element.rectangle
            rectangle = f"({rect.left}, {rect.top}) → ({rect.right}, {rect.bottom})"
        except Exception:
            rectangle = ""
        data.update(
            {
                "automation_id": auto_id,
                "control_type": control_type,
                "name": name,
                "framework": framework,
                "class_name": class_name,
                "rectangle": rectangle,
            }
        )
        manifest_entry = self._manifest_entries.get(auto_id or "")
        if manifest_entry:
            details = f"{manifest_entry.group}.{manifest_entry.name}"
            if manifest_entry.control_type and manifest_entry.control_type != control_type:
                details += f" (manifest ctrl: {manifest_entry.control_type})"
            data["manifest"] = details
        else:
            data["manifest"] = "(not found in manifest)"
        return data

    def _select_preferred_wrapper(self, wrapper: Any) -> Tuple[Any, str]:
        """Return the nearest wrapper with a meaningful AutomationId."""
        current = wrapper
        depth = 0
        fallback_match: Optional[Tuple[Any, str]] = None
        while current is not None and depth < 12:
            try:
                element = current.element_info
            except Exception:
                break
            auto_id = getattr(element, "automation_id", "") or ""
            if auto_id:
                if not _is_generic_automation_id(auto_id):
                    return current, auto_id
                if fallback_match is None and auto_id in self._manifest_entries:
                    fallback_match = (current, auto_id)
            try:
                current = current.parent()
            except Exception:
                current = None
            depth += 1
        if fallback_match is not None:
            return fallback_match
        # fall back to original even if auto_id is generic
        try:
            auto_id = getattr(wrapper.element_info, "automation_id", "") or ""
        except Exception:
            auto_id = ""
        return wrapper, auto_id

    def _poll(self) -> None:
        if not self._running:
            return
        if not self._paused.get():
            info = self._lookup_element()
            if info:
                for key, value in info.items():
                    if key in self._values:
                        self._values[key].set(value)
        self._window.after(self.POLL_MS, self._poll)

    def close(self) -> None:
        self._running = False
        try:
            self._window.destroy()
        except Exception:
            pass
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass

    def focus(self) -> None:
        try:
            self._window.deiconify()
            self._window.lift()
            self._window.focus_force()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        try:
            return bool(self._window.winfo_exists())
        except Exception:
            return False
