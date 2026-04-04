"""
core/blur_exporter.py

Exports a new video file where all detected sensitive regions are blurred.

Pipeline
--------
1. OpenCV reads the source video frame by frame.
2. For frames that fall inside a known flagged-scene window (from the prior scan)
   plus a small buffer (0.5 s each side), NudeNet is run at a very low threshold
   (0.20) so bounding boxes are captured on all frames in that range, even when
   per-frame confidence is mediocre.
3. Frames outside flagged windows are passed through unchanged (fast).
4. A strong pixelate+Gaussian blur is applied over each bounding box.
5. OpenCV writes the blurred frames to a temp .avi (no audio).
6. FFmpeg muxes the original audio tracks into the final output MP4.

Signals
-------
progress(int)   : 0-100
finished(str)   : absolute path of the exported file
error(str)      : error message
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

from core.detector import CATEGORY_CLASSES, DEFAULT_ENABLED

if TYPE_CHECKING:
    from core.scene_grouper import Scene

# Buffer added around each scene window so we never clip the first/last frame
_SCENE_BUFFER_SEC: float = 0.5

# Threshold used INSIDE a known scene window — low enough to reliably get boxes
_IN_SCENE_THRESHOLD: float = 0.20


def _apply_blur(frame: np.ndarray, box: list[int], strength: int = 51) -> np.ndarray:
    """Fill the region defined by box [x, y, w, h] with a fully opaque black rectangle.

    A 10 % padding margin is added on all sides so the box reliably covers the
    full body-part region even when NudeNet slightly under-estimates the boundary.
    """
    x, y, w, h = box
    # Add 10% padding on every side
    pad_x = max(2, w // 10)
    pad_y = max(2, h // 10)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(frame.shape[1], x + w + pad_x)
    y2 = min(frame.shape[0], y + h + pad_y)
    if x2 <= x1 or y2 <= y1:
        return frame
    # Solid black — completely opaque, nothing visible through
    frame[y1:y2, x1:x2] = 0
    return frame


class BlurExporter(QObject):
    progress = Signal(int)    # 0-100
    finished = Signal(str)    # output file path
    error = Signal(str)

    def __init__(
        self,
        video_path: str,
        detector,                     # core.detector.Detector instance
        scenes: list[Scene],          # confirmed scenes from previous scan
        threshold: float = 0.55,      # used for frames NOT in a known window (fallback)
        enabled: set[str] | None = None,
        blur_strength: int = 51,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.detector = detector
        self.scenes = list(scenes)
        self.threshold = threshold
        self.enabled = enabled if enabled is not None else set(DEFAULT_ENABLED)
        self.blur_strength = blur_strength
        self._running = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        try:
            out_path = self._export()
            if self._running:
                self.finished.emit(str(out_path))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_in_scene(self, ts: float) -> bool:
        """Return True if timestamp falls inside any known scene ± buffer."""
        for scene in self.scenes:
            if (scene.start - _SCENE_BUFFER_SEC) <= ts <= (scene.end + _SCENE_BUFFER_SEC):
                return True
        return False

    def _export(self) -> Path:
        src = str(self.video_path)
        out_path = self.video_path.with_stem(
            self.video_path.stem + "_blurred"
        ).with_suffix(".mp4")

        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {src}")

        fps    = cap.get(cv2.CAP_PROP_FPS) or 25.0
        width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

        print(f"[BlurExporter] {len(self.scenes)} scenes to blur:")
        for s in self.scenes:
            print(f"  {s.start:.1f}s → {s.end:.1f}s  cats={s.categories}")
        print(f"[BlurExporter] video: {fps}fps {width}x{height} {total} frames")

        with tempfile.NamedTemporaryFile(suffix=".avi", delete=False) as tmp:
            tmp_path = tmp.name

        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        out = cv2.VideoWriter(tmp_path, fourcc, fps, (width, height))
        if not out.isOpened():
            cap.release()
            raise RuntimeError("Could not open VideoWriter for temp file.")

        nudenet = self.detector._get_detector()

        # Build the set of labels we actually care about
        enabled_labels: set[str] = {
            label
            for group, labels in CATEGORY_CLASSES.items()
            if group in self.enabled
            for label in labels
        }
        print(f"[BlurExporter] enabled_labels: {enabled_labels}")
        print(f"[BlurExporter] in-scene threshold: {_IN_SCENE_THRESHOLD}")

        frame_idx = 0
        last_pct = -1
        blurred_frames = 0

        while self._running:
            ret, frame = cap.read()
            if not ret:
                break

            ts = frame_idx / fps
            in_scene = self._is_in_scene(ts)

            if in_scene:
                try:
                    detections = nudenet.detect(frame)
                except Exception as exc:
                    print(f"[BlurExporter] NudeNet error at {ts:.1f}s: {exc}")
                    detections = []

                applied = 0
                for det in detections:
                    label: str = det.get("class", "")
                    score: float = float(det.get("score", 0.0))
                    box: list[int] = det.get("box", [])
                    if label in enabled_labels and score >= _IN_SCENE_THRESHOLD and len(box) == 4:
                        frame = _apply_blur(frame, box, self.blur_strength)
                        applied += 1

                if applied:
                    blurred_frames += 1
                elif frame_idx % 125 == 0:  # log every ~5s if inside scene but no boxes
                    print(f"[BlurExporter] {ts:.1f}s IN scene but 0 boxes (total dets={len(detections)})")

            out.write(frame)
            frame_idx += 1

            pct = int(frame_idx / total * 100)
            if pct != last_pct:
                self.progress.emit(pct)
                last_pct = pct

        print(f"[BlurExporter] Done. {blurred_frames}/{frame_idx} frames blurred.")

        cap.release()
        out.release()

        if not self._running:
            Path(tmp_path).unlink(missing_ok=True)
            raise RuntimeError("Export cancelled.")

        self._mux_audio(src, tmp_path, str(out_path))
        Path(tmp_path).unlink(missing_ok=True)
        return out_path

    def _mux_audio(self, original: str, video_only: str, output: str) -> None:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_only,
            "-i", original,
            "-map", "0:v:0",
            "-map", "1:a?",
            "-c:v", "copy",
            "-c:a", "copy",
            "-shortest",
            output,
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode != 0:
            import shutil
            shutil.copy2(video_only, output)
            print(f"[BlurExporter] FFmpeg mux failed, saving video-only.\n"
                  f"{result.stderr.decode(errors='replace')}")
