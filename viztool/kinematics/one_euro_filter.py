"""1€ (One Euro) adaptive low-pass filter for jitter-free, low-latency HCI."""

from __future__ import annotations

import math
from typing import Optional


class OneEuroFilter:
    """Adaptive first-order low-pass filter with velocity-based cutoff frequency."""

    def __init__(
        self,
        min_cutoff: float = 1.15,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x_prev: Optional[float] = None
        self._dx_prev: float = 0.0
        self._t_prev: Optional[float] = None

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None

    @staticmethod
    def _alpha(dt: float, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, t: float, x: float) -> float:
        if self._t_prev is None or self._x_prev is None:
            self._t_prev = t
            self._x_prev = x
            self._dx_prev = 0.0
            return x

        dt = t - self._t_prev
        if dt <= 1e-6:
            return self._x_prev

        dx = (x - self._x_prev) / dt
        a_d = self._alpha(dt, self.d_cutoff)
        dx_hat = a_d * dx + (1.0 - a_d) * self._dx_prev

        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        a = self._alpha(dt, cutoff)
        x_hat = a * x + (1.0 - a) * self._x_prev

        self._x_prev = x_hat
        self._dx_prev = dx_hat
        self._t_prev = t
        return x_hat


class Point2DFilter:
    """Dual-axis 1€ filter for (x, y) pointer coordinates."""

    def __init__(
        self,
        min_cutoff: float = 1.15,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ) -> None:
        self._fx = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)
        self._fy = OneEuroFilter(min_cutoff=min_cutoff, beta=beta, d_cutoff=d_cutoff)

    def reset(self) -> None:
        self._fx.reset()
        self._fy.reset()

    def filter(self, t: float, x: float, y: float) -> tuple[float, float]:
        return self._fx.filter(t, x), self._fy.filter(t, y)
