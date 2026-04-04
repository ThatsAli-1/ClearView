"""
core/live_blur.py

Background worker that syncs to the current playback position,
extracts a single frame via OpenCV, runs NudeNet, and emits bounding boxes.

Runs in its OWN background thread with its own private ONNX/NudeNet session
so it never conflicts with the scan pipeline's session (DirectML is not
thread-safe when the same session object is shared across threads).

The worker polls at ~4 fps. It only runs NudeNet inside flagged windows
(+ 0.5 s buffer) at a threshold of 0.20, so it catches all body parts that
NudeNet can see even on borderline frames.
Outside flagged windows the worker emits `boxes_cleared` and sleeps cheaply.
"""
from __future__ import annotations

import time
import threading
from typing import Callable

import cv2
from PySide6.QtCore import QObject, Signal

from core.detector import CATEGORY_CLASSES, DEFAULT_ENABLED

_SCENE_BUFFER_SEC: float = 2.0
_IN_SCENE_THRESHOLD: float = 0.15
_POLL_INTERVAL: float = 0.25   # seconds between detections (≈4 fps)


class LiveBlurWorker(QObject):
    """
    Signals
    -------
    boxes_updated(boxes, video_w, video_h) : new boxes ready to paint
    boxes_cleared()                          : outside any scene — remove overlay
    """

    boxes_updated = Signal(list, int, int)   # list[(x,y,w,h)], w, h
    boxes_cleared = Signal()

    def __init__(
        self,
        video_path: str,
        detector,                              # core.detector.Detector
        get_position_ms: Callable[[], int],    # reads QMediaPlayer.position()
        scenes: list,                          # list[Scene]
        enabled: set[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = video_path
        self.detector = detector
        self.get_position_ms = get_position_ms
        self.scenes = list(scenes)
        self.enabled = enabled if enabled is not None else set(DEFAULT_ENABLED)
        self._running = False
        self._thread: threading.Thread | None = None

        # Build enabled label set once
        self._enabled_labels: set[str] = {
            lbl
            for group, lbls in CATEGORY_CLASSES.items()
            if group in self.enabled
            for lbl in lbls
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_scenes(self, scenes: list) -> None:
        self.scenes = list(scenes)

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="LiveBlur"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_in_scene(self, ts_sec: float) -> bool:
        for scene in self.scenes:
            if (scene.start - _SCENE_BUFFER_SEC) <= ts_sec <= (scene.end + _SCENE_BUFFER_SEC):
                return True
        return False

    def _loop(self) -> None:
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return

        video_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Create a completely private ONNX session for this thread.
        # MUST use CPU-only — DirectML is not thread-safe and will crash
        # if two GPU sessions run concurrently (scan pipeline owns the GPU).
        import onnxruntime
        from nudenet import NudeDetector
        from core.inference_providers import MODEL_PATH as _640m_path
        import os

        if self.detector.model_path and os.path.exists(self.detector.model_path):
            model_file = self.detector.model_path
        elif _640m_path.exists():
            model_file = str(_640m_path)
        else:
            import nudenet as _nn_pkg
            model_file = os.path.join(os.path.dirname(_nn_pkg.__file__), "320n.onnx")

        nudenet = NudeDetector(model_path=model_file)
        # Force CPU provider to avoid DirectML conflict
        nudenet.onnx_session = onnxruntime.InferenceSession(
            model_file,
            providers=["CPUExecutionProvider"],
        )
        print("[LiveBlur] Using CPU-only ONNX session (GPU reserved for scan pipeline)")

        last_pos_ms = -1

        while self._running:
            pos_ms = self.get_position_ms()
            ts_sec = pos_ms / 1000.0

            if not self._is_in_scene(ts_sec):
                self.boxes_cleared.emit()
                time.sleep(_POLL_INTERVAL)
                continue

            # Seek only if position changed meaningfully (>200 ms deviation)
            if abs(pos_ms - last_pos_ms) > 200:
                cap.set(cv2.CAP_PROP_POS_MSEC, pos_ms)
                last_pos_ms = pos_ms

            ret, frame = cap.read()
            if not ret:
                time.sleep(_POLL_INTERVAL)
                continue
            # Advance our tracked position by one frame
            last_pos_ms += int(1000 / (cap.get(cv2.CAP_PROP_FPS) or 25))

            try:
                detections = nudenet.detect(frame)
            except Exception as exc:
                print(f"[LiveBlur] detection error: {exc}")
                time.sleep(_POLL_INTERVAL)
                continue

            boxes = [
                det["box"]  # [x, y, w, h]
                for det in detections
                if det.get("class") in self._enabled_labels
                and float(det.get("score", 0)) >= _IN_SCENE_THRESHOLD
                and len(det.get("box", [])) == 4
            ]

            if boxes:
                self.boxes_updated.emit(boxes, video_w, video_h)
            else:
                self.boxes_cleared.emit()

            time.sleep(_POLL_INTERVAL)

        cap.release()
