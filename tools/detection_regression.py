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
        Reports two things from the same captured session: M2's detection-
        stability metrics (longest zero-detection gap, score stability,
        bbox jitter), and - by replaying the same real detection stream
        through the real TrackingStateMachine/IouKalmanTracker - docs plan
        M3's own reacquisition-success-rate and false-lost-rate metrics
        (>=90% / <=5%). A session already captured for M2 works immediately
        for this too; no separate hardware run needed for M3.

analyze_session()/replay_through_tracker() and the JSON schema they read
are fully exercised in this project's own test suite with a synthetic
session file (companion/tests/test_detection_regression.py) - only
`capture` needs the real Pi and camera.
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


MIN_REACQUISITION_SUCCESS_RATE = 0.90
MAX_FALSE_LOST_RATE = 0.05


@dataclass
class TrackingReplayReport:
    """docs plan M3's own acceptance metrics - >=90% reacquisition success,
    <5% false-lost rate - measured by replaying a REAL captured detection
    session (the exact JSON tools/detection_regression.py capture already
    produces for M2) through the REAL TrackingStateMachine/IouKalmanTracker.
    Deliberately not a synthetic occlusion model: a real detector's actual
    frame-to-frame dropout pattern (motion blur, angle, distance) is
    exactly what these metrics are about, and a synthetic model can't
    reproduce that - see this module's own docstring for the same
    reasoning applied to M2."""

    total_episodes: int
    successful_reacquisitions: int
    escalated_to_lost: int

    @property
    def success_rate(self) -> Optional[float]:
        return self.successful_reacquisitions / self.total_episodes if self.total_episodes else None

    @property
    def false_lost_rate(self) -> Optional[float]:
        return self.escalated_to_lost / self.total_episodes if self.total_episodes else None

    def success_rate_ok(self) -> bool:
        return self.success_rate is None or self.success_rate >= MIN_REACQUISITION_SUCCESS_RATE

    def false_lost_rate_ok(self) -> bool:
        return self.false_lost_rate is None or self.false_lost_rate <= MAX_FALSE_LOST_RATE

    def report(self) -> str:
        if self.total_episodes == 0:
            return (
                "No brief-loss episodes occurred in this session (detection never dropped out "
                "and recovered) - nothing to measure. Capture a session where the subject "
                "briefly leaves frame or gets occluded and comes back."
            )
        lines = [
            f"Reacquisition episodes:  {self.total_episodes}",
            f"  Recovered to TRACKING: {self.successful_reacquisitions} "
            f"({self.success_rate * 100:.0f}%, target >= {MIN_REACQUISITION_SUCCESS_RATE * 100:.0f}%)"
            f"  {'PASS' if self.success_rate_ok() else 'FAIL'}",
            f"  Escalated to LOST:     {self.escalated_to_lost} "
            f"({self.false_lost_rate * 100:.0f}%, target <= {MAX_FALSE_LOST_RATE * 100:.0f}%)"
            f"  {'PASS' if self.false_lost_rate_ok() else 'FAIL'}",
        ]
        return "\n".join(lines)


def replay_through_tracker(frames: list, reacquire_timeout_s: float = 2.0) -> TrackingReplayReport:
    """Pure function over the same plain-dict frame list analyze_session()
    reads - no camera/detector involved, so this is fully testable without
    real hardware, and directly replayable against a session someone
    already captured for M2's benchmark (no new hardware run needed).

    class_id isn't part of the captured session JSON schema (only
    class_name is - see _detection_to_dict()) - assigned a stable per-name
    id locally here rather than changing that schema, so an
    already-captured session.json works with this immediately."""
    from companion.tracking.iou_tracker import IouKalmanTracker
    from companion.tracking.state import TrackingState, TrackingStateMachine
    from companion.vision.detector import BBox

    class_ids: dict = {}

    def to_detections(raw_list: list, ts: float) -> list:
        result = []
        for d in raw_list:
            class_ids.setdefault(d["class_name"], len(class_ids))
            result.append(
                Detection(
                    bbox=BBox(d["x"], d["y"], d["w"], d["h"]),
                    score=d["score"],
                    class_id=class_ids[d["class_name"]],
                    class_name=d["class_name"],
                    frame_ts=ts,
                )
            )
        return result

    sm = TrackingStateMachine(IouKalmanTracker(), reacquire_timeout_s=reacquire_timeout_s)
    started = False
    in_episode = False
    total_episodes = 0
    successful = 0
    escalated = 0

    for f in frames:
        detections = to_detections(f["detections"], f["ts"])
        if not started:
            if detections:
                sm.start(f["ts"], max(detections, key=lambda d: d.score))
                started = True
            continue

        state = sm.update(f["ts"], detections)

        if state == TrackingState.REACQUIRE and not in_episode:
            in_episode = True
            total_episodes += 1
        elif state == TrackingState.TRACKING and in_episode:
            in_episode = False
            successful += 1
        elif state == TrackingState.TARGET_LOST:
            if in_episode:
                escalated += 1
                in_episode = False
            # A real full loss - a real operator would re-tap (or
            # appearance-based reidentification would re-select, a
            # separate mechanism not replayed here). Mirrors
            # TrackingStateMachine.start()'s own behavior (a clean
            # overwrite via Tracker.init_target(), no explicit reset
            # needed first - confirmed directly, not assumed): pick back
            # up on the next frame that has a detection.
            started = False

    return TrackingReplayReport(
        total_episodes=total_episodes, successful_reacquisitions=successful, escalated_to_lost=escalated
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
    from companion.vision.camera import open_real_camera_and_detector

    hardware_cfg = load_yaml("hardware.yaml")
    camera, detector = open_real_camera_and_detector(hardware_cfg)

    print(
        f"Capturing {args.duration:.0f}s of live detection - point the camera at a moving "
        f"human/vehicle subject, per docs plan M2's own acceptance test..."
    )
    frames = asyncio.run(capture_session(camera, detector, args.duration))
    Path(args.out).write_text(json.dumps({"frames": frames}, indent=2))
    print(f"Saved {len(frames)} frames to {args.out}")


def _cmd_analyze(args: argparse.Namespace) -> None:
    data = json.loads(Path(args.session).read_text())
    frames = data["frames"]

    print("--- Detection stability (docs plan M2) ---")
    print(analyze_session(frames).report())
    print()
    print("--- Tracking reacquisition (docs plan M3) ---")
    print(replay_through_tracker(frames).report())


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
