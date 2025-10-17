# ui_testing/explorer.py
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from ui_testing.action import Action

logger = logging.getLogger(__name__)

try:
    from pywinauto import Desktop, keyboard
    from pywinauto.application import Application
    from pywinauto.timings import TimeoutError as PyWinTimeoutError
except Exception:  # pragma: no cover - optional dependency during packaging
    Desktop = None  # type: ignore[assignment]
    Application = None  # type: ignore[assignment]
    keyboard = None  # type: ignore[assignment]
    PyWinTimeoutError = RuntimeError  # type: ignore[assignment]

WINDOW_CLASS = "CabinetWClass"
DEFAULT_WAIT = 8.0


class ExplorerController:
    """Translate explorer.* actions into Windows Explorer automation."""

    def __init__(self, base_path: Optional[Path] = None) -> None:
        self.base_path = base_path
        self._app: Optional[Application] = None
        self._window = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle(self, action: Action) -> None:
        if Desktop is None or Application is None or keyboard is None:
            logger.warning("Explorer automation unavailable (pywinauto missing).")
            return

        action_type = action.action_type or ""
        dispatch: Dict[str, Callable[[Action], None]] = {
            "explorer.open": self._handle_open,
            "explorer.navigate": self._handle_navigate,
            "explorer.select": self._handle_select,
            "explorer.ensure": self._handle_ensure,
            "explorer.copy": self._handle_copy,
            "explorer.delete": self._handle_delete,
            "explorer.search": self._handle_search,
        }
        handler = dispatch.get(action_type)
        if handler is None:
            logger.warning("Unknown explorer action: %s", action_type)
            return
        try:
            handler(action)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Explorer action %s failed: %s", action_type, exc)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------
    def _handle_open(self, action: Action) -> None:
        payload = action.explorer or {}
        path = self._resolve_path(payload.get("path"))
        if path is None:
            raise ValueError("explorer.open requires 'path'")
        if path.is_dir():
            logger.info("Explorer: open folder %s", path)
            nav_action = Action(action_type="explorer.navigate", explorer={"path": str(path)})
            self._handle_navigate(nav_action)
            return
        logger.info("Explorer: launch %s", path)
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["explorer", str(path)])
        self._wait_for_window(path.parent if path.parent.exists() else None)

    def _handle_navigate(self, action: Action) -> None:
        payload = action.explorer or {}
        path = self._resolve_path(payload.get("path"))
        if path is None:
            raise ValueError("explorer.navigate requires 'path'")
        window = self._ensure_window(prefer_path=path) or self._open_blank_window()
        if window is None:
            raise RuntimeError("Explorer window not available")
        self._focus_window(window)
        logger.info("Explorer: navigate to %s", path)
        keyboard.send_keys("^l", set_foreground=False)
        keyboard.send_keys(str(path) + "{ENTER}", set_foreground=False, with_spaces=True)
        self._wait_for_path(path)

    def _handle_select(self, action: Action) -> None:
        names = self._extract_items(action)
        if not names:
            raise ValueError("explorer.select requires 'items'")
        payload = action.explorer or {}
        path = self._resolve_path(payload.get("path"))
        window = self._ensure_window(prefer_path=path)
        if window is None:
            window = self._open_blank_window(path)
        if window is None:
            raise RuntimeError("Explorer window not available")
        self._focus_window(window)
        if path is not None:
            self._handle_navigate(action)
        listview = self._locate_list(window)
        if listview is None:
            raise RuntimeError("Explorer list view not found")
        failed: List[str] = []
        for item in names:
            try:
                element = listview.child_window(title=item, control_type="ListItem")
                element.wait("ready", timeout=DEFAULT_WAIT)
                element.select()
            except Exception:
                failed.append(item)
        if failed:
            logger.warning("Explorer: failed to select items: %s", ", ".join(failed))
        else:
            logger.info("Explorer: selected %s", ", ".join(names))

    def _handle_ensure(self, action: Action) -> None:
        payload = action.explorer or {}
        path = self._resolve_path(payload.get("path"))
        if path is None:
            return
        kind = (payload.get("kind") or "").lower()
        template = payload.get("template")
        if kind == "dir" or (kind == "" and payload.get("ensure_dir", True)):
            path.mkdir(parents=True, exist_ok=True)
            logger.info("Explorer: ensured directory %s", path)
        else:
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() and template:
                src = self._resolve_path(template)
                if src and src.is_file():
                    self._copy_files([src], parent, rename=path.name)
            elif not path.exists():
                path.touch()
            logger.info("Explorer: ensured file %s", path)

    def _handle_copy(self, action: Action) -> None:
        payload = action.explorer or {}
        destination = self._resolve_path(payload.get("destination"))
        if destination is None:
            raise ValueError("explorer.copy requires 'destination'")
        items = self._collect_paths(action)
        if not items:
            raise ValueError("explorer.copy requires source 'items'")
        destination.mkdir(parents=True, exist_ok=True)
        self._copy_files(items, destination)
        logger.info("Explorer: copied %d item(s) to %s", len(items), destination)

    def _handle_delete(self, action: Action) -> None:
        payload = action.explorer or {}
        recycle = bool(payload.get("recycle", True))
        items = self._collect_paths(action)
        if not items:
            raise ValueError("explorer.delete requires 'items'")
        for path in items:
            try:
                if recycle:
                    self._send_to_recycle(path)
                else:
                    if path.is_dir():
                        for child in path.rglob("*"):
                            if child.is_file():
                                child.unlink(missing_ok=True)
                        path.rmdir()
                    else:
                        path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Explorer: delete failed for %s (%s)", path, exc)
        logger.info("Explorer: delete complete")

    def _handle_search(self, action: Action) -> None:
        payload = action.explorer or {}
        query = payload.get("query") or ""
        if not query:
            raise ValueError("explorer.search requires 'query'")
        window = self._ensure_window()
        if window is None:
            window = self._open_blank_window()
        if window is None:
            raise RuntimeError("Explorer window not available")
        self._focus_window(window)
        try:
            search_box = window.child_window(auto_id="SearchEditBox", control_type="Edit")
            search_box.wait("ready", timeout=DEFAULT_WAIT)
            search_box.set_edit_text(query)
            keyboard.send_keys("{ENTER}", set_foreground=False)
        except Exception:
            keyboard.send_keys("^e", set_foreground=False)
            keyboard.send_keys(query + "{ENTER}", set_foreground=False, with_spaces=True)
        logger.info("Explorer: search for %s", query)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ensure_window(self, prefer_path: Optional[Path] = None):
        if Desktop is None:
            return None
        try:
            if self._window is not None and self._window.exists():
                return self._window
        except Exception:
            self._window = None
        windows = Desktop(backend="uia").windows(class_name=WINDOW_CLASS)
        if prefer_path is not None:
            folder_token = prefer_path.name.lower() or str(prefer_path).lower()
            for win in windows:
                try:
                    if folder_token in win.window_text().lower():
                        self._window = win
                        return win
                except Exception:
                    continue
        if windows:
            self._window = windows[0]
            return self._window
        return None

    def _open_blank_window(self, path: Optional[Path] = None):
        target = str(path) if path else "::{" + "FBB3477E-C9E4-4B3B-A2BA-D3F5D3CD46F9" + "}"  # This PC
        subprocess.Popen(["explorer", target])
        return self._wait_for_window(path)

    def _wait_for_window(self, path: Optional[Path]) -> Optional[object]:
        if Desktop is None:
            return None
        deadline = time.time() + DEFAULT_WAIT
        title_token = (path.name.lower() if path else "").strip()
        while time.time() < deadline:
            windows = Desktop(backend="uia").windows(class_name=WINDOW_CLASS)
            if title_token:
                for win in windows:
                    try:
                        if title_token in win.window_text().lower():
                            self._window = win
                            return win
                    except Exception:
                        continue
            if windows:
                self._window = windows[0]
                return self._window
            time.sleep(0.4)
        return self._ensure_window()

    def _focus_window(self, window) -> None:
        try:
            window.set_focus()
        except Exception:
            try:
                window.set_keyboard_focus()
            except Exception:
                pass

    def _wait_for_path(self, path: Path) -> None:
        if Desktop is None:
            return
        deadline = time.time() + DEFAULT_WAIT
        token = path.name.lower()
        while time.time() < deadline:
            window = self._ensure_window(path)
            if window is None:
                time.sleep(0.4)
                continue
            try:
                current = window.window_text().lower()
                if token in current:
                    return
            except Exception:
                pass
            time.sleep(0.4)

    def _locate_list(self, window):
        try:
            listview = window.child_window(title="Items View", control_type="List")
            listview.wait("exists ready", timeout=DEFAULT_WAIT)
            return listview
        except (AttributeError, PyWinTimeoutError, Exception):
            try:
                return window.child_window(control_type="List")
            except Exception:
                return None

    def _resolve_path(self, value: Optional[str]) -> Optional[Path]:
        if value is None:
            return None
        candidate = Path(os.path.expandvars(os.path.expanduser(value)))
        if not candidate.is_absolute() and self.base_path:
            candidate = (self.base_path / candidate).resolve()
        return candidate

    def _extract_items(self, action: Action) -> List[str]:
        items: List[str] = []
        if action.items:
            items.extend(action.items)
        payload = action.explorer or {}
        explorer_items = payload.get("items")
        if isinstance(explorer_items, list):
            items.extend([str(it) for it in explorer_items])
        return [item for item in items if item]

    def _collect_paths(self, action: Action) -> List[Path]:
        payload = action.explorer or {}
        data = payload.get("paths") or payload.get("items") or action.items
        if data is None:
            return []
        if isinstance(data, (str, Path)):
            data = [data]
        resolved: List[Path] = []
        for entry in data:
            p = self._resolve_path(str(entry))
            if p is not None:
                resolved.append(p)
        return resolved

    def _copy_files(
        self, sources: Iterable[Path], destination: Path, *, rename: Optional[str] = None
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for path in sources:
            if not path.exists():
                logger.warning("Explorer: source not found %s", path)
                continue
            target_name = rename if rename else path.name
            target = destination / target_name
            if path.is_dir():
                self._copytree(path, target)
            else:
                self._copyfile(path, target)

    def _copyfile(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as fsrc, dst.open("wb") as fdst:
            fdst.write(fsrc.read())

    def _copytree(self, src: Path, dst: Path) -> None:
        for root, dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            target_dir = dst / rel
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                self._copyfile(Path(root) / name, target_dir / name)

    def _send_to_recycle(self, path: Path) -> None:
        try:
            import winshell  # type: ignore

            winshell.delete_file(str(path), no_confirm=True, allow_undo=True)
        except Exception:
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
