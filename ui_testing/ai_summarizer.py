# ui_testing/ai_summarizer.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
import numpy as np
from PIL import Image

def _load_rgba(p: Path) -> np.ndarray:
    im = Image.open(p).convert("RGBA")
    return np.asarray(im, dtype=np.int16)

def _diff_boxes(o: np.ndarray, t: np.ndarray, cell: int = 12, min_area: int = 60, pad: int = 3) -> Tuple[np.ndarray, list[tuple[int,int,int,int]]]:
    absdiff = np.abs(o - t)
    mask = np.any(absdiff > 0, axis=2)  # HxW bool
    h, w = mask.shape
    ys, xs = np.where(mask)
    if len(xs) == 0: return mask, []
    gx, gy = xs // cell, ys // cell
    cells = np.stack([gy, gx], axis=1)
    uniq = np.unique(cells, axis=0)
    from collections import deque
    cell_set = {tuple(c) for c in uniq}
    visited = set()
    boxes = []
    for cy, cx in uniq:
        if (cy, cx) in visited: continue
        Q = deque([(cy, cx)]); visited.add((cy, cx)); comp = [(cy, cx)]
        while Q:
            y, x = Q.popleft()
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    if dy==0 and dx==0: continue
                    ny, nx = y+dy, x+dx
                    if (ny, nx) in cell_set and (ny, nx) not in visited:
                        visited.add((ny, nx)); Q.append((ny, nx)); comp.append((ny, nx))
        y0 = min(c for c,_ in comp) * cell; x0 = min(_ for _,_ in [(r,c) for r,c in comp]) * cell
        y1 = min((max(c for c,_ in comp)+1)*cell-1, h-1); x1 = min((max(_ for _,_ in [(r,c) for r,c in comp])+1)*cell-1, w-1)
        sub = mask[y0:y1+1, x0:x1+1]
        if sub.any():
            sy, sx = np.where(sub)
            ry0 = y0 + sy.min(); ry1 = y0 + sy.max()
            rx0 = x0 + sx.min(); rx1 = x0 + sx.max()
        else:
            ry0, ry1, rx0, rx1 = y0, y1, x0, x1
        ry0 = max(0, ry0-pad); rx0 = max(0, rx0-pad)
        ry1 = min(h-1, ry1+pad); rx1 = min(w-1, rx1+pad)
        if (ry1-ry0+1)*(rx1-rx0+1) >= min_area:
            boxes.append((rx0, ry0, rx1, ry1))
    return mask, boxes

def _crop_and_save(img: np.ndarray, box: tuple[int,int,int,int], out: Path, scale: float = 1.0):
    x0, y0, x1, y1 = box
    pil = Image.fromarray(img.astype(np.uint8), mode="RGBA").crop((x0, y0, x1+1, y1+1))
    if scale != 1.0:
        w, h = pil.size; pil = pil.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    pil.save(out)

def write_run_bug_report(paths, script_rel: str, results: List[Dict[str,str]]) -> tuple[Path, str] | None:
    """Create a Markdown defect draft and return (path, note_text) for a failed run of script_rel."""
    try:
        # Identify the worst (max diff) failing screenshot
        worst = None
        worst_val = -1.0
        for r in results:
            if r.get("status", "fail") == "pass":
                continue
            try:
                d = float(r.get("diff_percent", "100"))
            except Exception:
                d = 100.0
            if d > worst_val:
                worst = r
                worst_val = d
        if not worst:
            return None

        orig = Path(worst.get("original", ""))
        test = Path(worst.get("test", ""))
        if not orig.exists() or not test.exists():
            return None

        o = _load_rgba(orig)
        t = _load_rgba(test)
        mask, boxes = _diff_boxes(o, t)

        # Small crops of each box for quick visual triage
        out_dir = paths.results_dir / script_rel
        out_dir.mkdir(parents=True, exist_ok=True)
        crops = []
        for i, box in enumerate(boxes[:8]):  # cap to 8 thumbnails
            out = out_dir / f"crop_{i+1}.png"
            _crop_and_save(t, box, out, scale=1.0)
            crops.append(out.name)

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        md = out_dir / f"bugdraft_{ts}.md"

        tolerance = getattr(paths, "tolerance", None)
        tol_str = f"{tolerance:.2f}" if isinstance(tolerance, (int, float)) else "N/A"

        stem = test.stem
        diff_name = (stem[:-1] + "D") if stem and stem[-1] in ("O", "T") else (stem + "_D")
        highlight_name = (stem[:-1] + "H") if stem and stem[-1] in ("O", "T") else (stem + "_H")

        note_lines = [
            f"Defect: {script_rel}",
            f"Failing checkpoint: index {worst.get('index', '?')} (diff {worst_val:.3f}% vs tolerance {tol_str}%)",
            "",
            "Evidence:",
            f"- Original (O): `{orig.name}`",
            f"- Playback (T): `{test.name}`",
            f"- Diff (D): `{diff_name}.png`",
            f"- Highlight (H): `{highlight_name}.png`",
        ]
        if crops:
            note_lines.append(f"- Cropped diff regions: {', '.join(crops)}")
        else:
            note_lines.append("- Cropped diff regions: none detected")

        hint = (
            "Transient popup/banner present"
            if len(boxes) == 1 and boxes[0][1] < 200
            else "Layout/position drift; consider increasing delay before this checkpoint"
            if len(boxes) > 1
            else "Minor antialiasing/text rendering diff"
        )

        note_lines.extend(
            [
                "",
                f"Likely cause: {hint}",
                f"Saved evidence: {out_dir.relative_to(paths.results_dir)}",
                f"Draft file: {md.name}",
            ]
        )

        note_text = "\n".join(note_lines) + "\n"
        with md.open("w", encoding="utf-8") as f:
            f.write(note_text)
        return md, note_text
    except Exception:
        return None
