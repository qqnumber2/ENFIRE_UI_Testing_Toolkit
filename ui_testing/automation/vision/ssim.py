"""SSIM-based image comparison helpers."""

from __future__ import annotations

from typing import Tuple

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim


def compute_ssim(a: Image.Image, b: Image.Image) -> float:
    """Return the structural similarity index between two images."""
    a_gray = np.asarray(a.convert("L"), dtype=np.float32)
    b_gray = np.asarray(b.convert("L"), dtype=np.float32)
    return float(ssim(a_gray, b_gray, data_range=255.0))


def compare_with_ssim(a: Image.Image, b: Image.Image, threshold: float) -> Tuple[bool, float]:
    score = compute_ssim(a, b)
    return score >= threshold, score
