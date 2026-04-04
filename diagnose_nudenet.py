"""
diagnose_nudenet.py
Run this from the clearview_v2 directory to see exactly what NudeNet returns.
It will extract a frame from a given video and run NudeNet on it, printing
all raw labels and scores — so we can verify the category class names match.

Usage:
    python diagnose_nudenet.py "path/to/your/video.mp4" [timestamp_seconds]
"""
import sys
import os
import tempfile
import cv2
from nudenet import NudeDetector

def diagnose(video_path: str, timestamp_sec: float = 60.0):
    print(f"\n{'='*60}")
    print(f"NudeNet Diagnostics")
    print(f"{'='*60}")
    print(f"Video : {video_path}")
    print(f"At    : {timestamp_sec:.1f}s")
    print()

    # --- Extract a frame ---
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("ERROR: Could not open video file!")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    print(f"Video FPS      : {fps:.2f}")
    print(f"Total duration : {duration:.1f}s  ({total_frames} frames)")
    print()

    target_frame = int(timestamp_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        print(f"ERROR: Could not extract frame at {timestamp_sec}s (frame #{target_frame})")
        return

    print(f"Frame extracted: {frame.shape[1]}x{frame.shape[0]} pixels")

    # --- Save frame to temp file ---
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp_path = f.name
    cv2.imwrite(tmp_path, frame)
    print(f"Saved temp frame: {tmp_path}")
    print()

    # --- Run NudeNet ---
    print("Loading NudeDetector...")
    detector = NudeDetector()
    print("Running detection...")
    results = detector.detect(tmp_path)
    os.unlink(tmp_path)

    print(f"\nRaw NudeNet results ({len(results)} detections):")
    print("-" * 50)
    if not results:
        print("  (none — NudeNet returned empty list)")
    for r in results:
        label = r.get("class", "???")
        score = r.get("score", 0.0)
        box   = r.get("box", [])
        print(f"  label={label!r:<35} score={score:.4f}  box={box}")

    print()

    # --- Check against current CATEGORY_CLASSES ---
    CATEGORY_CLASSES = {
        "breast":      ["EXPOSED_BREAST_F", "COVERED_BREAST_F"],
        "genitalia_f": ["EXPOSED_GENITALIA_F"],
        "genitalia_m": ["EXPOSED_GENITALIA_M"],
        "buttocks":    ["EXPOSED_BUTTOCKS"],
        "anus":        ["EXPOSED_ANUS"],
    }

    print("Checking against current CATEGORY_CLASSES mapping:")
    print("-" * 50)
    all_returned_labels = {r.get("class", "") for r in results}
    all_expected_labels = {lbl for lst in CATEGORY_CLASSES.values() for lbl in lst}

    matched = all_returned_labels & all_expected_labels
    unmatched = all_returned_labels - all_expected_labels

    if matched:
        print(f"  ✅ Labels that MATCH our mapping: {sorted(matched)}")
    else:
        print(f"  ❌ NONE of the returned labels match our mapping!")

    if unmatched:
        print(f"  ⚠️  Labels returned by NudeNet but NOT in our mapping: {sorted(unmatched)}")
        print(f"     --> These are being SILENTLY IGNORED by detector.py")
    else:
        print(f"  ✅ All returned labels are covered by our mapping.")

    print()
    print("All unique labels returned by NudeNet in this frame:")
    for lbl in sorted(all_returned_labels):
        print(f"  {lbl!r}")
    print()
    print("="*60)
    print("DONE. If the labels don't match, detector.py needs updating.")
    print("="*60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_nudenet.py <video_path> [timestamp_sec]")
        print("Example: python diagnose_nudenet.py movie.mp4 65")
        sys.exit(1)

    video = sys.argv[1]
    ts = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
    diagnose(video, ts)
