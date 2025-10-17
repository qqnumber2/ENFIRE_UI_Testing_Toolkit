# ui_testing/services/ai_summarizer.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

try:
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.lsa import LsaSummarizer
except Exception:  # pragma: no cover - optional dependency
    PlaintextParser = None
    Tokenizer = None
    LsaSummarizer = None


@dataclass
class BugNote:
    """Structured result for an AI-assisted defect note."""

    note_path: Path
    note_text: str
    summary: Optional[str] = None
    recommendations: Optional[List[str]] = None
    analysis: Optional[str] = None


def _load_rgba(p: Path) -> np.ndarray:
    im = Image.open(p).convert("RGBA")
    return np.asarray(im, dtype=np.int16)


def _diff_boxes(
    o: np.ndarray,
    t: np.ndarray,
    cell: int = 12,
    min_area: int = 60,
    pad: int = 3,
) -> Tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    absdiff = np.abs(o - t)
    mask = np.any(absdiff > 0, axis=2)  # HxW bool
    h, w = mask.shape
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return mask, []
    gx, gy = xs // cell, ys // cell
    cells = np.stack([gy, gx], axis=1)
    uniq = np.unique(cells, axis=0)
    from collections import deque

    cell_set = {tuple(c) for c in uniq}
    visited = set()
    boxes = []
    for cy, cx in uniq:
        if (cy, cx) in visited:
            continue
        queue = deque([(cy, cx)])
        visited.add((cy, cx))
        comp = [(cy, cx)]
        while queue:
            y, x = queue.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny, nx = y + dy, x + dx
                    if (ny, nx) in cell_set and (ny, nx) not in visited:
                        visited.add((ny, nx))
                        queue.append((ny, nx))
                        comp.append((ny, nx))
        y0 = min(c for c, _ in comp) * cell
        x0 = min(c for _, c in comp) * cell
        y1 = min((max(c for c, _ in comp) + 1) * cell - 1, h - 1)
        x1 = min((max(c for _, c in comp) + 1) * cell - 1, w - 1)
        sub = mask[y0 : y1 + 1, x0 : x1 + 1]
        if sub.any():
            sy, sx = np.where(sub)
            ry0 = y0 + sy.min()
            ry1 = y0 + sy.max()
            rx0 = x0 + sx.min()
            rx1 = x0 + sx.max()
        else:
            ry0, ry1, rx0, rx1 = y0, y1, x0, x1
        ry0 = max(0, ry0 - pad)
        rx0 = max(0, rx0 - pad)
        ry1 = min(h - 1, ry1 + pad)
        rx1 = min(w - 1, rx1 + pad)
        if (ry1 - ry0 + 1) * (rx1 - rx0 + 1) >= min_area:
            boxes.append((rx0, ry0, rx1, ry1))
    return mask, boxes


def _crop_and_save(img: np.ndarray, box: tuple[int, int, int, int], out: Path, scale: float = 1.0):
    x0, y0, x1, y1 = box
    pil = Image.fromarray(img.astype(np.uint8), mode="RGBA").crop((x0, y0, x1 + 1, y1 + 1))
    if scale != 1.0:
        w, h = pil.size
        pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    pil.save(out)


def _summarize_text(text: str, max_sentences: int = 3) -> Optional[str]:
    if not text.strip():
        return None
    if not all((PlaintextParser, Tokenizer, LsaSummarizer)):
        return None
    try:
        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = LsaSummarizer()
        summary_sentences = summarizer(parser.document, max_sentences)
        summary = " ".join(str(s) for s in summary_sentences).strip()
        return summary or None
    except Exception:
        return None



def _brief_summary(total: int, failure_count: int, worst_idx: str, worst_val: float, tol_str: str, location: str, coverage: float) -> str:
    if failure_count <= 0:
        prefix = f"0/{total} checkpoints failed"
    elif failure_count == 1:
        prefix = "1 checkpoint failed"
    else:
        prefix = f"{failure_count}/{total} checkpoints failed"

    coverage_text = f"covers ~{coverage:.1f}% of the screen" if coverage > 0 else "covers a very small area"
    return f"{prefix}; worst diff {worst_val:.2f}% (tol {tol_str}%) at checkpoint {worst_idx}; region {location}, {coverage_text}."



def _condense_summary(summary: Optional[str], fallback: str, max_sentences: int = 2, max_chars: int = 220) -> str:
    if summary:
        compact = " ".join(summary.split())
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', compact) if s.strip()]
        trimmed = " ".join(sentences[:max_sentences]).strip()
        if trimmed:
            if len(trimmed) > max_chars:
                trimmed = trimmed[:max_chars].rsplit(" ", 1)[0].rstrip(",;") + "..."
            if trimmed and trimmed[-1] not in ".!?":
                trimmed += "."
            return trimmed
    return fallback


def _box_statistics(boxes: List[tuple[int, int, int, int]], shape: Tuple[int, int, int]) -> Dict[str, float | str | int]:
    h, w = shape[:2]
    total_pixels = float(h * w)
    if not boxes:
        return {
            "count": 0,
            "coverage_pct": 0.0,
            "avg_height": 0.0,
            "avg_width": 0.0,
            "location": "no diff regions detected",
            "max_box_pct": 0.0,
        }

    areas = [(x1 - x0 + 1) * (y1 - y0 + 1) for (x0, y0, x1, y1) in boxes]
    coverage_pct = sum(areas) / total_pixels * 100.0
    centers_y = [((y0 + y1) / 2) / h for (_, y0, _, y1) in boxes]
    avg_center_y = mean(centers_y)
    if avg_center_y < 0.33:
        location = "upper third of the viewport"
    elif avg_center_y > 0.66:
        location = "lower third of the viewport"
    else:
        location = "center of the viewport"

    max_box_pct = max(areas) / total_pixels * 100.0
    avg_height = mean(y1 - y0 + 1 for (_, y0, _, y1) in boxes) / h * 100.0
    avg_width = mean(x1 - x0 + 1 for (x0, _, x1, _) in boxes) / w * 100.0

    return {
        "count": len(boxes),
        "coverage_pct": coverage_pct,
        "avg_height": avg_height,
        "avg_width": avg_width,
        "location": location,
        "max_box_pct": max_box_pct,
    }


def _compose_analysis_lines(
    results: List[Dict[str, str]],
    failures: List[Dict[str, str]],
    stats: Dict[str, float | str | int],
    worst_diff: float,
    hint: str,
) -> List[str]:
    lines: List[str] = []
    indices_preview = ", ".join(str(f.get("index", "?")) for f in failures[:8])
    if len(failures) > 8:
        indices_preview += " ..."
    lines.append(
        f"Run summary: {len(failures)} of {len(results)} checkpoints failed (indices: {indices_preview})."
    )
    lines.append(
        f"Worst diff {worst_diff:.3f}% with {stats['count']} diff region(s) concentrated in the {stats['location']}."
    )
    lines.append(
        f"Diff coverage spans approx. {stats['coverage_pct']:.2f}% of the frame; largest cluster covers approx. {stats['max_box_pct']:.2f}% of pixels."
    )
    lines.append(
        f"Average diff region footprint: {stats['avg_width']:.2f}% width by {stats['avg_height']:.2f}% height."
    )
    lines.append(f"Heuristic assessment: {hint}.")

    for fail in failures[:5]:
        diff_val = fail.get("diff_percent", "?")
        idx = fail.get("index", "?")
        screenshot = Path(fail.get("test", "?")).name
        lines.append(f"Checkpoint {idx} failed with {diff_val}% diff (playback screenshot: {screenshot}).")

    if len(failures) > 5:
        lines.append(f"… plus {len(failures) - 5} additional failures not detailed here.")

    return lines


def _recommendations_from_context(
    script_rel: str,
    failures: List[Dict[str, str]],
    stats: Dict[str, float | str | int],
    worst_val: float,
    tolerance: Optional[float],
    total_checkpoints: int,
) -> List[str]:
    coverage = float(stats.get("coverage_pct", 0.0) or 0.0)
    max_box = float(stats.get("max_box_pct", 0.0) or 0.0)
    count = int(stats.get("count", 0) or 0)

    recs: List[str] = []
    tol = tolerance if isinstance(tolerance, (int, float)) else None

    if tol is not None and worst_val < max(0.5, tol * 4):
        recs.append(
            "Observed delta is marginal; re-capture the baseline screenshot or relax tolerance slightly after confirming the UI is unchanged."
        )
    if coverage > 15.0 or max_box > 10.0:
        recs.append(
            "Large UI regions changed; verify window sizing, scaling (DPI), or recent layout updates in ENFIRE before replaying."
        )
    if count >= 3 and coverage < 10.0:
        recs.append(
            "Multiple thin diff clusters detected; likely transient widgets or animations; try adding delay before this checkpoint or disabling popups."
        )
    if total_checkpoints and len(failures) > total_checkpoints * 0.3:
        recs.append(
            "High failure rate across checkpoints; replay with `Ignore recorded delays` enabled and inspect automation IDs for brittle steps."
        )
    recs.append(
        "Review highlighted evidence under results/{}/ for context and re-record once the UI is stable.".format(script_rel)
    )
    return recs


def write_run_bug_report(paths, script_rel: str, results: List[Dict[str, str]]) -> Optional[BugNote]:
    """Build a Markdown defect draft enriched with AI generated insight."""
    try:
        failures = [r for r in results if r.get("status", "fail") != "pass"]
        if not failures:
            return None

        worst = max(
            failures,
            key=lambda r: float(r.get("diff_percent", "100") or 100.0),
        )
        try:
            worst_val = float(worst.get("diff_percent", "100") or 100.0)
        except Exception:
            worst_val = 100.0

        orig = Path(worst.get("original", ""))
        test = Path(worst.get("test", ""))
        if not orig.exists() or not test.exists():
            return None

        o = _load_rgba(orig)
        t = _load_rgba(test)
        _, boxes = _diff_boxes(o, t)
        stats = _box_statistics(boxes, o.shape)

        out_dir = paths.results_dir / script_rel
        out_dir.mkdir(parents=True, exist_ok=True)
        crops = []
        for i, box in enumerate(boxes[:8]):  # cap to 8 thumbnails
            out = out_dir / f"crop_{i + 1}.png"
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
            f"- Cropped diff regions: {', '.join(crops)}" if crops else "- Cropped diff regions: none detected",
        ]

        count = int(stats.get("count", 0) or 0)
        coverage = float(stats.get("coverage_pct", 0.0) or 0.0)
        location = str(stats.get("location", "unknown region"))
        worst_idx = str(worst.get("index", "?"))
        if count == 1 and location.startswith("upper"):
            hint = "Transient popup/banner present"
        elif coverage > 10.0:
            hint = "Layout/position drift; consider increasing delay before this checkpoint"
        else:
            hint = "Minor antialiasing/text rendering diff"

        note_lines.extend(
            [
                "",
                f"Likely cause: {hint}",
                f"Saved evidence: {out_dir.relative_to(paths.results_dir)}",
                f"Draft file: {md.name}",
            ]
        )

        analysis_lines = _compose_analysis_lines(results, failures, stats, worst_val, hint)

        context_parts = [
            f"Total checkpoints: {len(results)}; failures: {len(failures)}.",
            f"Worst diff: {worst_val:.3f}% at checkpoint {worst_idx}.",
            f"Diff regions located in the {location} covering approx. {coverage:.2f}% of the screen.",
            f"Heuristic cause: {hint}.",
        ] + analysis_lines

        summary_source = " ".join(context_parts)
        generated_summary = _summarize_text(summary_source, max_sentences=2)
        fallback_summary = _brief_summary(
            len(results),
            len(failures),
            worst_idx,
            worst_val,
            tol_str,
            location,
            coverage,
        )
        summary = _condense_summary(generated_summary, fallback_summary)

        recommendations = _recommendations_from_context(
            script_rel,
            failures,
            stats,
            worst_val,
            tolerance if isinstance(tolerance, (float, int)) else None,
            len(results),
        )

        if summary:
            note_lines.extend(["", "AI Summary:", summary])
        if analysis_lines:
            note_lines.extend(["", "AI Analysis:"])
            note_lines.extend(f"- {line}" for line in analysis_lines)
        if recommendations:
            note_lines.extend(["", "AI Recommendations:"])
            note_lines.extend(f"- {rec}" for rec in recommendations)

        note_text = "\n".join(note_lines) + "\n"
        with md.open("w", encoding="utf-8") as f:
            f.write(note_text)

        return BugNote(
            note_path=md,
            note_text=note_text,
            summary=summary,
            recommendations=recommendations or None,
            analysis="\n".join(analysis_lines) if analysis_lines else None,
        )
    except Exception as exc:
        logging.exception("Bug note generation failed for %s", script_rel)
        return None
