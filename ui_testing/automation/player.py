import json
import logging
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime
import pyautogui
import numpy as np
from PIL import Image, ImageChops

# NEW: guarded pywinauto import (so EXE still runs even if not installed)

try:
    from pywinauto import Desktop  # UIA selector
except Exception:
    Desktop = None  # type: ignore
# EXE-safe imports

try:
    from ui_testing.automation.action import Action  # noqa: F401
    from ui_testing.automation.util import dotted_code_from_test_name, ensure_png_name
except Exception:
    try:
        from .action import Action  # noqa: F401
        from .util import dotted_code_from_test_name, ensure_png_name
    except Exception:
        from action import Action  # type: ignore  # noqa: F401
        from util import dotted_code_from_test_name, ensure_png_name  # type: ignore
try:
    from ui_testing.automation.explorer import ExplorerController
except Exception:
    try:
        from .explorer import ExplorerController
    except Exception:
        ExplorerController = None  # type: ignore
logger = logging.getLogger(__name__)

@dataclass
class PlayerConfig:
    scripts_dir: Path
    images_dir: Path
    results_dir: Path
    taskbar_crop_px: int = 60
    wait_between_actions: float = 1
    app_title_regex: Optional[str] = None  # regex to scope UIA search to app window
    diff_tolerance: float = 0.01  # 0.0 = exact; >0 allows small diffs
    diff_tolerance_percent: float = 0.01
    use_default_delay_always: bool = False
    use_automation_ids: bool = True
    use_screenshots: bool = True
    prefer_semantic_scripts: bool = True
    automation_manifest: Optional[Dict[str, Dict[str, str]]] = None


class Player:
    def __init__(self, config: PlayerConfig) -> None:
        self.config = config
        self.update_automation_manifest(config.automation_manifest or {})

        self._stop_event = threading.Event()

        # Lazy Explorer automation helper (wired by upcoming feature work)


    def update_automation_manifest(self, manifest: Optional[Dict[str, Dict[str, str]]]) -> None:
        self.automation_manifest: Dict[str, Dict[str, str]] = manifest or {}
        self.config.automation_manifest = self.automation_manifest
        self._automation_lookup: Dict[str, Tuple[str, str]] = {}
        for group, mapping in self.automation_manifest.items():
            for name, value in mapping.items():
                self._automation_lookup[value] = (group, name)


        self._explorer_controller = None

        self._primary_bounds = self._init_primary_bounds()

        try:
            pyautogui.PAUSE = 0

            pyautogui.MINIMUM_DURATION = 0

        except Exception:
            pass

    def play(self, script_name: str) -> List[Dict[str, Any]]:
        """Returns per-checkpoint results and writes an Excel summary per run."""

        script_path = self._select_script_path(script_name)

        with script_path.open("r", encoding="utf-8") as f:
            actions: List[Dict[str, Any]] = json.load(f)

        results: List[Dict[str, Any]] = []
        assert_count = 0
        screenshot_count = 0

        shot_idx = 0

        base_code = dotted_code_from_test_name(Path(script_name).name)

        total_actions = len(actions)

        i = 0

        while i < total_actions:
            action = actions[i]

            a_type = action.get("action_type")

            pre = self._compute_action_delay(a_type, action)

            if pre > 0:
                remaining = pre

                while remaining > 0 and not self.should_stop():
                    chunk = min(0.1, remaining)

                    time.sleep(chunk)

                    remaining -= chunk

            if self.should_stop():
                break

            if a_type and str(a_type).startswith("explorer."):
                self._play_explorer_action(action)

                i += 1

                continue

            if a_type == "click":
                x, y = int(action["x"]), int(action["y"])

                auto_id: Optional[str]   = action.get("auto_id")

                ctrl_type: Optional[str] = action.get("control_type")

                if not self._in_primary_monitor(x, y):
                    logger.info(f"Playback: click skipped outside primary monitor at ({x}, {y})")

                    i += 1

                    continue

                if auto_id and getattr(self.config, "use_automation_ids", True) and Desktop is not None:
                    if self._automation_lookup and str(auto_id) not in self._automation_lookup:
                        logger.debug("AutomationId %s not found in manifest", auto_id)
                    try:
                        desk = Desktop(backend="uia")

                        target = None

                        if self.config.app_title_regex:
                            try:
                                appwin = desk.window(title_re=self.config.app_title_regex)

                                query: Dict[str, Any] = {"auto_id": auto_id}

                                if ctrl_type:
                                    query["control_type"] = ctrl_type

                                target = appwin.child_window(**query).wrapper_object()

                            except Exception:
                                target = None

                        if target is None:
                            query2: Dict[str, Any] = {"auto_id": auto_id}

                            if ctrl_type:
                                query2["control_type"] = ctrl_type

                            target = desk.window(**query2).wrapper_object()

                        logger.info(f"Playback(UIA): click auto_id='{auto_id}'"

                                    f"{' ctrl=' + ctrl_type if ctrl_type else ''}")

                        target.click_input()

                        time.sleep(0.005)

                        i += 1

                        continue

                    except Exception as e:
                        logger.warning(

                            f"UIA click failed for auto_id='{auto_id}' (fallback to coords): {e}"

                        )

                fallback_note = "" if auto_id else " [coordinate fallback]"
                logger.info(f"Playback: click at ({x}, {y}){fallback_note}")

                pyautogui.click(x, y, _pause=False)

            elif a_type == "mouse_down":
                x = int(action.get("x", 0))

                y = int(action.get("y", 0))

                button = str(action.get("button") or "left").lower()

                logger.debug(f"Playback: mouse_down({button}) at ({x}, {y})")

                try:
                    pyautogui.mouseDown(x=x, y=y, button=button, _pause=False)

                except Exception as exc:
                    logger.warning(f"mouse_down failed at ({x}, {y}): {exc}")

            elif a_type == "mouse_move":
                button = action.get("button")

                try:
                    duration_val = action.get("move_duration")

                    move_duration = max(0.0, float(duration_val)) if duration_val is not None else 0.0

                except Exception:
                    move_duration = 0.0

                if button:
                    final_x = int(action.get("x", 0))

                    final_y = int(action.get("y", 0))

                    j = i + 1

                    while j < total_actions:
                        next_action = actions[j]

                        if next_action.get("action_type") != "mouse_move" or next_action.get("button") != button:
                            break

                        final_x = int(next_action.get("x", final_x))

                        final_y = int(next_action.get("y", final_y))

                        j += 1

                    duration = move_duration if move_duration > 0 else 0.02

                    duration = min(duration, 0.08)

                    logger.debug(f"Playback: drag -> ({final_x}, {final_y}) [{button}]")

                    try:
                        pyautogui.moveTo(final_x, final_y, duration=duration, _pause=False)

                    except Exception as exc:
                        logger.warning(f"drag move failed to ({final_x}, {final_y}): {exc}")

                    i = j

                    continue

                x = int(action.get("x", 0))

                y = int(action.get("y", 0))

                try:
                    if move_duration > 0:
                        pyautogui.moveTo(x, y, duration=move_duration, _pause=False)

                    else:
                        pyautogui.moveTo(x, y, _pause=False)

                except Exception as exc:
                    logger.warning(f"mouse_move failed to ({x}, {y}): {exc}")

            elif a_type == "mouse_up":
                x = int(action.get("x", 0))

                y = int(action.get("y", 0))

                button = str(action.get("button") or "left").lower()

                logger.debug(f"Playback: mouse_up({button}) at ({x}, {y})")

                try:
                    pyautogui.mouseUp(x=x, y=y, button=button, _pause=False)

                except Exception as exc:
                    logger.warning(f"mouse_up failed at ({x}, {y}): {exc}")

            elif a_type == "drag":
                raw_path = action.get("path") or []

                button = str(action.get("button") or "left").lower()

                coords: List[Tuple[int, int]] = []

                for point in raw_path:
                    try:
                        px, py = int(point[0]), int(point[1])

                    except Exception:
                        continue

                    coords.append((px, py))

                coords = [pt for pt in coords if self._in_primary_monitor(pt[0], pt[1])]

                if len(coords) > 1:
                    logger.debug(f"Playback: drag path ({len(coords)} points) [{button}]")

                    self._play_drag_path(coords, button)

                else:
                    logger.debug("Playback: drag skipped (insufficient path points)")

            elif a_type == "key":
                key_name = action.get("key")

                if key_name:
                    logger.info(f"Playback: key {key_name}")

                    try:
                        pyautogui.press(key_name)

                    except Exception as exc:
                        logger.warning(f"key press failed ({key_name}): {exc}")

            elif a_type == "hotkey":
                keys = action.get("keys")

                if not keys:
                    i += 1

                    continue

                if not isinstance(keys, list):
                    try:
                        keys = list(keys)

                    except Exception:
                        keys = [str(keys)]

                str_keys = [str(k).lower() for k in keys]

                label = ' + '.join(str_keys)

                logger.info(f"Playback: hotkey {label}")

                try:
                    pyautogui.hotkey(*str_keys)

                except Exception as exc:
                    logger.warning(f"hotkey failed ({label}): {exc}")

            elif a_type == "scroll":
                x = action.get("x")

                y = action.get("y")

                dx = int(action.get("scroll_dx", 0) or 0)

                dy = int(action.get("scroll_dy", 0) or 0)

                if dx or dy:
                    if x is not None and y is not None:
                        try:
                            cur = pyautogui.position()

                            cx = int(getattr(cur, 'x', cur[0]))

                            cy = int(getattr(cur, 'y', cur[1]))

                        except Exception:
                            cx = cy = None

                        try:
                            if cx != int(x) or cy != int(y):
                                pyautogui.moveTo(int(x), int(y), duration=0)

                        except Exception:
                            pass

                        xi = int(x)

                        yi = int(y)

                    else:
                        xi = yi = None

                    if xi is not None and yi is not None and not self._in_primary_monitor(xi, yi):
                        logger.info(f"Playback: scroll ignored outside primary monitor at ({xi}, {yi})")

                        i += 1

                        continue

                    logger.info(f"Playback: scroll at ({xi if xi is not None else '?'}, {yi if yi is not None else '?'}) dx={dx}, dy={dy}")

                    try:
                        if dy:
                            pyautogui.scroll(dy, x=xi, y=yi)

                        if dx:
                            if hasattr(pyautogui, 'hscroll'):
                                pyautogui.hscroll(dx, x=xi, y=yi)

                            else:
                                logger.debug("Horizontal scroll not supported on this platform")

                        time.sleep(0.005)

                    except Exception as exc:
                        logger.warning(f"scroll failed at ({xi if xi is not None else '?'}, {yi if yi is not None else '?'}):: {exc}")

            elif a_type == "type":
                text = action.get("text", "")

                safe_preview = text.replace("\n", "<ENTER>")

                logger.info(f"Playback: type '{safe_preview}'")

                pyautogui.typewrite(text, interval=0.02)

            elif a_type == "assert.property":
                if not getattr(self.config, "prefer_semantic_scripts", True):
                    logger.debug("Playback: semantic assertion skipped (semantic checks disabled).")
                elif not getattr(self.config, "use_automation_ids", True):
                    logger.debug("Playback: semantic assertion skipped (automation IDs disabled).")
                elif Desktop is None:
                    logger.debug("Playback: semantic assertion skipped (UI Automation backend unavailable).")
                else:
                    before_len = len(results)
                    self._handle_assert_property(action, results)
                    if len(results) > before_len:
                        assert_count += 1
            elif a_type == "screenshot":
                if not getattr(self.config, "use_screenshots", True):
                    logger.info("Playback: screenshot checkpoint skipped (screenshots disabled)")
                    i += 1
                    continue
                prev_pos = None

                try:
                    pos = pyautogui.position()

                    if hasattr(pos, "x") and hasattr(pos, "y"):
                        prev_pos = (int(pos.x), int(pos.y))

                    else:
                        prev_pos = (int(pos[0]), int(pos[1]))

                except Exception:
                    prev_pos = None

                logger.info(f"Playback: screenshot #{shot_idx}")
                time.sleep(0.5)
                test_img = self._capture_screenshot_primary()

                if prev_pos is not None:
                    try:
                        pyautogui.moveTo(prev_pos[0], prev_pos[1], duration=0)

                    except Exception:
                        pass

                img_dir = self.config.images_dir / script_name

                img_dir.mkdir(parents=True, exist_ok=True)

                test_name = ensure_png_name(0, shot_idx, "T")

                test_path = img_dir / test_name

                test_img.save(test_path)

                orig_name = ensure_png_name(0, shot_idx, "O")

                orig_path = img_dir / orig_name

                passed, diff_pct = self._compare_and_highlight(orig_path, test_path)

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                result = {

                    "index": shot_idx,

                    "original": str(orig_path),

                    "test": str(test_path),

                    "diff_percent": round(float(diff_pct), 3),

                    "status": "pass" if passed else "fail",

                    "timestamp": timestamp,

                }

                logger.info(f"Result: screenshot #{shot_idx} -> {'PASS' if passed else 'FAIL'}")

                results.append(result)

                shot_idx += 1
                screenshot_count += 1

            i += 1

        summary_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        validation_fail = any(r.get("status") == "fail" for r in results)
        validation_total = assert_count + screenshot_count
        note_parts = [f"Asserts: {assert_count}", f"Screenshots: {screenshot_count}"]
        if validation_total == 0:
            summary_status = "warn"
            note_parts.append("No semantic assertions or screenshot checkpoints executed.")
            logger.warning("Playback summary [%s]: no validations executed (asserts=0, screenshots=0).", script_name)
        elif validation_fail:
            summary_status = "fail"
            note_parts.append("At least one validation failed.")
        else:
            summary_status = "pass"
            note_parts.append("All validations passed.")
        summary_entry = {
            "index": "summary",
            "timestamp": summary_timestamp,
            "original": "",
            "test": "",
            "diff_percent": "",
            "status": summary_status,
            "note": " | ".join(note_parts),
            "assertions": assert_count,
            "screenshots": screenshot_count,
        }
        results.append(summary_entry)

        # Write Excel after this test

        self._write_excel_results(script_name, results)

        return results

    def _handle_assert_property(self, action: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
        if not getattr(self.config, "prefer_semantic_scripts", True):
            return
        if not getattr(self.config, "use_automation_ids", True):
            return
        if Desktop is None:
            return
        auto_id = action.get("auto_id")
        if not auto_id:
            logger.warning("assert.property skipped (missing auto_id)")
            return
        ctrl_type = action.get("control_type")
        if self._automation_lookup and str(auto_id) not in self._automation_lookup:
            logger.debug("AutomationId %s not defined in manifest", auto_id)
        prop_name = (
            action.get("property")
            or action.get("property_name")
            or action.get("propertyName")
            or "name"
        )
        comparator = str(action.get("compare") or action.get("comparison") or "equals").strip().lower()
        expected = action.get("expected")
        element = self._resolve_element_by_auto_id(str(auto_id), ctrl_type)
        if element is None:
            logger.warning("assert.property failed: element auto_id='%s' not found", auto_id)
            self._record_assert_result(results, str(auto_id), prop_name, expected, None, False, "not found")
            return
        actual = self._read_element_property(element, prop_name)
        passed, note = self._compare_property(actual, expected, comparator)
        logger.info(
            "Assert property: auto_id='%s' property='%s' comparator='%s' -> %s",
            auto_id,
            prop_name,
            comparator,
            "PASS" if passed else "FAIL",
        )
        self._record_assert_result(results, str(auto_id), prop_name, expected, actual, passed, note)

    def _capture_screenshot_primary(self) -> Image.Image:
        prev_failsafe = pyautogui.FAILSAFE

        pyautogui.FAILSAFE = False

        try:
            sw, sh = pyautogui.size()

            pyautogui.moveTo(sw - 5, sh - 5, duration=0)

            shot = pyautogui.screenshot()

        finally:
            pyautogui.FAILSAFE = prev_failsafe

        if self.config.taskbar_crop_px > 0:
            w, h = shot.size

            shot = shot.crop((0, 0, w, h - self.config.taskbar_crop_px))

        return shot

    def _compare_exact(self, orig_path: Path, test_path: Path) -> bool:
        """Backward-compat entry; now delegates to tolerance-based compare."""

        is_pass, _pct = self._compare_and_highlight(orig_path, test_path)

        return is_pass

    def _bounding_boxes_from_mask(self, mask: np.ndarray, cell: int = 12,

                                min_area: int = 60, pad: int = 3) -> list[tuple[int,int,int,int]]:
        """

        Cluster a boolean mask into disjoint components using a coarse grid,

        return a list of pixel-space bounding boxes (x0, y0, x1, y1).

        - cell: size of coarse grid cell in pixels (larger = faster, fewer boxes)

        - min_area: drop tiny boxes (in pixels, after final bbox)

        - pad: expand each bbox by this many pixels on each side (clamped)

        """

        h, w = mask.shape

        ys, xs = np.where(mask)

        if len(xs) == 0:
            return []

        # Map pixels to coarse cells

        gx = xs // cell

        gy = ys // cell

        cells = np.stack([gy, gx], axis=1)

        # Unique cells containing diffs

        uniq = np.unique(cells, axis=0)

        # Build adjacency on grid (8-neighborhood)

        from collections import defaultdict, deque

        cell_set = {tuple(c) for c in uniq}

        visited = set()

        boxes = []

        def cell_to_bbox(cy: int, cx: int):
            # Coarse cell bounds in pixel space

            y0 = cy * cell

            x0 = cx * cell

            y1 = min((cy + 1) * cell - 1, h - 1)

            x1 = min((cx + 1) * cell - 1, w - 1)

            return y0, x0, y1, x1

        # Precompute a fine mask to refine bounds inside coarse unions

        fine_mask = mask

        for cy, cx in uniq:
            if (cy, cx) in visited:
                continue

            # BFS over coarse neighbors

            Q = deque([(cy, cx)])

            visited.add((cy, cx))

            comp_cells = [(cy, cx)]

            while Q:
                y, x = Q.popleft()

                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue

                        ny, nx = y + dy, x + dx

                        if (ny, nx) in cell_set and (ny, nx) not in visited:
                            visited.add((ny, nx))

                            Q.append((ny, nx))

                            comp_cells.append((ny, nx))

            # Convert component coarse cells to a union bbox (coarse)

            y0 = min(cy for cy, cx in comp_cells) * cell

            x0 = min(cx for cy, cx in comp_cells) * cell

            y1 = min((max(cy for cy, cx in comp_cells) + 1) * cell - 1, h - 1)

            x1 = min((max(cx for cy, cx in comp_cells) + 1) * cell - 1, w - 1)

            # Refine bbox using fine mask in that region (shrinks to true extents)

            sub = fine_mask[y0:y1+1, x0:x1+1]

            if sub.any():
                sy, sx = np.where(sub)

                ry0 = y0 + sy.min()

                ry1 = y0 + sy.max()

                rx0 = x0 + sx.min()

                rx1 = x0 + sx.max()

            else:
                ry0, ry1, rx0, rx1 = y0, y1, x0, x1

            # Pad and clamp

            ry0 = max(0, ry0 - pad); rx0 = max(0, rx0 - pad)

            ry1 = min(h - 1, ry1 + pad); rx1 = min(w - 1, rx1 + pad)

            if (ry1 - ry0 + 1) * (rx1 - rx0 + 1) >= min_area:
                boxes.append((rx0, ry0, rx1, ry1))

        return boxes

    def _compare_and_highlight(self, orig_path: Path, test_path: Path) -> tuple[bool, float]:
        """Return (is_pass, diff_percent). PASS ? diff_percent <= diff_tolerance_percent.

        Also saves:
        - D image (...D.png): black & white absolute difference (all channels)

        - H image (...H.png): semi-transparent red overlay + red bounding boxes (one per region)

        """

        try:
            if not orig_path.exists() or not test_path.exists():
                logger.error(f"Missing image(s): {orig_path} | {test_path}")

                return False, 100.0

            o = Image.open(orig_path).convert("RGBA")

            t = Image.open(test_path).convert("RGBA")

            if o.size != t.size:
                t = t.resize(o.size, Image.LANCZOS)

            a = np.asarray(o, dtype=np.int16)

            b = np.asarray(t, dtype=np.int16)

            absdiff = np.abs(a - b)

            diff_mask = np.any(absdiff > 0, axis=2)      # H×W bool

            total = diff_mask.size

            num_diff = int(diff_mask.sum())

            diff_percent = (num_diff / total) * 100.0

            # ----- Save D (black & white difference) -----

            perpix = absdiff[..., :3].max(axis=2)  # ignore alpha for D

            if perpix.max() > 0:
                perpix = (perpix.astype(np.float32) / perpix.max()) * 255.0

            d_img = Image.fromarray(perpix.astype(np.uint8), mode="L")

            stem = test_path.stem

            d_name = (stem[:-1] + "D") if stem and stem[-1] in ("T", "O") else (stem + "_D")

            d_path = test_path.with_name(d_name + ".png")

            try:
                d_img.save(d_path)

            except Exception:
                pass

            # ----- Save H (semi-transparent red + MULTI boxes) -----

            if num_diff > 0:
                overlay = np.zeros_like(a)

                overlay[..., 0] = 255  # red

                overlay[..., 3] = np.where(diff_mask, 96, 0)

                hi = Image.alpha_composite(o, Image.fromarray(overlay.astype(np.uint8)))

                # draw multiple rectangles

                boxes = self._bounding_boxes_from_mask(diff_mask, cell=12, min_area=60, pad=3)

                arr = np.array(hi)

                for (x0, y0, x1, y1) in boxes:
                    # 3px outline

                    arr[y0:y0+3, x0:x1+1] = [255, 0, 0, 255]

                    arr[y1-2:y1+1, x0:x1+1] = [255, 0, 0, 255]

                    arr[y0:y1+1, x0:x0+3] = [255, 0, 0, 255]

                    arr[y0:y1+1, x1-2:x1+1] = [255, 0, 0, 255]

                hi = Image.fromarray(arr, mode="RGBA")

                h_name = (stem[:-1] + "H") if stem and stem[-1] in ("T", "O") else (stem + "_H")

                try:
                    hi.save(test_path.with_name(h_name + ".png"))

                except Exception:
                    pass

            # ----- PASS/FAIL based on tolerance -----

            tol = float(getattr(self.config, "diff_tolerance_percent",

                                getattr(self.config, "diff_tolerance", 0.0)))

            is_pass = (diff_percent <= tol)

            return is_pass, diff_percent

        except Exception as e:
            logger.exception(f"Compare failed for {orig_path} vs {test_path}: {e}")

            return False, 100.0

    def _make_highlight_image(self, base_img: Image.Image, mask: np.ndarray) -> Image.Image:
        """Return base_img with semi-transparent red overlay where mask is True, and a union bbox outline."""

        h, w = mask.shape

        # Create an RGBA from base

        comp = base_img.convert("RGBA")

        overlay = Image.new("RGBA", (w, h), (255, 0, 0, 0))

        # Semi-transparent red where mask True

        alpha = 96  # tweak intensity (0..255)

        r = np.zeros((h, w, 4), dtype=np.uint8)

        r[..., 0] = 255  # R

        r[..., 3] = 0

        r[mask, 3] = alpha

        overlay = Image.fromarray(r, mode="RGBA")

        comp = Image.alpha_composite(comp, overlay)

        # Draw a union bounding box (single outline) for quick spotting

        if mask.any():
            ys, xs = np.where(mask)

            y0, y1 = ys.min(), ys.max()

            x0, x1 = xs.min(), xs.max()

            # Draw rectangle  (simple 3px outline)

            draw = Image.fromarray(np.array(comp))

            arr = np.array(draw)

            # top & bottom

            arr[y0:y0+3, x0:x1+1] = [255, 0, 0, 255]

            arr[y1-2:y1+1, x0:x1+1] = [255, 0, 0, 255]

            # left & right

            arr[y0:y1+1, x0:x0+3] = [255, 0, 0, 255]

            arr[y0:y1+1, x1-2:x1+1] = [255, 0, 0, 255]

            comp = Image.fromarray(arr, mode="RGBA")

        return comp.convert("RGB")

    def _split_hierarchy(self, script_name: str) -> Tuple[str, str, str]:
        p = Path(script_name)

        test = p.name

        sec = p.parent.name if p.parent.name else ""

        proc = p.parent.parent.name if p.parent.parent and p.parent.parent.name else ""

        return proc, sec, test

    def request_stop(self, clear_only: bool=False):
        """If clear_only=True, clears previous stop; else sets stop."""

        if clear_only:
            self._stop_event.clear()

        else:
            self._stop_event.set()

    def _compute_action_delay(self, action_type: str, action: Dict[str, Any]) -> float:
        default_wait = float(getattr(self.config, 'wait_between_actions', 0.0) or 0.0)

        use_default = bool(getattr(self.config, 'use_default_delay_always', False))

        drag_actions = {'mouse_down', 'mouse_move', 'mouse_up'}

        scroll_actions = {'scroll'}

        if use_default and action_type not in drag_actions and action_type not in scroll_actions:
            target = default_wait

        else:
            target = action.get('delay', 0.0 if action_type in scroll_actions else default_wait)

        try:
            delay = float(target)

        except Exception:
            if action_type in drag_actions:
                delay = 0.01

            elif action_type in scroll_actions:
                delay = 0.0

            else:
                delay = default_wait

        if delay < 0:
            delay = 0.0

        if use_default and action_type in drag_actions and delay == 0.0:
            delay = 0.01

        if action_type in drag_actions:
            delay *= 0.1

        return delay

    def _play_drag_path(self, coords: List[Tuple[int, int]], button: str) -> None:
        if len(coords) < 2:
            return

        sampled = self._downsample_points(coords)

        for px, py in sampled[1:]:
            try:
                pyautogui.moveTo(px, py, duration=0)

            except Exception as exc:
                logger.warning(f"drag move failed to ({px}, {py}): {exc}")

                break

    def _downsample_points(self, coords: List[Tuple[int, int]], max_points: int = 120) -> List[Tuple[int, int]]:
        if len(coords) <= max_points:
            return coords

        stride = max(1, len(coords) // max_points)

        sampled = coords[::stride]

        if sampled[-1] != coords[-1]:
            sampled.append(coords[-1])

        return sampled

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def _write_excel_results(self, script_name: str, results: List[Dict[str, Any]]) -> None:
        # Lazy import so users without Excel don't break other features

        try:
            from openpyxl import Workbook, load_workbook

            from openpyxl.styles import Font, Alignment, PatternFill

        except Exception as e:
            logger.warning(f"Excel export skipped (openpyxl not available): {e}")

            return

        proc, sec, test = self._split_hierarchy(script_name)

        sheet_name = (proc or "General")[:31] or "General"

        out_path = self.config.results_dir / "results_summary.xlsx"

        if out_path.exists():
            wb = load_workbook(out_path)

            if sheet_name in wb.sheetnames:
                ws = wb[sheet_name]

            else:
                ws = wb.create_sheet(title=sheet_name)

                self._initialize_results_sheet(ws, Font, Alignment)

        else:
            wb = Workbook()

            ws = wb.active

            ws.title = sheet_name

            self._initialize_results_sheet(ws, Font, Alignment)

        existing_rows = ws.max_row

        headers_written = existing_rows > 1

        target_key = ((proc or ""), (sec or ""), (test or ""))

        if existing_rows > 1:
            rows_to_keep = []

            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row:
                    continue

                row_key = ((row[0] or ""), (row[1] or ""), (row[2] or ""))

                if row_key != target_key:
                    rows_to_keep.append(list(row))

            if len(rows_to_keep) != existing_rows - 1:
                ws.delete_rows(2, existing_rows - 1)

                for values in rows_to_keep:
                    ws.append(values)

        for r in results:
            raw_index = r.get("index", 0)
            if isinstance(raw_index, str) and raw_index.lower() == "summary":
                continue

            try:
                checkpoint = f"{int(raw_index) + 1}"

            except Exception:
                checkpoint = str(raw_index)

            timestamp = r.get("timestamp", "")

            diff_value: Optional[float]

            try:
                diff_value = round(float(r.get("diff_percent")), 3)

            except Exception:
                diff_value = None

            status = "PASS" if r.get("status") == "pass" else "FAIL"

            row = [

                proc,

                sec,

                test,

                checkpoint,

                timestamp,

                diff_value,

                status,

                r.get("original", ""),

                r.get("test", ""),

            ]

            ws.append(row)

            last_row = ws.max_row

            # apply formatting

            timestamp_cell = ws.cell(row=last_row, column=5)

            timestamp_cell.alignment = Alignment(horizontal="center")

            diff_cell = ws.cell(row=last_row, column=6)

            if diff_value is None:
                diff_cell.value = None

            else:
                diff_cell.number_format = "0.000"

            result_cell = ws.cell(row=last_row, column=7)

            result_cell.alignment = Alignment(horizontal="center")

            if status == "PASS":
                result_cell.fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

            else:
                result_cell.fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

        if not headers_written:
            self._apply_column_widths(ws)

        try:
            wb.save(out_path)

            logger.info(f"Excel results saved: {out_path}")

        except Exception as e:
            logger.warning(f"Failed to save Excel results: {e}")

    def _initialize_results_sheet(self, ws, Font, Alignment) -> None:
        headers = ["Procedure", "Section", "Test", "Checkpoint", "Timestamp", "% Diff", "Result", "Original", "Playback"]

        ws.append(headers)

        bold = Font(bold=True)

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)

            cell.font = bold

            cell.alignment = Alignment(horizontal="center")

        ws.freeze_panes = "A2"

        self._apply_column_widths(ws)

    def _apply_column_widths(self, ws) -> None:
        widths = [16, 14, 36, 14, 20, 10, 12, 48, 48]

        for idx, width in enumerate(widths, start=1):
            column_letter = chr(ord("A") + idx - 1)

            ws.column_dimensions[column_letter].width = width

    def _init_primary_bounds(self) -> Tuple[int, int, int, int]:
        try:
            sw, sh = pyautogui.size()

            return (0, 0, int(sw), int(sh))

        except Exception:
            return (0, 0, 1920, 1080)

    def _in_primary_monitor(self, x: Optional[int], y: Optional[int]) -> bool:
        if x is None or y is None:
            return True

        left, top, right, bottom = self._primary_bounds

        try:
            xi = int(x)

            yi = int(y)

        except Exception:
            return False

        if left <= xi < right and top <= yi < bottom:
            return True

        # Screen size might have changed; refresh once.

        self._primary_bounds = self._init_primary_bounds()

        left, top, right, bottom = self._primary_bounds

        return left <= xi < right and top <= yi < bottom

    def _select_script_path(self, script_name: str) -> Path:
        base = self.config.scripts_dir / f"{script_name}.json"
        try:
            prefer_flag = getattr(self.config, "prefer_semantic_scripts", None)
            if prefer_flag is True:
                prefer_semantic = True
            elif prefer_flag is False:
                prefer_semantic = False
            else:
                prefer_semantic = (not getattr(self.config, "use_screenshots", True)) or getattr(self.config, "use_automation_ids", True)
            if prefer_semantic:
                semantic = base.with_suffix(".semantic.json")
                if semantic.exists():
                    logger.debug("Using semantic script for %s", script_name)
                    return semantic
        except Exception:
            pass
        return base

    def _play_explorer_action(self, action_dict: Dict[str, Any]) -> None:
        if ExplorerController is None:
            logger.info("Explorer automation unavailable; skipping %s", action_dict.get("action_type"))

            return

        controller = self._get_explorer_controller()

        if controller is None:
            logger.info("Explorer controller could not be initialised; skipping %s", action_dict.get("action_type"))

            return

        try:
            explorer_action = self._to_action_dataclass(action_dict)

            controller.handle(explorer_action)

        except Exception as exc:
            logger.warning("Explorer action skipped (%s): %s", action_dict.get("action_type"), exc)

    def _get_explorer_controller(self):
        if ExplorerController is None:
            return None

        if self._explorer_controller is None:
            base_path = getattr(self.config, "scripts_dir", None)

            self._explorer_controller = ExplorerController(base_path=base_path)

        return self._explorer_controller

    def _to_action_dataclass(self, payload: Dict[str, Any]) -> Action:
        field_names = getattr(Action, "__dataclass_fields__", {}).keys()

        filtered = {name: payload.get(name) for name in field_names}

        if not filtered.get("action_type"):
            filtered["action_type"] = payload.get("action_type", "explorer.unknown")

        return Action(**filtered)

    def _resolve_element_by_auto_id(self, auto_id: str, ctrl_type: Optional[str] = None):
        if Desktop is None:
            return None
        try:
            desk = Desktop(backend="uia")
        except Exception:
            return None
        query: Dict[str, Any] = {"auto_id": auto_id}
        if ctrl_type:
            query["control_type"] = ctrl_type
        try:
            if self.config.app_title_regex:
                try:
                    appwin = desk.window(title_re=self.config.app_title_regex)
                    return appwin.child_window(**query).wrapper_object()
                except Exception:
                    pass
            return desk.window(**query).wrapper_object()
        except Exception:
            try:
                return desk.child_window(**query).wrapper_object()
            except Exception:
                return None

    def _read_element_property(self, element: Any, prop: str) -> Any:
        target = (prop or "name").strip().lower()
        try:
            if target in {"text", "name", "title", "window_text"}:
                return element.window_text()
        except Exception:
            pass
        try:
            if target in {"value", "currentvalue"} and hasattr(element, "get_value"):
                return element.get_value()
        except Exception:
            pass
        try:
            if target in {"enabled", "is_enabled"}:
                return element.is_enabled()
        except Exception:
            pass
        try:
            attr = getattr(element, target, None)
            if callable(attr):
                return attr()
            if attr is not None:
                return attr
        except Exception:
            pass
        info = getattr(element, "element_info", None)
        if info is not None:
            return getattr(info, target, None)
        return None

    def _compare_property(self, actual: Any, expected: Any, comparator: str) -> tuple[bool, str]:
        actual_str = "" if actual is None else str(actual)
        expected_str = "" if expected is None else str(expected)
        note = ""
        if comparator in {"equals", "equal", "=="}:
            passed = actual_str == expected_str
            if not passed:
                note = f"expected '{expected_str}' got '{actual_str}'"
        elif comparator in {"contains", "in"}:
            passed = expected_str in actual_str
            if not passed:
                note = f"'{expected_str}' not in '{actual_str}'"
        else:
            passed = actual_str == expected_str
            if not passed:
                note = f"unknown comparator '{comparator}'"
        return passed, note

    def _record_assert_result(
        self,
        results: List[Dict[str, Any]],
        auto_id: str,
        property_name: str,
        expected: Any,
        actual: Any,
        passed: bool,
        note: str,
    ) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {
            "index": f"assert:{auto_id}",
            "original": str(expected),
            "test": str(actual),
            "diff_percent": 0.0,
            "status": "pass" if passed else "fail",
            "timestamp": timestamp,
            "auto_id": auto_id,
            "property": property_name,
        }
        if note:
            result["note"] = note
        results.append(result)


