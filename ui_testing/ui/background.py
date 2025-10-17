# ui_testing/ui/background.py
from __future__ import annotations

import tkinter as tk
import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageTk

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore


_LOGGER = logging.getLogger(__name__)


class VideoBackground:
    """Lightweight video loop that renders behind the rest of the UI."""

    def __init__(self, root: tk.Misc, video_path: str, alpha: float = 0.35) -> None:
        self.root = root
        self.video_path = Path(video_path)
        self._alpha = min(max(alpha, 0.05), 0.9)
        self._label = tk.Label(root, borderwidth=0, highlightthickness=0)
        self._label.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._label.lower()  # ensure all other widgets sit above the background
        self._cap: Optional["cv2.VideoCapture"] = None  # type: ignore
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._job: Optional[str] = None
        self._size: tuple[int, int] = (root.winfo_width() or 1, root.winfo_height() or 1)
        self._fps: int = 30

        if cv2 is None:
            _LOGGER.warning("OpenCV not available; skipping video background.")
            self._label.destroy()
            return

        if not self.video_path.exists():
            _LOGGER.warning("Video background asset missing: %s", self.video_path)
            self._label.destroy()
            return

        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            _LOGGER.warning("Unable to open video background: %s", self.video_path)
            self._label.destroy()
            return
        self._cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS)
        self._fps = int(fps) if fps and fps > 0 else 30
        self.root.bind("<Configure>", self._on_resize, add=True)

    def start(self) -> None:
        if self._cap is None:
            _LOGGER.debug("Video background start ignored; capture not initialized.")
            return
        # Ensure we have an initial size
        self.root.after_idle(self._update_frame)

    def stop(self) -> None:
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            finally:
                self._job = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            finally:
                self._cap = None
        try:
            self._label.destroy()
        except Exception:
            pass

    def _on_resize(self, event: tk.Event) -> None:
        if event.width > 0 and event.height > 0:
            self._size = (event.width, event.height)

    def _sync_stack_order(self) -> None:
        try:
            self._label.lower()
        except Exception:
            pass

    def _update_frame(self) -> None:
        if self._cap is None:
            return
        ret, frame = self._cap.read()
        if not ret:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret:
                _LOGGER.warning("Video background stopped reading frames; disabling.")
                self.stop()
                return
        try:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            _LOGGER.exception("Failed to convert video frame to RGB.")
            return

        width = max(1, self._size[0])
        height = max(1, self._size[1])
        frame_image = Image.fromarray(frame).resize((width, height), Image.LANCZOS)
        try:
            overlay = Image.new("RGB", frame_image.size, (16, 24, 32))
            image = Image.blend(overlay, frame_image, self._alpha)
        except Exception:
            image = frame_image
        self._photo = ImageTk.PhotoImage(image)
        self._sync_stack_order()
        self._label.configure(image=self._photo)
        delay = max(15, int(1000 / self._fps))
        self._job = self.root.after(delay, self._update_frame)
