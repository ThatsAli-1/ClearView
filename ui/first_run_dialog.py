"""
ui/first_run_dialog.py
Shown on first launch if 640m.onnx is not present.
Downloads the model in a background thread with a progress bar.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.inference_providers import MODEL_PATH, ensure_model, provider_display_name


class _DownloadWorker(QObject):
    progress = Signal(int)    # 0-100
    finished = Signal(bool)   # success

    def run(self) -> None:
        def on_progress(downloaded: int, total: int) -> None:
            pct = int(downloaded / total * 100) if total else 0
            self.progress.emit(pct)

        path = ensure_model(progress_callback=on_progress)
        self.finished.emit(path is not None)


class FirstRunDialog(QDialog):
    """
    Blocking dialog shown when 640m.onnx needs to be downloaded.
    Closes automatically on success.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ClearView — First Run Setup")
        self.setFixedSize(420, 200)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setStyleSheet("""
            QDialog { background: #111114; border: 1px solid #2a2a38; border-radius: 12px; }
            QLabel  { color: #888898; font-size: 12px; }
            QLabel#title { color: #e0ddd8; font-size: 15px; font-weight: 600; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)

        title = QLabel("Downloading AI model")
        title.setObjectName("title")
        layout.addWidget(title)

        sub = QLabel(
            "ClearView needs the 640m.onnx detection model (~99 MB).\n"
            "This only happens once."
        )
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setStyleSheet(
            "QProgressBar { background:#1e1e26; border-radius:4px; height:8px; text-align:center; }"
            "QProgressBar::chunk { background:#3d7cf4; border-radius:4px; }"
        )
        layout.addWidget(self._bar)

        self._status = QLabel("Starting download…")
        self._status.setStyleSheet("color:#44444e; font-size:10px;")
        layout.addWidget(self._status)

        provider = QLabel(f"Inference: {provider_display_name()}")
        provider.setStyleSheet("color:#3d7cf4; font-size:10px;")
        layout.addWidget(provider)

        self._start_download()

    def _start_download(self) -> None:
        self._worker = _DownloadWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)

        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def _on_progress(self, pct: int) -> None:
        self._bar.setValue(pct)
        self._status.setText(f"Downloading… {pct}%")

    def _on_finished(self, success: bool) -> None:
        if success:
            self._status.setText("Model ready.")
            self.accept()
        else:
            self._status.setText("Download failed — check your internet connection.")
            btn = QPushButton("Close")
            btn.clicked.connect(self.reject)
            self.layout().addWidget(btn)


def ensure_first_run(parent=None) -> bool:
    """
    Show the first-run dialog if needed.
    Returns True if ready to proceed, False if user cancelled / error.
    """
    if MODEL_PATH.exists():
        return True
    dlg = FirstRunDialog(parent)
    return dlg.exec() == QDialog.Accepted
