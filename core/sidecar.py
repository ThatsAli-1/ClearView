"""
core/sidecar.py
Save and load scan results as JSON inside the project's scans/ folder.
If a sidecar exists and is newer than the video, the scan is skipped.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from core.scene_grouper import Scene

# Increment this when the detection logic changes to force re-scans
SIDECAR_SCHEMA_VERSION = 7

# All scan results are stored here (inside the project directory)
_PROJECT_DIR = Path(__file__).resolve().parent.parent


def sidecar_path(video_path: str | Path) -> Path:
    """Return the sidecar path saved directly in the project root folder.
    
    The filenames will directly match the video filename plus _clearview.json.
    """
    p = Path(video_path)
    return _PROJECT_DIR / f"{p.stem}_clearview.json"


def is_fresh(video_path: str | Path, enabled: Optional[set] = None) -> bool:
    """True if a valid sidecar exists, is newer than the video, and used the same enabled categories."""
    vp = Path(video_path)
    sp = sidecar_path(vp)
    if not sp.exists():
        return False
    try:
        if sp.stat().st_mtime < vp.stat().st_mtime:
            return False
        # Check schema version and enabled categories match
        if enabled is not None:
            data = json.loads(sp.read_text(encoding="utf-8"))
            if data.get("version", 0) < SIDECAR_SCHEMA_VERSION:
                return False
            cached_enabled = set(data.get("enabled_categories", []))
            if cached_enabled != enabled:
                return False
        return True
    except OSError:
        return False


def save(
    video_path: str | Path,
    scenes: list[Scene],
    enabled: Optional[set] = None,
    meta: Optional[dict] = None,
) -> None:
    sp = sidecar_path(video_path)
    data = {
        "version": SIDECAR_SCHEMA_VERSION,
        "video": str(video_path),
        "enabled_categories": sorted(enabled or []),
        "meta": meta or {},
        "scenes": [s.to_dict() for s in scenes],
    }
    sp.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load(video_path: str | Path) -> Optional[list[Scene]]:
    """Return list of Scenes from sidecar, or None if absent/corrupt."""
    sp = sidecar_path(video_path)
    if not sp.exists():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8"))
        scenes = []
        for d in data.get("scenes", []):
            scenes.append(
                Scene(
                    start=float(d["start"]),
                    end=float(d["end"]),
                    peak_confidence=float(d["peak_confidence"]),
                    categories=d["categories"],
                )
            )
        return scenes
    except Exception:
        return None


def write_edl(video_path: str | Path, scenes: list[Scene]) -> Path:
    """Write MPC-HC compatible .edl skip file."""
    edl = sidecar_path(video_path).with_suffix(".edl")
    lines = []
    for s in scenes:
        # MPC-HC EDL format: start_ms end_ms action (0=cut, 1=mute, 2=scene)
        lines.append(f"{s.start:.3f} {s.end:.3f} 0")
    edl.write_text("\n".join(lines), encoding="utf-8")
    return edl
