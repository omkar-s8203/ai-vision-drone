from companion.config.loader import load_yaml


def test_camera_score_threshold_is_configurable_and_sane():
    """build_hardware_orchestrator() (companion/main.py) reads
    hardware.yaml's camera.score_threshold and passes it to IMX500Detector
    instead of always using the hardcoded 0.5 default - real-world
    conditions (motion blur, an awkward bench-test camera angle, distance)
    can push a genuine detection's confidence below a fixed threshold, and
    this makes it a one-line config edit to retune instead of a code
    change. This guards against the same class of bug as
    test_mavlink_bridge.py::test_connect_passes_baud_when_specified (a
    real hardware-bring-up bug where a config value was read but never
    actually threaded through to where it mattered)."""
    hardware_cfg = load_yaml("hardware.yaml")
    threshold = hardware_cfg["camera"]["score_threshold"]
    assert isinstance(threshold, float)
    assert 0.0 <= threshold <= 1.0
