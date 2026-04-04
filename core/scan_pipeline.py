"""
core/scan_pipeline.py

Orchestrates the full scan in a background thread:
  FrameExtractor  →  Detector  →  SceneGrouper  →  signals to UI

Emits Qt signals so the UI can update in real time without polling.
Designed to run concurrently with video playback.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.detector import Detection, Detector
from core.frame_extractor import FrameExtractor
from core.scene_grouper import Scene, SceneGrouper

log = logging.getLogger(__name__)


class ScanPipeline(QObject):
    """
    Background scan pipeline with Qt signals.

    Signals
    -------
    scene_found(Scene)              : a new scene was just closed/confirmed
    progress(current_sec, total_sec): scan head moved forward
    scan_finished()                 : entire video scanned
    scan_error(str)                 : something went wrong
    """

    scene_found = Signal(object)       # Scene
    progress = Signal(float, float)    # current_sec, total_sec
    scan_finished = Signal()
    scan_error = Signal(str)

    def __init__(
        self,
        video_path: str | Path,
        detector: Detector,
        fps: float = 4.0,
        gap_sec: float = 5.0,
        min_detections: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self.video_path = Path(video_path)
        self.detector = detector
        self.fps = fps
        self.gap_sec = gap_sec
        self.min_detections = min_detections

        self._thread: Optional[threading.Thread] = None
        self._extractor: Optional[FrameExtractor] = None
        self._grouper = SceneGrouper(gap_sec=gap_sec, min_detections=min_detections)
        self._running = False
        self._consecutive_errors: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._consecutive_errors = 0
        self._grouper.reset()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="ScanPipeline",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._extractor:
            self._extractor.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8.0)

    @property
    def scenes(self) -> list[Scene]:
        return self._grouper.scenes

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            self._extractor = FrameExtractor(
                video_path=self.video_path,
                fps=self.fps,
                on_progress=lambda cur, tot: self.progress.emit(cur, tot),
            )
            self._extractor.start()

            while self._running:
                item = self._extractor.get(timeout=1.0)
                if item is None:
                    # Check if the extractor failed to open the file
                    if self._extractor.open_error:
                        self.scan_error.emit(self._extractor.open_error)
                        return
                    break

                ts, frame = item

                try:
                    detection: Optional[Detection] = self.detector.detect(ts, frame)
                    self._consecutive_errors = 0  # reset on success
                except Exception as exc:
                    self._consecutive_errors += 1
                    log.warning(
                        "Detection error at %.1fs (#%d): %s: %s",
                        ts, self._consecutive_errors, type(exc).__name__, exc,
                    )
                    if self._consecutive_errors >= 5:
                        self.scan_error.emit(
                            f"NudeNet failed on {self._consecutive_errors} frames in a row: {exc}"
                        )
                        return
                    continue

                if detection:
                    closed_scene = self._grouper.add_detection(detection)
                    if closed_scene:
                        self.scene_found.emit(closed_scene)

            # Flush any open scene at end of video
            if self._running:
                final = self._grouper.flush()
                if final:
                    self.scene_found.emit(final)
                self.scan_finished.emit()

        except Exception as exc:
            self.scan_error.emit(str(exc))
        finally:
            self._running = False
