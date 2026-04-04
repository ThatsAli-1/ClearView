"""
ui/warn_banner.py
Animated warning banner that appears above the video when a flagged scene
is approaching. Shows scene categories, countdown, and a manual skip button.
"""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.scene_grouper import Scene


class WarnBanner(QWidget):
    """
    Overlay widget placed inside the player area.
    Parent must set its geometry; this widget is NOT a dialog.

    Usage:
        banner = WarnBanner(parent=player_widget)
        banner.show_warning(scene, seconds_until)
        banner.hide_banner()
    """

    def __init__(self, on_skip, parent=None):
        """
        Parameters
        ----------
        on_skip : callable — called when the user presses Skip Now
        """
        super().__init__(parent)
        self._on_skip = on_skip
        self._target_scene: Scene | None = None
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick_countdown)
        self._seconds_left = 0.0

        self._build_ui()
        self.hide()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def show_warning(self, scene: Scene, seconds_until: float) -> None:
        self._target_scene = scene
        self._seconds_left = seconds_until
        self._update_content()
        self._countdown_timer.start()
        self.setVisible(True)
        self.raise_()

    def hide_banner(self) -> None:
        self._countdown_timer.stop()
        self.hide()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("warnBanner")
        self.setFixedHeight(64)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 0, 14, 0)
        outer.setSpacing(12)

        # Icon circle
        icon_label = QLabel("!")
        icon_label.setFixedSize(30, 30)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setStyleSheet(
            "background: rgba(245,166,35,0.15); border: 1px solid rgba(245,166,35,0.35);"
            "border-radius: 15px; color: #f5a623; font-weight: bold; font-size: 14px;"
        )
        outer.addWidget(icon_label)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._title_label = QLabel("Immodest scene detected ahead")
        self._title_label.setObjectName("warn")
        self._sub_label = QLabel("")
        self._sub_label.setObjectName("muted")
        self._sub_label.setStyleSheet("color: #9a7a40; font-size: 10px;")
        text_col.addWidget(self._title_label)
        text_col.addWidget(self._sub_label)
        outer.addLayout(text_col, stretch=1)

        # Countdown
        self._countdown_label = QLabel("1:00")
        self._countdown_label.setStyleSheet(
            "color: #f5a623; font-family: Consolas, monospace; font-size: 14px; font-weight: 600;"
        )
        self._countdown_label.setFixedWidth(44)
        self._countdown_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        outer.addWidget(self._countdown_label)

        # Skip button
        skip_btn = QPushButton("Skip now")
        skip_btn.setObjectName("primaryBtn")
        skip_btn.setFixedWidth(80)
        skip_btn.clicked.connect(self._on_skip_clicked)
        outer.addWidget(skip_btn)

    def _update_content(self) -> None:
        if not self._target_scene:
            return
        cats = ", ".join(self._target_scene.categories)
        start_str = _fmt_time(self._target_scene.start)
        dur = int(self._target_scene.duration)
        self._sub_label.setText(
            f"Skipping at {start_str} · {dur}s · {cats}"
        )
        self._update_countdown()

    def _update_countdown(self) -> None:
        secs = max(0, int(self._seconds_left))
        m, s = divmod(secs, 60)
        self._countdown_label.setText(f"{m}:{s:02d}")

    def _tick_countdown(self) -> None:
        self._seconds_left = max(0.0, self._seconds_left - 1.0)
        self._update_countdown()

    def _on_skip_clicked(self) -> None:
        if self._target_scene:
            self._on_skip(self._target_scene.end + 0.5)
        self.hide_banner()


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"
