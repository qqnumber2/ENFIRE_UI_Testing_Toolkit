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
try:
    from ui_testing.automation.locator import is_generic_automation_id
except Exception:  # pragma: no cover - fallback when package layout differs
    try:
        from ..automation.locator import is_generic_automation_id  # type: ignore
    except Exception:  # pragma: no cover - final fallback
        def is_generic_automation_id(value: Optional[str]) -> bool:  # type: ignore
            if not value:
                return True
            lowered = str(value).strip().lower()
            return lowered in {"", "window", "pane", "mainwindowcontrol"}

logger = logging.getLogger(__name__)


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
        self._center_over_root()

        self._values: Dict[str, tk.StringVar] = {
            "coordinates": tk.StringVar(value="(0, 0)"),
            "automation_id": tk.StringVar(value=""),
            "nearest_auto_id": tk.StringVar(value=""),
            "manifest": tk.StringVar(value=""),
            "control_type": tk.StringVar(value=""),
            "name": tk.StringVar(value=""),
            "class_name": tk.StringVar(value=""),
            "framework": tk.StringVar(value=""),
            "rectangle": tk.StringVar(value=""),
            "hierarchy": tk.StringVar(value=""),
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
        self._add_row(frame, row, "Nearest AutomationId", "nearest_auto_id")
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
        row += 1
        self._add_row(frame, row, "Hierarchy", "hierarchy", add_copy=True)

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

        element = wrapper.element_info
        raw_auto_id = getattr(element, "automation_id", "") or ""
        auto_id = str(raw_auto_id).strip()
        if is_generic_automation_id(auto_id):
            auto_id = ""
        _, nearest_auto_id = self._find_nearest_automation_id(wrapper)
        nearest_auto_id = str(nearest_auto_id).strip() if nearest_auto_id else ""

        control_type = getattr(element, "control_type", "") or ""
        name = getattr(element, "name", "") or ""
        framework = getattr(element, "framework_id", "") or ""
        class_name = getattr(element, "class_name", "") or ""
        try:
            rect = element.rectangle
            rectangle = f"({rect.left}, {rect.top}) -> ({rect.right}, {rect.bottom})"
        except Exception:
            rectangle = ""

        if auto_id:
            status_msg = "AutomationId resolved on element."
        elif nearest_auto_id:
            status_msg = f"No AutomationId on element; nearest parent '{nearest_auto_id}'."
        else:
            status_msg = "No AutomationId found in hierarchy. Consider adding one."
        self._status_var.set(status_msg)

        data.update(
            {
                "automation_id": auto_id,
                "nearest_auto_id": (
                    nearest_auto_id if nearest_auto_id and nearest_auto_id != auto_id else ""
                ),
                "control_type": control_type,
                "name": name,
                "framework": framework,
                "class_name": class_name,
                "rectangle": rectangle,
                "hierarchy": self._describe_hierarchy(wrapper),
            }
        )

        manifest_lookup_id = auto_id or nearest_auto_id or ""
        manifest_entry = self._manifest_entries.get(manifest_lookup_id)
        if manifest_entry:
            details = f"{manifest_entry.group}.{manifest_entry.name}"
            if manifest_lookup_id and manifest_lookup_id != auto_id:
                details += " [nearest parent]"
            if manifest_entry.control_type and manifest_entry.control_type != control_type:
                details += f" (manifest ctrl: {manifest_entry.control_type})"
            data["manifest"] = details
        else:
            data["manifest"] = "(not found in manifest)"
        return data

    def _find_nearest_automation_id(self, wrapper: Any) -> Tuple[Any, str]:
        """Return the closest ancestor that exposes a meaningful AutomationId."""
        current = wrapper
        depth = 0
        while current is not None and depth < 16:
            try:
                element = current.element_info
            except Exception:
                break
            auto_id = getattr(element, "automation_id", "") or ""
            if auto_id and not is_generic_automation_id(auto_id):
                return current, auto_id
            try:
                current = current.parent()
            except Exception:
                current = None
            depth += 1
        return wrapper, ""

    def _describe_hierarchy(self, wrapper: Any) -> str:
        parts: list[str] = []
        current = wrapper
        depth = 0
        while current is not None and depth < 16:
            try:
                element = current.element_info
            except Exception:
                break
            label = getattr(element, "control_type", "") or getattr(element, "class_name", "") or "Element"
            auto_id = getattr(element, "automation_id", "") or ""
            name = getattr(element, "name", "") or ""
            if auto_id and not is_generic_automation_id(auto_id):
                descriptor = f"{label}#{auto_id}"
            elif name:
                descriptor = f"{label}('{name}')"
            else:
                descriptor = label
            parts.append(descriptor)
            try:
                current = current.parent()
            except Exception:
                current = None
            depth += 1
        if not parts:
            return ""
        return " <- ".join(parts)

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
            self._center_over_root()
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        try:
            return bool(self._window.winfo_exists())
        except Exception:
            return False

    def _center_over_root(self) -> None:
        try:
            self._window.update_idletasks()
            root_x = self._root.winfo_rootx()
            root_y = self._root.winfo_rooty()
            root_w = self._root.winfo_width() or self._root.winfo_reqwidth()
            root_h = self._root.winfo_height() or self._root.winfo_reqheight()
            win_w = self._window.winfo_width() or self._window.winfo_reqwidth()
            win_h = self._window.winfo_height() or self._window.winfo_reqheight()
            x = root_x + max(0, (root_w - win_w) // 2)
            y = root_y + max(0, (root_h - win_h) // 2)
            self._window.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass
