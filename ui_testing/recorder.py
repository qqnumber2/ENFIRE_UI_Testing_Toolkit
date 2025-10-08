import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set

from pynput import mouse, keyboard
from pynput.keyboard import Key, KeyCode
import pyautogui
from PIL import Image
import win32gui

# EXE-safe imports
try:
    from ui_testing.action import Action  # type: ignore
    from ui_testing.util import ensure_png_name  # type: ignore
except Exception:
    try:
        from .action import Action  # type: ignore
        from .util import ensure_png_name  # type: ignore
    except Exception:
        from action import Action  # type: ignore
        from util import ensure_png_name  # type: ignore

# add near the top, after other imports
try:
    from pywinauto import Desktop
except Exception:
    Desktop = None  # type: ignore

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
        self._move_threshold_px = 2
        self._move_min_interval = 0.03
        self._modifiers: Set[str] = set()

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


    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not self.running:
            return

        btn_name = self._button_name(button)

        if pressed:
            if self._point_on_gui(x, y):
                logger.info("Ignored: click on recorder GUI")
                return

            self._commit_text_buffer()

            auto_id = None
            ctrl_type = None
            if Desktop is not None:
                try:
                    elem = Desktop(backend="uia").from_point(x, y)
                    info = elem.element_info
                    auto_id = (info.automation_id or None)
                    ctrl_type = (getattr(info, "control_type", None) or None)
                except Exception:
                    pass

            self._pressed_buttons[btn_name] = {
                "last_move_pos": (x, y),
                "last_move_time": time.perf_counter(),
            }

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
            meta = f" [auto_id={auto_id}, ctrl={ctrl_type}]" if auto_id or ctrl_type else ""
            logger.info(f"Recorded: mouse_down({btn_name}) at ({x}, {y}){meta}")
            return

        state = self._pressed_buttons.pop(btn_name, None)
        in_gui = self._point_on_gui(x, y)
        if state is None and in_gui:
            logger.info("Ignored: release on recorder GUI")
            return

        if state is not None:
            self._record_mouse_move(btn_name, x, y, force=True)

        self._commit_text_buffer()

        action = Action(
            action_type='mouse_up',
            x=x,
            y=y,
            delay=self._elapsed(),
            button=btn_name,
        )
        self.actions.append(action)
        logger.info(f"Recorded: mouse_up({btn_name}) at ({x}, {y})")


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

        action = Action(
            action_type='mouse_move',
            x=x,
            y=y,
            delay=self._elapsed(),
            button=btn_name,
        )
        self.actions.append(action)
        state["last_move_pos"] = (x, y)
        state["last_move_time"] = now
        logger.debug(f"Recorded: mouse_move({btn_name}) -> ({x}, {y})")

    def _on_move(self, x: int, y: int) -> None:
        if not self.running or not self._pressed_buttons:
            return
        for btn_name in list(self._pressed_buttons.keys()):
            self._record_mouse_move(btn_name, x, y)

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self.running:
            return
        if dx == 0 and dy == 0:
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
        payload = [asdict(a) for a in self.actions]
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Saved script: {path}")


