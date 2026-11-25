"""Interaction mode definitions for VizTool."""

from __future__ import annotations

from enum import Enum


class AppMode(str, Enum):
    MOUSE = "MOUSE"
    MEDIA = "MEDIA"
    KEYBOARD = "KEYBOARD"
    LASER = "LASER"


RADIAL_SLICES = (
    AppMode.MOUSE,     # Top (angle ~ -90 deg)
    AppMode.MEDIA,     # Right (angle ~ 0 deg)
    AppMode.KEYBOARD,  # Bottom (angle ~ +90 deg)
    AppMode.LASER,     # Left (angle ~ 180 deg)
)
