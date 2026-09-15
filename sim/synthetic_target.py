from __future__ import annotations

import math
from typing import Optional

import numpy as np

from companion.vision.detector import BBox, Detection


class SyntheticTargetGenerator:
    """Produces a moving-target Detection stream for testing tracking,
    distance estimation, follow, and approach-test logic without a real
    camera or AI Camera (docs plan M13). Feed `detections_at` into
    SyntheticCamera(detection_source=...).
    """

    def __init__(
        self,
        image_width: int = 1280,
        image_height: int = 720,
        class_name: str = "person",
        class_id: int = 0,
        base_width_px: float = 80.0,
        base_height_px: float = 160.0,
        path_amplitude_px: float = 200.0,
        path_period_s: float = 8.0,
        occlusion_windows: Optional[list[tuple[float, float]]] = None,
    ) -> None:
        self.image_width = image_width
        self.image_height = image_height
        self.class_name = class_name
        self.class_id = class_id
        self.base_width_px = base_width_px
        self.base_height_px = base_height_px
        self.path_amplitude_px = path_amplitude_px
        self.path_period_s = path_period_s
        self.occlusion_windows = occlusion_windows or []

    def detections_at(self, ts: float) -> list[Detection]:
        for start, end in self.occlusion_windows:
            if start <= ts < end:
                return []

        cx = self.image_width / 2 + self.path_amplitude_px * math.sin(
            2 * math.pi * ts / self.path_period_s
        )
        cy = self.image_height / 2
        bbox = BBox(
            x=cx - self.base_width_px / 2,
            y=cy - self.base_height_px / 2,
            w=self.base_width_px,
            h=self.base_height_px,
        )
        return [
            Detection(
                bbox=bbox,
                score=0.9,
                class_id=self.class_id,
                class_name=self.class_name,
                frame_ts=ts,
            )
        ]


def render_frame(width: int, height: int, detections: list[Detection]) -> np.ndarray:
    """Renders a plain BGR frame with the synthetic target drawn as a solid
    rectangle - purely a visualization aid so the sim video pipeline has
    something real to stream (docs plan M5/M13), not a stand-in detector."""
    frame = np.full((height, width, 3), (40, 40, 40), dtype=np.uint8)
    for det in detections:
        x0 = max(0, int(det.bbox.x))
        y0 = max(0, int(det.bbox.y))
        x1 = min(width, int(det.bbox.x + det.bbox.w))
        y1 = min(height, int(det.bbox.y + det.bbox.h))
        frame[y0:y1, x0:x1] = (60, 180, 60)
    return frame
