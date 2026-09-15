from companion.tests.test_mode_command import _build_minimal_orchestrator


def test_fps_is_none_with_fewer_than_two_samples(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    assert orchestrator._current_fps() is None
    recorder.close()


def test_fps_computed_from_recent_frame_timestamps(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    # 10 frames spaced 0.1s apart -> 10 fps
    orchestrator._recent_frame_ts = [i * 0.1 for i in range(10)]
    assert abs(orchestrator._current_fps() - 10.0) < 1e-6
    recorder.close()


def test_health_payload_reports_computed_fps(tmp_path):
    orchestrator, recorder = _build_minimal_orchestrator(tmp_path)
    orchestrator.watchdog.beat("camera")
    orchestrator.watchdog.beat("tracker")
    orchestrator.watchdog.beat("mavlink")
    orchestrator._recent_frame_ts = [i * 0.05 for i in range(20)]

    payload = orchestrator._build_health_payload()

    assert payload["fps"] is not None
    assert abs(payload["fps"] - 20.0) < 1e-6
    recorder.close()
