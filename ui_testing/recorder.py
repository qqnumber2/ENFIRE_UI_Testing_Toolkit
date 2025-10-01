import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

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

    def start(self) -> None:
        self.running = True
        logger.info("Recorder started. Press 'p' to take a screenshot. Use GUI Stop to finish.")
        self._mouse_listener = mouse.Listener(on_click=self._on_click)
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
        self._save_json()

    def _on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if not self.running:
            return

        # ESC stops the recording cleanly
        if key == Key.esc:
            try:
                self._commit_text_buffer()
            except Exception:
                pass
            # stopping the listener from inside its callback can deadlock on some systems
            # hand off to a short thread
            import threading
            threading.Thread(target=self.stop, daemon=True).start()
            return

        # 'p' hotkey for screenshots (primary monitor)
        try:
            if isinstance(key, KeyCode) and key.char and key.char.lower() == "p":
                self._commit_text_buffer()
                self.record_screenshot()
                return
        except Exception:
            pass

        # always record text while recording (except 'p' which is screenshot)
        ch = None
        if isinstance(key, KeyCode) and key.char is not None:
            ch = key.char
        elif key == Key.space:
            ch = " "
        elif key == Key.enter:
            ch = "\n"

        if ch is not None:
            if ch.lower() == "p":
                return  # 'p' reserved for screenshot
            self._text_buffer.append(ch)
            # single log line per key buffer append
            safe = "<ENTER>" if ch == "\n" else ch
            logger.info(f"Recorded: type (buffer) '{safe}'")

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
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
        if not self.running or not pressed:
            return

        # Ignore clicks on GUI window (or children) if we know its HWND
        if self.config.gui_hwnd:
            hwnd_under = win32gui.WindowFromPoint((x, y))
            if self._is_same_or_child(hwnd_under, self.config.gui_hwnd):
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

        a = Action(action_type='click', x=x, y=y, delay=self._elapsed())
        if auto_id:
            # Action dataclass will accept arbitrary fields when serialized via asdict
            setattr(a, "auto_id", auto_id)
        if ctrl_type:
            setattr(a, "control_type", ctrl_type)

        self.actions.append(a)
        logger.info(f"Recorded: click at ({x}, {y})"
                    + (f" [auto_id={auto_id}, ctrl={ctrl_type}]" if auto_id or ctrl_type else ""))


    def _is_same_or_child(self, hwnd_under: int, hwnd_parent: int) -> bool:
        cur = hwnd_under
        while cur and cur != 0:
            if cur == hwnd_parent:
                return True
            cur = win32gui.GetParent(cur)
        return False

    def record_screenshot(self) -> None:
        img = self._capture_screenshot_primary()
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
            time.sleep(0.05)
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