"""Stateless & hysteresis-protected 3D geometric gesture detector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from viztool.config import GestureConfig
from viztool.kinematics.hand_kinematics import HandFeatures


class GestureType(str, Enum):
    NONE = "NONE"
    HOVER = "HOVER"
    INDEX_PINCH = "INDEX_PINCH"
    MIDDLE_PINCH = "MIDDLE_PINCH"
    RING_PINCH = "RING_PINCH"
    PINKY_PINCH = "PINKY_PINCH"
    TWO_FINGER_SCROLL = "TWO_FINGER_SCROLL"
    OPEN_PALM = "OPEN_PALM"
    FIST = "FIST"


class SchmittTrigger:
    """Dual-threshold hysteresis gate to eliminate boundary bounce/multi-clicks."""

    def __init__(self, enter_thresh: float, exit_thresh: float) -> None:
        self._enter = enter_thresh
        self._exit = exit_thresh
        self.active = False

    def update(self, value: float) -> bool:
        if not self.active and value < self._enter:
            self.active = True
        elif self.active and value > self._exit:
            self.active = False
        return self.active

    def reset(self) -> None:
        self.active = False


@dataclass(frozen=True)
class GestureFrame:
    primary_gesture: GestureType
    index_pinch: bool
    middle_pinch: bool
    ring_pinch: bool
    pinky_pinch: bool
    air_poke: bool
    pointer_xy: tuple[float, float]
    palm_center_xy: tuple[float, float]


class GestureDetector:
    """Classifies 3D hand features into bounce-free semantic gestures."""

    def __init__(self, cfg: GestureConfig) -> None:
        self._index_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._middle_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._ring_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._pinky_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._prev_z: float | None = None

    def reset(self) -> None:
        self._index_gate.reset()
        self._middle_gate.reset()
        self._ring_gate.reset()
        self._pinky_gate.reset()
        self._prev_z = None

    def detect(self, feat: HandFeatures) -> GestureFrame:
        idx_pinch = self._index_gate.update(feat.thumb_index_ratio)
        mid_pinch = self._middle_gate.update(feat.thumb_middle_ratio)
        ring_pinch = self._ring_gate.update(feat.thumb_ring_ratio)
        pinky_pinch = self._pinky_gate.update(feat.thumb_pinky_ratio)

        # Air-Poke: rapid forward Z-impulse of index tip while index is straight
        air_poke = False
        if self._prev_z is not None and feat.index_straight and not idx_pinch:
            dz = feat.pointer_z - self._prev_z
            if dz < -0.018:
                air_poke = True
        self._prev_z = feat.pointer_z

        # Priority order prevents overlapping triggers
        if idx_pinch:
            gesture = GestureType.INDEX_PINCH
        elif mid_pinch:
            gesture = GestureType.MIDDLE_PINCH
        elif ring_pinch:
            gesture = GestureType.RING_PINCH
        elif pinky_pinch:
            gesture = GestureType.PINKY_PINCH
        elif (
            feat.index_straight
            and feat.middle_straight
            and not feat.ring_straight
            and not feat.pinky_straight
        ):
            gesture = GestureType.TWO_FINGER_SCROLL
        elif (
            feat.index_straight
            and feat.middle_straight
            and feat.ring_straight
            and feat.pinky_straight
            and feat.thumb_straight
        ):
            gesture = GestureType.OPEN_PALM
        elif (
            not feat.index_straight
            and not feat.middle_straight
            and not feat.ring_straight
            and not feat.pinky_straight
        ):
            gesture = GestureType.FIST
        else:
            gesture = GestureType.HOVER

        return GestureFrame(
            primary_gesture=gesture,
            index_pinch=idx_pinch,
            middle_pinch=mid_pinch,
            ring_pinch=ring_pinch,
            pinky_pinch=pinky_pinch,
            air_poke=air_poke,
            pointer_xy=feat.pointer_xy,
            palm_center_xy=feat.palm_center_xy,
        )
