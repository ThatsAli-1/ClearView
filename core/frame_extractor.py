"""
core/frame_extractor.py
Extracts frames from a video file on a background thread.
Pushes (timestamp_sec, frame_bgr) tuples to a queue with backpressure.
Designed to run in parallel with playback — starts from the beginning
regardless of playback position so the scan always stays ahead.
"""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable, Optional

import cv2

log = logging.getLogger(__name__)

# Sentinel pushed onto the queue when extraction finishes (replaces the
# fragile `_done` flag that was subject to TOCTOU races).
_SENTINEL = None


class FrameExtractor:
    """
    Producer thread: decode frames at `fps` frames-per-second of video time.
    The queue has a max size so memory stays bounded on long 4K files.

    Usage:
        extractor = FrameExtractor("movie.mkv", fps=2.0)
        extractor.start()
        while True:
            item = extractor.get(timeout=1.0)   # (ts_sec, frame) or None when done
            if item is None:
                break
            ts, frame = item
        extractor.stop()
    """

    QUEUE_MAXSIZE = 30  # frames buffered; at 2 fps this is ~15 s of look-ahead

    def __init__(
        self,
        video_path: str | Path,
        fps: float = 2.0,
        on_progress: Optional[Callable[[float, float], None]] = None,
    ):
        """
        Parameters
        ----------
        video_path : path to video file
        fps        : how many frames per second of video time to extract
        on_progress: optional callback(current_sec, total_sec) called each frame
        """
        self.video_path = str(video_path)
        self.fps = fps
        self.on_progress = on_progress

        self._queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.total_duration: float = 0.0
        self._finished = False  # only used by is_done property for external checks
        self._open_error: str | None = None  # set if video file can't be opened

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background extraction thread."""
        self._stop_event.clear()
        self._finished = False
        self._open_error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="FrameExtractor")
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and wait for it."""
        self._stop_event.set()
        # Drain the queue so the producer thread isn't stuck on put()
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def get(self, timeout: float = 0.5) -> Optional[tuple[float, any]]:
        """
        Get next (timestamp_sec, frame_bgr) or None when extraction is finished.

        Uses a sentinel approach: the producer pushes None when done,
        so get() never needs to inspect a separate flag (no TOCTOU race).
        """
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                return None
            return item
        return None

    @property
    def is_done(self) -> bool:
        return self._finished

    @property
    def open_error(self) -> str | None:
        """Non-None if the video file could not be opened."""
        return self._open_error

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            self._open_error = f"Could not open video: {self.video_path}"
            log.error(self._open_error)
            self._queue.put(_SENTINEL)
            self._finished = True
            return

        video_fps: float = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.total_duration = total_frames / video_fps if video_fps else 0.0

        # How many video frames to skip between each extracted frame
        frame_interval = max(1, int(round(video_fps / self.fps)))
        frame_index = 0

        try:
            while not self._stop_event.is_set():
                if frame_index % frame_interval == 0:
                    # This is a frame we want — fully decode it
                    ret, frame = cap.read()
                    if not ret:
                        break

                    timestamp_sec = frame_index / video_fps
                    if self.on_progress:
                        self.on_progress(timestamp_sec, self.total_duration)

                    # Blocking put — natural backpressure
                    while not self._stop_event.is_set():
                        try:
                            self._queue.put((timestamp_sec, frame), timeout=0.5)
                            break
                        except queue.Full:
                            continue
                else:
                    # Skip this frame — grab() advances without full decode
                    if not cap.grab():
                        break

                frame_index += 1

        finally:
            cap.release()
            # Push sentinel so consumers unblock reliably
            try:
                self._queue.put(_SENTINEL, timeout=2.0)
            except queue.Full:
                pass
            self._finished = True
