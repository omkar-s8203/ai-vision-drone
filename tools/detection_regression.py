"""Frame-to-frame detection-stability tool for docs plan M2's "recorded-
video regression set" testing requirement.

Real architectural constraint this respects: the AI Camera (Sony IMX500)
runs inference ON THE SENSOR at capture time - there is no way to "replay"
a saved video file through it afterward the way you'd replay a clip through
an off-sensor model. That's the whole architectural point of this camera
(detection costs ~0 Pi CPU - see companion/vision/camera.py), but it means
a literal "recorded clip -> re-run detection -> compare" regression test,
as the plan phrases it, isn't buildable against this hardware. What *is*
buildable, and is the actually-useful equivalent: capture a live session's
detection RESULTS (class/score/bbox per frame, not the sensor's internal
state) and analyze that stream for frame-to-frame consistency - stable
detection while a subject is in view is exactly what a "regression" would
break, and this catches that class of problem (it's exactly the shape of
bug that already happened once for real - see docs/hardware-wiring.md's
capture_request() saga, where detections silently stopped arriving).

Two subcommands:

    python tools/detection_regression.py capture --duration 30 --out session.json
        Runs the real detection pipeline live on the Pi (point the camera
        at a moving human/vehicle subject, per the plan's own M2
        acceptance test) and saves every frame's detections as JSON.

    python tools/detection_regression.py analyze session.json
        Reports stability metrics for a saved session and flags likely
        regressions: the longest run of consecutive zero-detection frames,
        detection-score stability, and bounding-box position jitter
        frame-to-frame for the most persistent target.

analyze_session() and the JSON schema it reads are fully exercised in this
project's own test suite with a synthetic session file
(companion/tests/test_detection_regression.py) - only `capture` needs the
real Pi and camera.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# See tools/benchmark_detection.py's identical comment - lets this script
# run directly (`python tools/detection_regression.py ...`) regardless of
# the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.config.loader import load_yaml  # noqa: E402
from companion.vision.camera import CameraBase  # noqa: E402
from companion.vision.detector import Detection, DetectorBase  # noqa: E402


@dataclass
class FrameRecord:
    ts: float
    detections: list  # list[dict] - {"class_name", "score", "x", "y", "w", "h"}


@dataclass
class StabilityReport:
    total_frames: int
    frames_with_detection: int
    longest_zero_detection_gap: int
    top_score_mean: Optional[float]
    top_score_stdev: Optional[float]
    bbox_jitter_px_mean: Optional[float]
    bbox_jitter_px_max: Optional[float]

    @property
    def detection_rate(self) -> float:
        return self.frames_with_detection / self.total_frames if self.total_frames else 0.0

    def report(self) -> str:
        lines = [
            f"Total frames:              {self.total_frames}",
            f"Frames with a detection:   {self.frames_with_detection} "
            f"({self.detection_rate * 100:.0f}%)",
            f"Longest zero-detection gap: {self.longest_zero_detection_gap} frames",
        ]
        if self.top_score_mean is not None:
            lines.append(
                f"Top score mean/stdev:      {self.top_score_mean:.2f} / "
                f"{self.top_score_stdev:.3f}"
            )
        if self.bbox_jitter_px_mean is not None:
            lines.append(
                f"Box position jitter mean/max: {self.bbox_jitter_px_mean:.1f}px / "
                f"{self.bbox_jitter_px_max:.1f}px"
            )
        return "\n".join(lines)


def _top_detection(detections: list) -> Optional[dict]:
    if not detections:
        return None
    return max(detections, key=lambda d: d["score"])


def analyze_session(frames: list) -> StabilityReport:
    """Pure function over a list of FrameRecord-shaped dicts - no camera/
    detector involved, so this is fully testable without real hardware."""
    total = len(frames)
    with_detection = sum(1 for f in frames if f["detections"])

    longest_gap = 0
    current_gap = 0
    for f in frames:
        if f["detections"]:
            current_gap = 0
        else:
            current_gap += 1
            longest_gap = max(longest_gap, current_gap)

    top_scores = [_top_detection(f["detections"])["score"] for f in frames if f["detections"]]
    top_score_mean = statistics.fmean(top_scores) if top_scores else None
    top_score_stdev = statistics.pstdev(top_scores) if len(top_scores) > 1 else (0.0 if top_scores else None)

    # Jitter: center-point movement between consecutive frames' top
    # detection, only counted when both frames actually have one and
    # agree on class (a naive but honest same-target proxy - this tool
    # doesn't run a full tracker, it's checking raw detection stability).
    jitters: list = []
    previous = None
    for f in frames:
        top = _top_detection(f["detections"])
        if top is not None and previous is not None and previous["class_name"] == top["class_name"]:
            prev_cx = previous["x"] + previous["w"] / 2
            prev_cy = previous["y"] + previous["h"] / 2
            cx = top["x"] + top["w"] / 2
            cy = top["y"] + top["h"] / 2
            jitters.append(((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2) ** 0.5)
        previous = top

    return StabilityReport(
        total_frames=total,
        frames_with_detection=with_detection,
        longest_zero_detection_gap=longest_gap,
        top_score_mean=top_score_mean,
        top_score_stdev=top_score_stdev,
        bbox_jitter_px_mean=statistics.fmean(jitters) if jitters else None,
        bbox_jitter_px_max=max(jitters) if jitters else None,
    )


def _detection_to_dict(detection: Detection) -> dict:
    return {
        "class_name": detection.class_name,
        "score": detection.score,
        "x": detection.bbox.x,
        "y": detection.bbox.y,
        "w": detection.bbox.w,
        "h": detection.bbox.h,
    }


async def capture_session(
    camera: CameraBase, detector: DetectorBase, duration_s: float
) -> list:
    """Real hardware capture loop - same capture-then-parse shape as
    tools/benchmark_detection.py's run_benchmark(), recording every
    frame's detections instead of timing them."""
    frames: list = []
    start = time.monotonic()
    deadline = start + duration_s

    async for frame in camera.frames():
        detections = detector.parse(frame.raw_detection_output, frame.ts)
        frames.append({"ts": frame.ts, "detections": [_detection_to_dict(d) for d in detections]})
        if time.monotonic() >= deadline:
            break

    return frames


def _cmd_capture(args: argparse.Namespace) -> None:
    from companion.vision.camera import Picamera2IMX500Camera
    from companion.vision.detector import IMX500Detector

    hardware_cfg = load_yaml("hardware.yaml")
    camera = Picamera2IMX500Camera(
        model_path=hardware_cfg["camera"]["imx500_model_path"],
        width=hardware_cfg["camera"]["width"],
        height=hardware_cfg["camera"]["height"],
        target_fps=hardware_cfg["camera"]["target_fps"],
    )
    detector = IMX500Detector(
        class_names=camera.imx500.network_intrinsics.labels,
        score_threshold=hardware_cfg["camera"].get("score_threshold", 0.5),
    )

    print(
        f"Capturing {args.duration:.0f}s of live detection - point the camera at a moving "
        f"human/vehicle subject, per docs plan M2's own acceptance test..."
    )
    frames = asyncio.run(capture_session(camera, detector, args.duration))
    Path(args.out).write_text(json.dumps({"frames": frames}, indent=2))
    print(f"Saved {len(frames)} frames to {args.out}")


def _cmd_analyze(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.session).read_text())
    report = analyze_session(data["frames"])
    print(report.report())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture", help="Record a live detection session (Pi only)")
    capture_parser.add_argument("--duration", type=float, default=30.0)
    capture_parser.add_argument("--out", type=str, default="detection_session.json")
    capture_parser.set_defaults(func=_cmd_capture)

    analyze_parser = subparsers.add_parser("analyze", help="Report stability metrics for a saved session")
    analyze_parser.add_argument("session", type=str)
    analyze_parser.set_defaults(func=_cmd_analyze)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
