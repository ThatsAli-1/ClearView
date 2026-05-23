# ClearView v2

> A dark-modern desktop guardian that scans video files for sensitive scenes **while playing them simultaneously** — zero waiting, real-time warnings, and live frame blurring.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & Design Philosophy](#2-architecture--design-philosophy)
3. [System Data-Flow](#3-system-data-flow)
4. [Module-by-Module Review](#4-module-by-module-review)
   - 4.1 [Entry Point — `main.py`](#41-entry-point--mainpy)
   - 4.2 [Core — `inference_providers.py`](#42-core--inference_providerspy)
   - 4.3 [Core — `frame_extractor.py`](#43-core--frame_extractorpy)
   - 4.4 [Core — `detector.py`](#44-core--detectorpy)
   - 4.5 [Core — `scene_grouper.py`](#45-core--scene_grouperpy)
   - 4.6 [Core — `scan_pipeline.py`](#46-core--scan_pipelinepy)
   - 4.7 [Core — `warning_scheduler.py`](#47-core--warning_schedulerpy)
   - 4.8 [Core — `live_blur.py`](#48-core--live_blurpy)
   - 4.9 [Core — `blur_exporter.py`](#49-core--blur_exporterpy)
   - 4.10 [Core — `sidecar.py`](#410-core--sidecarpy)
   - 4.11 [UI — `style.py`](#411-ui--stylepy)
   - 4.12 [UI — `first_run_dialog.py`](#412-ui--first_run_dialogpy)
   - 4.13 [UI — `file_sidebar.py`](#413-ui--file_sidebarpy)
   - 4.14 [UI — `player_widget.py`](#414-ui--player_widgetpy)
   - 4.15 [UI — `blur_overlay.py`](#415-ui--blur_overlaypy)
   - 4.16 [UI — `warn_banner.py`](#416-ui--warn_bannerpy)
   - 4.17 [UI — `scene_panel.py`](#417-ui--scene_panelpy)
   - 4.18 [UI — `main_window.py`](#418-ui--main_windowpy)
5. [Concurrency Model](#5-concurrency-model)
6. [Detection Strategy — Deep Dive](#6-detection-strategy--deep-dive)
7. [Overlay Safety Strategy](#7-overlay-safety-strategy)
8. [Caching & Output Files](#8-caching--output-files)
9. [Settings Reference](#9-settings-reference)
10. [Setup & Running](#10-setup--running)
11. [Packaging to `.exe`](#11-packaging-to-exe)
12. [Known Limitations & Future Work](#12-known-limitations--future-work)

---

## 1. Project Overview

ClearView is a Python desktop application targeting Windows, built with **PySide6** (Qt 6). Its core proposition is:

- Load any video file and **start playing it immediately** — no pre-scan required.
- A background AI scanner (NudeNet ONNX) races ~60 seconds ahead of the playback head.
- Detected sensitive scenes are shown as **amber markers on a custom timeline**, listed in a real-time right panel, and trigger a **60-second advance warning banner** on screen.
- When playback reaches a flagged scene, the player **auto-skips** past its end — or, alternatively, a **live blur overlay** blacks out the detected body-part regions frame by frame.
- Scan results are cached to a JSON sidecar file next to the video, so re-opening the same file is instant.
- A separate `BlurExporter` can render a new blurred MP4 that works in any player without ClearView.

---

## 2. Architecture & Design Philosophy

### 2.1 Separation of Concerns

The project is split into two top-level Python packages:

| Package | Responsibility |
|---------|---------------|
| `core/` | All business logic: frame extraction, AI detection, scene grouping, scheduling, caching, blur export |
| `ui/`   | Pure presentation: Qt widgets, overlays, stylesheets, dialogs |

No UI code imports from `core` except through well-defined **Qt signals**. No core code ever touches a widget directly. This means the core modules are independently testable without a display.

### 2.2 Concurrent-by-Design

Three threads run simultaneously during playback:

| Thread | Name | Purpose |
|--------|------|---------|
| Qt main thread | — | UI rendering, QMediaPlayer playback, WarningScheduler ticker |
| `ScanPipeline` | `ScanPipeline` | Frame extraction → NudeNet scan (GPU session) |
| `LiveBlurWorker` | `LiveBlur` | Frame-accurate bounding-box extraction (CPU session) |

These threads communicate exclusively through **Qt signals** (queued connections), which are thread-safe by design and eliminate the need for manual mutex locking in the UI layer.

### 2.3 GPU / CPU Session Isolation

DirectML (Windows GPU) ONNX sessions are **not thread-safe** across concurrent inference calls. ClearView solves this by giving each worker its own private ONNX session:

- `ScanPipeline` → uses `DmlExecutionProvider` (GPU) for maximum throughput.
- `LiveBlurWorker` → uses `CPUExecutionProvider` (explicitly, to avoid conflicts).

### 2.4 Progressive Confidence (Recall-maximising)

A two-pass detection strategy ensures no sensitive frame is silently missed:

1. **Primary pass** at the configured threshold (e.g. 0.55).
2. **Rescue pass** at a lower secondary threshold (e.g. 0.50) if the primary found nothing.

This biases toward higher recall at the cost of occasional false positives — the intentional design choice for a content-protection tool.

---

## 3. System Data-Flow

```
Video File
    │
    ├──► QMediaPlayer ─────────────────────────────────────────► Screen (plays immediately)
    │                                                                │
    │                                                         positionChanged
    │                                                                │
    │                                                    WarningScheduler._tick()
    │                                                         (every 500 ms)
    │                                                       ┌────────────────┐
    │                                                       │  warn signal   │──► WarnBanner (overlay)
    │                                                       │  skip_to signal│──► QMediaPlayer.setPosition()
    │                                                       └────────────────┘
    │
    └──► FrameExtractor (background thread, OpenCV)
              │  (timestamp, BGR frame) via bounded queue (max 30)
              ▼
         NudeNet Detector — primary pass @ threshold
              │  if nothing fires → rescue pass @ secondary_threshold
              ▼
         SceneGrouper.add_detection()
              │  merges hits within gap_sec=5.0 s into Scene objects
              │  applies SCENE_PAD_BEFORE=1.5s / SCENE_PAD_AFTER=1.0s safety margins
              ▼
         ScanPipeline emits scene_found(Scene)  ──────────────────────────────────►
              │                                                                     │
              │                                                    MainWindow._on_scene_found()
              │                                                         ├── ScenePanel.add_scene()
              │                                                         ├── PlayerWidget.add_scene()
              │                                                         │      ├── SceneTimeline (amber marker)
              │                                                         │      └── BlurOverlay.set_scenes()
              │                                                         └── WarningScheduler.add_scene()
              │
         BlurOverlay (transparent child of QVideoWidget)
              │  Source 1 (guaranteed): set_time() called on every positionChanged
              │    → full-frame blackout whenever ts ∈ [scene.start-0.5, scene.end+0.5]
              │  Source 2 (precise): LiveBlurWorker polls at ≈4 fps
              │    → per-bounding-box blackout when NudeNet fires
              └────────────────────────────────────────────────────────────────────►

         On scan_finished:
              └──► sidecar.save()      → <video>_clearview.json
              └──► sidecar.write_edl() → <video>_clearview.edl  (MPC-HC skip file)
```

---

## 4. Module-by-Module Review

### 4.1 Entry Point — `main.py`

**Size:** ~40 lines | **Role:** Bootstrap

`main.py` is intentionally thin. It:

1. Creates the `QApplication` and sets global metadata.
2. Sets the app-wide font to `Segoe UI 10pt` for a native Windows feel.
3. Calls `ensure_first_run()` — blocks until the `640m.onnx` model is present or the user cancels.
4. Instantiates `MainWindow`, writes the active inference provider into the status bar, and enters the Qt event loop.

**Design note:** The first-run gate at startup means the rest of the application can assume the model always exists — simplifying error handling throughout `core/`.

---

### 4.2 Core — `inference_providers.py`

**Size:** ~108 lines | **Role:** GPU auto-selection + model download

Responsible for two things:

**Provider detection:**
```
CUDA → DirectML → ROCm → CPU
```
`get_providers()` queries `onnxruntime.get_available_providers()` at runtime and returns an ordered list of whatever is actually installed. The scan pipeline uses the top entry.

**Model management:**
- Stores `640m.onnx` under `~/.clearview/models/` (user profile, not project directory).
- `ensure_model()` validates file size (must be ≥ 10 MB) before trusting a cached file — guards against partial downloads or HTML redirect blobs being saved as the model.
- Downloads from Hugging Face (`huggingface.co`) rather than GitHub releases, which avoids HTML redirect issues that plagued earlier versions.
- Atomic rename: downloads to `.tmp` first, validates, then renames — so a failed download never leaves a corrupt model in place.

---

### 4.3 Core — `frame_extractor.py`

**Size:** ~172 lines | **Role:** Threaded frame producer

`FrameExtractor` runs OpenCV's `VideoCapture` on a background thread and pushes `(timestamp_sec, BGR_frame)` tuples onto a bounded `queue.Queue`.

**Key design decisions:**

| Decision | Reasoning |
|----------|-----------|
| `QUEUE_MAXSIZE = 30` | Caps memory at ~15 s of look-ahead buffer at 2 fps; prevents OOM on 4K files |
| `cap.grab()` for skipped frames | Advances the codec without full decode — 5-10× cheaper than `cap.read()` |
| **Sentinel pattern** (`_SENTINEL = None`) | Producer pushes `None` when done; consumer sees it and exits — eliminates TOCTOU race vs. a separate `_done` flag |
| Stop drains the queue | `stop()` empties the queue before joining, so the producer is never blocked on a full queue and the join completes in ≤ 5 s |
| `_open_error` property | If `VideoCapture` fails to open the file, an error string is stored and the pipeline emits `scan_error` — user sees a clear message rather than a silent hang |

---

### 4.4 Core — `detector.py`

**Size:** ~290 lines | **Role:** NudeNet wrapper with multi-resolution strategy

The most complex core module. `Detector` wraps `nudenet.NudeDetector` with several important additions:

**Category mapping:**
NudeNet v3 returns raw class names (e.g. `FEMALE_BREAST_EXPOSED`). `detector.py` maps these into logical groups (`breast`, `genitalia_f`, `genitalia_m`, `buttocks`, `anus`) so the rest of the app never depends on NudeNet's internal naming, and optional covered-category groups (`breast_covered`, `genitalia_f_covered`) can be toggled independently.

**Kissing detection (face-proximity heuristic):**
ClearView adds an original kissing detector on top of NudeNet:
- Collects all `FACE_FEMALE` / `FACE_MALE` bounding boxes with score ≥ 0.35.
- Computes pairwise Euclidean distance between face centres.
- If any two face centres are within 40% of the average face width, a pseudo-confidence `(score₁ + score₂) / 2` is generated.
- This fires the `kissing` category without any additional model.

**Two-pass detection:**
```python
det = self._evaluate(results, timestamp, self.threshold)      # primary
if det is None:
    det = self._evaluate(results, timestamp, self.secondary)  # rescue
```
The rescue pass re-evaluates the *same* NudeNet results at a lower bar — no extra inference cost.

**Breast strict mode:**
Adds `+0.15` to the effective breast threshold when enabled, reducing the highest false-positive category without disabling it entirely.

**Lazy loading + DirectML injection:**
NudeNet's API doesn't expose an ONNX providers parameter. ClearView works around this by directly replacing `detector.onnx_session` with a hand-constructed `onnxruntime.InferenceSession` using `["DmlExecutionProvider", "CPUExecutionProvider"]`. This fires only on first `detect()` call.

**Hot-update:** `update_settings()` changes threshold, enabled set, and secondary threshold without reloading the model — critical for IMDb severity changes mid-session.

---

### 4.5 Core — `scene_grouper.py`

**Size:** ~132 lines | **Role:** Merge detections → coherent scenes

`SceneGrouper` is a stateful incremental grouper. It receives `Detection` objects in timestamp order and produces `Scene` objects.

**Grouping rule:**
A new detection extends the current open scene if `detection.timestamp - scene.end ≤ gap_sec` (default: **5.0 s**). Otherwise the current scene closes and a new one opens.

**Minimum evidence filter:**
`min_detections` (default: 1) discards scenes that never accumulated enough frames — filters single-frame false positives when set > 1.

**Safety padding (applied on close):**
```
scene.start -= SCENE_PAD_BEFORE  # 1.5 s earlier
scene.end   += SCENE_PAD_AFTER   # 1.0 s later
```
This ensures the skip/blur fires *before* the first detectable frame, not at it — preventing any stray frames from reaching the viewer.

**`Scene.to_dict()`** serialises to the JSON sidecar format.

---

### 4.6 Core — `scan_pipeline.py`

**Size:** ~153 lines | **Role:** Orchestrate the full scan in a QThread

`ScanPipeline(QObject)` wires `FrameExtractor → Detector → SceneGrouper` and exposes results via **Qt signals**:

| Signal | Payload | Meaning |
|--------|---------|---------|
| `scene_found` | `Scene` | A new scene was confirmed |
| `progress` | `(current_sec, total_sec)` | Scan head position |
| `scan_finished` | — | All frames processed |
| `scan_error` | `str` | Fatal error occurred |

**Resilience:** Up to 4 consecutive NudeNet failures are tolerated (logged as warnings) before `scan_error` is emitted — preventing a single bad frame from killing the entire scan.

**Lifecycle:** `start()` spawns a daemon thread named `"ScanPipeline"`. `stop()` sets `_running = False`, stops the extractor, then joins with an 8-second timeout — long enough for the ONNX session to finish its current inference before the thread exits cleanly.

---

### 4.7 Core — `warning_scheduler.py`

**Size:** ~113 lines | **Role:** Watch playback position, emit warn/skip

`WarningScheduler` runs a `QTimer` every **500 ms** on the main thread. On each tick it:

1. Iterates all known scenes.
2. Computes `seconds_until = scene.start - current_pos`.
3. **Auto-skip:** If `|seconds_until| ≤ 1.5 s` and the scene hasn't been skipped yet, emits `skip_to(scene.end + 0.5)`. Uses a `_skipped` set to guard against re-triggering.
4. **Warn:** If `seconds_until ≤ warn_ahead_sec` (default: **60 s**), adds the scene to the upcoming list and emits `warn(scene, seconds_until)` for the nearest one.
5. **Clear:** If no upcoming scenes are found, emits `banner_clear()`.

The 60-second advance warning gives the viewer roughly one minute to decide whether to watch or skip.

---

### 4.8 Core — `live_blur.py`

**Size:** ~180 lines | **Role:** Real-time per-frame bounding box extraction

`LiveBlurWorker` is the precision layer of the overlay system. It:

- Runs in its **own daemon thread** (`"LiveBlur"`), separate from the scan pipeline.
- Owns a **private CPU-only ONNX session** to avoid DirectML threading conflicts.
- Polls the media player's position at **≈4 fps** (`_POLL_INTERVAL = 0.25 s`).
- **Only runs NudeNet inside flagged scene windows + 2.0 s buffer** — idles cheaply everywhere else.
- Uses an aggressive low threshold of **0.15** inside scene windows so even borderline detections produce boxes.
- Emits `boxes_updated(boxes, video_w, video_h)` when boxes are found, or `boxes_cleared()` when not — the `BlurOverlay` falls back to full-frame blackout if `boxes_cleared` is received while inside a scene.

**`cap.set(cv2.CAP_PROP_POS_MSEC, pos_ms)`** is called only when the position changes by more than 200 ms, avoiding redundant seeks.

---

### 4.9 Core — `blur_exporter.py`

**Size:** ~234 lines | **Role:** Export a blurred MP4 that works standalone

`BlurExporter` produces a new video file with detected regions permanently blacked out:

**Pipeline:**
1. OpenCV reads every frame of the source video.
2. Frames inside known scene windows (± 0.5 s buffer) are passed through NudeNet at threshold 0.20 to get bounding boxes.
3. `_apply_blur()` fills each bounding box with **solid black** (not a Gaussian blur as the name implies — solid black is computationally cheaper and completely opaque). A 10% padding is added on all sides to account for NudeNet's tendency to slightly underestimate bounding boxes.
4. Frames outside scene windows pass through unchanged (very fast).
5. Output is written to a temporary `.avi` via `cv2.VideoWriter`.
6. **FFmpeg** muxes the original audio tracks into the final `.mp4` output. If FFmpeg is not available, the video-only `.avi` is copied as a fallback.

**Progress tracking:** Emits `progress(int)` 0–100 so the UI can display a progress bar.

---

### 4.10 Core — `sidecar.py`

**Size:** ~101 lines | **Role:** JSON cache + MPC-HC EDL writer

**Sidecar JSON format:**
```json
{
  "version": 7,
  "video": "/path/to/movie.mkv",
  "enabled_categories": ["anus", "buttocks", "genitalia_f", "genitalia_m"],
  "meta": {},
  "scenes": [
    { "start": 312.5, "end": 328.0, "duration": 15.5, "peak_confidence": 0.87, "categories": ["genitalia_f"] }
  ]
}
```

**Freshness check (`is_fresh`):**
The sidecar is considered valid only if:
- It exists and its `mtime` is newer than the video's `mtime`.
- Its `version` matches `SIDECAR_SCHEMA_VERSION` (currently **7**) — stale caches from earlier detection logic are automatically invalidated.
- Its `enabled_categories` exactly matches the current session's enabled set — changing which categories to scan forces a re-scan.

**EDL output:** MPC-HC compatible `.edl` skip file. Format: `start_sec end_sec 0` per line (action `0` = cut/skip). This lets the video play ad-hoc in MPC-HC with auto-skip, without ClearView running.

**Storage location:** Sidecars are stored in the **project root directory** (next to `main.py`), named `<video_stem>_clearview.json` / `.edl` — not alongside the video file, which may be on a different drive.

---

### 4.11 UI — `style.py`

**Size:** ~221 lines | **Role:** Central QSS stylesheet

A single `STYLESHEET` constant applied to `QMainWindow`. Key design tokens:

| Token | Value | Usage |
|-------|-------|-------|
| Background | `#0d0d0f` | Near-black main window |
| Surface | `#111114` | Sidebars, control bar |
| Primary blue | `#3d7cf4` | Playhead, progress, active items, timestamps |
| Accent amber | `#f5a623` | Scene markers on timeline, warning banner border |
| Text primary | `#e0ddd8` | Headings |
| Text muted | `#888898` / `#44444e` | Secondary labels, status bar |

All component styles are named with Qt object names (`QFrame#fileItem`, `QLabel#heading`, etc.) — making the stylesheet predictable and component-local.

---

### 4.12 UI — `first_run_dialog.py`

**Size:** ~119 lines | **Role:** First-launch model download UI

A frameless `QDialog` that:
- Shows on startup if `640m.onnx` is missing.
- Spawns a daemon thread running `ensure_model()` with a progress callback.
- Updates a `QProgressBar` and status `QLabel` via emitted Qt signals.
- **Auto-closes** on success (`dlg.accept()`).
- Shows a "Close" button and an error message on failure — no retry (user must restart).

The dialog is **blocking**: `main.py` will not open `MainWindow` until it resolves.

---

### 4.13 UI — `file_sidebar.py`

**Size:** ~7.6 KB | **Role:** Left panel — drop zone + file queue

Features:
- Drag-and-drop zone accepting video files.
- Click-to-browse file picker.
- A scrollable queue of file items with colour-coded status badges:
  - `idle` → grey
  - `scanning N%` → blue with progress percentage
  - `warn (N scenes)` → amber badge with scene count
  - `done` → green
- **IMDb Severity selector** (ComboBox: None / Mild / Moderate / Severe) that maps to `(threshold, fps, enabled_categories, min_detections)` tuples consumed by `MainWindow._start_scan()`.
- Category toggle checkboxes that feed the enabled set.

Exposes two signals:
- `files_added(list[str])` — when new files are loaded
- `file_selected(str)` — when the user clicks a queued file to play it

---

### 4.14 UI — `player_widget.py`

**Size:** ~448 lines | **Role:** Video player + custom timeline + transport controls

**`SceneTimeline(QWidget)`** — a custom-painted `QWidget` (20 px tall):
- **Track background:** `#1e1e26`
- **Buffered region:** `#2a2a38` slightly lighter
- **Played region:** solid `#3d7cf4` (primary blue)
- **Scan region:** translucent blue (`alpha=35`) from the current scan head to the right edge — gives a visual indication of how far ahead the scanner has gone
- **Scene markers:** amber (`#f5a623`) bars, 2 px taller than the track, so they stand out
- **Playhead:** white circle (12 px diameter) centred on the current position
- Click-to-seek: converts click X position to a millisecond value and emits `seek_requested`

**`PlayerWidget(QWidget)`:**
- Embeds `QVideoWidget`, `BlurOverlay` (transparent child), `WarnBanner`, controls bar with `SceneTimeline`, timestamp labels (`QLabel`), transport buttons, and a volume slider.
- **Auto-hide controls in fullscreen:** a `QTimer` (2.5 s one-shot) hides the controls bar and sets a blank cursor after 2.5 s of mouse inactivity; mouse movement shows them again.
- **Double-click to go fullscreen** via `eventFilter` on the video widget.
- Manages `LiveBlurWorker` lifecycle: starts it when a file is loaded with a detector, stops it on file switch.
- `_on_blur_boxes()` translates NudeNet's `[x, y, w, h]` into `(int, int, int, int)` tuples for `BlurOverlay.update_boxes()`.

---

### 4.15 UI — `blur_overlay.py`

**Size:** ~179 lines | **Role:** Transparent video-cover overlay

A `QWidget` child of `QVideoWidget` with:
- `Qt.WA_TransparentForMouseEvents` — all clicks pass through to the video widget.
- `Qt.WA_NoSystemBackground` — no Qt background fill.

**Two-source strategy (see [Section 7](#7-overlay-safety-strategy) for details):**

1. **`set_time(ts_sec)`** — called on every `positionChanged` (~25 Hz). If `ts_sec` falls within `[scene.start - 0.5, scene.end + 0.5]` for any known scene, the overlay is marked "in scene".
2. **`update_boxes(boxes, video_w, video_h)`** — called by `LiveBlurWorker` (~4 Hz) when NudeNet fires.

In `paintEvent`:
- **In scene + boxes available:** draw per-bounding-box black rectangles, accounting for QVideoWidget's letterboxing (`scale = min(ww/vw, wh/vh)`, offsets `off_x`, `off_y`).
- **In scene + no boxes:** draw a full-frame black rectangle covering the entire video area — guarantees no sensitive frame is ever displayed unobscured.
- **Outside scene + stale boxes:** renders last-known boxes (handles the case where LiveBlur's 4 fps update cycle hasn't cleared yet).

---

### 4.16 UI — `warn_banner.py`

**Size:** ~4.9 KB | **Role:** Warning overlay banner

A styled `QFrame` with object name `warnBanner` (amber border, dark background from QSS). Positioned at `(20, 14)` inside `QVideoWidget`. Shows:
- ⚠ heading label
- Categories found in the upcoming scene
- Countdown (e.g. "in 47 s")
- A "Skip now" button

The banner updates its countdown text on every `warn(scene, seconds_until)` signal. It disappears on `banner_clear()` or after an auto-skip fires.

---

### 4.17 UI — `scene_panel.py`

**Size:** ~7.3 KB | **Role:** Right panel — live scene list

A scrollable list of `QFrame#sceneItem` widgets, one per detected scene. Each item shows:
- Timestamp range (e.g. `5:12 – 5:28`)
- Duration
- Categories
- Peak confidence score

Clicking a scene item emits `scene_clicked(start_sec)` which is connected to `PlayerWidget.seek()` in `MainWindow` — jump directly to any flagged moment.

The panel updates in real time as `scene_found` signals arrive from the scan pipeline.

---

### 4.18 UI — `main_window.py`

**Size:** ~308 lines | **Role:** Top-level orchestrator

`MainWindow` wires all components together. Signal connections:

```
FileSidebar.files_added    → MainWindow._on_files_added
FileSidebar.file_selected  → MainWindow._on_file_selected (loads player + starts scan)

PlayerWidget.position_changed → WarningScheduler.update_position

WarningScheduler.warn        → MainWindow._on_warn → PlayerWidget.show_banner
WarningScheduler.skip_to     → PlayerWidget.seek
WarningScheduler.banner_clear→ PlayerWidget.hide_banner

ScenePanel.scene_clicked     → PlayerWidget.seek

ScanPipeline.scene_found     → MainWindow._on_scene_found
                                 → PlayerWidget.add_scene
                                 → ScenePanel.add_scene
                                 → WarningScheduler.add_scene
ScanPipeline.progress        → MainWindow._on_scan_progress → PlayerWidget.update_scan_head
ScanPipeline.scan_finished   → MainWindow._on_scan_finished → sidecar.save + write_edl
ScanPipeline.scan_error      → StatusBar message

Arrow keys                   → PlayerWidget.step_backward/forward (5 s)
Escape (fullscreen)          → toggle_fullscreen
Double-click video           → toggle_fullscreen
```

**Sidecar-first loading:** When a file is selected, `is_fresh()` is checked *before* starting the player. If the cache is valid, scenes are pre-loaded into `ScenePanel`, `WarningScheduler`, and `PlayerWidget` *before* `player.load()` is called — meaning `LiveBlurWorker` starts already knowing the scene list and can blur from the first frame.

**`closeEvent`:** Cleanly stops the scan pipeline, joins its thread, and stops the scheduler timer before Qt shuts down.

---

## 5. Concurrency Model

```
Main Thread (Qt event loop)
├── QMediaPlayer (hardware decode, DX11/DX12 video output)
├── WarningScheduler QTimer (500 ms)
├── BlurOverlay.paintEvent (driven by positionChanged)
└── All UI signal handlers (queued connections from worker threads)

Thread: "ScanPipeline" (daemon)
├── FrameExtractor loop (OpenCV VideoCapture, cap.grab() skips)
└── Detector.detect() → SceneGrouper.add_detection()
    → Signal emission (marshalled to main thread via queued connection)

Thread: "LiveBlur" (daemon)  
├── Own private CPU ONNX session
└── Poll loop at ≈4 fps, seeks OpenCV cap to current player position
    → Signal emission (marshalled to main thread via queued connection)
```

**Thread safety guarantees:**
- All cross-thread communication is via Qt signals (thread-safe queued connections).
- `FrameExtractor` queue uses Python's `queue.Queue` (GIL-protected).
- `_running` flags are plain Python `bool` — single-writer (the thread that owns it) with reads in the other thread relying on Python's GIL for coherence.
- No shared mutable state between the two ONNX sessions (different `onnxruntime.InferenceSession` objects).

---

## 6. Detection Strategy — Deep Dive

### 6.1 IMDb Severity Levels

| Level | Threshold | FPS | Notes |
|-------|-----------|-----|-------|
| None | 0.50 | 1 | Very conservative — catches only high-confidence exposures |
| Mild | 0.55 | 2 | Fewer false positives, higher confidence bar |
| **Moderate** (default) | **0.40** | **3** | Good balance of recall and precision |
| Severe | 0.30 | 4 | Maximum recall — more false positives |

Higher FPS means the scanner samples more frames per second of video, reducing the chance of missing a brief exposure.

### 6.2 Enabled Categories

| Category | NudeNet Label | Default |
|----------|--------------|---------|
| `breast` | `FEMALE_BREAST_EXPOSED` | ✅ |
| `genitalia_f` | `FEMALE_GENITALIA_EXPOSED` | ✅ |
| `genitalia_m` | `MALE_GENITALIA_EXPOSED` | ✅ |
| `buttocks` | `BUTTOCKS_EXPOSED` | ✅ |
| `anus` | `ANUS_EXPOSED` | ✅ |
| `kissing` | *(face-proximity heuristic)* | ✅ |
| `breast_covered` | `FEMALE_BREAST_COVERED` | ❌ |
| `genitalia_f_covered` | `FEMALE_GENITALIA_COVERED` | ❌ |

Covered categories are opt-in because they produce far more false positives (swimwear, tight clothing, etc.).

### 6.3 Scene Window Timing

```
Raw detection timestamps:  t₁  t₂  t₃              t₄  t₅
                           ├───┤   ├───────────────┤───┤
                           ↑ gap ≤ 5s keeps merged   ↑ gap > 5s → new scene

After padding:
Scene 1:  [t₁ - 1.5s  ─────────────────────────────  t₃ + 1.0s]
Scene 2:  [t₄ - 1.5s  ──────────  t₅ + 1.0s]
```

---

## 7. Overlay Safety Strategy

The `BlurOverlay` uses a **dual-source, fail-safe design** to guarantee no sensitive frame ever reaches the viewer:

```
positionChanged (~25 Hz) ──► set_time(ts_sec)
                              │
                              ├─ in scene? ──NO──► nothing
                              │
                              └─ YES
                                    │
                                    ├─ LiveBlur boxes available? ──YES──► precise per-box blackout
                                    │
                                    └─ NO ──────────────────────────────► full-frame blackout (guaranteed)
```

The full-frame fallback activates in any of these cases:
- `LiveBlurWorker` hasn't processed this second yet (polling lag).
- NudeNet found no boxes on this frame (could be costume, angle, lighting).
- `LiveBlurWorker` was cleared when a scene was removed.

This means **even if the AI fails to detect anything in a specific frame, the viewer still sees black** during the scene window — the protective property never depends on AI succeeding.

---

## 8. Caching & Output Files

For each scanned video `movie.mkv`, ClearView creates (in the project directory):

| File | Format | Purpose |
|------|--------|---------|
| `movie_clearview.json` | JSON (schema v7) | Full scene list, re-loaded instantly on next open |
| `movie_clearview.edl` | MPC-HC EDL | Auto-skip in MPC-HC without running ClearView |

Re-opening a previously scanned file skips the scan entirely, pre-populates the scene panel and timeline, and starts the live blur immediately — sub-second load times even for long movies.

The cache is **automatically invalidated** if:
- The video file is modified (mtime check).
- The schema version increases (detection algorithm changed).
- The enabled category set changes.

---

## 9. Settings Reference

### IMDb Severity → Scan Parameters

| Label | `threshold` | `fps` | `min_detections` |
|-------|-------------|-------|-----------------|
| None | 0.50 | 1 | 1 |
| Mild | 0.55 | 2 | 1 |
| Moderate | 0.40 | 3 | 1 |
| Severe | 0.30 | 4 | 1 |

### Scene Grouper Constants

| Constant | Value | Effect |
|----------|-------|--------|
| `gap_sec` | 5.0 s | Max gap between detections to still merge into one scene |
| `SCENE_PAD_BEFORE` | 1.5 s | Skip/blur starts this early |
| `SCENE_PAD_AFTER` | 1.0 s | Skip/blur ends this late |

### Scheduler Constants

| Constant | Value | Effect |
|----------|-------|--------|
| `warn_ahead_sec` | 60.0 s | Warning banner appears this far before a scene |
| Tick interval | 500 ms | How often the scheduler checks playback position |
| Skip window | ±1.5 s | Player seeks past scene end when within this window of scene.start |

### Live Blur Constants

| Constant | Value |
|----------|-------|
| `_SCENE_BUFFER_SEC` | 2.0 s |
| `_IN_SCENE_THRESHOLD` | 0.15 |
| `_POLL_INTERVAL` | 0.25 s (≈4 fps) |

---

## 10. Setup & Running

### Requirements

- **Python 3.10+**
- **Windows** (DirectML GPU acceleration; CPU fallback works on any OS)
- Optional: **FFmpeg** on PATH for `BlurExporter` audio muxing

### Install

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` installs:
- `PySide6 ≥ 6.6` — Qt 6 UI framework
- `opencv-python ≥ 4.9` — frame extraction & blur export
- `nudenet ≥ 3.4.2` — AI body-part detection (installs `onnxruntime` as a dep)
- `onnxruntime-directml` — AMD/Intel/NVIDIA GPU via DirectX 12 (Windows)

> To use NVIDIA CUDA instead, replace `onnxruntime-directml` with `onnxruntime-gpu` and ensure CUDA 11/12 is installed.

### Run

```bash
python main.py
```

On first launch, the app downloads `640m.onnx` (~99 MB) from Hugging Face. This is a one-time operation; the model is cached in `~/.clearview/models/`.

### Usage

1. **Drop a video** onto the left sidebar drop zone, or click the zone to browse.
2. **Set IMDb severity** in the sidebar dropdown (Moderate is the recommended default).
3. **Click a queued file** to start playback and scanning simultaneously.
4. The scan races ahead — amber markers appear on the timeline as scenes are found.
5. A **yellow warning banner** appears ~60 s before any flagged scene.
6. The player **auto-skips** when it reaches a scene's start timestamp.
7. The **blur overlay** blacks out detected regions frame by frame during scenes.
8. Flagged scenes appear in the right panel; click any to jump to it.

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `←` / `→` | Step back / forward 5 seconds |
| `Escape` | Exit fullscreen |
| Double-click video | Toggle fullscreen |

---

## 11. Download & Install

### Option A — Download the Installer (Recommended)

Go to the [GitHub Releases page](https://github.com/ThatsAli-1/ClearView/releases) and download **`ClearView_Setup_v2.0.exe`**.

- Double-click to install — **no admin rights required**.
- Creates a Start Menu entry and optional Desktop shortcut.
- On first launch, ClearView downloads the AI model (~99 MB) from Hugging Face automatically.
- Registered in Add/Remove Programs for clean uninstallation.

### Option B — Build from Source

#### Step 1: Install dependencies

```bash
pip install -r requirements.txt
pip install pyinstaller
```

#### Step 2: Build with PyInstaller

```bash
pyinstaller ClearView.spec
```

This creates `dist/ClearView/ClearView.exe` — a fully self-contained directory.
The `640m.onnx` model is **not** bundled; it downloads to `~/.clearview/models/` on first run.

> Use the spec file (not bare CLI flags) — it correctly collects NudeNet data files, PySide6 Qt plugins, and ONNX runtime DLLs.

#### Step 3 (Optional): Build the Windows Installer

Requires **[Inno Setup 6](https://jrsoftware.org/isdl.php)** (free).

```bash
iscc installer\clearview_setup.iss
```

Output: `installer\Output\ClearView_Setup_v2.0.exe`

### Automated Builds via GitHub Actions

A CI/CD workflow (`.github/workflows/build.yml`) automatically builds the installer whenever a version tag is pushed:

```bash
git tag v2.0
git push origin v2.0
```

GitHub Actions will build on Windows, produce the installer, and attach it to a GitHub Release.

---

## 12. Known Limitations & Future Work

### Current Limitations

| Limitation | Detail |
|------------|--------|
| **Approximate timestamps** | Scanner samples at N fps (1–4), not every frame. A 0.5 s exposure at 2 fps may be missed entirely if both sampled frames fall outside it. Safety padding (1.5 s before, 1.0 s after) mitigates but cannot eliminate this. |
| **Content type scope** | Only detects exposed body parts (and kissing via heuristic). Audio cues (moaning, heavy breathing), contextual romance, or non-nudity adult content are outside scope. |
| **IMDb scraping** | The sidebar has an IMDb rating lookup that is frequently rate-limited or blocked — the manual severity dropdown is the reliable path. |
| **One ONNX runtime variant** | Only one `onnxruntime-*` variant can be installed at a time (CPU, DirectML, or CUDA). Having multiple creates provider-selection conflicts. |
| **FFmpeg dependency** | `BlurExporter`'s audio muxing requires FFmpeg on PATH. Without it, the output is video-only. |
| **Sidecar location** | ~~Sidecars are stored in the project directory, not beside the video.~~ **Fixed in v2.0** — sidecars are now stored in `scans/` subfolder, and the directory is gitignored. |
| **No subtitle / chapter awareness** | The scanner cannot correlate detections with SRT subtitles or chapter markers, which could improve context-aware skip decisions. |

### Potential Future Improvements

- [ ] Store sidecars beside the video file (or in a user-configurable directory) for portability.
- [ ] Add a configurable minimum scene duration filter to suppress very brief false positives.
- [ ] Implement a frame-accurate re-scan mode after the initial pass, targeting only detected scene windows at full frame-rate.
- [ ] Surface an export UI inside the application (currently `BlurExporter` exists but may require manual integration).
- [ ] Support for CUDA (NVIDIA) provider by detecting which `onnxruntime-*` package is installed and selecting provider accordingly.
- [ ] macOS/Linux support (remove DirectML dependency, use CoreML or ROCm providers).
- [ ] Add unit tests for `SceneGrouper`, `Detector._evaluate`, and `Sidecar.is_fresh` — the pure-logic core modules that require no display.
