from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Sequence, Union

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BBox:
    """Pixel-space bounding box, top-left origin."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def iou(self, other: "BBox") -> float:
        ix1 = max(self.x, other.x)
        iy1 = max(self.y, other.y)
        ix2 = min(self.x + self.w, other.x + other.w)
        iy2 = min(self.y + self.h, other.y + other.h)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        union = self.area + other.area - inter
        if union <= 0:
            return 0.0
        return inter / union


@dataclass(frozen=True)
class Detection:
    bbox: BBox
    score: float
    class_id: int
    class_name: str
    frame_ts: float


class DetectorBase:
    """Normalizes a camera backend's raw per-frame output into Detection objects."""

    def parse(self, raw: object, frame_ts: float) -> list[Detection]:
        raise NotImplementedError


class IMX500Detector(DetectorBase):
    """Parses picamera2 IMX500 on-sensor inference output for the SSD
    MobileNetV2 FPN-Lite model (imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk).

    Confirmed against real hardware: `raw` is the 4-tuple
    `(imx500, outputs, metadata, picam2)` bundled by Picamera2IMX500Camera.
    `outputs` is `[boxes, scores, classes, count]` where boxes are
    normalized `(y0, x0, y1, x1)` per detection - `imx500.convert_inference_coords`
    converts a box straight to pixel-space `(x, y, w, h)`, and `class_id` is
    a direct 0-based index into `intrinsics.labels` (90 COCO categories, no
    background offset). `outputs` is None on frames before the on-sensor
    network has produced its first result (normal for ~1s after start()).
    """

    def __init__(
        self,
        class_names: Union[Sequence[str], dict],
        score_threshold: float = 0.5,
        diagnostic_log_interval_s: float = 5.0,
    ) -> None:
        self.class_names = class_names
        self.score_threshold = score_threshold
        # Rate-limited, not per-frame - "is the AI actually seeing
        # anything" is exactly the kind of question that's invisible from
        # the Android app's health panel alone (that only reflects the
        # tracker heartbeat, not whether real detections are occurring),
        # and a real field report ("clear, well-lit subject, zero
        # detections") needs *some* signal from the Pi's own logs
        # (journalctl -u ai-vision-drone -f) to tell apart "the model
        # genuinely sees nothing" from "it sees something, just under
        # score_threshold" from "the on-sensor network isn't producing
        # output at all".
        self._diagnostic_log_interval_s = diagnostic_log_interval_s
        self._last_diagnostic_log_ts = 0.0

    def _label_for(self, class_id: int) -> str:
        if isinstance(self.class_names, dict):
            return self.class_names.get(class_id, "unknown")
        if 0 <= class_id < len(self.class_names):
            return self.class_names[class_id]
        return "unknown"

    def _maybe_log_diagnostic(self, message: str, *args: object) -> None:
        now = time.monotonic()
        if now - self._last_diagnostic_log_ts >= self._diagnostic_log_interval_s:
            log.warning(message, *args)
            self._last_diagnostic_log_ts = now

    def parse(self, raw: object, frame_ts: float) -> list[Detection]:
        imx500, outputs, metadata, picam2 = raw
        if outputs is None:
            self._maybe_log_diagnostic(
                "IMX500Detector: outputs is None (no on-sensor inference result yet) - "
                "normal for ~1s after start(), but if this keeps logging, the on-sensor "
                "network isn't running at all (check the .rpk model path/firmware), and "
                "score_threshold has nothing to do with it"
            )
            return []

        boxes, scores, classes, count = outputs[0][0], outputs[1][0], outputs[2][0], outputs[3][0]
        n = max(int(count[0]), 0)

        if n == 0:
            self._maybe_log_diagnostic(
                "IMX500Detector: on-sensor model returned 0 candidate detections this frame "
                "(threshold=%.2f is irrelevant here - there was nothing to threshold)",
                self.score_threshold,
            )
        else:
            best_score = float(max(scores[:n]))
            if best_score < self.score_threshold:
                self._maybe_log_diagnostic(
                    "IMX500Detector: %d candidate(s) this frame, but the best score %.2f is "
                    "below score_threshold=%.2f - everything is being filtered out; lower "
                    "camera.score_threshold in hardware.yaml if this is a real object",
                    n, best_score, self.score_threshold,
                )

        detections: list[Detection] = []
        for score, class_id_raw, box in zip(scores[:n], classes[:n], boxes[:n]):
            if score < self.score_threshold:
                continue
            y0, x0, y1, x1 = box
            x, y, w, h = imx500.convert_inference_coords((y0, x0, y1, x1), metadata, picam2)
            if not all(math.isfinite(float(v)) for v in (x, y, w, h)) or w <= 1 or h <= 1:
                # A NaN/inf or degenerate box from the on-sensor model would
                # poison tracking, distance and appearance math downstream.
                continue
            class_id = int(class_id_raw)
            detections.append(
                Detection(
                    bbox=BBox(float(x), float(y), float(w), float(h)),
                    score=float(score),
                    class_id=class_id,
                    class_name=self._label_for(class_id),
                    frame_ts=frame_ts,
                )
            )
        return detections


class PassthroughDetector(DetectorBase):
    """Sim/dev detector: raw is already a list[Detection] (from a synthetic source)."""

    def parse(self, raw: object, frame_ts: float) -> list[Detection]:
        assert isinstance(raw, list)
        return raw
