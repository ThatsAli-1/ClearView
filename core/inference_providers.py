"""
core/inference_providers.py
Auto-selects the best available ONNX execution provider at runtime.
Priority: CUDA → DirectML → ROCm → CPU

Call get_providers() and pass the result to onnxruntime.InferenceSession
(or NudeDetector if it exposes providers).

Also handles first-run auto-download of the 640m.onnx model.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Optional

# NudeNet 640m model — more accurate than the default 320n
# Using Hugging Face direct download (GitHub releases can redirect to HTML)
MODEL_URL = (
    "https://huggingface.co/zhangsongbo365/nudenet_onnx/resolve/main/"
    "640m.onnx"
)
MODEL_DIR  = Path.home() / ".clearview" / "models"
MODEL_PATH = MODEL_DIR / "640m.onnx"


def get_providers() -> list[str]:
    """Return ordered list of available ONNX execution providers."""
    try:
        import onnxruntime as ort
        available = set(ort.get_available_providers())
    except ImportError:
        return ["CPUExecutionProvider"]

    order = [
        "CUDAExecutionProvider",
        "DmlExecutionProvider",       # DirectML (Windows GPU)
        "ROCMExecutionProvider",
        "CPUExecutionProvider",
    ]
    return [p for p in order if p in available]


def best_provider() -> str:
    """Return the single best provider name."""
    providers = get_providers()
    return providers[0] if providers else "CPUExecutionProvider"


_MIN_MODEL_BYTES = 10_000_000   # real 640m.onnx is ~99 MB; anything <10 MB is corrupt


def ensure_model(progress_callback=None) -> Optional[str]:
    """
    Ensure 640m.onnx exists locally. Downloads if absent or corrupt.

    Parameters
    ----------
    progress_callback : callable(downloaded_bytes, total_bytes) | None

    Returns
    -------
    str path to model, or None if download failed.
    """
    # Validate existing file — delete if suspiciously small (corrupt)
    if MODEL_PATH.exists():
        if MODEL_PATH.stat().st_size >= _MIN_MODEL_BYTES:
            return str(MODEL_PATH)
        print(f"[ClearView] Cached 640m.onnx too small ({MODEL_PATH.stat().st_size} bytes), re-downloading…")
        MODEL_PATH.unlink()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    try:
        def _report(block_num, block_size, total_size):
            if progress_callback and total_size > 0:
                downloaded = block_num * block_size
                progress_callback(downloaded, total_size)

        tmp = MODEL_PATH.with_suffix(".tmp")
        urllib.request.urlretrieve(MODEL_URL, tmp, reporthook=_report)

        # Validate downloaded size before promoting
        if tmp.stat().st_size < _MIN_MODEL_BYTES:
            tmp.unlink()
            print(f"[ClearView] Downloaded file too small — likely an HTML redirect, not the model.")
            return None

        tmp.rename(MODEL_PATH)
        return str(MODEL_PATH)

    except Exception as exc:
        print(f"[ClearView] Model download failed: {exc}")
        return None


def provider_display_name() -> str:
    """Human-readable name of the active provider for the status bar."""
    p = best_provider()
    names = {
        "CUDAExecutionProvider":  "NVIDIA CUDA",
        "DmlExecutionProvider":   "DirectML",
        "ROCMExecutionProvider":  "AMD ROCm",
        "CPUExecutionProvider":   "CPU",
    }
    return names.get(p, p)
