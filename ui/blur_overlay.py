"""
ui/blur_overlay.py

Transparent overlay widget that sits on top of QVideoWidget.

Strategy
--------
The overlay is driven by TWO sources:

1. **Position-based (guaranteed)** — PlayerWidget calls set_time() on every
   positionChanged signal (~25 Hz).  If the current timestamp falls inside any
   known scene window the overlay fills the entire video area with solid black.
   This requires NO NudeNet at playback time and is 100 % reliable.

2. **NudeNet-based (precise, optional)** — LiveBlurWorker calls update_boxes()
   when it successfully detects bounding boxes inside a scene window.  When
   boxes are available they replace the full-frame blackout with precise
   per-body-part rectangles.  If NudeNet finds nothing the full-frame fallback
   (from source 1) still protects the viewer.

Usage
-----
    overlay = BlurOverlay(parent_widget)
    overlay.resize(parent_widget.size())
    overlay.show()

    # Every frame tick:
    overlay.set_time(ts_sec)          # drives position-based blackout

    # Optional NudeNet boxes when available:
    overlay.update_boxes([(x,y,w,h),...], video_w, video_h)
    overlay.clear_boxes()

    # When scenes are loaded / updated:
    overlay.set_scenes(scene_list)
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

_SCENE_BUFFER_SEC: float = 0.5   # padding on each side of a scene window


class BlurOverlay(QWidget):
    """
    Transparent overlay drawn on top of the video widget.
    Guarantees full-frame blackout during detected scene windows.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        # Completely transparent — mouse events pass through to the video widget
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")

        self._boxes: list[tuple[int, int, int, int]] = []
        self._video_w: int = 0       # 0 = unknown yet
        self._video_h: int = 0
        self._scenes: list = []      # list[Scene]
        self._current_ts: float = -1.0

    # ------------------------------------------------------------------
    # Public – scene-aware
    # ------------------------------------------------------------------

    def set_scenes(self, scenes: list) -> None:
        """Replace the full scene list.  Called whenever scenes are added/loaded."""
        self._scenes = list(scenes)
        self.update()

    def set_time(self, ts_sec: float) -> None:
        """Called every positionChanged tick to drive position-based blackout."""
        self._current_ts = ts_sec
        self.update()

    # ------------------------------------------------------------------
    # Public – NudeNet precision override
    # ------------------------------------------------------------------

    def update_boxes(
        self,
        boxes: list[tuple[int, int, int, int]],
        video_w: int,
        video_h: int,
    ) -> None:
        """Optional: replace generic blackout with precise NudeNet boxes."""
        self._boxes = list(boxes)
        self._video_w = max(1, video_w)
        self._video_h = max(1, video_h)
        self.update()

    def clear_boxes(self) -> None:
        """Clear NudeNet boxes (fall back to position-based blackout if in scene)."""
        if self._boxes:
            self._boxes = []
            self.update()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _in_scene(self) -> bool:
        if self._current_ts < 0:
            return False
        for s in self._scenes:
            if (s.start - _SCENE_BUFFER_SEC) <= self._current_ts <= (s.end + _SCENE_BUFFER_SEC):
                return True
        return False

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        in_scene = self._in_scene()

        # Nothing to paint
        if not in_scene and not self._boxes:
            return

        p = QPainter(self)
        ww, wh = self.width(), self.height()
        _black = QColor(0, 0, 0, 255)

        if in_scene:
            # --- precise NudeNet boxes if available ---
            if self._boxes and self._video_w > 0 and self._video_h > 0:
                vw, vh = self._video_w, self._video_h
                scale = min(ww / vw, wh / vh)
                disp_w = int(vw * scale)
                disp_h = int(vh * scale)
                off_x = (ww - disp_w) // 2
                off_y = (wh - disp_h) // 2

                for bx, by, bw, bh in self._boxes:
                    pad_x = max(4, int(bw * 0.12))
                    pad_y = max(4, int(bh * 0.12))
                    sx = off_x + int(bx * scale) - pad_x
                    sy = off_y + int(by * scale) - pad_y
                    sw = max(8, int(bw * scale)) + pad_x * 2
                    sh = max(8, int(bh * scale)) + pad_y * 2
                    p.fillRect(sx, sy, sw, sh, _black)

            else:
                # --- GUARANTEED full-frame fallback — always protects the viewer ---
                if self._video_w > 0 and self._video_h > 0:
                    vw, vh = self._video_w, self._video_h
                    scale = min(ww / vw, wh / vh)
                    disp_w = int(vw * scale)
                    disp_h = int(vh * scale)
                    off_x = (ww - disp_w) // 2
                    off_y = (wh - disp_h) // 2
                    p.fillRect(off_x, off_y, disp_w, disp_h, _black)
                else:
                    # Video dimensions not known yet — cover everything
                    p.fillRect(0, 0, ww, wh, _black)

        else:
            # Outside scene window — show stale NudeNet boxes if any
            if self._boxes and self._video_w > 0 and self._video_h > 0:
                vw, vh = self._video_w, self._video_h
                scale = min(ww / vw, wh / vh)
                disp_w = int(vw * scale)
                disp_h = int(vh * scale)
                off_x = (ww - disp_w) // 2
                off_y = (wh - disp_h) // 2

                for bx, by, bw, bh in self._boxes:
                    pad_x = max(4, int(bw * 0.12))
                    pad_y = max(4, int(bh * 0.12))
                    sx = off_x + int(bx * scale) - pad_x
                    sy = off_y + int(by * scale) - pad_y
                    sw = max(8, int(bw * scale)) + pad_x * 2
                    sh = max(8, int(bh * scale)) + pad_y * 2
                    p.fillRect(sx, sy, sw, sh, _black)
