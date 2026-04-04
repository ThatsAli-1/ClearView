"""
core/detector.py
Wraps NudeNet (ONNX) with lazy loading, per-class thresholds, and a
multi-resolution detection strategy to maximise recall.

Category groups
---------------
BREAST      : EXPOSED_BREAST_F, COVERED_BREAST_F (optional)
GENITALIA_F : EXPOSED_GENITALIA_F
GENITALIA_M : EXPOSED_GENITALIA_M
BUTTOCKS    : EXPOSED_BUTTOCKS
ANUS        : EXPOSED_ANUS
KISSING     : two faces (FACE_FEMALE / FACE_MALE) in close proximity
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category definitions — maps logical group → NudeNet v3 class name variants
# Labels verified from installed nudenet/nudenet.py __labels list
# ---------------------------------------------------------------------------
CATEGORY_CLASSES: dict[str, list[str]] = {
    "breast":      ["FEMALE_BREAST_EXPOSED"],
    "genitalia_f": ["FEMALE_GENITALIA_EXPOSED"],
    "genitalia_m": ["MALE_GENITALIA_EXPOSED"],
    "buttocks":    ["BUTTOCKS_EXPOSED"],
    "anus":        ["ANUS_EXPOSED"],
    # opt-in: covered categories — bra/swimwear/lingerie; very noisy
    "breast_covered":     ["FEMALE_BREAST_COVERED"],
    "genitalia_f_covered": ["FEMALE_GENITALIA_COVERED"],
}

# Face labels used for kissing detection (not a nudity group per se)
FACE_LABELS: set[str] = {"FACE_FEMALE", "FACE_MALE"}

# Default enabled groups
DEFAULT_ENABLED: set[str] = {
    "breast", "genitalia_f", "genitalia_m", "buttocks", "anus",
    "kissing",
}


@dataclass
class Detection:
    """Single detection result for one frame."""
    timestamp: float                  # seconds into the video
    categories: list[str]             # logical group names that fired
    scores: dict[str, float]          # group → peak score
    raw_labels: list[str] = field(default_factory=list)


class Detector:
    """
    Lazy-loading NudeNet detector with multi-resolution rescanning.

    To maximise recall (never miss a nude scene) the detector:
    1. Runs the primary 640m model at full resolution.
    2. If nothing fires, re-checks with lower confidence (secondary_threshold)
       to pick up marginal detections that should not be silently dropped.
    3. Uses the higher-accuracy 640m model by default (falls back to 320n
       only if 640m isn't available).

    Parameters
    ----------
    threshold          : primary minimum confidence score
    secondary_threshold: lower threshold for the rescue pass (default 0.25)
    enabled            : set of logical group names to check
    model_path         : path to .onnx model file; None = auto-detect 640m
    breast_strict      : add +0.15 to breast threshold to reduce false positives
    """

    def __init__(
        self,
        threshold: float = 0.55,
        enabled: Optional[set[str]] = None,
        model_path: Optional[str] = None,
        breast_strict: bool = False,
        secondary_threshold: float = 0.55,
    ):
        self.threshold = threshold
        self.secondary_threshold = secondary_threshold
        self.enabled = enabled if enabled is not None else set(DEFAULT_ENABLED)
        self.model_path = model_path
        self.breast_strict = breast_strict
        self._detector = None   # lazy init

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def detect(self, timestamp: float, frame_bgr: np.ndarray) -> Optional[Detection]:
        """
        Run inference on a single BGR frame.

        Strategy for maximum recall:
        1. Run at primary threshold.
        2. If no groups fire, run a *rescue pass* at secondary_threshold
           to catch marginal detections.
        Returns a Detection if anything was found at either pass, else None.
        """
        detector = self._get_detector()

        # --- Primary pass ---------------------------------------------------
        results = detector.detect(frame_bgr)
        det = self._evaluate(results, timestamp, self.threshold)
        if det is not None:
            return det

        # --- Rescue pass (lower threshold) ----------------------------------
        if self.secondary_threshold < self.threshold:
            det = self._evaluate(results, timestamp, self.secondary_threshold)
            if det is not None:
                return det

        return None

    def _evaluate(
        self,
        results: list[dict],
        timestamp: float,
        threshold: float,
    ) -> Optional[Detection]:
        """Score raw NudeNet results against *threshold*."""
        if not results:
            return None

        fired_groups: list[str] = []
        peak_scores: dict[str, float] = {}
        raw_labels: list[str] = []

        for r in results:
            label: str = r.get("class", "")
            score: float = float(r.get("score", 0.0))
            raw_labels.append(label)

            for group, class_list in CATEGORY_CLASSES.items():
                if group not in self.enabled:
                    continue
                if label not in class_list:
                    continue

                # Apply breast strict-mode bonus
                eff_threshold = threshold
                if group == "breast" and self.breast_strict:
                    eff_threshold += 0.15

                if score >= eff_threshold:
                    if group not in fired_groups:
                        fired_groups.append(group)
                    peak_scores[group] = max(peak_scores.get(group, 0.0), score)

        # --- Kissing detection (face-proximity heuristic) ---
        if "kissing" in self.enabled:
            kiss_conf = self._check_kissing(results)
            if kiss_conf >= threshold:
                if "kissing" not in fired_groups:
                    fired_groups.append("kissing")
                peak_scores["kissing"] = max(peak_scores.get("kissing", 0.0), kiss_conf)

        if not fired_groups:
            return None

        return Detection(
            timestamp=timestamp,
            categories=fired_groups,
            scores=peak_scores,
            raw_labels=raw_labels,
        )

    # ------------------------------------------------------------------
    # Kissing detection — face-proximity heuristic
    # ------------------------------------------------------------------

    @staticmethod
    def _check_kissing(
        results: list[dict],
        min_face_score: float = 0.35,
        proximity_ratio: float = 0.40,
    ) -> float:
        """
        Return a pseudo-confidence (0–1) that a kissing scene is happening.

        Logic: collect all face bounding boxes (FACE_FEMALE / FACE_MALE)
        with score >= *min_face_score*.  If any two face centres are within
        *proximity_ratio* × average face width, it's a kiss.

        Returns 0.0 if fewer than 2 faces or no pair is close enough.
        """
        faces: list[tuple[float, float, float, float, float]] = []  # cx, cy, w, h, score
        for r in results:
            label = r.get("class", "")
            if label not in FACE_LABELS:
                continue
            score = float(r.get("score", 0.0))
            if score < min_face_score:
                continue
            box = r.get("box")  # [x, y, w, h]
            if not box or len(box) != 4:
                continue
            x, y, w, h = box
            faces.append((x + w / 2, y + h / 2, w, h, score))

        if len(faces) < 2:
            return 0.0

        # Check every pair
        best = 0.0
        for i in range(len(faces)):
            for j in range(i + 1, len(faces)):
                cx1, cy1, w1, h1, s1 = faces[i]
                cx2, cy2, w2, h2, s2 = faces[j]
                avg_w = (w1 + w2) / 2
                if avg_w <= 0:
                    continue
                dist = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
                if dist <= avg_w * proximity_ratio:
                    pair_conf = (s1 + s2) / 2
                    best = max(best, pair_conf)

        return best

    def update_settings(
        self,
        threshold: float,
        enabled: set[str],
        breast_strict: bool = False,
        secondary_threshold: float | None = None,
    ) -> None:
        """Hot-update settings without reloading the model."""
        self.threshold = threshold
        self.enabled = enabled
        self.breast_strict = breast_strict
        if secondary_threshold is not None:
            self.secondary_threshold = secondary_threshold
        else:
            # Keep rescue pass 0.05 below primary, clamped to 0.15 minimum
            self.secondary_threshold = max(0.15, threshold - 0.05)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_detector(self):
        """Lazy-load NudeDetector on first call, forcing DirectML (AMD GPU) provider.

        Model resolution order:
        1. Explicit ``model_path`` if provided and exists.
        2. Downloaded 640m.onnx from ~/.clearview/models/.
        3. Bundled NudeNet 320n.onnx (last resort).
        """
        if self._detector is None:
            import onnxruntime
            from nudenet import NudeDetector
            import os
            from core.inference_providers import MODEL_PATH as _640m_path

            if self.model_path and Path(self.model_path).exists():
                model_file = self.model_path
            elif _640m_path.exists():
                model_file = str(_640m_path)
            else:
                import nudenet as _nn_pkg
                model_file = os.path.join(os.path.dirname(_nn_pkg.__file__), "320n.onnx")
                log.warning("640m.onnx not found, falling back to 320n (lower accuracy)")

            self._detector = NudeDetector(model_path=model_file)
            log.info("Loaded model: %s", Path(model_file).name)

            # NudeNet ignores the providers param (it's commented out in source).
            # Directly replace the session to use AMD GPU via DirectML.
            available = onnxruntime.get_available_providers()
            if "DmlExecutionProvider" in available:
                self._detector.onnx_session = onnxruntime.InferenceSession(
                    model_file,
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                )
                log.info("Using DirectML GPU")
            else:
                log.info("DirectML not available — using CPU")

        return self._detector
