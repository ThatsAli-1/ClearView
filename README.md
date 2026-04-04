# ClearView v2

A dark-modern desktop app that scans video files for immodest scenes **while playing them simultaneously** — no waiting for the scan to finish before watching.

## How it works

```
Video File
    │
    ├──► QMediaPlayer ──────────────────────► Screen (plays immediately)
    │
    └──► FrameExtractor (background thread)
              │  frames @ N fps
              ▼
         NudeNet Detector (ONNX)
              │  detections
              ▼
         SceneGrouper (merges nearby hits)
              │  Scene objects (via Qt signals)
              ├──► ScenePanel (right sidebar, live updates)
              ├──► SceneTimeline (amber markers on progress bar)
              └──► WarningScheduler
                        │  60s ahead of playback
                        ├──► WarnBanner (overlay on video)
                        └──► Auto-skip (jumps past scene end)
```

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

For Windows GPU acceleration (recommended — much faster scanning):
```bash
pip install onnxruntime-directml
```

### 2. Run

```bash
python main.py
```

On first launch, NudeNet will auto-download the `640m.onnx` model (~99 MB).

## Usage

1. **Drop a video file** onto the left sidebar drop zone (or click to browse)
2. **Playback starts immediately** — no need to wait for scanning
3. The scanner runs ~60 seconds ahead of your playback position
4. A **yellow banner** appears ~60 seconds before any flagged scene
5. The player **auto-skips** when it reaches the scene start
6. Flagged scenes appear in the right panel in real time with timestamps and categories

## File structure

```
clearview_v2/
├── main.py                    Entry point
├── requirements.txt
├── core/
│   ├── frame_extractor.py     Threaded frame producer (OpenCV)
│   ├── detector.py            NudeNet wrapper (lazy load, per-class thresholds)
│   ├── scan_pipeline.py       Orchestrates extractor + detector on QThread
│   ├── scene_grouper.py       Merges detections within 9s gap into scenes
│   ├── warning_scheduler.py   Watches playback position, fires warn/skip signals
│   └── sidecar.py             JSON cache + MPC-HC .edl writer
└── ui/
    ├── main_window.py         Main window, wires everything together
    ├── player_widget.py       QMediaPlayer + custom timeline with scene markers
    ├── warn_banner.py         Overlay warning banner with countdown
    ├── scene_panel.py         Right panel: live scene list
    ├── file_sidebar.py        Left panel: drop zone + file queue
    └── style.py               QSS stylesheet (dark modern)
```

## Output files

For each scanned video `movie.mkv`, ClearView creates:
- `movie_clearview.json` — full scene list (cached, re-opens instantly)
- `movie.edl` — MPC-HC skip file (auto-skip in MPC-HC without ClearView)

## Settings

| Setting | Default | Notes |
|---------|---------|-------|
| IMDb: None | threshold 0.50, 1 fps | Very conservative |
| IMDb: Mild | threshold 0.55, 2 fps | Higher bar, fewer false positives |
| IMDb: Moderate | threshold 0.40, 3 fps | **Default — good balance** |
| IMDb: Severe | threshold 0.30, 4 fps | Catches more, more false positives |

Detection categories (all enabled by default except breast):
- Female breast — disabled by default (highest false-positive rate)
- Female genitalia
- Male genitalia  
- Buttocks
- Anus

## Known limitations

1. Timestamps are approximate (sampled frames, not frame-perfect)
2. Only detects exposed body regions — not kissing, romance, audio
3. IMDb scraping is often blocked — use the manual dropdown
4. One onnxruntime variant at a time (CPU, DirectML, or CUDA — not mixed)

## Packaging to .exe

```bash
pip install pyinstaller
pyinstaller --onedir --windowed --name ClearView main.py
```
