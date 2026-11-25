"""Translates raw GestureFrames (1 or 2 hands) into Semantic Intents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Optional

from viztool.gestures.gesture_detector import GestureFrame, GestureType


class IntentType(str, Enum):
    NO_HAND = "NO_HAND"
    POINTER_MOVE = "POINTER_MOVE"
    CLUTCH_PAUSE = "CLUTCH_PAUSE"
    PRIMARY_HOLD = "PRIMARY_HOLD"
    SECONDARY_TRIGGER = "SECONDARY_TRIGGER"
    MIDDLE_TRIGGER = "MIDDLE_TRIGGER"
    RADIAL_HOLD = "RADIAL_HOLD"
    SCROLL_PAN = "SCROLL_PAN"
    PALM_READY = "PALM_READY"
    FIST_ACTIVATE = "FIST_ACTIVATE"
    BIMANUAL_ZOOM = "BIMANUAL_ZOOM"


@dataclass(frozen=True)
class IntentFrame:
    intent: IntentType
    pointer_xy: tuple[float, float]
    scroll_anchor_y: float
    gesture_label: str
    secondary_open_palm: bool = False
    bimanual_span: float = 0.0
    air_poke: bool = False


def resolve_intent(
    primary: Optional[GestureFrame],
    secondary: Optional[GestureFrame] = None,
) -> IntentFrame:
    """Map primary (+ optional secondary modifier hand) to a Semantic Intent."""
    if primary is None:
        return IntentFrame(
            intent=IntentType.NO_HAND,
            pointer_xy=(0.5, 0.5),
            scroll_anchor_y=0.5,
            gesture_label="STANDBY",
        )

    sec_open = secondary is not None and secondary.primary_gesture == GestureType.OPEN_PALM

    # Bimanual Zoom: both hands pinching index+thumb
    if (
        secondary is not None
        and primary.index_pinch
        and secondary.index_pinch
    ):
        span = math.hypot(
            primary.palm_center_xy[0] - secondary.palm_center_xy[0],
            primary.palm_center_xy[1] - secondary.palm_center_xy[1],
        )
        return IntentFrame(
            intent=IntentType.BIMANUAL_ZOOM,
            pointer_xy=primary.pointer_xy,
            scroll_anchor_y=primary.palm_center_xy[1],
            gesture_label="ZOOM",
            secondary_open_palm=sec_open,
            bimanual_span=span,
        )

    g = primary.primary_gesture
    if g == GestureType.INDEX_PINCH:
        intent = IntentType.PRIMARY_HOLD
    elif g == GestureType.MIDDLE_PINCH:
        intent = IntentType.SECONDARY_TRIGGER
    elif g == GestureType.CLUSTER_PINCH:
        intent = IntentType.RADIAL_HOLD
    elif g == GestureType.TWO_FINGER_SCROLL:
        intent = IntentType.SCROLL_PAN
    elif g == GestureType.OPEN_PALM:
        intent = IntentType.PALM_READY
    elif g == GestureType.FIST:
        intent = IntentType.FIST_ACTIVATE
    else:
        intent = IntentType.POINTER_MOVE

    return IntentFrame(
        intent=intent,
        pointer_xy=primary.pointer_xy,
        scroll_anchor_y=primary.palm_center_xy[1],
        gesture_label=g.value,
        secondary_open_palm=sec_open,
        air_poke=bool(getattr(primary, "air_poke", False)),
    )
