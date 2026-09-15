from __future__ import annotations

from dataclasses import dataclass


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
    """Parses picamera2 IMX500 on-sensor inference metadata.

    The IMX500 runs the network on-sensor; this class only reshapes its
    output into the common Detection type - it performs no inference itself.
    """

    def __init__(self, class_names: dict[int, str], score_threshold: float = 0.5) -> None:
        self.class_names = class_names
        self.score_threshold = score_threshold

    def parse(self, raw: object, frame_ts: float) -> list[Detection]:
        # `raw` is expected to be the IMX500 outputs object from picamera2
        # (boxes, scores, classes arrays). Real parsing wired up in M2 once
        # running on actual hardware; kept isolated here so it's the only
        # thing that needs to change when the real metadata format is known.
        boxes = getattr(raw, "boxes", [])
        scores = getattr(raw, "scores", [])
        classes = getattr(raw, "classes", [])
        detections: list[Detection] = []
        for box, score, class_id in zip(boxes, scores, classes):
            if score < self.score_threshold:
                continue
            x, y, w, h = box
            detections.append(
                Detection(
                    bbox=BBox(float(x), float(y), float(w), float(h)),
                    score=float(score),
                    class_id=int(class_id),
                    class_name=self.class_names.get(int(class_id), "unknown"),
                    frame_ts=frame_ts,
                )
            )
        return detections


class PassthroughDetector(DetectorBase):
    """Sim/dev detector: raw is already a list[Detection] (from a synthetic source)."""

    def parse(self, raw: object, frame_ts: float) -> list[Detection]:
        assert isinstance(raw, list)
        return raw
