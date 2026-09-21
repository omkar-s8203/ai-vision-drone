"""Benchmarks the real detection pipeline against docs plan M2's own
acceptance criteria - not arbitrary numbers:

    >= 15 FPS at 720p+, < 60ms end-to-end per-frame detection latency,
    Pi 5 CPU usage from detection alone < 15%.

Detection has been confirmed *working* on real hardware (see README M2),
but never formally *measured* against these - this tool closes that gap.
Run on the Raspberry Pi with the real AI Camera attached:

    python tools/benchmark_detection.py --duration 30

Only main()'s camera/detector construction is Pi-only (imports
Picamera2IMX500Camera, which raises RuntimeError off a Pi - see
companion/vision/camera.py). The actual measurement loop, run_benchmark(),
takes any CameraBase/DetectorBase, so it's exercised in this project's own
test suite against SyntheticCamera/PassthroughDetector without needing
real hardware - see companion/tests/test_benchmark_detection.py.

CPU measurement needs the optional `psutil` dependency
(`pip install -e .[benchmark]`) - degrades to "unavailable" rather than
failing if it isn't installed, matching this project's existing pattern
for other optional pieces (aiortc/av for video).
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Lets `python tools/benchmark_detection.py` work when run directly (its
# own documented usage) regardless of the current working directory -
# Python only adds this script's own directory (tools/) to sys.path by
# default when invoked this way, not the repo root, so the `companion.*`
# imports below would otherwise fail with ModuleNotFoundError outside a
# repo-root cwd or an editable install. Must run before those imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from companion.config.loader import load_yaml  # noqa: E402
from companion.vision.camera import CameraBase  # noqa: E402
from companion.vision.detector import DetectorBase  # noqa: E402

MIN_FPS = 15.0
MAX_P95_LATENCY_MS = 60.0
MAX_MEAN_CPU_PCT = 15.0


@dataclass
class BenchmarkResult:
    frame_count: int
    duration_s: float
    fps: float
    parse_latency_ms: list = field(default_factory=list)
    cpu_samples_pct: list = field(default_factory=list)

    @property
    def mean_latency_ms(self) -> float:
        return statistics.fmean(self.parse_latency_ms) if self.parse_latency_ms else 0.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.parse_latency_ms:
            return 0.0
        ordered = sorted(self.parse_latency_ms)
        index = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return ordered[index]

    @property
    def mean_cpu_pct(self) -> Optional[float]:
        return statistics.fmean(self.cpu_samples_pct) if self.cpu_samples_pct else None

    def fps_ok(self) -> bool:
        return self.fps >= MIN_FPS

    def latency_ok(self) -> bool:
        return self.p95_latency_ms < MAX_P95_LATENCY_MS

    def cpu_ok(self) -> bool:
        return self.mean_cpu_pct is None or self.mean_cpu_pct < MAX_MEAN_CPU_PCT

    def passes(self) -> bool:
        return self.fps_ok() and self.latency_ok() and self.cpu_ok()

    def report(self) -> str:
        def line(label: str, value: str, ok: Optional[bool]) -> str:
            verdict = "" if ok is None else ("  PASS" if ok else "  FAIL")
            return f"{label:<24}{value}{verdict}"

        lines = [
            f"Frames captured:        {self.frame_count} over {self.duration_s:.1f}s",
            line("FPS:", f"{self.fps:.1f} (target >= {MIN_FPS:.0f})", self.fps_ok()),
            f"Parse latency mean:     {self.mean_latency_ms:.1f} ms",
            line(
                "Parse latency p95:",
                f"{self.p95_latency_ms:.1f} ms (target < {MAX_P95_LATENCY_MS:.0f})",
                self.latency_ok(),
            ),
        ]
        if self.mean_cpu_pct is not None:
            lines.append(
                line(
                    "Mean process CPU:",
                    f"{self.mean_cpu_pct:.1f}% (target < {MAX_MEAN_CPU_PCT:.0f})",
                    self.cpu_ok(),
                )
            )
        else:
            lines.append("Mean process CPU:      unavailable (psutil not installed)")
        lines.append("")
        lines.append(f"Overall: {'PASS' if self.passes() else 'FAIL'}")
        return "\n".join(lines)


async def run_benchmark(
    camera: CameraBase, detector: DetectorBase, duration_s: float
) -> BenchmarkResult:
    """The real measurement loop - the same capture-then-parse shape as
    CompanionOrchestrator.process_frame()'s own first step, just without
    everything after it (tracking/guidance/MAVLink/comms), so this isolates
    detection's own cost - matching what the plan's "<15% CPU from
    detection alone" criterion is actually asking about, not the whole
    pipeline's cost."""
    try:
        import psutil  # type: ignore

        process: Optional[object] = psutil.Process()
        process.cpu_percent(interval=None)  # first call always returns 0.0 - primes it
    except ImportError:
        process = None

    result = BenchmarkResult(frame_count=0, duration_s=0.0, fps=0.0)
    start = time.monotonic()
    deadline = start + duration_s

    async for frame in camera.frames():
        parse_start = time.perf_counter()
        detector.parse(frame.raw_detection_output, frame.ts)
        result.parse_latency_ms.append((time.perf_counter() - parse_start) * 1000.0)
        result.frame_count += 1
        if process is not None:
            result.cpu_samples_pct.append(process.cpu_percent(interval=None))
        if time.monotonic() >= deadline:
            break

    result.duration_s = time.monotonic() - start
    result.fps = result.frame_count / result.duration_s if result.duration_s > 0 else 0.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark the real IMX500 detection pipeline against docs plan M2's "
        "acceptance criteria."
    )
    parser.add_argument(
        "--duration", type=float, default=30.0, help="Seconds to sample (default: 30)"
    )
    args = parser.parse_args()

    # Real hardware only past this point - Picamera2IMX500Camera raises
    # RuntimeError with a clear message on any machine without picamera2.
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
        f"Benchmarking detection for {args.duration:.0f}s against docs plan M2's own "
        f"acceptance criteria (>= {MIN_FPS:.0f} FPS, < {MAX_P95_LATENCY_MS:.0f}ms p95 parse "
        f"latency, < {MAX_MEAN_CPU_PCT:.0f}% mean process CPU)...\n"
        f"Point the camera at a moving human/vehicle subject for a real result, "
        f"per the plan's own acceptance test."
    )
    result = asyncio.run(run_benchmark(camera, detector, args.duration))
    print()
    print(result.report())


if __name__ == "__main__":
    main()
