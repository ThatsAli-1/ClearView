"""
ui/scene_panel.py
Right-side panel showing flagged scenes as they are discovered in real time.
Each row shows timestamp range, category tags, and confidence bar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.scene_grouper import Scene


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


CAT_COLORS: dict[str, tuple[str, str]] = {
    "breast":      ("#271525", "#d46ea0"),
    "genitalia_f": ("#251510", "#d46030"),
    "genitalia_m": ("#251510", "#d46030"),
    "buttocks":    ("#1a2010", "#7ab040"),
    "anus":        ("#1a2010", "#7ab040"),
}


class SceneRow(QFrame):
    clicked = Signal(float)   # emits scene.start

    def __init__(self, scene: Scene, parent=None):
        super().__init__(parent)
        self.setObjectName("sceneItem")
        self.scene = scene
        self._build(scene)
        self.setCursor(Qt.PointingHandCursor)

    def _build(self, scene: Scene) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        # Timestamp range
        ts_label = QLabel(f"{_fmt_time(scene.start)}  →  {_fmt_time(scene.end)}")
        ts_label.setObjectName("timestamp")
        layout.addWidget(ts_label)

        # Category pills
        cats_row = QHBoxLayout()
        cats_row.setSpacing(4)
        cats_row.setContentsMargins(0, 0, 0, 0)
        for cat in scene.categories:
            bg, fg = CAT_COLORS.get(cat, ("#222", "#888"))
            pill = QLabel(cat.replace("_", " "))
            pill.setStyleSheet(
                f"background:{bg}; color:{fg}; border-radius:4px;"
                f"font-size:9px; font-weight:600; padding:2px 6px;"
            )
            pill.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            cats_row.addWidget(pill)
        cats_row.addStretch()
        layout.addLayout(cats_row)

        # Confidence bar (color scale based on confidence level)
        conf = scene.peak_confidence
        
        bar = QProgressBar()
        bar.setFixedHeight(4)
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        bar.setValue(int(conf * 100))
        
        if conf >= 0.80:
            fill = "#e74c3c"  # Reddish
            bg = "rgba(231, 76, 60, 0.15)"
        elif conf >= 0.65:
            fill = "#e67e22"  # Orange
            bg = "rgba(230, 126, 34, 0.15)"
        elif conf >= 0.50:
            fill = "#f1c40f"  # Yellow
            bg = "rgba(241, 196, 15, 0.15)"
        else:
            fill = "#888898"  # Grey
            bg = "#1e1e26"

        bar.setStyleSheet(f"""
            QProgressBar {{
                background: {bg};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {fill};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(bar)

        # Confidence label
        conf_label = QLabel(f"peak confidence {conf:.2f}")
        conf_label.setObjectName("muted")
        layout.addWidget(conf_label)

        # Auto-skip badge
        badge = QLabel("⤼ auto-skip queued")
        badge.setStyleSheet(
            "background:#151d2a; color:#3d7cf4; border-radius:4px;"
            "font-size:9px; font-weight:600; padding:2px 6px;"
        )
        badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(badge)

    def mousePressEvent(self, event):
        self.clicked.emit(self.scene.start)


class ScenePanel(QWidget):
    """Scrollable list of scene rows, updated in real time."""

    scene_clicked = Signal(float)   # seek to this time

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rightPanel")
        self.setFixedWidth(240)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet("background:#111114; border-bottom:1px solid #1e1e24;")
        header.setFixedHeight(38)
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(14, 0, 14, 0)
        title = QLabel("Flagged scenes")
        title.setStyleSheet("color:#888898; font-size:11px; font-weight:600;")
        self._count_badge = QLabel("0 found")
        self._count_badge.setStyleSheet(
            "background:rgba(245,166,35,0.12); color:#f5a623;"
            "border-radius:8px; font-size:10px; font-weight:600; padding:2px 7px;"
        )
        h_row.addWidget(title)
        h_row.addStretch()
        h_row.addWidget(self._count_badge)
        root.addWidget(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

        # Bottom settings area (placeholder — thresholds are in sidebar)
        root.addWidget(self._build_settings_area())

    def _build_settings_area(self) -> QWidget:
        area = QWidget()
        area.setStyleSheet("background:#111114; border-top:1px solid #1e1e24;")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)

        lbl = QLabel("LIVE BLUR")
        lbl.setStyleSheet("color:#44444e; font-size:9px; letter-spacing:1px; font-weight:600;")
        layout.addWidget(lbl)

        self._blur_status = QLabel("Detected body parts are blurred live during playback.")
        self._blur_status.setWordWrap(True)
        self._blur_status.setStyleSheet("color:#44444e; font-size:10px;")
        layout.addWidget(self._blur_status)
        return area

    def add_scene(self, scene: Scene) -> None:
        """Add a newly discovered scene row (call from main thread via signal)."""
        row = SceneRow(scene)
        row.clicked.connect(self.scene_clicked)
        # Insert before the stretch at the bottom
        idx = self._list_layout.count() - 1
        self._list_layout.insertWidget(idx, row)
        n = self._list_layout.count() - 1  # subtract stretch
        self._count_badge.setText(f"{n} found")

    def clear(self) -> None:
        while self._list_layout.count() > 1:  # keep the trailing stretch
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._count_badge.setText("0 found")
