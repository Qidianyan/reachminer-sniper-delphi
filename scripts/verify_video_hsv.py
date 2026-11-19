"""HSV Color Redline & Frame Audit Scanner for ReachMiner-Sniper Demo Video.

Verifies across sampled frames of an MP4 video that zero pixels fall into the
forbidden blue / deep-teal / cyan / purple HSV hue band [165 deg, 325 deg].
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image


def compute_hsv_arrays(rgb_uint8: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Convert HxWx3 uint8 RGB array to float32 (H_deg, S_01, V_01, delta_01)."""
    arr = rgb_uint8.astype(np.float32) / 255.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    df = mx - mn

    s = np.where(mx > 0.0, df / np.maximum(mx, 1e-9), 0.0)
    v = mx
    h = np.zeros_like(mx)

    mask = df > 1e-6
    rm = mask & (mx == r)
    gm = mask & (mx == g) & (~rm)
    bm = mask & (mx == b) & (~rm) & (~gm)

    h[rm] = (60.0 * ((g[rm] - b[rm]) / df[rm])) % 360.0
    h[gm] = (60.0 * ((b[gm] - r[gm]) / df[gm]) + 120.0) % 360.0
    h[bm] = (60.0 * ((r[bm] - g[bm]) / df[bm]) + 240.0) % 360.0
    return h, s, v, df


def audit_video_hsv(
    video_path: Path,
    sample_fps: float = 0.5,
    hue_min: float = 165.0,
    hue_max: float = 325.0,
    min_saturation: float = 0.05,
    min_value: float = 0.05,
) -> dict:
    """Extract frames at sample_fps and verify 0 forbidden HSV pixels."""
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    with tempfile.TemporaryDirectory(prefix="reachminer_hsv_") as td:
        pattern = str(Path(td) / "frame_%04d.png")
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"fps={sample_fps}",
                pattern,
            ],
            check=True,
        )
        frame_files = sorted(Path(td).glob("frame_*.png"))
        if not frame_files:
            raise RuntimeError("ffmpeg extracted 0 frames from video")

        total_bad_strict = 0
        total_bad_any = 0
        per_frame_violations: list[dict] = []

        for fpath in frame_files:
            rgb = np.asarray(Image.open(fpath).convert("RGB"))
            h, s, v, df = compute_hsv_arrays(rgb)
            bad_strict_mask = (h >= hue_min) & (h <= hue_max) & (s >= min_saturation) & (v >= min_value)
            bad_any_mask = (h >= hue_min) & (h <= hue_max) & (df > 0.004)
            bad_strict = int(bad_strict_mask.sum())
            bad_any = int(bad_any_mask.sum())
            total_bad_strict += bad_strict
            total_bad_any += bad_any
            if bad_strict > 0 or bad_any > 0:
                per_frame_violations.append(
                    {
                        "frame": fpath.name,
                        "bad_strict_px": bad_strict,
                        "bad_any_px": bad_any,
                    }
                )

    return {
        "video_path": str(video_path),
        "frames_scanned": len(frame_files),
        "sample_fps": sample_fps,
        "forbidden_hue_range_deg": [hue_min, hue_max],
        "min_saturation": min_saturation,
        "min_value": min_value,
        "total_bad_strict_pixels": total_bad_strict,
        "total_bad_any_nongray_pixels": total_bad_any,
        "passed": total_bad_strict == 0 and total_bad_any == 0,
        "violations": per_frame_violations[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="HSV Forbidden-Color Video Audit Scanner")
    parser.add_argument("video", help="Path to MP4 video file")
    parser.add_argument("--fps", type=float, default=0.5, help="Frame sampling rate (default 0.5 fps)")
    args = parser.parse_args()

    result = audit_video_hsv(Path(args.video), sample_fps=args.fps)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
