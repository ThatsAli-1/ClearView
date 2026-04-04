"""
ui/style.py
Central QSS stylesheet for ClearView v2 — dark modern aesthetic.
"""

STYLESHEET = """
/* ── Global ─────────────────────────────────────────────────── */
* {
    font-family: "Segoe UI", "Inter", sans-serif;
    color: #e0ddd8;
    outline: none;
}

QMainWindow, QWidget#root {
    background: #0d0d0f;
}

QWidget {
    background: transparent;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #2a2a38;
    border-radius: 3px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #3d3d52; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* ── Sidebar ────────────────────────────────────────────────── */
QWidget#sidebar {
    background: #111114;
    border-right: 1px solid #1e1e24;
}

QLabel#sidebarSection {
    color: #44444e;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 8px 14px 4px;
}

/* ── File Queue Items ───────────────────────────────────────── */
QFrame#fileItem {
    background: #18181d;
    border: 1px solid #26262c;
    border-radius: 8px;
    margin: 3px 8px;
    padding: 4px;
}
QFrame#fileItem:hover {
    background: #1c1c22;
    border-color: #32323c;
}
QFrame#fileItem[active="true"] {
    background: #1a1f35;
    border-color: #3d7cf4;
}

/* ── Drop Zone ──────────────────────────────────────────────── */
QFrame#dropZone {
    background: transparent;
    border: 2px dashed #2a2a38;
    border-radius: 10px;
    margin: 8px;
}
QFrame#dropZone:hover {
    border-color: #3d7cf4;
}

/* ── Right Panel ────────────────────────────────────────────── */
QWidget#rightPanel {
    background: #111114;
    border-left: 1px solid #1e1e24;
}

/* ── Scene Items ─────────────────────────────────────────────  */
QFrame#sceneItem {
    background: #15151a;
    border-bottom: 1px solid #1a1a20;
    border-radius: 0;
}
QFrame#sceneItem:hover {
    background: #18181f;
}

/* ── Controls bar ────────────────────────────────────────────── */
QWidget#controlsBar {
    background: #111114;
    border-top: 1px solid #1e1e24;
}

/* ── Player area ─────────────────────────────────────────────── */
QWidget#playerArea {
    background: #080808;
}

/* ── Status bar ──────────────────────────────────────────────── */
QStatusBar {
    background: #0d0d0f;
    border-top: 1px solid #1a1a20;
    color: #3a3a48;
    font-size: 10px;
}
QStatusBar::item { border: none; }

/* ── Buttons ─────────────────────────────────────────────────── */
QPushButton {
    background: #18181d;
    border: 1px solid #26262c;
    border-radius: 7px;
    padding: 5px 14px;
    color: #888898;
    font-size: 12px;
}
QPushButton:hover {
    background: #1e1e26;
    border-color: #383848;
    color: #c0bdb8;
}
QPushButton:pressed {
    background: #141418;
}
QPushButton#primaryBtn {
    background: #3d7cf4;
    border-color: #3d7cf4;
    color: #fff;
    font-weight: 600;
}
QPushButton#primaryBtn:hover {
    background: #5590f6;
    border-color: #5590f6;
}
QPushButton#primaryBtn:pressed {
    background: #2d6ce0;
}

/* ── Sliders ─────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 4px;
    background: #1e1e26;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px;
    height: 12px;
    margin: -4px 0;
    background: #ffffff;
    border: 2px solid #3d7cf4;
    border-radius: 6px;
}
QSlider::sub-page:horizontal {
    background: #3d7cf4;
    border-radius: 2px;
}

/* ── CheckBoxes ─────────────────────────────────────────────── */
QCheckBox {
    font-size: 11px;
    color: #666676;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #333340;
    background: #18181d;
}
QCheckBox::indicator:checked {
    background: #3d7cf4;
    border-color: #3d7cf4;
}
QCheckBox:hover { color: #a0a0b0; }

/* ── ComboBox ────────────────────────────────────────────────── */
QComboBox {
    background: #18181d;
    border: 1px solid #26262c;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    color: #888898;
}
QComboBox:hover { border-color: #383848; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #1a1a22;
    border: 1px solid #28282e;
    selection-background-color: #1a1f35;
    color: #c0bdb8;
}

/* ── Labels ─────────────────────────────────────────────────── */
QLabel { color: #888898; }
QLabel#heading { color: #e0ddd8; font-size: 13px; font-weight: 600; }
QLabel#timestamp { color: #3d7cf4; font-family: "Consolas", monospace; font-size: 11px; }
QLabel#muted { color: #44444e; font-size: 10px; }
QLabel#warn { color: #f5d090; font-size: 12px; font-weight: 600; }
QLabel#scanStatus { color: #3d7cf4; font-size: 11px; }

/* ── Warning banner ─────────────────────────────────────────── */
QFrame#warnBanner {
    background: #1a1408;
    border: 1px solid #f5a623;
    border-radius: 8px;
}
"""
