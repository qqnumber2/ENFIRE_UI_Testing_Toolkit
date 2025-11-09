from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageChops

try:
    from ui_testing.automation.vision.ssim import compare_with_ssim
except Exception:  # pragma: no cover - optional dependency
    compare_with_ssim = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScreenshotResult:
    passed: bool
    diff_percent: float
    diff_path: Optional[Path]
    highlight_path: Optional[Path]
    ssim_score: Optional[float]
    ssim_threshold: Optional[float]


class ScreenshotComparator:
    """Encapsulates screenshot diff/SSIM logic."""

    def __init__(self, use_ssim: bool, ssim_threshold: float) -> None:
        self._ssim_requested = bool(use_ssim)
        self._ssim_threshold = float(ssim_threshold)
        self._ssim_available = compare_with_ssim is not None
        self._use_ssim = self._ssim_requested and self._ssim_available

    @property
    def ssim_available(self) -> bool:
        return self._ssim_available

    @property
    def using_ssim(self) -> bool:
        return self._use_ssim

    def compare(
        self,
        original_path: Path,
        test_path: Path,
        diff_tolerance_percent: float,
    ) -> ScreenshotResult:
        original = Image.open(original_path).convert("RGBA")
        test = Image.open(test_path).convert("RGBA")

        if original.size != test.size:
            logger.warning("Screenshot sizes differ: %s vs %s", original.size, test.size)
            test = test.resize(original.size)
            test.save(test_path)

        diff_image = ImageChops.difference(original, test)
        diff_path: Optional[Path] = None
        highlight_path: Optional[Path] = None

        ssim_score: Optional[float] = None
        ssim_pass = True
        if self._use_ssim:
            try:
                ssim_pass, ssim_score = compare_with_ssim(original_path, test_path, self._ssim_threshold)
                logger.debug("SSIM score %.4f (threshold %.4f)", ssim_score, self._ssim_threshold)
            except Exception as exc:  # pragma: no cover - numerical differences
                logger.debug("SSIM comparison failed: %s", exc)
                ssim_pass = True
                ssim_score = None

        a = np.asarray(original, dtype=np.int16)
        b = np.asarray(test, dtype=np.int16)
        absdiff = np.abs(a - b)
        diff_mask = np.any(absdiff > 0, axis=2)
        total = diff_mask.size
        num_diff = int(diff_mask.sum())
        diff_percent = (num_diff / total) * 100.0

        diff_path = self._save_diff_image(test_path, absdiff)
        highlight_path = self._save_highlight_image(test_path, original, diff_mask)

        pixel_pass = diff_percent <= diff_tolerance_percent
        passed = pixel_pass and (ssim_pass if self._use_ssim else True)
        return ScreenshotResult(
            passed=passed,
            diff_percent=diff_percent,
            diff_path=diff_path,
            highlight_path=highlight_path,
            ssim_score=ssim_score,
            ssim_threshold=self._ssim_threshold if self._use_ssim else None,
        )

    def _save_diff_image(self, test_path: Path, absdiff: np.ndarray) -> Optional[Path]:
        perpix = absdiff[..., :3].max(axis=2)
        if perpix.max() > 0:
            perpix = (perpix.astype(np.float32) / perpix.max()) * 255.0
        diff_image = Image.fromarray(perpix.astype(np.uint8), mode="L")
        stem = test_path.stem
        d_name = (stem[:-1] + "D") if stem and stem[-1] in ("T", "O") else (stem + "_D")
        d_path_candidate = test_path.with_name(d_name + ".png")
        try:
            diff_image.save(d_path_candidate)
            return d_path_candidate
        except Exception:
            return None

    def _save_highlight_image(self, test_path: Path, original: Image.Image, diff_mask: np.ndarray) -> Optional[Path]:
        if not diff_mask.any():
            return None
        overlay = np.zeros((diff_mask.shape[0], diff_mask.shape[1], 4), dtype=np.uint8)
        overlay[..., 0] = 255
        overlay[..., 3] = np.where(diff_mask, 96, 0)
        hi = Image.alpha_composite(original, Image.fromarray(overlay))
        boxes = self._bounding_boxes_from_mask(diff_mask, cell=12, min_area=60, pad=3)
        arr = np.array(hi)
        for (x0, y0, x1, y1) in boxes:
            arr[y0:y0 + 3, x0:x1 + 1] = [255, 0, 0, 255]
            arr[y1 - 2:y1 + 1, x0:x1 + 1] = [255, 0, 0, 255]
            arr[y0:y1 + 1, x0:x0 + 3] = [255, 0, 0, 255]
            arr[y0:y1 + 1, x1 - 2:x1 + 1] = [255, 0, 0, 255]
        hi = Image.fromarray(arr, mode="RGBA")
        stem = test_path.stem
        h_name = (stem[:-1] + "H") if stem and stem[-1] in ("T", "O") else (stem + "_H")
        h_path_candidate = test_path.with_name(h_name + ".png")
        try:
            hi.save(h_path_candidate)
            return h_path_candidate
        except Exception:
            return None

    @staticmethod
    def _bounding_boxes_from_mask(mask: np.ndarray, cell: int = 12, min_area: int = 60, pad: int = 3) -> List[Tuple[int, int, int, int]]:
        h, w = mask.shape
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return []

        gx = xs // cell
        gy = ys // cell
        cells = np.stack([gy, gx], axis=1)
        uniq = np.unique(cells, axis=0)

        from collections import deque

        cell_set = {tuple(c) for c in uniq}
        visited = set()
        boxes = []

        def cell_to_bbox(cy: int, cx: int):
            x0 = cx * cell
            y0 = cy * cell
            x1 = min(w, x0 + cell)
            y1 = min(h, y0 + cell)
            return x0, y0, x1, y1

        for cy, cx in uniq:
            if (cy, cx) in visited:
                continue
            queue = deque([(cy, cx)])
            visited.add((cy, cx))
            min_cx = max_cx = cx
            min_cy = max_cy = cy
            while queue:
                py, px = queue.popleft()
                for ny in range(py - 1, py + 2):
                    for nx in range(px - 1, px + 2):
                        if (ny, nx) in cell_set and (ny, nx) not in visited:
                            visited.add((ny, nx))
                            queue.append((ny, nx))
                            min_cx = min(min_cx, nx)
                            max_cx = max(max_cx, nx)
                            min_cy = min(min_cy, ny)
                            max_cy = max(max_cy, ny)
            x0, y0, _, _ = cell_to_bbox(min_cy, min_cx)
            _, _, x1, y1 = cell_to_bbox(max_cy, max_cx)
            x0 = max(0, x0 - pad)
            y0 = max(0, y0 - pad)
            x1 = min(w, x1 + pad)
            y1 = min(h, y1 + pad)
            if (x1 - x0) * (y1 - y0) >= min_area:
                boxes.append((x0, y0, x1, y1))
        return boxes
