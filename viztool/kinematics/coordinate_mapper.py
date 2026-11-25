"""Ergonomic Relative Air-Trackpad & Absolute ROI coordinate projection."""

from __future__ import annotations

import math
from typing import Optional

from viztool.config import KinematicsConfig
from viztool.kinematics.one_euro_filter import Point2DFilter


class CoordinateMapper:
    """Projects smoothed hand motion to virtual-screen pixels (Relative or Absolute)."""

    def __init__(self, cfg: KinematicsConfig, screen_bounds: tuple[int, int, int, int]) -> None:
        self._cfg = cfg
        self._vx, self._vy, self._vw, self._vh = screen_bounds
        self._filter = Point2DFilter(
            min_cutoff=cfg.filter_min_cutoff,
            beta=cfg.filter_beta,
            d_cutoff=cfg.filter_d_cutoff,
        )
        self._prev_filtered_norm: Optional[tuple[float, float]] = None
        self._cursor_f: tuple[float, float] = (
            self._vx + self._vw * 0.5,
            self._vy + self._vh * 0.5,
        )

    def reset(self) -> None:
        """Reset filter & relative delta reference (preserves current cursor position)."""
        self._filter.reset()
        self._prev_filtered_norm = None

    def set_cursor_px(self, x_px: int, y_px: int) -> None:
        """Sync internal cursor tracker (e.g. after external/OS mouse move)."""
        self._cursor_f = (float(x_px), float(y_px))

    def map_to_screen(self, t: float, norm_x: float, norm_y: float) -> tuple[int, int]:
        """Project normalized [0..1] anchor into virtual-screen pixel coordinates."""
        sx, sy = self._filter.filter(t, norm_x, norm_y)

        if self._cfg.tracking_mode == "absolute":
            mx = self._cfg.roi_margin_x
            top_m = max(0.08, self._cfg.roi_margin_y * 0.65)
            bot_m = min(0.32, self._cfg.roi_margin_y * 1.75)  # Asymmetric bottom margin for easy Taskbar clicks
            roi_x = max(0.0, min(1.0, (sx - mx) / max(0.1, 1.0 - 2.0 * mx)))
            roi_y = max(0.0, min(1.0, (sy - top_m) / max(0.1, 1.0 - top_m - bot_m)))
            tx = self._vx + roi_x * (self._vw - 1)
            ty = self._vy + roi_y * (self._vh - 1)
            self._cursor_f = (tx, ty)
            return int(round(tx)), int(round(ty))

        # --- Relative Air-Trackpad Mode (Default: zero Gorilla-Arm fatigue) ---
        if self._prev_filtered_norm is None:
            self._prev_filtered_norm = (sx, sy)
            return int(round(self._cursor_f[0])), int(round(self._cursor_f[1]))

        dx_norm = sx - self._prev_filtered_norm[0]
        dy_norm = sy - self._prev_filtered_norm[1]
        self._prev_filtered_norm = (sx, sy)

        # Base pixel delta scaled by sensitivity
        raw_dx = dx_norm * self._vw * self._cfg.relative_sensitivity
        raw_dy = dy_norm * self._vh * self._cfg.relative_sensitivity
        dist_px = math.hypot(raw_dx, raw_dy)

        if dist_px < self._cfg.deadzone_px:
            return int(round(self._cursor_f[0])), int(round(self._cursor_f[1]))

        # Non-linear acceleration curve: slow = 1px precision, fast = effortless sweep
        ref_speed = 12.0
        gain = max(0.55, (dist_px / ref_speed) ** (self._cfg.accel_gamma - 1.0))
        gain = min(gain, 3.2)

        nx = self._cursor_f[0] + raw_dx * gain
        ny = self._cursor_f[1] + raw_dy * gain

        nx = max(float(self._vx), min(float(self._vx + self._vw - 1), nx))
        ny = max(float(self._vy), min(float(self._vy + self._vh - 1), ny))
        self._cursor_f = (nx, ny)
        return int(round(nx)), int(round(ny))
