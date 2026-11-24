"""Translates raw GestureFrames into mode-agnostic Semantic Intents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from viztool.gestures.gesture_detector import GestureFrame, GestureType


class IntentType(str, Enum):
    NO_HAND = "NO_HAND"
    POINTER_MOVE = "POINTER_MOVE"
    PRIMARY_HOLD = "PRIMARY_HOLD"
    SECONDARY_TRIGGER = "SECONDARY_TRIGGER"
    MIDDLE_TRIGGER = "MIDDLE_TRIGGER"
    SCROLL_PAN = "SCROLL_PAN"


@dataclass(frozen=True)
class IntentFrame:
    intent: IntentType
    pointer_xy: tuple[float, float]
    scroll_anchor_y: float
    gesture_label: str


def resolve_intent(gframe: Optional[GestureFrame]) -> IntentFrame:
    """Map a GestureFrame (or None when no hand is visible) to a Semantic Intent."""
    if gframe is None:
        return IntentFrame(
            intent=IntentType.NO_HAND,
            pointer_xy=(0.5, 0.5),
            scroll_anchor_y=0.5,
            gesture_label="STANDBY",
        )

    g = gframe.primary_gesture
    if g == GestureType.INDEX_PINCH:
        intent = IntentType.PRIMARY_HOLD
    elif g == GestureType.MIDDLE_PINCH:
        intent = IntentType.SECONDARY_TRIGGER
    elif g == GestureType.RING_PINCH:
        intent = IntentType.MIDDLE_TRIGGER
    elif g == GestureType.TWO_FINGER_SCROLL:
        intent = IntentType.SCROLL_PAN
    else:
        intent = IntentType.POINTER_MOVE

    return IntentFrame(
        intent=intent,
        pointer_xy=gframe.pointer_xy,
        scroll_anchor_y=gframe.palm_center_xy[1],
        gesture_label=g.value,
    )
