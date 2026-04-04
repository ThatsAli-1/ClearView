"""
core/warning_scheduler.py

Watches the current playback position against the list of known scenes.
Emits a warning signal when playback is within `warn_ahead_sec` of a flagged scene.
Emits a skip signal when playback reaches the start of a scene.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from core.scene_grouper import Scene


class WarningScheduler(QObject):
    """
    Attach to a player's position-changed signal and tick every 500 ms.

    Signals
    -------
    warn(scene, seconds_until)  : upcoming scene detected within warn_ahead_sec
    skip_to(target_sec)         : playback should jump to scene.end + 0.5 s
    banner_clear()              : no upcoming scene — hide the banner
    """

    warn = Signal(object, float)      # Scene, seconds_until_start
    skip_to = Signal(float)           # target position in seconds
    banner_clear = Signal()

    # Warn this many seconds before scene start
    DEFAULT_WARN_AHEAD = 60.0         # 1 minute warning

    def __init__(self, warn_ahead_sec: float = DEFAULT_WARN_AHEAD, parent=None):
        super().__init__(parent)
        self.warn_ahead_sec = warn_ahead_sec
        self._scenes: list[Scene] = []
        self._skipped: set[float] = set()  # scene.start values already skipped
        self._warned: set[float] = set()   # scene.start values already warned
        self._current_pos: float = 0.0
        self._auto_skip = True

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def add_scene(self, scene: Scene) -> None:
        self._scenes.append(scene)

    def set_scenes(self, scenes: list[Scene]) -> None:
        self._scenes = list(scenes)

    def update_position(self, pos_sec: float) -> None:
        self._current_pos = pos_sec

    def set_auto_skip(self, enabled: bool) -> None:
        self._auto_skip = enabled

    def reset(self) -> None:
        self._scenes.clear()
        self._skipped.clear()
        self._warned.clear()
        self._current_pos = 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        pos = self._current_pos
        upcoming: list[tuple[float, Scene]] = []   # (seconds_until, scene)

        for scene in self._scenes:
            seconds_until = scene.start - pos

            # Already past this scene (ended)
            if seconds_until < -scene.duration:
                continue

            # Auto-skip: if we've hit the start
            if self._auto_skip and scene.start not in self._skipped:
                if -1.5 <= seconds_until <= 1.5:
                    self._skipped.add(scene.start)
                    self.skip_to.emit(scene.end + 0.5)
                    self.banner_clear.emit()
                    continue

            # Warn if within window AHEAD, OR currently inside the scene
            if seconds_until <= self.warn_ahead_sec:
                # Include scenes we're inside (seconds_until < 0) and upcoming
                upcoming.append((seconds_until, scene))

        if upcoming:
            # Pick the nearest upcoming; if all are in the past, pick the one we're deepest inside
            future = [(s, sc) for s, sc in upcoming if s > 0]
            if future:
                seconds_until, scene = min(future, key=lambda x: x[0])
            else:
                # Currently inside a scene — pick most recent start
                seconds_until, scene = max(upcoming, key=lambda x: x[0])
            self.warn.emit(scene, max(0.0, seconds_until))
        else:
            self.banner_clear.emit()
