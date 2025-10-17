import json
import logging
import time
import ctypes
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from pynput import mouse, keyboard
from pynput.keyboard import Key, KeyCode
import pyautogui
from PIL import Image
import win32gui

# EXE-safe imports
try:
    from ui_testing.automation.action import Action  # type: ignore
    from ui_testing.automation.util import ensure_png_name  # type: ignore
except Exception:
    try:
        from .action import Action  # type: ignore
        from .util import ensure_png_name  # type: ignore
    except Exception:
        from action import Action  # type: ignore  # noqa: F401
        from util import ensure_png_name  # type: ignore

# add near the top, after other imports
try:
    from pywinauto import Desktop
except Exception:
    Desktop = None  # type: ignore

try:
    import win32com.client as win32com_client  # type: ignore
except Exception:
    win32com_client = None  # type: ignore

logger = logging.getLogger(__name__)

@dataclass
class RecorderConfig:
    scripts_dir: Path
    images_dir: Path
    results_dir: Path
    script_name: str            # e.g. "12_EBS/6/6.7_ATTACHMENTS_TAB"
    taskbar_crop_px: int = 60
    gui_hwnd: Optional[int] = None
    always_record_text: bool = True
    default_delay: float = 0.5 

class Recorder:
    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        self.actions: List[Action] = []
        self.running = False
        self._text_buffer: List[str] = []
        self._mouse_listener: Optional[mouse.Listener] = None
        self._kb_listener: Optional[keyboard.Listener] = None
        # All shots grouped under index 0 to produce 0_000O / 0_000T naming
        self._shot_idx = 0
        self._group_idx = 0   # use group 0 so names are 0_000O.png, 0_001O.png
        self._last_ts = None
        self.default_delay = config.default_delay
        self.current_delay = config.default_delay
        self._pressed_buttons: Dict[str, Dict[str, object]] = {}
        self._move_threshold_px = 1
        self._move_min_interval = 0.01
        self._modifiers: Set[str] = set()
        self._primary_bounds = self._init_primary_bounds()
        self._last_explorer_click: Optional[Tuple[str, str, float]] = None

    def start(self) -> None:
        self.running = True
        logger.info("Recorder started. Press 'p' to take a screenshot. Use GUI Stop to finish.")
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_move=self._on_move,
            on_scroll=self._on_scroll,
        )
        self._kb_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener.start()
        self._kb_listener.start()
        self._last_ts = time.perf_counter()

    def _elapsed(self) -> float:
        """Seconds since last recorded action; also resets the timer anchor."""
        now = time.perf_counter()
        if self._last_ts is None:
            self._last_ts = now
            return 0.0
        dt = now - self._last_ts
        self._last_ts = now
        # Clamp to a sane range; tweak if you want
        if dt < 0:
            dt = 0.0
        if dt > 10:
            dt = 10.0
        return round(dt, 3)


    def stop(self) -> None:
        if not self.running:
            return
        self._commit_text_buffer()
        self.running = False
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kb_listener:
            self._kb_listener.stop()
        self._pressed_buttons.clear()
        self._modifiers.clear()
        self._save_json()

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if not self.running:
            return

        if isinstance(key, KeyCode) and key.char and key.char.lower() == "f" and not self._modifiers:
            try:
                self._commit_text_buffer()
            except Exception:
                pass
            import threading
            threading.Thread(target=self.stop, daemon=True).start()
            return

        mod = self._normalize_modifier(key)
        if mod:
            self._modifiers.add(mod)
            return

        try:
            if isinstance(key, KeyCode) and key.char:
                if key.char == "p" and not self._modifiers:
                    self._commit_text_buffer()
                    self.record_screenshot()
                    return
        except Exception:
            pass

        key_name = self._key_name(key)
        non_shift_mods = {m for m in self._modifiers if m != "shift"}

        if key_name:
            if non_shift_mods or ("shift" in self._modifiers and key_name not in {"backspace", "enter"}):
                self._record_hotkey(key_name)
                return
            if key_name == "backspace":
                if self._text_buffer:
                    self._text_buffer.pop()
                    logger.info("Recorded: backspace (buffer)")
                else:
                    self._record_keypress(key_name)
                return
            if key_name in {"tab", "delete", "insert", "home", "end", "pageup", "pagedown", "up", "down", "left", "right"}:
                self._record_keypress(key_name)
                return
            if key_name == "enter":
                ch = "\n"
            else:
                ch = None
        else:
            ch = None

        if isinstance(key, KeyCode) and key.char is not None and ch is None:
            ch = key.char
        elif key == Key.space:
            ch = " "

        if ch is not None:
            if ch == "p" and not self._modifiers:
                return  # 'p' reserved for screenshot
            if any(mod in {"ctrl", "alt", "win"} for mod in self._modifiers):
                return
            self._text_buffer.append(ch)
            safe = "<ENTER>" if ch == "\n" else ch
            logger.info(f"Recorded: type (buffer) '{safe}'")

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        mod = self._normalize_modifier(key)
        if mod:
            self._modifiers.discard(mod)
            return
        if key == Key.enter:
            self._commit_text_buffer()

    def _commit_text_buffer(self) -> None:
        if not self._text_buffer:
            return
        text = "".join(self._text_buffer)
        self._text_buffer.clear()
        self.actions.append(Action(action_type='type', text=text, delay=self._elapsed()))
        logger.info(f"Recorded: type '{text.replace(chr(10), '<ENTER>')}'")

    def _resolve_automation_target(self, x: int, y: int) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
        if Desktop is None:
            return None, None, None
        try:
            element = Desktop(backend="uia").from_point(x, y)
        except Exception:
            return None, None, None
        target, auto_id, ctrl_type = self._locate_element_with_auto_id(element)
        return target, auto_id, ctrl_type

    def _locate_element_with_auto_id(self, element: Any) -> Tuple[Optional[Any], Optional[str], Optional[str]]:
        current = element
        ctrl_type_hint: Optional[str] = None
        depth = 0
        while current is not None and depth < 8:
            try:
                info = current.element_info
            except Exception:
                break
            auto_id = getattr(info, "automation_id", None) or None
            ctrl_type = getattr(info, "control_type", None) or ctrl_type_hint
            if auto_id:
                if element is not None and current is not element:
                    try:
                        logger.debug("Resolved AutomationId '%s' via ancestor (depth=%d)", auto_id, depth)
                    except Exception:
                        pass
                return current, auto_id, ctrl_type
            ctrl_type_hint = ctrl_type
            try:
                current = current.parent()
            except Exception:
                current = None
            depth += 1
        return element, None, ctrl_type_hint


    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not self.running:
            return

        if not self._in_primary_monitor(x, y):
            logger.info("Ignored: click outside primary monitor")
            return

        if self._handle_explorer_click(x, y, pressed):
            return

        btn_name = self._button_name(button)

        if pressed:
            if self._point_on_gui(x, y):
                logger.info("Ignored: click on recorder GUI")
                return

            self._commit_text_buffer()

            auto_id = None
            ctrl_type = None
            target_elem = None
            if Desktop is not None:
                target_elem, auto_id, ctrl_type = self._resolve_automation_target(x, y)

            action = Action(
                action_type='mouse_down',
                x=x,
                y=y,
                delay=self._elapsed(),
                button=btn_name,
            )
            if auto_id:
                action.auto_id = auto_id
            if ctrl_type:
                action.control_type = ctrl_type

            self.actions.append(action)
            self._pressed_buttons[btn_name] = {
                "last_move_pos": (x, y),
                "last_move_time": time.perf_counter(),
                "path_points": [(int(x), int(y))],
                "start_time": time.perf_counter(),
                "auto_id": auto_id,
                "control_type": ctrl_type,
                "down_index": len(self.actions) - 1,
                "down_delay": action.delay,
            }
            meta = f" [auto_id={auto_id}, ctrl={ctrl_type}]" if auto_id or ctrl_type else ""
            logger.info(f"Recorded: mouse_down({btn_name}) at ({x}, {y}){meta}")

            if target_elem is not None and auto_id:
                self._append_assert_property(auto_id, ctrl_type, target_elem)
            return

        state = self._pressed_buttons.pop(btn_name, None)
        in_gui = self._point_on_gui(x, y)
        if state is None and in_gui:
            logger.info("Ignored: release on recorder GUI")
            return

        self._commit_text_buffer()
        release_delay = self._elapsed()
        click_recorded = False

        if state is not None:
            self._record_mouse_move(btn_name, x, y, force=True)
            path = state.get("path_points") or []
            total_distance = 0
            drag_performed = False
            if len(path) > 1:
                sampled = self._downsample_path(path)
                if sampled:
                    for (x1, y1), (x2, y2) in zip(sampled, sampled[1:]):
                        total_distance += abs(x2 - x1) + abs(y2 - y1)
                    if total_distance >= 6:
                        drag_action = Action(
                            action_type='drag',
                            x=sampled[-1][0],
                            y=sampled[-1][1],
                            delay=release_delay,
                            button=btn_name,
                            path=[[int(px), int(py)] for px, py in sampled],
                        )
                        self.actions.append(drag_action)
                        logger.info(f"Recorded: drag({btn_name}) path_points={len(sampled)} distance={total_distance}")
                        release_delay = self._elapsed()
                        drag_performed = True
            if not drag_performed:
                down_index = state.get("down_index")
                auto_id = state.get("auto_id")
                ctrl_type = state.get("control_type")
                down_delay = state.get("down_delay")
                if down_index is not None and 0 <= down_index < len(self.actions):
                    down_action = self.actions[down_index]
                    down_action.action_type = 'click'
                    down_action.x = int(x)
                    down_action.y = int(y)
                    down_action.button = btn_name
                    down_action.auto_id = auto_id
                    down_action.control_type = ctrl_type
                    if down_delay is not None:
                        down_action.delay = down_delay
                else:
                    click_action = Action(
                        action_type='click',
                        x=int(x),
                        y=int(y),
                        delay=release_delay,
                        button=btn_name,
                    )
                    if auto_id:
                        click_action.auto_id = auto_id
                    if ctrl_type:
                        click_action.control_type = ctrl_type
                    self.actions.append(click_action)
                meta = f" [auto_id={auto_id}, ctrl={ctrl_type}]" if auto_id or ctrl_type else ""
                logger.info(f"Recorded: click({btn_name}) at ({x}, {y}){meta}")
                click_recorded = True

        if click_recorded:
            return

        action = Action(
            action_type='mouse_up',
            x=x,
            y=y,
            delay=release_delay,
            button=btn_name,
        )
        self.actions.append(action)
        logger.info(f"Recorded: mouse_up({btn_name}) at ({x}, {y})")

    def _append_assert_property(self, auto_id: str, ctrl_type: Optional[str], element: Any) -> None:
        extracted = self._extract_element_property(element)
        if not extracted:
            return
        prop_name, expected = extracted
        if self.actions:
            last = self.actions[-1]
            if (
                getattr(last, "action_type", None) == "assert.property"
                and getattr(last, "auto_id", None) == auto_id
                and getattr(last, "expected", None) == expected
                and getattr(last, "property_name", "name") == prop_name
            ):
                return
        action = Action(
            action_type="assert.property",
            delay=0.0,
            auto_id=auto_id,
            control_type=ctrl_type,
            property_name=prop_name,
            expected=expected,
            compare="equals",
        )
        self.actions.append(action)
        logger.debug(
            "Recorded: assert.property auto_id=%s property=%s expected=%s", auto_id, prop_name, expected
        )

    def _extract_element_property(self, element: Any) -> Optional[Tuple[str, str]]:
        try:
            if hasattr(element, "get_value"):
                val = element.get_value()
                if val is not None:
                    val_str = str(val).strip()
                    if val_str:
                        return ("value", val_str)
        except Exception:
            pass
        try:
            txt = element.window_text()
            if txt:
                txt = str(txt).strip()
                if txt:
                    return ("name", txt)
        except Exception:
            pass
        info = getattr(element, "element_info", None)
        if info is not None:
            for attr in ("name", "rich_text", "window_text"):
                val = getattr(info, attr, None)
                if val:
                    val = str(val).strip()
                    if val:
                        return ("name", val)
        try:
            if hasattr(element, "texts"):
                texts = element.texts()
                for entry in texts or []:
                    if entry:
                        txt = str(entry).strip()
                        if txt:
                            return ("name", txt)
        except Exception:
            pass
        return None


    def _normalize_modifier(self, key) -> Optional[str]:
        if key in {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}:
            return "ctrl"
        if key in {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}:
            return "alt"
        if key in {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}:
            return "shift"
        win_keys = [getattr(keyboard.Key, name, None) for name in ("cmd", "cmd_l", "cmd_r", "win")]
        if key in {k for k in win_keys if k is not None}:
            return "win"
        return None

    def _key_name(self, key) -> Optional[str]:
        if isinstance(key, KeyCode) and key.char:
            ch = key.char
            mods = set(self._modifiers)
            non_shift_mods = {m for m in mods if m != "shift"}
            if non_shift_mods:
                if ch.isprintable():
                    return ch.lower()
                if 'ctrl' in non_shift_mods and len(ch) == 1:
                    code = ord(ch)
                    if 1 <= code <= 26:
                        return chr(code + 96)
                return None
            if mods == {"shift"}:
                return None
            if ch.isprintable():
                return None
            return ch.lower()
        mapping = {
            keyboard.Key.enter: "enter",
            keyboard.Key.tab: "tab",
            keyboard.Key.backspace: "backspace",
            keyboard.Key.delete: "delete",
            keyboard.Key.insert: "insert",
            keyboard.Key.home: "home",
            keyboard.Key.end: "end",
            keyboard.Key.page_up: "pageup",
            keyboard.Key.page_down: "pagedown",
            keyboard.Key.up: "up",
            keyboard.Key.down: "down",
            keyboard.Key.left: "left",
            keyboard.Key.right: "right",
        }
        return mapping.get(key)

    def _record_keypress(self, key_name: str) -> None:
        self._commit_text_buffer()
        action = Action(action_type='key', key=key_name, delay=self._elapsed())
        self.actions.append(action)
        logger.info(f"Recorded: key '{key_name}'")

    def _record_hotkey(self, key_name: str) -> None:
        if key_name == "tab" and "alt" in self._modifiers:
            return
        ordered: List[str] = []
        for mod in ("ctrl", "alt", "shift", "win"):
            if mod in self._modifiers:
                ordered.append(mod)
        if key_name not in ordered:
            ordered.append(key_name)
        self._commit_text_buffer()
        action = Action(action_type='hotkey', keys=ordered, delay=self._elapsed())
        self.actions.append(action)
        logger.info("Recorded: hotkey %s", "+".join(ordered))

    def _handle_explorer_click(self, x: int, y: int, pressed: bool) -> bool:
        if Desktop is None or win32com_client is None:
            return False
        try:
            elem = Desktop(backend="uia").from_point(x, y)
            top = elem.top_level_parent()
            info = top.element_info
            if getattr(info, "class_name", "") != "CabinetWClass":
                return False
            if not pressed:
                return True  # swallow release so we don't emit mouse_up
            folder_path = self._get_explorer_directory(getattr(info, "handle", None))
            item_name = getattr(elem.element_info, "name", "") or ""
            now = time.perf_counter()

            # Double-click detection -> treat as open/navigate
            if (
                self._last_explorer_click
                and now - self._last_explorer_click[2] < 0.45
                and self._last_explorer_click[0] == (str(folder_path) if folder_path else "")
                and self._last_explorer_click[1] == item_name
            ):
                payload: Dict[str, object] = {}
                if folder_path and item_name:
                    payload["path"] = str((folder_path / item_name).resolve())
                elif folder_path:
                    payload["path"] = str(folder_path)
                else:
                    payload["path"] = item_name
                action = Action(action_type="explorer.open", delay=self._elapsed(), explorer=payload)
                self.actions.append(action)
                logger.info("Recorded: explorer.open path=%s", payload.get("path"))
                self._last_explorer_click = None
                return True

            # Single click -> selection
            if not item_name and folder_path is None:
                return True
            payload: Dict[str, object] = {}
            if folder_path:
                payload["path"] = str(folder_path)
            if item_name:
                payload["items"] = [item_name]
            self._commit_text_buffer()
            action = Action(
                action_type="explorer.select",
                delay=self._elapsed(),
                items=[item_name] if item_name else None,
                explorer=payload or None,
            )
            self.actions.append(action)
            logger.info("Recorded: explorer.select path=%s item=%s", payload.get("path"), item_name or "<none>")
            self._last_explorer_click = (
                str(folder_path) if folder_path else "",
                item_name,
                now,
            )
            return True
        except Exception as exc:
            logger.debug("Explorer capture failed: %s", exc)
            return False

    def _get_explorer_directory(self, hwnd: Optional[int]) -> Optional[Path]:
        if hwnd is None or win32com_client is None:
            return None
        try:
            shell = win32com_client.Dispatch("Shell.Application")
            target_hwnd = int(hwnd)
            for window in shell.Windows():
                try:
                    if int(window.HWND) != target_hwnd:
                        continue
                    url = window.LocationURL or ""
                    if not url.lower().startswith("file://"):
                        continue
                    path_str = unquote(url).replace("file:///", "").replace("file://", "")
                    if path_str:
                        return Path(path_str)
                except Exception:
                    continue
        except Exception:
            return None
        return None

    def _button_name(self, button) -> str:
        name = getattr(button, "name", None)
        if name:
            return name
        if button == getattr(mouse.Button, "left", None):
            return "left"
        if button == getattr(mouse.Button, "right", None):
            return "right"
        if button == getattr(mouse.Button, "middle", None):
            return "middle"
        return str(button)

    def _record_mouse_move(self, btn_name: str, x: int, y: int, force: bool = False) -> None:
        state = self._pressed_buttons.get(btn_name)
        if state is None:
            return

        if not self._in_primary_monitor(x, y):
            return

        last_pos = state.get("last_move_pos")
        now = time.perf_counter()
        if last_pos is not None:
            dx = abs(x - last_pos[0])
            dy = abs(y - last_pos[1])
            if not force and dx < self._move_threshold_px and dy < self._move_threshold_px:
                last_time = state.get("last_move_time", 0.0)
                if now - last_time < self._move_min_interval:
                    return
            if force and last_pos == (x, y):
                return

        state["last_move_pos"] = (x, y)
        state["last_move_time"] = now
        path = state.setdefault("path_points", [])
        if not path:
            path.append((int(x), int(y)))
        else:
            last_px, last_py = path[-1]
            if force or abs(x - last_px) >= self._move_threshold_px or abs(y - last_py) >= self._move_threshold_px:
                path.append((int(x), int(y)))

    def _on_move(self, x: int, y: int) -> None:
        if not self.running or not self._pressed_buttons:
            return
        if not self._in_primary_monitor(x, y):
            return
        for btn_name in list(self._pressed_buttons.keys()):
            self._record_mouse_move(btn_name, x, y)

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self.running:
            return
        if dx == 0 and dy == 0:
            return
        if not self._in_primary_monitor(x, y):
            logger.info("Ignored: scroll outside primary monitor")
            return
        if self._point_on_gui(x, y):
            logger.info("Ignored: scroll on recorder GUI")
            return

        self._commit_text_buffer()

        action = Action(
            action_type='scroll',
            x=x,
            y=y,
            delay=self._elapsed(),
            scroll_dx=int(dx),
            scroll_dy=int(dy),
        )
        self.actions.append(action)
        logger.info(f"Recorded: scroll at ({x}, {y}) dx={dx}, dy={dy}")

    def _init_primary_bounds(self) -> Tuple[int, int, int, int]:
        try:
            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
            width = max(1, int(user32.GetSystemMetrics(0)))
            height = max(1, int(user32.GetSystemMetrics(1)))
            return (0, 0, width, height)
        except Exception:
            return (0, 0, 1920, 1080)

    def _in_primary_monitor(self, x: int, y: int) -> bool:
        left, top, right, bottom = self._primary_bounds
        return left <= int(x) < right and top <= int(y) < bottom

    def _downsample_path(self, path: List[Tuple[int, int]], max_points: int = 240) -> List[Tuple[int, int]]:
        if len(path) <= max_points:
            return path
        stride = max(1, len(path) // max_points)
        sampled = path[::stride]
        if sampled[-1] != path[-1]:
            sampled.append(path[-1])
        return sampled

    def _point_on_gui(self, x: int, y: int) -> bool:
        if not self.config.gui_hwnd:
            return False
        try:
            hwnd_under = win32gui.WindowFromPoint((x, y))
        except Exception:
            return False
        return self._is_same_or_child(hwnd_under, self.config.gui_hwnd)


    def _is_same_or_child(self, hwnd_under: int, hwnd_parent: int) -> bool:
        cur = hwnd_under
        while cur and cur != 0:
            if cur == hwnd_parent:
                return True
            cur = win32gui.GetParent(cur)
        return False

    def record_screenshot(self) -> None:
        prev_pos = None
        try:
            try:
                pos = pyautogui.position()
                if hasattr(pos, 'x') and hasattr(pos, 'y'):
                    prev_pos = (int(pos.x), int(pos.y))
                else:
                    prev_pos = (int(pos[0]), int(pos[1]))
            except Exception:
                prev_pos = None
            img = self._capture_screenshot_primary()
        finally:
            if prev_pos is not None:
                try:
                    pyautogui.moveTo(prev_pos[0], prev_pos[1], duration=0)
                except Exception:
                    pass
        img_dir = self.config.images_dir / self.config.script_name
        img_dir.mkdir(parents=True, exist_ok=True)

        # New naming: 0_000O.png, 0_001O.png, ...
        name = ensure_png_name(self._group_idx, self._shot_idx, "O")
        out = img_dir / name
        img.save(out)

        self.actions.append(Action(action_type='screenshot', screenshot=name, delay=self._elapsed()))
        logger.info(f'Recorded: screenshot -> {out}')
        self._shot_idx += 1


    def _capture_screenshot_primary(self) -> Image.Image:
        prev_failsafe = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            sw, sh = pyautogui.size()
            # move cursor to bottom-right corner, then crop taskbar so cursor isn't visible
            pyautogui.moveTo(sw - 5, sh - 5, duration=0)
            time.sleep(0.02)
            shot = pyautogui.screenshot()
        finally:
            pyautogui.FAILSAFE = prev_failsafe

        if self.config.taskbar_crop_px > 0:
            w, h = shot.size
            shot = shot.crop((0, 0, w, h - self.config.taskbar_crop_px))
        return shot

    def _save_json(self) -> None:
        self.config.scripts_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.scripts_dir / f"{self.config.script_name}.json"
        payload = [self._action_to_payload(a) for a in self.actions]
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Saved script: {path}")

    def _action_to_payload(self, action: Action) -> Dict[str, Any]:
        data = asdict(action)
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            if value in (None, [], {}, ""):
                continue
            cleaned[key] = value
        return cleaned


