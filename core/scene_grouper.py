"""
core/scene_grouper.py
Merges consecutive Detection hits within a gap threshold into coherent scenes.
A "scene" has a start time, end time, peak confidence, and union of categories.

Safety padding is applied when a scene is closed so the skip / blur activates
*before* the first detection and lingers *after* the last.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.detector import Detection

# Safety margins (seconds) — applied when a scene closes.
# Ensures the player starts skipping / blurring slightly *before* the
# earliest detection so no stray frames leak through.
SCENE_PAD_BEFORE: float = 1.5   # start this much earlier
SCENE_PAD_AFTER:  float = 1.0   # end this much later


@dataclass
class Scene:
    start: float                       # seconds
    end: float                         # seconds
    peak_confidence: float
    categories: list[str]
    _detections: list[Detection] = field(default_factory=list, repr=False)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration": round(self.duration, 3),
            "peak_confidence": round(self.peak_confidence, 4),
            "categories": self.categories,
        }


class SceneGrouper:
    """
    Incremental scene grouper — call add_detection() as detections arrive
    in timestamp order, then call flush() at the end to close any open scene.

    Parameters
    ----------
    gap_sec        : max gap between consecutive detections to still be one scene
    min_detections : minimum number of detections required to confirm a scene
                     (filters single-frame false positives)
    """

    def __init__(self, gap_sec: float = 5.0, min_detections: int = 1):
        self.gap_sec = gap_sec
        self.min_detections = min_detections
        self._current: Optional[Scene] = None
        self._scenes: list[Scene] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def add_detection(self, det: Detection) -> Optional[Scene]:
        """
        Feed a new detection. Returns a completed Scene if one just closed,
        otherwise returns None.
        """
        closed: Optional[Scene] = None

        if self._current is None:
            self._current = self._open(det)
        elif det.timestamp - self._current.end <= self.gap_sec:
            # Extend current scene
            self._current.end = det.timestamp
            self._current.peak_confidence = max(
                self._current.peak_confidence,
                max(det.scores.values(), default=0.0),
            )
            for cat in det.categories:
                if cat not in self._current.categories:
                    self._current.categories.append(cat)
            self._current._detections.append(det)
        else:
            # Gap too large — close current and open new
            closed = self._close_current()
            self._current = self._open(det)

        return closed

    def flush(self) -> Optional[Scene]:
        """Call at end of video to close any open scene."""
        return self._close_current()

    @property
    def scenes(self) -> list[Scene]:
        return list(self._scenes)

    def reset(self) -> None:
        self._current = None
        self._scenes.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open(self, det: Detection) -> Scene:
        return Scene(
            start=det.timestamp,
            end=det.timestamp,
            peak_confidence=max(det.scores.values(), default=0.0),
            categories=list(det.categories),
            _detections=[det],
        )

    def _close_current(self) -> Optional[Scene]:
        if self._current is None:
            return None
        scene = self._current
        self._current = None
        # Discard scenes that didn't accumulate enough evidence
        if len(scene._detections) < self.min_detections:
            return None
        # Apply safety padding so skip/blur activates early & stays late
        scene.start = max(0.0, scene.start - SCENE_PAD_BEFORE)
        scene.end   = scene.end + SCENE_PAD_AFTER
        self._scenes.append(scene)
        return scene
