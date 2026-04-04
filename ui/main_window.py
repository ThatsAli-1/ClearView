"""
ui/main_window.py
ClearView v2 — Main Window

Wires together:
  FileSidebar  →  ScanPipeline (background thread)
                               ↓  scene_found signal
  PlayerWidget  ←  WarningScheduler  ←  position_changed
  ScenePanel    ←  scene_found
  WarnBanner    ←  WarningScheduler.warn
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStatusBar,
    QWidget,
)

from core.detector import Detector
from core.scan_pipeline import ScanPipeline
from core.scene_grouper import Scene
from core.sidecar import is_fresh, load as load_sidecar, save as save_sidecar, write_edl
from core.warning_scheduler import WarningScheduler
from ui.file_sidebar import FileSidebar
from ui.player_widget import PlayerWidget
from ui.scene_panel import ScenePanel
from ui.style import STYLESHEET


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ClearView")
        self.resize(1280, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLESHEET)

        # State
        self._active_path: str | None = None
        self._pipeline: ScanPipeline | None = None
        self._scan_thread: QThread | None = None
        self._current_scenes: list = []   # scenes for the currently loaded file

        # Core objects
        self._detector = Detector(threshold=0.55)
        self._scheduler = WarningScheduler(warn_ahead_sec=60.0)

        self._build_ui()
        self._connect_signals()
        self._build_status_bar()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = FileSidebar()
        self._player = PlayerWidget()
        self._scene_panel = ScenePanel()

        layout.addWidget(self._sidebar)
        layout.addWidget(self._player, stretch=1)
        layout.addWidget(self._scene_panel)

    def _connect_signals(self) -> None:
        # Sidebar: files added / file selected
        self._sidebar.files_added.connect(self._on_files_added)
        self._sidebar.file_selected.connect(self._on_file_selected)

        # Player → scheduler position updates
        self._player.position_changed.connect(self._scheduler.update_position)

        # Scheduler → player
        self._scheduler.warn.connect(self._on_warn)
        self._scheduler.skip_to.connect(self._player.seek)
        self._scheduler.banner_clear.connect(self._player.hide_banner)

        # Scene panel → player seek
        self._scene_panel.scene_clicked.connect(self._player.seek)

        self._player.toggle_fullscreen.connect(self._toggle_fullscreen)

        # Keyboard Shortcuts
        self._shortcut_left = QShortcut(QKeySequence(Qt.Key_Left), self)
        self._shortcut_left.activated.connect(lambda: self._player.step_backward(5000))

        self._shortcut_right = QShortcut(QKeySequence(Qt.Key_Right), self)
        self._shortcut_right.activated.connect(lambda: self._player.step_forward(5000))

        # Start the scheduler ticker
        self._scheduler.start()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._sidebar.show()
            self._scene_panel.show()
            self.statusBar().show()
            self.showNormal()
            self._player.set_fullscreen_mode(False)
        else:
            self._sidebar.hide()
            self._scene_panel.hide()
            self.statusBar().hide()
            self.showFullScreen()
            self._player.set_fullscreen_mode(True)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
        super().keyPressEvent(event)

    def _build_status_bar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._status_scan = QLabel("Ready")
        self._status_scan.setObjectName("scanStatus")
        self._status_model = QLabel("model: 640m.onnx")
        self._status_model.setObjectName("muted")
        sb.addWidget(self._status_scan)
        sb.addPermanentWidget(self._status_model)

    # ------------------------------------------------------------------
    # File Handling
    # ------------------------------------------------------------------

    def _on_files_added(self, paths: list[str]) -> None:
        """Called when user drops or browses files."""
        for p in paths:
            item = self._sidebar.get_item(p)
            if item:
                item.set_status("idle")

        # Do not auto-select: user should set IMDb severity first, then click a
        # queued file to load, play, and scan.

    def _on_file_selected(self, path: str) -> None:
        """Switch playback and scan to a different file."""
        if path == self._active_path:
            return

        # Stop any in-progress scan
        self._stop_scan()

        self._active_path = path
        _, _, enabled, _ = self._sidebar.imdb_settings

        # Reset state FIRST before loading anything
        self._scene_panel.clear()
        self._current_scenes.clear()
        self._scheduler.reset()

        # Check for existing sidecar and pre-load scenes BEFORE starting the player
        # so the LiveBlurWorker is created with the correct scene list.
        if is_fresh(path, enabled=enabled):
            scenes = load_sidecar(path) or []
            for s in scenes:
                self._current_scenes.append(s)
                self._scene_panel.add_scene(s)
                self._scheduler.add_scene(s)
            self._status_scan.setText(f"Loaded from cache — {len(scenes)} scene(s)")
            print(f"[MainWindow] Loaded {len(scenes)} scene(s) from cache for live blur")
            for s in scenes:
                print(f"  scene {s.start:.1f}s – {s.end:.1f}s  cats={s.categories}")
        else:
            scenes = []

        # Push scenes into the player so its internal timeline and LiveBlur worker receive them
        self._player.set_scenes(scenes)

        # Now load the player — LiveBlurWorker starts correctly populated
        self._player.load(path, detector=self._detector, enabled=enabled)

        # If not from cache, kick off a scan
        if not scenes:
            self._start_scan(path)

    # ------------------------------------------------------------------
    # Scan Management
    # ------------------------------------------------------------------

    def _start_scan(self, path: str) -> None:
        # Read IMDb settings from sidebar
        threshold, fps, enabled, min_detections = self._sidebar.imdb_settings
        self._detector.update_settings(
            threshold=threshold,
            enabled=enabled,
        )

        # Create pipeline on a QThread so signals marshal to UI thread
        self._pipeline = ScanPipeline(
            video_path=path,
            detector=self._detector,
            fps=fps,
            min_detections=min_detections,
        )

        self._scan_thread = QThread()
        self._pipeline.moveToThread(self._scan_thread)

        self._pipeline.scene_found.connect(self._on_scene_found)
        self._pipeline.progress.connect(self._on_scan_progress)
        self._pipeline.scan_finished.connect(self._on_scan_finished)
        self._pipeline.scan_error.connect(self._on_scan_error)
        self._scan_thread.started.connect(self._pipeline.start)

        self._scan_thread.start()

        item = self._sidebar.get_item(path)
        if item:
            item.set_status("scanning", pct=0)

        self._status_scan.setText("Scanning…")

    def _stop_scan(self) -> None:
        if self._pipeline:
            self._pipeline.stop()
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.quit()
            self._scan_thread.wait(5000)
        self._pipeline = None
        self._scan_thread = None

    # ------------------------------------------------------------------
    # Scan Callbacks (run in UI thread via queued connections)
    # ------------------------------------------------------------------

    def _on_scene_found(self, scene) -> None:
        self._current_scenes.append(scene)
        self._player.add_scene(scene)
        self._scene_panel.add_scene(scene)
        self._scheduler.add_scene(scene)

        path = self._active_path
        if path:
            item = self._sidebar.get_item(path)
            if item:
                cnt = len(self._scheduler._scenes)
                item.set_status("warn", scene_count=cnt)

    def _on_scan_progress(self, current_sec: float, total_sec: float) -> None:
        self._player.update_scan_head(current_sec)
        if total_sec > 0:
            pct = int(current_sec / total_sec * 100)
            path = self._active_path
            if path:
                item = self._sidebar.get_item(path)
                if item:
                    # Preserve the current scene count — don't reset to 0 on every tick
                    cnt = len(self._scheduler._scenes)
                    item.set_status("scanning", pct=pct, scene_count=cnt)
            self._status_scan.setText(f"Scanning {pct}%")

    def _on_scan_finished(self) -> None:
        path = self._active_path
        if path:
            scenes = self._scheduler._scenes
            cnt = len(scenes)
            item = self._sidebar.get_item(path)
            if item:
                if cnt:
                    item.set_status("warn", scene_count=cnt)
                else:
                    item.set_status("done")
            # Save sidecar + EDL
            _, _, enabled, _ = self._sidebar.imdb_settings
            save_sidecar(path, scenes, enabled=enabled)
            write_edl(path, scenes)

        cnt = len(self._scheduler._scenes)
        self._status_scan.setText(
            f"Scan complete — {cnt} scene(s) found"
        )

    def _on_scan_error(self, msg: str) -> None:
        self._status_scan.setText(f"Scan error: {msg}")

    # ------------------------------------------------------------------
    # Warning Callbacks
    # ------------------------------------------------------------------

    def _on_warn(self, scene: Scene, seconds_until: float) -> None:
        self._player.show_banner(scene, seconds_until)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._stop_scan()
        self._scheduler.stop()
        super().closeEvent(event)
