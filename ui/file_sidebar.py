"""
ui/file_sidebar.py
Left sidebar: drop zone + file queue with scan status badges.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)


class DropZone(QFrame):
    files_dropped = Signal(list)  # list of str paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setFixedHeight(90)
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(4)

        arrow = QLabel("⬆")
        arrow.setAlignment(Qt.AlignCenter)
        arrow.setStyleSheet("font-size: 22px; color: #44444e;")
        layout.addWidget(arrow)

        hint = QLabel("Drop videos or click to browse")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #44444e; font-size: 11px;")
        layout.addWidget(hint)

    def mousePressEvent(self, event):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Video Files",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov *.wmv *.m4v *.ts *.webm);;All Files (*)",
        )
        if paths:
            self.files_dropped.emit(paths)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("QFrame#dropZone { border-color: #3d7cf4; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)


class FileItem(QFrame):
    clicked = Signal(str)   # path

    STATUS_IDLE     = "idle"
    STATUS_SCANNING = "scanning"
    STATUS_DONE     = "done"
    STATUS_WARN     = "warn"

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setObjectName("fileItem")
        self.path = path
        self.status = self.STATUS_IDLE
        self.scene_count = 0
        self.scan_pct = 0

        self.setCursor(Qt.PointingHandCursor)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        name = Path(self.path).name
        self._name_lbl = QLabel(name)
        self._name_lbl.setObjectName("heading")
        self._name_lbl.setStyleSheet("font-size:12px; color:#e0ddd8;")
        self._name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self._name_lbl)

        self._meta_lbl = QLabel("—")
        self._meta_lbl.setObjectName("muted")
        layout.addWidget(self._meta_lbl)

        self._badge = QLabel("")
        self._badge.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self._badge)

        self._update_badge()

    def set_meta(self, text: str) -> None:
        self._meta_lbl.setText(text)

    def set_status(self, status: str, pct: int = 0, scene_count: int = 0) -> None:
        self.status = status
        self.scan_pct = pct
        self.scene_count = scene_count
        self._update_badge()
        # Active styling
        self.setProperty("active", status == self.STATUS_SCANNING)
        self.style().unpolish(self)
        self.style().polish(self)

    def _update_badge(self) -> None:
        s = self.status
        if s == self.STATUS_SCANNING:
            self._badge.setText(f"scanning {self.scan_pct}%")
            self._badge.setStyleSheet(
                "background:#1a2535; color:#3d7cf4; border-radius:4px;"
                "font-size:9px; font-weight:600; padding:2px 6px;"
            )
        elif s == self.STATUS_WARN:
            n = self.scene_count
            self._badge.setText(f"{n} scene{'s' if n != 1 else ''} found")
            self._badge.setStyleSheet(
                "background:#2a1c10; color:#f5a623; border-radius:4px;"
                "font-size:9px; font-weight:600; padding:2px 6px;"
            )
        elif s == self.STATUS_DONE:
            self._badge.setText("Clean")
            self._badge.setStyleSheet(
                "background:#152318; color:#34c474; border-radius:4px;"
                "font-size:9px; font-weight:600; padding:2px 6px;"
            )
        else:
            self._badge.setText("Queued")
            self._badge.setStyleSheet(
                "background:#1a1a22; color:#44444e; border-radius:4px;"
                "font-size:9px; font-weight:600; padding:2px 6px;"
            )

    def mousePressEvent(self, event):
        self.clicked.emit(self.path)


class FileSidebar(QWidget):
    file_selected = Signal(str)     # user clicked a file item
    files_added = Signal(list)      # new paths dropped/browsed

    # Fixed detection settings: (threshold, fps, enabled_categories, min_detections)
    # Tuned for maximum recall — we'd rather false-positive than miss a scene.
    _DETECTION_SETTINGS = (
        0.55,
        4.0,
        {"breast", "genitalia_f", "genitalia_m", "buttocks", "anus", "kissing"},
        1,
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(220)
        self._items: dict[str, FileItem] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Section label
        lbl = QLabel("QUEUE")
        lbl.setObjectName("sidebarSection")
        root.addWidget(lbl)

        # Drop zone
        self._drop_zone = DropZone()
        self._drop_zone.files_dropped.connect(self._on_files)
        root.addWidget(self._drop_zone)

        # File list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 4, 0, 4)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, stretch=1)

    @property
    def imdb_settings(self) -> tuple[float, float, set, int]:
        """Returns (threshold, fps, enabled_categories, min_detections)."""
        return self._DETECTION_SETTINGS

    def add_file(self, path: str) -> FileItem:
        if path in self._items:
            return self._items[path]
        item = FileItem(path)
        item.clicked.connect(self.file_selected)
        idx = self._list_layout.count() - 1
        self._list_layout.insertWidget(idx, item)
        self._items[path] = item
        return item

    def get_item(self, path: str) -> FileItem | None:
        return self._items.get(path)

    def _on_files(self, paths: list[str]) -> None:
        for p in paths:
            self.add_file(p)
        self.files_added.emit(paths)
