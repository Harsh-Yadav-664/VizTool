"""Active ROI mapping, 1€ smoothing, and virtual screen coordinate projection."""

from __future__ import annotations

import math
from typing import Optional

from viztool.config import KinematicsConfig
from viztool.kinematics.one_euro_filter import Point2DFilter


class CoordinateMapper:
    """Maps normalized camera coordinates inside an ergonomic ROI to screen pixels."""

    def __init__(self, cfg: KinematicsConfig, screen_bounds: tuple[int, int, int, int]) -> None:
        self._cfg = cfg
        self._vx, self._vy, self._vw, self._vh = screen_bounds
        self._filter = Point2DFilter(
            min_cutoff=cfg.filter_min_cutoff,
            beta=cfg.filter_beta,
            d_cutoff=cfg.filter_d_cutoff,
        )
        self._last_px: Optional[tuple[float, float]] = None

    def reset(self) -> None:
        self._filter.reset()
        self._last_px = None

    def map_to_screen(self, t: float, norm_x: float, norm_y: float) -> tuple[int, int]:
        """Project normalized camera [0..1] into smoothed virtual-screen pixel coords."""
        mx = self._cfg.roi_margin_x
        my = self._cfg.roi_margin_y

        # Map comfortable center ROI [margin .. 1-margin] -> [0 .. 1]
        roi_x = (norm_x - mx) / max(0.1, 1.0 - 2.0 * mx)
        roi_y = (norm_y - my) / max(0.1, 1.0 - 2.0 * my)
        roi_x = max(0.0, min(1.0, roi_x))
        roi_y = max(0.0, min(1.0, roi_y))

        # Apply 1€ adaptive smoothing in normalized ROI space
        sx, sy = self._filter.filter(t, roi_x, roi_y)

        # Convert to virtual desktop pixel coordinates
        target_x = self._vx + sx * (self._vw - 1)
        target_y = self._vy + sy * (self._vh - 1)

        # Micro-deadzone to keep resting cursor pixel-locked
        if self._last_px is not None:
            dist = math.hypot(target_x - self._last_px[0], target_y - self._last_px[1])
            if dist < self._cfg.deadzone_px:
                return int(round(self._last_px[0])), int(round(self._last_px[1]))

        self._last_px = (target_x, target_y)
        return int(round(target_x)), int(round(target_y))
