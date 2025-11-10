import json
import logging
import time
import ctypes
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from pynput import mouse, keyboard
from pynput.keyboard import Key, KeyCode
import pyautogui
from PIL import Image
import win32gui
try:
    from pynput._util import win32 as pynput_win32  # type: ignore
except Exception:
    pynput_win32 = None  # type: ignore
try:
    from ui_testing.automation.driver import AutomationSession, DEFAULT_WINDOW_SPEC, WindowSpec  # type: ignore
except Exception:
    AutomationSession = None  # type: ignore
    DEFAULT_WINDOW_SPEC = None  # type: ignore
    WindowSpec = None  # type: ignore

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

# Shared locator helpers
try:
    from ui_testing.automation.locator import LocatorService, is_generic_automation_id
except Exception:
    try:
        from .locator import LocatorService, is_generic_automation_id  # type: ignore
    except Exception:
        class LocatorService:  # type: ignore[no-redef]
            def __init__(self, manifest=None) -> None:
                self._manifest = manifest or {}

            def update_manifest(self, manifest) -> None:
                self._manifest = manifest or {}

            def contains(self, automation_id):
                if automation_id is None:
                    return False
                return False

            def semantic_metadata(self, automation_id, control_type=None, registry=None):
                if not automation_id:
                    return None
                payload = {"automation_id": str(automation_id)}
                if control_type:
                    payload["control_type"] = control_type
                if registry is not None and hasattr(registry, "get"):
                    try:
                        entry = registry.get(str(automation_id))
                    except Exception:
                        entry = None
                    if entry is not None:
                        payload["group"] = getattr(entry, "group", None)
                        payload["name"] = getattr(entry, "name", None)
                        desc = getattr(entry, "description", None)
                        if desc:
                            payload["description"] = desc
                        ctrl = getattr(entry, "control_type", None)
                        if ctrl and "control_type" not in payload:
                            payload["control_type"] = ctrl
                return payload

        def is_generic_automation_id(value: Optional[str]) -> bool:  # type: ignore
            if not value:
                return True
            lowered = str(value).strip().lower()
            return lowered in {"", "window", "pane", "mainwindowcontrol"}
from ui_testing.tools.calibration import (
    CalibrationProfile,
    capture_window_anchor,
    load_profile,
    save_profile,
)
# add near the top, after other imports
try:
    from pywinauto import Desktop
except Exception:
    Desktop = None  # type: ignore

try:
    import win32com.client as win32com_client  # type: ignore
except Exception:
    win32com_client = None  # type: ignore

try:
    from ui_testing.automation.semantic import SemanticContext, get_semantic_context
    from ui_testing.automation.semantic.registry import AutomationRegistry, ControlEntry
except Exception:
    SemanticContext = None  # type: ignore
    AutomationRegistry = None  # type: ignore
    ControlEntry = None  # type: ignore

    def _semantic_registry(self) -> Optional[AutomationRegistry]:
        if self._semantic_disabled or SemanticContext is None or AutomationRegistry is None:
            return None
        try:
            if self._semantic_context is None:
                self._semantic_context = get_semantic_context()
            if self._semantic_registry_cache is None:
                self._semantic_registry_cache = self._semantic_context.registry
            return self._semantic_registry_cache
        except Exception as exc:
            logger.debug("Semantic registry unavailable: %s", exc)
            self._semantic_disabled = True
            self._semantic_context = None
            self._semantic_registry_cache = None
            return None

    def _make_semantic_metadata(self, auto_id: Optional[str], ctrl_type: Optional[str]) -> Optional[Dict[str, Any]]:
        if not auto_id or is_generic_automation_id(auto_id):
            return None
        payload: Dict[str, Any] = {"automation_id": str(auto_id)}
        if ctrl_type:
            payload["control_type"] = str(ctrl_type)
        registry = self._semantic_registry()
        if registry is None:
            return payload
        entry = registry.get(str(auto_id))
        if entry is None:
            logger.debug("Semantic metadata skipped; AutomationId '%s' not in manifest.", auto_id)
            return None
        payload["group"] = entry.group
        payload["name"] = entry.name
        if entry.control_type and "control_type" not in payload:
            payload["control_type"] = entry.control_type
        if entry.description:
            payload["description"] = entry.description
        return payload

    def get_semantic_context(*args, **kwargs):  # type: ignore
        raise RuntimeError("Semantic automation context unavailable")

logger = logging.getLogger(__name__)


def _guard_pynput_handler() -> None:
    if pynput_win32 is None:
        return
    handler = getattr(pynput_win32.ListenerMixin, "_handler", None)
    if handler is None:
        return
    if getattr(handler, "_ui_testing_patched", False):
        return

    def _safe_handler(self, code, msg, lpdata):
        try:
            return handler(self, code, msg, lpdata)
        except NotImplementedError:
            try:
                logger.debug("Pynput handler ignored NotImplementedError (msg=%s).", msg)
            except Exception:
                pass
            return False

    _safe_handler._ui_testing_patched = True  # type: ignore[attr-defined]
    pynput_win32.ListenerMixin._handler = _safe_handler


_guard_pynput_handler()

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
    calibration_profile: Optional[str] = None
    calibration_dir: Optional[Path] = None
    window_spec: Optional[Any] = None  # WindowSpec when available
    automation_manifest: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None

class Recorder:
    def __init__(self, config: RecorderConfig) -> None:
        self.config = config
        if getattr(self.config, "window_spec", None) is None and DEFAULT_WINDOW_SPEC is not None:
            self.config.window_spec = DEFAULT_WINDOW_SPEC
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
        self._semantic_context: Optional[SemanticContext] = None
        self._semantic_registry_cache: Optional[AutomationRegistry] = None
        self._semantic_disabled = False
        self._locator = LocatorService(config.automation_manifest or {})
        self._manifest_rect_cache: Dict[str, Tuple[int, int, int, int]] = {}
        self._calibration_profile: Optional[CalibrationProfile] = None
        self._calibration_anchor: Optional[Tuple[int, int]] = None
        self._current_window_size: Optional[Tuple[int, int]] = None
        self._initialize_calibration()

    def _initialize_calibration(self) -> None:
        profile_name = getattr(self.config, "calibration_profile", None)
        base_dir = getattr(self.config, "calibration_dir", None)
        if not profile_name or base_dir is None:
            self._calibration_profile = None
            self._calibration_anchor = None
            self._current_window_size = None
            return
        anchor = capture_window_anchor(getattr(self.config, "window_spec", None))
        if anchor is None:
            logger.warning("Calibration profile '%s' requested but ENFIRE window anchor unavailable.", profile_name)
            self._calibration_profile = None
            self._calibration_anchor = None
            self._current_window_size = None
            return
        ax, ay, width, height = anchor
        profile = load_profile(base_dir, profile_name)
        if profile is None:
            profile = CalibrationProfile(
                name=profile_name,
                anchor_x=int(ax),
                anchor_y=int(ay),
                width=width,
                height=height,
            )
        else:
            profile.anchor_x = int(ax)
            profile.anchor_y = int(ay)
            profile.width = width
            profile.height = height
            profile.updated_at = datetime.now(timezone.utc).isoformat()
        save_profile(base_dir, profile)
        self._calibration_profile = profile
        self._calibration_anchor = (int(ax), int(ay))
        if width and height:
            self._current_window_size = (int(width), int(height))
        else:
            try:
                calc_width = int(profile.width) if profile.width else None
                calc_height = int(profile.height) if profile.height else None
                self._current_window_size = (calc_width, calc_height) if calc_width and calc_height else None
            except Exception:
                self._current_window_size = None
        logger.info("Calibration profile '%s' updated with anchor (%s, %s)", profile_name, ax, ay)

    def start(self) -> None:
        self.running = True
        logger.info("Recorder started. Press 'p' to take a screenshot. Use GUI Stop to finish.")
        self._manifest_rect_cache.clear()
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

    def _relative_coords(self, x: int, y: int) -> Tuple[Optional[int], Optional[int]]:
        if self._calibration_anchor is None:
            return None, None
        ax, ay = self._calibration_anchor
        return int(x) - int(ax), int(y) - int(ay)

    def _relative_path(self, points: List[Tuple[int, int]]) -> Optional[List[List[int]]]:
        if self._calibration_anchor is None:
            return None
        rel_points: List[List[int]] = []
        ax, ay = self._calibration_anchor
        for px, py in points:
            rel_points.append([int(px) - int(ax), int(py) - int(ay)])
        return rel_points

    def _relative_percent(self, x: int, y: int) -> Tuple[Optional[float], Optional[float]]:
        if self._calibration_anchor is None or self._current_window_size is None:
            return None, None
        width, height = self._current_window_size
        if not width or not height:
            return None, None
        ax, ay = self._calibration_anchor
        rel_x = (int(x) - int(ax)) / float(width)
        rel_y = (int(y) - int(ay)) / float(height)
        return rel_x, rel_y


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

    def _semantic_registry(self) -> Optional[AutomationRegistry]:
        if self._semantic_disabled or SemanticContext is None or AutomationRegistry is None:
            return None
        try:
            if self._semantic_context is None:
                self._semantic_context = get_semantic_context()
            if self._semantic_registry_cache is None:
                self._semantic_registry_cache = self._semantic_context.registry
                if self._semantic_registry_cache is not None:
                    self._refresh_locator_from_registry(self._semantic_registry_cache)
            elif not self._locator.manifest:
                self._refresh_locator_from_registry(self._semantic_registry_cache)
            return self._semantic_registry_cache
        except Exception as exc:
            logger.debug("Semantic registry unavailable: %s", exc)
            self._semantic_disabled = True
            self._semantic_context = None
            self._semantic_registry_cache = None
            return None

    def _make_semantic_metadata(self, auto_id: Optional[str], ctrl_type: Optional[str]) -> Optional[Dict[str, Any]]:
        registry = self._semantic_registry()
        return self._locator.semantic_metadata(auto_id, ctrl_type, registry)

    def _refresh_locator_from_registry(self, registry: AutomationRegistry) -> None:
        manifest: Dict[str, Dict[str, Dict[str, Any]]] = {}
        try:
            for group in getattr(registry, "groups", lambda: [])():
                entries = registry.by_group(group)
                if not entries:
                    continue
                manifest[group] = {}
                for name, entry in entries.items():
                    manifest[group][name] = {
                        "automation_id": entry.automation_id,
                        "control_type": entry.control_type,
                        "description": entry.description,
                    }
        except Exception as exc:
            logger.debug("Unable to rebuild manifest from registry: %s", exc)
            return
        if manifest:
            existing = {
                group: dict(entries)
                for group, entries in self._locator.manifest.items()
            }
            for group, entries in existing.items():
                target = manifest.setdefault(group, {})
                for name, payload in entries.items():
                    target.setdefault(name, payload)
            self._locator.update_manifest(manifest)

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
            if auto_id and not is_generic_automation_id(auto_id):
                if element is not None and current is not element:
                    try:
                        logger.debug("Resolved AutomationId '%s' via ancestor (depth=%d)", auto_id, depth)
                    except Exception:
                        pass
                return current, auto_id, ctrl_type
            else:
                if auto_id:
                    logger.debug("Ignoring generic AutomationId '%s' (depth=%d)", auto_id, depth)
                auto_id = None
            ctrl_type_hint = ctrl_type
            try:
                current = current.parent()
            except Exception:
                current = None
            depth += 1
        return element, None, ctrl_type_hint

    def _resolve_manifest_entry_at_point(
        self, x: int, y: int
    ) -> Tuple[Optional["ControlEntry"], Optional[Any]]:
        if self._semantic_disabled or SemanticContext is None or AutomationSession is None:
            return None, None
        registry = self._semantic_registry()
        if registry is None:
            return None, None
        ctx = self._semantic_context
        if ctx is None:
            return None, None
        try:
            session = ctx.session
        except Exception:
            return None, None
        best_entry: Optional["ControlEntry"] = None
        best_wrapper: Optional[Any] = None
        best_area: Optional[int] = None
        try:
            entries = registry.all().values()
        except Exception:
            return None, None
        for entry in entries:
            auto_id = getattr(entry, "automation_id", None)
            if not auto_id or is_generic_automation_id(auto_id):
                continue
            rect = self._manifest_rect_cache.get(auto_id)
            wrapper = None
            if rect is None:
                try:
                    wrapper = session.resolve_control(
                        automation_id=auto_id,
                        control_type=getattr(entry, "control_type", None),
                    )
                    rect_obj = wrapper.rectangle()
                    rect = (
                        int(rect_obj.left),
                        int(rect_obj.top),
                        int(rect_obj.right),
                        int(rect_obj.bottom),
                    )
                    self._manifest_rect_cache[auto_id] = rect
                except Exception:
                    continue
            left, top, right, bottom = rect
            if left <= x <= right and top <= y <= bottom:
                area = max(1, (right - left) * (bottom - top))
                if best_entry is None or area < (best_area or area):
                    if wrapper is None:
                        try:
                            wrapper = session.resolve_control(
                                automation_id=auto_id,
                                control_type=getattr(entry, "control_type", None),
                            )
                        except Exception:
                            wrapper = None
                    best_entry = entry
                    best_wrapper = wrapper
                    best_area = area
        return best_entry, best_wrapper


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
            rel_x, rel_y = self._relative_coords(x, y)
            rel_pct_x, rel_pct_y = self._relative_percent(x, y)
            calibration_profile = self._calibration_profile.name if self._calibration_profile else None

            auto_id: Optional[str] = None
            ctrl_type: Optional[str] = None
            target_elem: Optional[Any] = None
            if Desktop is not None:
                target_elem, auto_id, ctrl_type = self._resolve_automation_target(x, y)
            manifest_wrapper: Optional[Any] = None
            if auto_id is None or is_generic_automation_id(auto_id):
                entry, wrapper = self._resolve_manifest_entry_at_point(int(x), int(y))
                if entry is not None:
                    auto_id = getattr(entry, "automation_id", auto_id)
                    ctrl_type = getattr(entry, "control_type", ctrl_type)
                    manifest_wrapper = wrapper
            if target_elem is None and manifest_wrapper is not None:
                target_elem = manifest_wrapper

            semantic_meta = self._make_semantic_metadata(auto_id, ctrl_type)
            resolved_auto_id: Optional[str] = None
            resolved_ctrl_type: Optional[str] = ctrl_type
            if semantic_meta:
                resolved_auto_id = str(semantic_meta.get("automation_id") or "")
                if not resolved_auto_id:
                    resolved_auto_id = None
                resolved_ctrl_type = semantic_meta.get("control_type", resolved_ctrl_type)

            action = Action(
                action_type='mouse_down',
                x=x,
                y=y,
                delay=self._elapsed(),
                button=btn_name,
                rel_x=rel_x,
                rel_y=rel_y,
                rel_percent_x=rel_pct_x,
                rel_percent_y=rel_pct_y,
                calibration_profile=calibration_profile,
            )

            prop_snapshot: Optional[Tuple[str, str]] = None
            if target_elem is not None:
                prop_snapshot = self._extract_element_property(target_elem)
                if prop_snapshot:
                    action.property_name = prop_snapshot[0]
                    action.expected = prop_snapshot[1]

            if semantic_meta:
                if resolved_auto_id:
                    action.auto_id = resolved_auto_id
                if resolved_ctrl_type:
                    action.control_type = resolved_ctrl_type
                action.semantic = semantic_meta

            self.actions.append(action)
            self._pressed_buttons[btn_name] = {
                "last_move_pos": (x, y),
                "last_move_time": time.perf_counter(),
                "path_points": [(int(x), int(y))],
                "start_time": time.perf_counter(),
                "auto_id": resolved_auto_id,
                "control_type": resolved_ctrl_type,
                "semantic": semantic_meta,
                "down_index": len(self.actions) - 1,
                "down_delay": action.delay,
                "rel_coords": (rel_x, rel_y),
                "rel_percent": (rel_pct_x, rel_pct_y),
                "calibration_profile": calibration_profile,
            }
            meta = ""
            if resolved_auto_id or resolved_ctrl_type:
                meta = f" [auto_id={resolved_auto_id}, ctrl={resolved_ctrl_type}]"
            logger.info(f"Recorded: mouse_down({btn_name}) at ({x}, {y}){meta}")

            if target_elem is not None and auto_id:
                self._append_assert_property(auto_id, ctrl_type, target_elem)
            return

        state = self._pressed_buttons.pop(btn_name, None)
        semantic_meta = state.get("semantic") if state else None
        in_gui = self._point_on_gui(x, y)
        if state is None and in_gui:
            logger.info("Ignored: release on recorder GUI")
            return

        self._commit_text_buffer()
        release_delay = self._elapsed()
        click_recorded = False
        release_rel = self._relative_coords(x, y)
        release_rel_pct = self._relative_percent(x, y)

        if state is not None:
            self._record_mouse_move(btn_name, x, y, force=True)
            path = state.get("path_points") or []
            total_distance = 0
            drag_performed = False
            if len(path) > 1:
                sampled = self._downsample_path(path)
                if sampled:
                    start_x, start_y = sampled[0]
                    max_delta = 0
                    drag_elapsed: Optional[float] = None
                    start_time = state.get("start_time")
                    if start_time is not None:
                        try:
                            drag_elapsed = max(time.perf_counter() - start_time, 0.0)
                        except Exception:
                            drag_elapsed = None
                        if drag_elapsed is not None:
                            drag_elapsed = round(drag_elapsed, 3)
                    for (x1, y1), (x2, y2) in zip(sampled, sampled[1:]):
                        total_distance += abs(x2 - x1) + abs(y2 - y1)
                        max_delta = max(max_delta, abs(x2 - start_x), abs(y2 - start_y))

                    should_record_drag = False
                    if drag_elapsed is not None and drag_elapsed >= 0.1:
                        should_record_drag = True
                    elif total_distance >= 3 or max_delta >= 3:
                        should_record_drag = True

                    if should_record_drag:
                        rel_path = self._relative_path(sampled)
                        drag_action = Action(
                            action_type='drag',
                            x=sampled[-1][0],
                            y=sampled[-1][1],
                            delay=release_delay,
                            button=btn_name,
                            path=[[int(px), int(py)] for px, py in sampled],
                            drag_duration=drag_elapsed,
                            rel_path=rel_path,
                            calibration_profile=self._calibration_profile.name if self._calibration_profile else None,
                        )
                        self.actions.append(drag_action)
                        if drag_elapsed is not None:
                            logger.info(
                                "Recorded: drag(%s) path_points=%d distance=%s duration=%0.3fs",
                                btn_name,
                                len(sampled),
                                total_distance,
                                drag_elapsed,
                            )
                        else:
                            logger.info(
                                "Recorded: drag(%s) path_points=%d distance=%s",
                                btn_name,
                                len(sampled),
                                total_distance,
                            )
                        release_delay = self._elapsed()
                        drag_performed = True
            if not drag_performed:
                down_index = state.get("down_index")
                auto_id = state.get("auto_id")
                ctrl_type = state.get("control_type")
                if semantic_meta is None:
                    semantic_meta = self._make_semantic_metadata(auto_id, ctrl_type)
                down_delay = state.get("down_delay")
                if down_index is not None and 0 <= down_index < len(self.actions):
                    down_action = self.actions[down_index]
                    down_action.action_type = 'click'
                    down_action.x = int(x)
                    down_action.y = int(y)
                    down_action.button = btn_name
                    down_action.auto_id = auto_id
                    down_action.control_type = ctrl_type
                    rel_coords = state.get("rel_coords")
                    if rel_coords:
                        down_action.rel_x, down_action.rel_y = rel_coords
                    rel_percent = state.get("rel_percent")
                    if rel_percent:
                        down_action.rel_percent_x, down_action.rel_percent_y = rel_percent
                    down_action.calibration_profile = state.get("calibration_profile")
                    if semantic_meta:
                        down_action.semantic = semantic_meta
                    if down_delay is not None:
                        down_action.delay = down_delay
                else:
                    rel_coords_state = state.get("rel_coords") if state else None
                    rel_percent_state = state.get("rel_percent") if state else None
                    click_action = Action(
                        action_type='click',
                        x=int(x),
                        y=int(y),
                        delay=release_delay,
                        button=btn_name,
                        rel_x=(rel_coords_state or release_rel)[0] if (rel_coords_state or release_rel) else None,
                        rel_y=(rel_coords_state or release_rel)[1] if (rel_coords_state or release_rel) else None,
                        rel_percent_x=(rel_percent_state or release_rel_pct)[0] if (rel_percent_state or release_rel_pct) else None,
                        rel_percent_y=(rel_percent_state or release_rel_pct)[1] if (rel_percent_state or release_rel_pct) else None,
                        calibration_profile=state.get("calibration_profile") if state else (self._calibration_profile.name if self._calibration_profile else None),
                    )
                    if auto_id:
                        click_action.auto_id = auto_id
                    if ctrl_type:
                        click_action.control_type = ctrl_type
                    if semantic_meta:
                        click_action.semantic = semantic_meta
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
            rel_x=release_rel[0],
            rel_y=release_rel[1],
            calibration_profile=self._calibration_profile.name if self._calibration_profile else None,
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
        semantic_meta = self._make_semantic_metadata(auto_id, ctrl_type)
        if semantic_meta is None:
            logger.debug("Skipped assert.property for auto_id=%s (not in manifest).", auto_id)
            return
        action = Action(
            action_type="assert.property",
            delay=0.0,
            auto_id=str(semantic_meta.get("automation_id") or auto_id),
            control_type=semantic_meta.get("control_type", ctrl_type),
            property_name=prop_name,
            expected=expected,
            compare="equals",
        )
        action.semantic = semantic_meta
        self.actions.append(action)
        logger.debug(
            "Recorded: assert.property auto_id=%s property=%s expected=%s",
            action.auto_id,
            prop_name,
            expected,
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


