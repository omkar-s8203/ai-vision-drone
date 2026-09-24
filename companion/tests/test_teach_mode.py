import json
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from companion.comms.protocol import Envelope, MessageType
from companion.comms.ws_server import GroundStationLink
from companion.config.loader import load_yaml
from companion.guidance.approach_test import ApproachTestController
from companion.guidance.distance import CameraIntrinsics, DistanceEstimator, estimate_distance_vision_m
from companion.guidance.follow import FollowController
from companion.guidance.orbit import OrbitController
from companion.learning.dataset import DatasetRecorder
from companion.learning.registry import CUSTOM_CLASS_ID_BASE, MAX_OBJECTS, TaughtObjectRegistry, slugify
from companion.learning.visual_tracker import TeachError, VisualObjectTracker, visual_tracking_available
from companion.logging_.session_recorder import SessionRecorder
from companion.main import CompanionOrchestrator
from companion.mavlink.bridge import MavlinkBridge
from companion.mavlink.rc_monitor import RcOverrideMonitor
from companion.safety.supervisor import SafetySupervisor
from companion.safety.watchdog import HeartbeatWatchdog
from companion.tests.conftest import FakeTransport
from companion.tracking.iou_tracker import IouKalmanTracker
from companion.tracking.state import TrackingState
from companion.vision.camera import CameraBase, Frame
from companion.vision.detector import BBox, Detection, PassthroughDetector

pytestmark = pytest.mark.skipif(not visual_tracking_available(), reason="no OpenCV single-object tracker in this install")

W, H = 1280, 720
LIMITS = load_yaml("teach_limits.yaml")
INTRINSICS = CameraIntrinsics(image_width=W, image_height=H, fx=900.0, fy=900.0, cx=640.0, cy=360.0)


# --- a synthetic scene: textured background, one textured object -------------

class Scene(CameraBase):
    def __init__(self, obj_w=100, obj_h=160):
        rng = np.random.default_rng(3)
        self.width, self.height = W, H
        self.bg = rng.integers(60, 120, (H, W, 3), dtype=np.uint8)
        self.tex = rng.integers(0, 255, (obj_h, obj_w, 3), dtype=np.uint8)
        self.tex[:, :, 2] = 250
        self.obj_w, self.obj_h = obj_w, obj_h
        self.frame = None
        self.visible = True
        self.place(500, 250)

    def place(self, x, y):
        f = self.bg.copy()
        if self.visible:
            f[y:y + self.obj_h, x:x + self.obj_w] = self.tex
        self.frame = f
        self.pos = (x, y)
        return f

    def get_latest_frame(self):
        return self.frame


# --- registry ---------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("Red Backpack", "red_backpack"),
    ("  my truck!! ", "my_truck"),
    ("../../etc/passwd", "etc_passwd"),
    ("..\\..\\windows", "windows"),
    ("a" * 100, "a" * 32),
    ("", None), ("   ", None), ("!!!", None), (None, None), (123, None), ("../..", None),
])
def test_names_are_reduced_to_a_safe_slug(name, expected):
    assert slugify(name) == expected


def test_registry_assigns_stable_high_class_ids_and_persists(tmp_path):
    path = tmp_path / "taught_objects.json"
    registry = TaughtObjectRegistry(path)
    a = registry.register("Backpack", real_width_m=0.35, real_height_m=0.5)
    b = registry.register("Truck")
    assert a.class_id == CUSTOM_CLASS_ID_BASE and b.class_id == CUSTOM_CLASS_ID_BASE + 1
    assert a.class_id >= 10_000  # can never collide with a 0-89 detector class id

    reloaded = TaughtObjectRegistry(path)
    assert [o.name for o in reloaded.all()] == ["backpack", "truck"]
    assert reloaded.get("backpack").real_width_m == 0.35


def test_reteaching_keeps_the_class_id_and_updates_the_size(tmp_path):
    registry = TaughtObjectRegistry(tmp_path / "r.json")
    first = registry.register("box", real_width_m=0.3)
    again = registry.register("BOX", real_height_m=0.4)
    assert again.class_id == first.class_id
    assert (again.real_width_m, again.real_height_m) == (0.3, 0.4)
    assert len(registry.all()) == 1


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), 999, "abc", [], {}])
def test_an_implausible_real_size_is_ignored_not_trusted(tmp_path, bad):
    obj = TaughtObjectRegistry(tmp_path / "r.json").register("thing", real_width_m=bad, real_height_m=bad)
    assert obj.real_width_m is None and obj.real_height_m is None


def test_the_registry_is_capped(tmp_path):
    registry = TaughtObjectRegistry(tmp_path / "r.json")
    for i in range(MAX_OBJECTS):
        assert registry.register(f"o{i}") is not None
    assert registry.register("one_too_many") is None


def test_a_corrupt_registry_file_does_not_crash_startup(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{not json", encoding="utf-8")
    assert TaughtObjectRegistry(path).all() == []


# --- distance for taught objects --------------------------------------------

def _det(name, w, h, x=400, y=200):
    return Detection(bbox=BBox(x, y, w, h), score=1.0, class_id=10_000, class_name=name, frame_ts=0.0)


def test_a_taught_object_has_no_distance_without_a_real_size():
    assert estimate_distance_vision_m(_det("thing", 100, 160), INTRINSICS, custom_sizes={}) is None


def test_distance_from_a_taught_width_and_height():
    sizes = {"thing": (0.5, 0.8)}
    assert estimate_distance_vision_m(_det("thing", 100, 160), INTRINSICS, custom_sizes=sizes) == pytest.approx(4.5)
    assert estimate_distance_vision_m(
        _det("thing", 100, 160), INTRINSICS, prefer_height=True, custom_sizes=sizes
    ) == pytest.approx(0.8 * 900 / 160)


def test_only_one_taught_dimension_is_enough():
    assert estimate_distance_vision_m(_det("t", 100, 160), INTRINSICS, custom_sizes={"t": (None, 0.8)}) == pytest.approx(4.5)
    assert estimate_distance_vision_m(_det("t", 100, 160), INTRINSICS, custom_sizes={"t": (0.5, None)}) == pytest.approx(4.5)


def test_a_clipped_taught_object_falls_back_to_the_intact_dimension():
    clipped_vertically = _det("t", 100, 160, x=400, y=600)  # bottom edge at 760 > 720
    d = estimate_distance_vision_m(
        clipped_vertically, INTRINSICS, reject_truncated=True, prefer_height=True, custom_sizes={"t": (0.5, 0.8)}
    )
    assert d == pytest.approx(0.5 * 900 / 100)
    only_height = estimate_distance_vision_m(
        clipped_vertically, INTRINSICS, reject_truncated=True, custom_sizes={"t": (None, 0.8)}
    )
    assert only_height is None


def test_the_estimator_registers_and_clears_taught_sizes():
    estimator = DistanceEstimator(INTRINSICS)
    estimator.register_custom_object("t", 0.5, None)
    assert estimator.estimate(_det("t", 100, 160))[0] == pytest.approx(4.5)
    estimator.register_custom_object("t", None, None)
    assert estimator.estimate(_det("t", 100, 160))[0] is None


# --- the visual tracker (real OpenCV, real pixels) --------------------------

def _tracker(scene):
    return VisualObjectTracker(lambda: scene.frame, LIMITS)


def _init(tracker, scene, ts=0.0):
    x, y = scene.pos
    return tracker.init_target(ts, Detection(BBox(x, y, scene.obj_w, scene.obj_h), 1.0, 10_000, "thing", ts), 1)


def test_the_visual_tracker_follows_a_moving_object():
    scene = Scene()
    tracker = _tracker(scene)
    _init(tracker, scene)
    errors = []
    for i in range(1, 90):
        scene.place(500 + 4 * i, 250 + int(20 * np.sin(i / 10)))
        result = tracker.update(i / 30, [])
        assert result is not None, f"lost the object at frame {i}"
        errors.append(abs(result.bbox.cx - (scene.pos[0] + 50)) + abs(result.bbox.cy - (scene.pos[1] + 80)))
    assert sum(errors) / len(errors) < 12  # pixels


def test_the_tracker_reports_a_smoothed_box_and_remembers_its_frame():
    scene = Scene()
    tracker = _tracker(scene)
    _init(tracker, scene)
    scene.place(520, 250)
    result = tracker.update(0.033, [])
    assert result.smooth_bbox is not None
    assert tracker.last_frame is scene.frame


def test_init_needs_a_frame_and_a_real_box():
    with pytest.raises(TeachError, match="no_camera_frame"):
        VisualObjectTracker(lambda: None, LIMITS).init_target(0.0, _det("t", 100, 100), 1)
    scene = Scene()
    with pytest.raises(TeachError, match="box_too_small"):
        VisualObjectTracker(lambda: scene.frame, LIMITS).init_target(0.0, _det("t", 5, 5), 1)


def test_the_tracker_gives_up_when_it_stops_reporting_the_object():
    scene = Scene()
    tracker = _tracker(scene)
    _init(tracker, scene)
    tracker._cv_tracker = type("Dead", (), {"update": lambda self, f: (False, (0, 0, 0, 0))})()
    assert tracker.update(0.1, []) is None


@pytest.mark.parametrize("jump", [
    (500, 250, 400, 640),      # area x16
    (500, 250, 100, 20),       # squashed - aspect change
    (2000, 250, 100, 160),     # far outside the frame
    (500, 250, 4, 4),          # tiny
    (float("nan"), 250, 100, 160),
])
def test_an_implausible_box_from_the_underlying_tracker_is_treated_as_lost(jump):
    scene = Scene()
    tracker = _tracker(scene)
    _init(tracker, scene)
    tracker._cv_tracker = type("Wild", (), {"update": lambda self, f: (True, jump)})()
    assert tracker.update(0.1, []) is None


def test_reset_forgets_the_object():
    scene = Scene()
    tracker = _tracker(scene)
    _init(tracker, scene)
    tracker.reset()
    assert tracker.update(0.1, []) is None


# --- dataset capture --------------------------------------------------------

def _recorder(tmp_path, **overrides):
    limits = {**LIMITS, "sample_interval_s": 0.0, "min_repeat_s": 3.0, **overrides}
    recorder = DatasetRecorder(tmp_path / "datasets", limits)
    obj = TaughtObjectRegistry(tmp_path / "datasets" / "r.json").register("thing", 0.5, 0.8)
    recorder.start(obj)
    return recorder, obj


def _frame_img():
    return np.zeros((H, W, 3), dtype=np.uint8)


def test_a_sample_is_saved_as_an_image_and_a_correct_yolo_label(tmp_path):
    recorder, obj = _recorder(tmp_path)
    assert recorder.maybe_save(_frame_img(), BBox(320, 180, 128, 72), 0.0, 0.9)
    recorder.wait()
    root = tmp_path / "datasets" / "thing"
    images = list((root / "images").glob("*.jpg"))
    labels = list((root / "labels").glob("*.txt"))
    assert len(images) == 1 and len(labels) == 1
    cls, cx, cy, w, h = labels[0].read_text().split()
    assert cls == "0"
    assert (float(cx), float(cy), float(w), float(h)) == pytest.approx((0.3, 0.3, 0.1, 0.1), abs=1e-5)
    meta = json.loads((root / "meta.json").read_text())
    assert meta["name"] == "thing" and meta["real_width_m"] == 0.5


def test_a_sample_is_refused_when_the_track_does_not_look_like_the_object(tmp_path):
    recorder, _ = _recorder(tmp_path)
    assert not recorder.maybe_save(_frame_img(), BBox(320, 180, 128, 72), 0.0, 0.3)   # low similarity
    assert not recorder.maybe_save(_frame_img(), BBox(320, 180, 128, 72), 0.0, None)  # unknown similarity


@pytest.mark.parametrize("box", [
    BBox(-5, 100, 100, 100), BBox(100, -5, 100, 100), BBox(1200, 100, 100, 100),
    BBox(100, 650, 100, 100), BBox(100, 100, 0.5, 100),
])
def test_clipped_or_degenerate_boxes_are_never_saved(tmp_path, box):
    recorder, _ = _recorder(tmp_path)
    assert not recorder.maybe_save(_frame_img(), box, 0.0, 0.9)


def test_near_duplicates_are_skipped_but_a_moved_or_later_sample_is_kept(tmp_path):
    recorder, _ = _recorder(tmp_path)
    assert recorder.maybe_save(_frame_img(), BBox(300, 200, 100, 100), 0.0, 0.9)
    assert not recorder.maybe_save(_frame_img(), BBox(302, 200, 100, 100), 0.1, 0.9)   # barely moved
    assert recorder.maybe_save(_frame_img(), BBox(400, 200, 100, 100), 0.2, 0.9)       # moved 100px
    assert not recorder.maybe_save(_frame_img(), BBox(402, 200, 100, 100), 0.3, 0.9)
    assert recorder.maybe_save(_frame_img(), BBox(402, 200, 100, 100), 4.0, 0.9)       # 3s+ later
    assert recorder.maybe_save(_frame_img(), BBox(402, 200, 160, 160), 4.1, 0.9)       # much bigger
    assert recorder.sample_count == 4


def test_the_sample_interval_limits_the_rate(tmp_path):
    recorder, _ = _recorder(tmp_path, sample_interval_s=0.5)
    assert recorder.maybe_save(_frame_img(), BBox(100, 100, 100, 100), 0.0, 0.9)
    assert not recorder.maybe_save(_frame_img(), BBox(600, 300, 100, 100), 0.2, 0.9)
    assert recorder.maybe_save(_frame_img(), BBox(600, 300, 100, 100), 0.6, 0.9)


def test_the_per_object_cap_stops_capture(tmp_path):
    recorder, _ = _recorder(tmp_path, max_samples_per_object=2)
    for i in range(6):
        recorder.maybe_save(_frame_img(), BBox(50 + 200 * i, 100, 100, 100), float(i), 0.9)
    assert recorder.sample_count == 2


def test_the_total_size_cap_stops_capture(tmp_path):
    recorder, _ = _recorder(tmp_path, max_total_mb=0.0)
    assert not recorder.maybe_save(_frame_img(), BBox(100, 100, 100, 100), 0.0, 0.9)


def test_the_frame_is_copied_so_a_reused_camera_buffer_cannot_corrupt_the_label(tmp_path):
    recorder, _ = _recorder(tmp_path)
    frame = _frame_img()
    frame[:, :] = 200
    recorder.maybe_save(frame, BBox(100, 100, 100, 100), 0.0, 0.9)
    frame[:, :] = 0                                     # the camera overwrites its buffer immediately
    recorder.wait()
    import cv2
    saved = cv2.imread(str(next((tmp_path / "datasets" / "thing" / "images").glob("*.jpg"))))
    assert saved.mean() > 150


def test_numbering_continues_across_sessions(tmp_path):
    recorder, obj = _recorder(tmp_path)
    recorder.maybe_save(_frame_img(), BBox(100, 100, 100, 100), 0.0, 0.9)
    recorder.stop()
    recorder.start(obj)
    assert recorder.sample_count == 1


def test_nothing_is_saved_when_not_teaching(tmp_path):
    recorder = DatasetRecorder(tmp_path / "datasets", LIMITS)
    assert not recorder.maybe_save(_frame_img(), BBox(100, 100, 100, 100), 0.0, 0.9)


# --- the orchestrator flow --------------------------------------------------

@contextmanager
def _build(tmp_path, camera, visual_tracker="default"):
    watchdog = HeartbeatWatchdog(timeout_s=2.0)
    transport = FakeTransport(connected=True)
    link = GroundStationLink(transport)
    recorder = SessionRecorder(tmp_path / "session")
    root = tmp_path / "datasets"
    limits = {**LIMITS, "sample_interval_s": 0.1, "min_repeat_s": 0.2}
    with patch("companion.mavlink.bridge.mavutil") as mock_mavutil:
        mavlink = MavlinkBridge("udpin:127.0.0.1:14795")
        mavlink.connect()
        conn = mock_mavutil.mavlink_connection.return_value
        conn.target_system = 1
        conn.target_component = 1
        mock_mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
        approach_cfg = load_yaml("approach_limits.yaml")
        kwargs = {}
        if visual_tracker != "default":
            kwargs["visual_tracker"] = visual_tracker
        orch = CompanionOrchestrator(
            camera=camera,
            detector=PassthroughDetector(),
            tracker=IouKalmanTracker(),
            distance_estimator=DistanceEstimator(CameraIntrinsics.from_dict(load_yaml("camera_calibration.yaml"))),
            follow_controller=FollowController(load_yaml("follow_limits.yaml")),
            orbit_controller=OrbitController(load_yaml("orbit_limits.yaml")),
            approach_controller=ApproachTestController(approach_cfg),
            mavlink=mavlink,
            rc_monitor=RcOverrideMonitor(deadband=approach_cfg["rc_override_deadband"]),
            supervisor=SafetySupervisor(watchdog),
            watchdog=watchdog,
            link=link,
            recorder=recorder,
            taught_registry=TaughtObjectRegistry(root / "taught_objects.json"),
            dataset_recorder=DatasetRecorder(root, limits),
            **kwargs,
        )
        orch.custom_max_speed_mps = LIMITS["custom_max_speed_mps"]
        orch.watchdog.beat("mavlink")
        orch.watchdog.beat("rc_channels")
        orch.mavlink.telemetry.fc_mode = "GUIDED"
        orch.mavlink.telemetry.armed = True
        orch.mavlink.telemetry.alt_m = 10.0
        orch.mavlink.telemetry.position_ts = time.monotonic()
        yield orch, transport, conn, root
        orch.dataset.stop()
        recorder.close()


def _teach(orch, scene, **extra):
    x, y = scene.pos
    orch._on_teach_object({"x": x, "y": y, "w": scene.obj_w, "h": scene.obj_h, "name": "Red Box", **extra})


def _fr(ts):
    return Frame(ts=ts, width=W, height=H, raw_detection_output=[])


def _messages(transport, msg_type):
    out = []
    for raw in transport.sent:
        m = json.loads(raw)
        if m["type"] == msg_type:
            out.append(m["payload"])
    return out


@pytest.mark.asyncio
async def test_teaching_starts_tracking_an_object_the_detector_does_not_know(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _conn, root):
        _teach(orch, scene, real_width_m=0.5, real_height_m=0.8)
        result = await orch.process_frame(_fr(0.0))
        assert result["tracking_state"] == TrackingState.TRACKING
        assert orch.state_machine.target.class_name == "red_box"
        assert _messages(transport, "teach_result")[-1] == {"ok": True, "name": "red_box", "has_distance": True}
        assert _messages(transport, "tracking_update")[-1]["teaching"] == "red_box"
        assert orch.distance_estimator.custom_sizes["red_box"] == (0.5, 0.8)


@pytest.mark.asyncio
async def test_a_taught_object_is_followed_as_it_moves_and_photos_are_saved(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _conn, root):
        _teach(orch, scene, real_width_m=0.5, real_height_m=0.8)
        await orch.process_frame(_fr(0.0))
        for i in range(1, 60):
            scene.place(500 + 4 * i, 250)
            result = await orch.process_frame(_fr(i / 30))
            assert result["tracking_state"] == TrackingState.TRACKING
        orch.dataset.wait()
        images = list((root / "red_box" / "images").glob("*.jpg"))
        labels = list((root / "red_box" / "labels").glob("*.txt"))
        assert len(images) >= 3 and len(images) == len(labels)
        assert _messages(transport, "tracking_update")[-1]["teach_samples"] == orch.dataset.sample_count


@pytest.mark.asyncio
async def test_photos_are_labelled_with_the_frame_the_tracker_saw(tmp_path):
    """The saved box must sit on the object in the saved image."""
    import cv2

    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        for i in range(1, 40):
            scene.place(500 + 6 * i, 250)
            await orch.process_frame(_fr(i / 30))
        orch.dataset.wait()
        checked = 0
        for label in (root / "red_box" / "labels").glob("*.txt"):
            _, cx, cy, bw, bh = (float(v) for v in label.read_text().split())
            img = cv2.imread(str(root / "red_box" / "images" / (label.stem + ".jpg")))
            x0, y0 = int((cx - bw / 2) * W), int((cy - bh / 2) * H)
            crop = img[y0 + 10:y0 + int(bh * H) - 10, x0 + 10:x0 + int(bw * W) - 10]
            assert crop[:, :, 2].mean() > 200  # the object texture is bright red; the background is not
            checked += 1
        assert checked >= 2


@pytest.mark.asyncio
async def test_following_a_taught_object_is_capped_below_the_normal_speed_limit(tmp_path):
    scene = Scene(obj_w=40, obj_h=64)              # small = far away = a big forward command
    scene.place(600, 300)
    with _build(tmp_path, scene) as (orch, _t, conn, _root):
        _teach(orch, scene, real_width_m=0.5, real_height_m=0.8)
        await orch.process_frame(_fr(0.0))
        orch._on_mode_command({"mode": "follow"})
        for i in range(1, 90):
            await orch.process_frame(_fr(i / 30))
        speeds = [c.args[8] for c in conn.mav.set_position_target_local_ned_send.call_args_list]
        assert speeds, "no setpoints were sent"
        cap = LIMITS["custom_max_speed_mps"]
        assert max(abs(v) for v in speeds) <= cap + 1e-9
        assert max(speeds) > 0.9 * cap  # it did drive toward the far object, just slower


@pytest.mark.asyncio
async def test_without_a_real_size_there_is_no_distance_and_no_forward_motion(tmp_path):
    scene = Scene(obj_w=40, obj_h=64)
    scene.place(600, 300)
    with _build(tmp_path, scene) as (orch, transport, conn, _root):
        _teach(orch, scene)                        # no real size given
        await orch.process_frame(_fr(0.0))
        assert _messages(transport, "teach_result")[-1]["has_distance"] is False
        orch._on_mode_command({"mode": "follow"})
        for i in range(1, 30):
            await orch.process_frame(_fr(i / 30))
        assert _messages(transport, "tracking_update")[-1]["distance_m"] is None
        assert all(c.args[8] == 0.0 for c in conn.mav.set_position_target_local_ned_send.call_args_list)


@pytest.mark.asyncio
async def test_a_wrong_object_replacing_the_taught_one_stops_the_follow(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, conn, _root):
        _teach(orch, scene, real_width_m=0.5, real_height_m=0.8)
        await orch.process_frame(_fr(0.0))
        orch._on_mode_command({"mode": "follow"})
        for i in range(1, 10):
            await orch.process_frame(_fr(i / 30))
        x, y = scene.pos
        scene.frame[y:y + scene.obj_h, x:x + scene.obj_w] = (255, 0, 0)   # a differently-looking thing takes its place
        states = []
        for i in range(10, 70):
            states.append((await orch.process_frame(_fr(i / 30)))["tracking_state"])
        assert TrackingState.REACQUIRE in states or TrackingState.TARGET_LOST in states
        assert conn.mav.set_position_target_local_ned_send.call_args_list[-1].args[8:11] == (0.0, 0.0, 0.0)


@pytest.mark.asyncio
async def test_losing_the_object_ends_teaching_and_needs_a_re_draw(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _c, _root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        scene.frame = None                        # camera gives nothing -> tracker cannot see it
        await orch.process_frame(_fr(0.1))
        result = await orch.process_frame(_fr(5.0))
        assert result["tracking_state"] == TrackingState.TARGET_LOST
        assert orch._custom_object is None
        assert _messages(transport, "tracking_update")[-1]["teaching"] is None
        assert orch.state_machine.tracker is orch.default_tracker


@pytest.mark.asyncio
async def test_abort_ends_teaching_and_restores_the_detector_tracker(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, _root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        orch._on_abort({"reason": "test"})
        assert orch._custom_object is None
        assert orch.state_machine.tracker is orch.default_tracker
        assert orch.state_machine.state == TrackingState.IDLE
        assert not orch.dataset.is_active


@pytest.mark.asyncio
async def test_a_teach_request_pending_at_abort_is_dropped(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, _root):
        _teach(orch, scene)
        orch._on_abort({"reason": "test"})
        result = await orch.process_frame(_fr(0.0))
        assert result["tracking_state"] == TrackingState.IDLE


@pytest.mark.asyncio
async def test_selecting_a_detected_object_returns_to_normal_tracking(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, _root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        person = Detection(BBox(100, 100, 80, 160), 0.9, 0, "person", 1.0)
        orch._on_target_selected({"x": 140.0, "y": 180.0, "point": True})
        await orch.process_frame(Frame(ts=0.1, width=W, height=H, raw_detection_output=[person]))
        assert orch._custom_object is None
        assert orch.state_machine.tracker is orch.default_tracker
        assert orch.state_machine.target.class_name == "person"
        assert not orch.dataset.is_active


@pytest.mark.asyncio
async def test_teaching_a_new_object_replaces_the_previous_one(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        orch._on_teach_object({"x": 500, "y": 250, "w": 100, "h": 160, "name": "Second"})
        await orch.process_frame(_fr(0.1))
        assert orch._custom_object.name == "second"
        assert {o.name for o in orch.registry.all()} == {"red_box", "second"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,reason", [
    ({"x": 1, "y": 1, "w": 50, "h": 50}, "bad_name"),
    ({"x": 1, "y": 1, "w": 50, "h": 50, "name": "!!!"}, "bad_name"),
    ({"x": "a", "y": 1, "w": 50, "h": 50, "name": "t"}, "bad_box"),
    ({"x": 1, "y": 1, "w": 0, "h": 50, "name": "t"}, "bad_box"),
    ({"x": 1, "y": 1, "w": -5, "h": 50, "name": "t"}, "bad_box"),
    ({"x": float("nan"), "y": 1, "w": 50, "h": 50, "name": "t"}, "bad_box"),
    ({"y": 1, "w": 50, "h": 50, "name": "t"}, "bad_box"),
    ({"x": 1, "y": 1, "w": 5, "h": 5, "name": "t"}, "box_too_small"),
])
async def test_bad_teach_requests_are_rejected_with_a_reason_and_change_nothing(tmp_path, payload, reason):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _c, root):
        orch._on_teach_object(payload)
        result = await orch.process_frame(_fr(0.0))
        assert _messages(transport, "teach_result")[-1] == {"ok": False, "reason": reason}
        assert orch._custom_object is None
        assert result["tracking_state"] == TrackingState.IDLE
        assert orch.registry.all() == [] or reason == "box_too_small"


@pytest.mark.asyncio
async def test_no_camera_frame_and_no_visual_tracker_fail_cleanly(tmp_path):
    scene = Scene()
    scene.frame = None
    with _build(tmp_path, scene) as (orch, transport, _c, _root):
        _teach_box = {"x": 500, "y": 250, "w": 100, "h": 160, "name": "t"}
        orch._on_teach_object(_teach_box)
        await orch.process_frame(_fr(0.0))
        assert _messages(transport, "teach_result")[-1] == {"ok": False, "reason": "no_camera_frame"}
    scene2 = Scene()
    with _build(tmp_path / "b", scene2, visual_tracker=None) as (orch, transport, _c, _root):
        orch.visual_tracker = None
        orch._on_teach_object({"x": 500, "y": 250, "w": 100, "h": 160, "name": "t"})
        await orch.process_frame(_fr(0.0))
        assert _messages(transport, "teach_result")[-1] == {"ok": False, "reason": "no_visual_tracker"}


@pytest.mark.asyncio
async def test_a_hostile_name_cannot_write_outside_the_dataset_folder(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, root):
        orch._on_teach_object({"x": 500, "y": 250, "w": 100, "h": 160, "name": "../../../evil"})
        await orch.process_frame(_fr(0.0))
        for i in range(1, 20):
            scene.place(500 + 6 * i, 250)
            await orch.process_frame(_fr(i / 30))
        orch.dataset.wait()
        created = {p.relative_to(tmp_path).parts[0] for p in tmp_path.rglob("*") if p.is_file()}
        assert created <= {"datasets", "session"}
        assert (root / "evil").is_dir()


@pytest.mark.asyncio
async def test_the_message_arrives_over_the_wire_and_taught_sizes_survive_a_restart(tmp_path):
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _c, root):
        envelope = Envelope(
            type=MessageType.TEACH_OBJECT, seq=1, ts=0.0,
            payload={"x": 500, "y": 250, "w": 100, "h": 160, "name": "Red Box", "real_width_m": 0.5},
        )
        transport.inject(envelope.to_json())
        await orch.process_frame(_fr(0.0))
        assert orch._custom_object.name == "red_box"
    with _build(tmp_path, Scene()) as (orch2, _t, _c, _root):
        assert orch2.distance_estimator.custom_sizes["red_box"] == (0.5, None)


@pytest.mark.asyncio
async def test_teach_mode_never_touches_normal_detector_tracking(tmp_path):
    """A plain tap-select run with teach mode built in must behave exactly as before."""
    scene = Scene()
    with _build(tmp_path, scene) as (orch, transport, _c, root):
        person = Detection(BBox(100, 100, 80, 160), 0.9, 0, "person", 0.0)
        orch._on_target_selected({"x": 140.0, "y": 180.0, "point": True})
        result = await orch.process_frame(Frame(ts=0.0, width=W, height=H, raw_detection_output=[person]))
        assert result["tracking_state"] == TrackingState.TRACKING
        assert orch._custom_object is None
        assert _messages(transport, "tracking_update")[-1]["teaching"] is None
        assert not (root / "person").exists()


@pytest.mark.asyncio
async def test_the_slow_visual_tracker_runs_off_the_event_loop_thread(tmp_path):
    """OpenCV's tracker costs tens of ms a frame; inline it would stall link
    heartbeats, the watchdog and MAVLink handling."""
    import threading

    scene = Scene()
    with _build(tmp_path, scene) as (orch, _t, _c, _root):
        _teach(orch, scene)
        await orch.process_frame(_fr(0.0))
        threads = []
        real_update = orch.state_machine.update

        def spy(ts, detections):
            threads.append(threading.current_thread())
            return real_update(ts, detections)

        orch.state_machine.update = spy
        await orch.process_frame(_fr(0.1))
        assert threads and threads[0] is not threading.main_thread()
