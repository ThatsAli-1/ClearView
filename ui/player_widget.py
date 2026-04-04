"""
ui/player_widget.py
Video player area using PySide6 QMediaPlayer + QVideoWidget.
Includes a custom timeline that renders flagged scene markers in amber
and a blue scanning-progress region.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal, QUrl, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QBrush
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from core.scene_grouper import Scene
from core.live_blur import LiveBlurWorker
from ui.blur_overlay import BlurOverlay
from ui.warn_banner import WarnBanner


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


class SceneTimeline(QWidget):
    """Custom timeline widget with playhead, buffered region, and scene markers."""

    seek_requested = Signal(int)   # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self._position_ms: int = 0
        self._duration_ms: int = 0
        self._buffered_ms: int = 0
        self._scenes: list[Scene] = []
        self._scan_head_sec: float = 0.0

        # Colors
        self._col_track     = QColor("#1e1e26")
        self._col_played    = QColor("#3d7cf4")
        self._col_buffered  = QColor("#2a2a38")
        self._col_scene     = QColor("#f5a623")
        self._col_scan      = QColor(61, 124, 244, 35)
        self._col_head      = QColor("#ffffff")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def set_position(self, ms: int) -> None:
        self._position_ms = ms
        self.update()

    def set_duration(self, ms: int) -> None:
        self._duration_ms = ms
        self.update()

    def set_scenes(self, scenes: list[Scene]) -> None:
        self._scenes = list(scenes)
        self.update()

    def add_scene(self, scene: Scene) -> None:
        self._scenes.append(scene)
        self.update()

    def set_scan_head(self, sec: float) -> None:
        self._scan_head_sec = sec
        self.update()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        track_h = 4
        track_y = (h - track_h) // 2

        dur = self._duration_ms or 1

        def x_of_ms(ms: int) -> int:
            return int(ms / dur * w)

        def x_of_sec(sec: float) -> int:
            return int(sec * 1000 / dur * w)

        # Track background
        p.fillRect(0, track_y, w, track_h, self._col_track)

        # Buffered
        buf_x = x_of_ms(self._buffered_ms)
        p.fillRect(0, track_y, buf_x, track_h, self._col_buffered)

        # Scan region (translucent blue from scan head to end)
        if self._scan_head_sec > 0 and self._duration_ms > 0:
            scan_x = x_of_sec(self._scan_head_sec)
            p.fillRect(scan_x, track_y - 1, w - scan_x, track_h + 2, self._col_scan)

        # Played
        play_x = x_of_ms(self._position_ms)
        p.fillRect(0, track_y, play_x, track_h, self._col_played)

        # Scene markers (amber, slightly taller)
        p.setBrush(QBrush(self._col_scene))
        p.setPen(Qt.NoPen)
        for scene in self._scenes:
            sx = x_of_sec(scene.start)
            ex = x_of_sec(scene.end)
            bar_w = max(4, ex - sx)
            p.fillRect(sx, track_y - 2, bar_w, track_h + 4, self._col_scene)

        # Playhead
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(self._col_head))
        cx = play_x
        p.drawEllipse(cx - 6, track_y + track_h // 2 - 6, 12, 12)

    def mousePressEvent(self, event) -> None:
        if self._duration_ms <= 0:
            return
        ratio = event.position().x() / max(1, self.width())
        ms = int(ratio * self._duration_ms)
        self.seek_requested.emit(ms)


class PlayerWidget(QWidget):
    """
    Full player: video surface + custom timeline + transport controls.
    Emits position_changed(sec) every 500 ms for the warning scheduler.
    """

    position_changed = Signal(float)   # seconds
    toggle_fullscreen = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("playerArea")
        self._scenes: list[Scene] = []
        self._live_blur: LiveBlurWorker | None = None
        self._overlay: BlurOverlay | None = None  # created in _build

        # Auto-hide controls timer
        self._controls_timer = QTimer(self)
        self._controls_timer.setInterval(2500)
        self._controls_timer.setSingleShot(True)
        self._controls_timer.timeout.connect(self._hide_controls)

        self._build()
        self._setup_player()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, path: str, detector=None, enabled: set | None = None) -> None:
        """Load a video and start the live blur worker if a detector is supplied."""
        self._stop_live_blur()
        self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()
        if detector is not None:
            self._start_live_blur(path, detector, enabled)

    def _start_live_blur(self, path: str, detector, enabled) -> None:
        print(f"[PlayerWidget] Starting LiveBlur with {len(self._scenes)} scene(s)")
        for s in self._scenes:
            print(f"  {s.start:.1f}s – {s.end:.1f}s")
        self._live_blur = LiveBlurWorker(
            video_path=path,
            detector=detector,
            get_position_ms=self._player.position,
            scenes=self._scenes,
            enabled=enabled,
        )
        self._live_blur.boxes_updated.connect(self._on_blur_boxes)
        self._live_blur.boxes_cleared.connect(self._overlay.clear_boxes)
        self._live_blur.start()

    def _stop_live_blur(self) -> None:
        if self._live_blur:
            self._live_blur.stop()
            self._live_blur = None
        if self._overlay:
            self._overlay.clear_boxes()

    def seek(self, sec: float) -> None:
        self._player.setPosition(int(sec * 1000))

    def step_forward(self, ms: int = 5000) -> None:
        self._player.setPosition(min(self._player.duration(), self._player.position() + ms))

    def step_backward(self, ms: int = 5000) -> None:
        self._player.setPosition(max(0, self._player.position() - ms))

    def add_scene(self, scene: Scene) -> None:
        self._scenes.append(scene)
        self._timeline.add_scene(scene)
        if self._overlay:
            self._overlay.set_scenes(self._scenes)
        if self._live_blur:
            self._live_blur.set_scenes(self._scenes)
        print(f"[PlayerWidget] Scene added: {scene.start:.1f}s–{scene.end:.1f}s  total={len(self._scenes)}")

    def set_scenes(self, scenes: list[Scene]) -> None:
        self._scenes = list(scenes)
        self._timeline.set_scenes(scenes)
        if self._overlay:
            self._overlay.set_scenes(self._scenes)
        if self._live_blur:
            self._live_blur.set_scenes(self._scenes)

    def update_scan_head(self, sec: float) -> None:
        self._timeline.set_scan_head(sec)

    def show_banner(self, scene: Scene, seconds_until: float) -> None:
        self._banner.show_warning(scene, seconds_until)

    def hide_banner(self) -> None:
        self._banner.hide_banner()
        
    def set_fullscreen_mode(self, is_fs: bool) -> None:
        """Called when the window enters/exits fullscreen mode."""
        if is_fs:
            self._controls_timer.start()
        else:
            self._controls_timer.stop()
            self._show_controls()

    def _show_controls(self) -> None:
        if self._controls.isHidden():
            self._controls.show()
            self._video_widget.setCursor(Qt.ArrowCursor)
            
        if self.window().isFullScreen():
            self._controls_timer.start()

    def _hide_controls(self) -> None:
        if self.window().isFullScreen():
            self._controls.hide()
            self._video_widget.setCursor(Qt.BlankCursor)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Video surface (fills available space)
        self._video_widget = QVideoWidget()
        self._video_widget.setStyleSheet("background: #060608;")
        self._video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._video_widget.setMouseTracking(True)
        self._video_widget.installEventFilter(self)
        root.addWidget(self._video_widget, stretch=1)

        # Blur overlay — transparent child that covers the video widget
        self._overlay = BlurOverlay(self._video_widget)
        self._overlay.resize(self._video_widget.size())
        self._overlay.show()

        # Banner overlay — parented to video widget, positioned on top
        self._banner = WarnBanner(on_skip=self.seek, parent=self._video_widget)
        self._banner.setFixedWidth(420)
        self._banner.move(20, 14)

        # Controls bar
        self._controls = QWidget()
        self._controls.setObjectName("controlsBar")
        self._controls.setFixedHeight(72)
        self._controls.setMouseTracking(True)
        self._controls.installEventFilter(self)
        ctl_layout = QVBoxLayout(self._controls)
        ctl_layout.setContentsMargins(16, 6, 16, 10)
        ctl_layout.setSpacing(6)

        # Timeline
        self._timeline = SceneTimeline()
        self._timeline.seek_requested.connect(lambda ms: self._player.setPosition(ms))
        ctl_layout.addWidget(self._timeline)

        # Timestamp labels
        ts_row = QHBoxLayout()
        ts_row.setContentsMargins(0, 0, 0, 0)
        self._pos_label = QLabel("0:00")
        self._pos_label.setObjectName("timestamp")
        self._dur_label = QLabel("0:00")
        self._dur_label.setObjectName("muted")
        ts_row.addWidget(self._pos_label)
        ts_row.addStretch()
        ts_row.addWidget(self._dur_label)
        ctl_layout.addLayout(ts_row)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 0, 0, 0)

        def make_btn(icon_standard, obj_name: str = "") -> QPushButton:
            b = QPushButton()
            b.setIcon(self.style().standardIcon(icon_standard))
            b.setFixedSize(32, 32)
            if obj_name:
                b.setObjectName(obj_name)
            return b

        self._btn_prev   = make_btn(QStyle.SP_MediaSkipBackward)
        self._btn_back   = make_btn(QStyle.SP_MediaSeekBackward)
        self._btn_play   = make_btn(QStyle.SP_MediaPlay, "primaryBtn")
        self._btn_fwd    = make_btn(QStyle.SP_MediaSeekForward)
        self._btn_next   = make_btn(QStyle.SP_MediaSkipForward)
        self._btn_fs     = make_btn(QStyle.SP_TitleBarMaxButton)

        self._btn_prev.clicked.connect(lambda: self._player.setPosition(0))
        self._btn_back.clicked.connect(lambda: self.step_backward(10_000))
        self._btn_play.clicked.connect(self._toggle_play)
        self._btn_fwd.clicked.connect(lambda: self.step_forward(10_000))
        self._btn_next.clicked.connect(lambda: self._player.setPosition(
            self._player.duration()))
        self._btn_fs.clicked.connect(self.toggle_fullscreen.emit)

        for b in [self._btn_prev, self._btn_back, self._btn_play,
                  self._btn_fwd, self._btn_next]:
            btn_row.addWidget(b)

        btn_row.addStretch()

        # Volume
        vol_lbl = QLabel()
        pm = self.style().standardIcon(QStyle.SP_MediaVolume).pixmap(16, 16)
        vol_lbl.setPixmap(pm)
        vol_lbl.setFixedWidth(18)
        btn_row.addWidget(vol_lbl)

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(80)
        self._vol_slider.setFixedWidth(80)
        self._vol_slider.valueChanged.connect(
            lambda v: self._audio.setVolume(v / 100.0))
        btn_row.addWidget(self._vol_slider)

        btn_row.addWidget(self._btn_fs)
        ctl_layout.addLayout(btn_row)

        # Install event filter on video widget to track its own resize events
        self._video_widget.installEventFilter(self)

        root.addWidget(self._controls)

    def resizeEvent(self, event) -> None:
        """Keep overlay matched to video widget size."""
        super().resizeEvent(event)
        if self._overlay and self._video_widget:
            self._overlay.resize(self._video_widget.size())
            self._overlay.move(0, 0)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            if self.window().isFullScreen():
                self._show_controls()

        if obj == self._video_widget:
            if event.type() == QEvent.Type.Resize:
                # Keep the blur overlay matched to the video widget at all times
                if self._overlay:
                    self._overlay.resize(self._video_widget.size())
                    self._overlay.move(0, 0)
            elif event.type() == QEvent.Type.MouseButtonDblClick:
                self.toggle_fullscreen.emit()
                return True

        return super().eventFilter(obj, event)

    def _on_blur_boxes(self, boxes: list, video_w: int, video_h: int) -> None:
        if self._overlay:
            # boxes from NudeNet: [[x, y, w, h], ...]
            parsed = [
                (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
                for b in boxes if len(b) == 4
            ]
            self._overlay.update_boxes(parsed, video_w, video_h)



    def _setup_player(self) -> None:
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._audio.setVolume(0.8)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video_widget)

        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.metaDataChanged.connect(self._on_metadata_changed)

    def _on_metadata_changed(self) -> None:
        """Capture video resolution so the overlay can do correct letterbox math."""
        res = self._player.metaData().value("Resolution")
        if res and self._overlay:
            self._overlay.update_boxes([], int(res.width()), int(res.height()))

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_position_changed(self, ms: int) -> None:
        self._pos_label.setText(_fmt_ms(ms))
        self._timeline.set_position(ms)
        self.position_changed.emit(ms / 1000.0)
        # Drive the overlay's position-based guaranteed blackout
        if self._overlay:
            self._overlay.set_time(ms / 1000.0)

    def _on_duration_changed(self, ms: int) -> None:
        self._dur_label.setText(_fmt_ms(ms))
        self._timeline.set_duration(ms)

    def _on_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self._btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self._btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
