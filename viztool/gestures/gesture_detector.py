"""Hysteresis-protected, biomechanically guarded 3D gesture detector."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from viztool.config import GestureConfig
from viztool.kinematics.hand_kinematics import HandFeatures


class GestureType(str, Enum):
    NONE = "NONE"
    HOVER = "HOVER"
    INDEX_PINCH = "INDEX_PINCH"
    MIDDLE_PINCH = "MIDDLE_PINCH"
    CLUSTER_PINCH = "CLUSTER_PINCH"  # Thumb+Index+Middle together -> Radial Menu (zero pinky pain!)
    TWO_FINGER_SCROLL = "TWO_FINGER_SCROLL"
    OPEN_PALM = "OPEN_PALM"
    FIST = "FIST"


class SchmittTrigger:
    """Dual-threshold hysteresis gate to eliminate boundary bounce/multi-clicks."""

    def __init__(self, enter_thresh: float, exit_thresh: float) -> None:
        self._enter = enter_thresh
        self._exit = exit_thresh
        self.active = False

    def update(self, value: float, allowed: bool = True) -> bool:
        if not allowed:
            # Force release only if value rises or finger clearly tucked into fist
            if self.active and value > self._enter + 0.04:
                self.active = False
            return self.active

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
    cluster_pinch: bool
    air_poke: bool
    pointer_xy: tuple[float, float]
    palm_center_xy: tuple[float, float]


class GestureDetector:
    """Classifies 3D hand features into bounce-free, curl-guarded gestures."""

    def __init__(self, cfg: GestureConfig) -> None:
        self._cfg = cfg
        self._index_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._middle_gate = SchmittTrigger(cfg.pinch_enter_ratio, cfg.pinch_exit_ratio)
        self._cluster_gate = SchmittTrigger(cfg.pinch_enter_ratio + 0.08, cfg.pinch_exit_ratio + 0.08)
        self._prev_z: Optional[float] = None

    def reset(self) -> None:
        self._index_gate.reset()
        self._middle_gate.reset()
        self._cluster_gate.reset()
        self._prev_z = None

    def detect(self, feat: HandFeatures) -> GestureFrame:
        # 1. Check 3-finger Cluster Pinch (Thumb + Index + Middle all reaching together)
        cluster_metric = max(feat.thumb_index_ratio, feat.thumb_middle_ratio)
        cluster_ok = feat.index_reaching and feat.middle_reaching
        cluster_pinch = self._cluster_gate.update(cluster_metric, allowed=cluster_ok)

        # 2. Winner-take-all + Curl Guard prevents closed middle finger from triggering MIDDLE_PINCH
        idx_allowed = (
            feat.index_reaching
            and not cluster_pinch
            and (feat.thumb_index_ratio <= feat.thumb_middle_ratio + 0.06)
        )
        mid_allowed = (
            feat.middle_reaching
            and not cluster_pinch
            and (feat.thumb_middle_ratio + 0.05 < feat.thumb_index_ratio)
        )

        idx_pinch = self._index_gate.update(feat.thumb_index_ratio, allowed=idx_allowed)
        mid_pinch = self._middle_gate.update(feat.thumb_middle_ratio, allowed=mid_allowed)

        # 3. Air-Poke: rapid forward Z-impulse of index tip
        air_poke = False
        if self._prev_z is not None and feat.index_straight and not idx_pinch:
            dz = feat.pointer_z - self._prev_z
            if dz < -0.020:
                air_poke = True
        self._prev_z = feat.pointer_z

        if cluster_pinch:
            gesture = GestureType.CLUSTER_PINCH
        elif idx_pinch:
            gesture = GestureType.INDEX_PINCH
        elif mid_pinch:
            gesture = GestureType.MIDDLE_PINCH
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
            cluster_pinch=cluster_pinch,
            air_poke=air_poke,
            pointer_xy=feat.pointer_xy,
            palm_center_xy=feat.palm_center_xy,
        )
