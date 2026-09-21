"""Tests for tools/benchmark_detection.py's own measurement logic.

Scope note: run_benchmark() is exercised here against SyntheticCamera/
PassthroughDetector - real hardware timing (the actual FPS/latency/CPU
numbers docs plan M2 needs) can only be measured for real on the Pi with
the real AI Camera; what's tested here is that the *tool itself* measures
and reports correctly given a known, controlled frame source, not that
real hardware passes the plan's thresholds.
"""

import pytest

from companion.vision.camera import SyntheticCamera
from companion.vision.detector import PassthroughDetector
from tools.benchmark_detection import (
    MAX_MEAN_CPU_PCT,
    MAX_P95_LATENCY_MS,
    MIN_FPS,
    BenchmarkResult,
    run_benchmark,
)


@pytest.mark.asyncio
async def test_run_benchmark_measures_real_fps_from_a_known_frame_rate():
    camera = SyntheticCamera(width=1280, height=720, target_fps=20)
    detector = PassthroughDetector()

    result = await run_benchmark(camera, detector, duration_s=0.5)

    # A fixed-rate synthetic source at 20 FPS for 0.5s should yield
    # something close to 10 frames - loose bounds since this runs on
    # whatever this dev machine's actual scheduler jitter looks like, not
    # real hardware, and the test only needs to prove FPS is computed from
    # real elapsed time and a real frame count, not hardcoded.
    assert 5 <= result.frame_count <= 20
    assert result.fps > 0
    assert result.duration_s > 0


@pytest.mark.asyncio
async def test_run_benchmark_records_a_real_latency_per_frame():
    calls = []

    class _SlowDetector(PassthroughDetector):
        def parse(self, raw, frame_ts):
            calls.append(frame_ts)
            return super().parse(raw, frame_ts)

    camera = SyntheticCamera(width=64, height=48, target_fps=30)
    result = await run_benchmark(camera, _SlowDetector(), duration_s=0.2)

    assert len(result.parse_latency_ms) == result.frame_count
    assert len(calls) == result.frame_count
    assert all(latency_ms >= 0 for latency_ms in result.parse_latency_ms)


@pytest.mark.asyncio
async def test_run_benchmark_without_psutil_leaves_cpu_samples_empty():
    """psutil genuinely isn't installed in this dev environment - this
    exercises the real ImportError fallback path, not a mocked one."""
    with pytest.raises(ImportError):
        import psutil  # noqa: F401

    camera = SyntheticCamera(width=64, height=48, target_fps=30)
    result = await run_benchmark(camera, PassthroughDetector(), duration_s=0.1)

    assert result.cpu_samples_pct == []
    assert result.mean_cpu_pct is None
    assert result.cpu_ok()  # missing data must not itself fail the benchmark


def test_benchmark_result_passes_when_all_three_criteria_are_met():
    result = BenchmarkResult(
        frame_count=100,
        duration_s=5.0,
        fps=MIN_FPS + 1,
        parse_latency_ms=[MAX_P95_LATENCY_MS - 10] * 100,
        cpu_samples_pct=[MAX_MEAN_CPU_PCT - 5] * 100,
    )
    assert result.fps_ok()
    assert result.latency_ok()
    assert result.cpu_ok()
    assert result.passes()


def test_benchmark_result_fails_on_low_fps_even_if_latency_and_cpu_are_fine():
    result = BenchmarkResult(
        frame_count=5,
        duration_s=5.0,
        fps=MIN_FPS - 5,
        parse_latency_ms=[1.0] * 5,
        cpu_samples_pct=[1.0] * 5,
    )
    assert not result.fps_ok()
    assert result.latency_ok()
    assert result.cpu_ok()
    assert not result.passes()


def test_benchmark_result_fails_on_high_p95_latency():
    # A handful of slow outlier frames must show up in p95 even with a
    # good mean - this is exactly the "usually fine, occasionally janky"
    # case a mean-only check would hide.
    latencies = [1.0] * 95 + [MAX_P95_LATENCY_MS + 50] * 5
    result = BenchmarkResult(
        frame_count=100, duration_s=5.0, fps=MIN_FPS + 5, parse_latency_ms=latencies
    )
    assert result.fps_ok()
    assert not result.latency_ok()
    assert not result.passes()


def test_benchmark_result_report_includes_pass_fail_verdict():
    result = BenchmarkResult(frame_count=10, duration_s=1.0, fps=MIN_FPS - 1)
    report = result.report()
    assert "FAIL" in report
    assert "Overall: FAIL" in report
