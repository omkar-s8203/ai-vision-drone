# Tools

Scripts in `tools/`. Anything that opens the camera needs the service stopped first (`sudo systemctl stop ai-vision-drone`), because only one process can hold the camera. Start it again afterwards.

| Tool | Purpose | Status |
|---|---|---|
| `live_monitor.py` | Live, readable view of everything the Pi sends | Used in the field |
| `benchmark_detection.py` | Detection FPS, latency and CPU vs the M2 targets | Run on the Pi: PASS |
| `detection_regression.py` | Record a detection session; analyse stability and tracking reacquisition | Captures run on the Pi |
| `calibrate_camera.py` | Fit camera intrinsics from checkerboard photos | Tested; **never run on real photos** |
| `distance_validation.py` | Compare distance estimates with tape-measured truth | Tested; waiting on calibration and data |
| `ws_latency_benchmark.py` | WebSocket round-trip time vs the <50 ms target | Loopback only so far |
| `export_taught_dataset.py` | Turn Teach-mode photos into a YOLO dataset | Tested |
| `imx500_convert.py` | Wrap Sony's IMX500 converter for custom models | Wrapper tested; real CLI flags unverified |

## live_monitor.py

```bash
pip install websockets
python tools/live_monitor.py --uri ws://<pi-ip>:8765
python tools/live_monitor.py --uri ws://<pi-ip>:8765 --only tracking_update,telemetry --rate 5
```

One line per message: telemetry, tracking and guidance state, commanded velocities, health, detections, events. High-rate types are throttled (default 2 lines/s per type; `--rate 0` for all), but flight-mode, arm and guidance changes and one-off events always print at once. `--raw` prints full JSON. It reconnects automatically.

It is **read-only**: it never sends anything, because the Pi judges the phone's liveness from received messages, and a monitor that sent pings could hide a dead phone link.

## benchmark_detection.py

```bash
python tools/benchmark_detection.py --duration 30
```

Point the camera at a moving person. Reports PASS/FAIL against **≥ 15 FPS, < 60 ms p95 latency, < 15 % CPU**. CPU needs `pip install -e .[benchmark]` (psutil). Real result: 27.1 FPS, 0.3 ms, ~12 %.

## detection_regression.py

```bash
python tools/detection_regression.py capture --duration 30 --out session.json
python tools/detection_regression.py analyze session.json
```

The IMX500 detects at capture time, so a saved video cannot be re-run through it. This records per-frame detection **results** instead. `analyze` reports:

1. **Detection stability**: detection rate, longest run of empty frames (the key regression signal), score and box jitter.
2. **Tracking reacquisition**: replays the session through the real tracker and state machine - target **≥ 90 % reacquired, ≤ 5 % false-lost**.

Keep a baseline session and compare after any camera, detection or tracking change. Frames with no AI result are recorded as empty.

## calibrate_camera.py

```bash
python tools/calibrate_camera.py --images "calib_photos/*.jpg" --board-cols 9 --board-rows 6
python tools/calibrate_camera.py --help        # includes --dry-run
```

Writes `companion/config/camera_calibration.yaml`. Photos must be at the running resolution (1280x720). Use a printed board, count inner corners, bright light, no blur.

## distance_validation.py

```bash
python tools/distance_validation.py --template > measurements.json
python tools/distance_validation.py measurements.json
```

Target: < 15 % error within 3-15 m. Only meaningful after real calibration.

## ws_latency_benchmark.py

```bash
python tools/ws_latency_benchmark.py --uri ws://<pi-ip>:8765 --count 100
python tools/ws_latency_benchmark.py --self-test          # local, no Pi
```

Uses the `ping`/`pong` pair answered at the transport layer, so it measures the channel's own latency. Target < 50 ms.

**Video glass-to-glass latency** (target < 200 ms) is measured by hand: start the service with `AI_VISION_DRONE_LATENCY_OVERLAY=1` to stamp wall-clock time on each frame, then compare the stamp in the app with the real time (clocks synced).

## export_taught_dataset.py

```bash
python tools/export_taught_dataset.py --datasets companion/datasets --out export/taught_v1
```

See [Teach Mode](Teach-Mode#step-2---export).

## imx500_convert.py

```bash
python tools/imx500_convert.py my_model.onnx --out imx500_converted/
```

Picks `imxconv-pt` for `.onnx`, `imxconv-tf` for `.h5`/`.pb`/`.keras`/SavedModel, and checks a `.rpk` came out. The converter needs Python 3.9-3.11 on x86_64 Linux. Check `CONVERTER_ARGS` against `imxconv-* --help` before trusting it.
