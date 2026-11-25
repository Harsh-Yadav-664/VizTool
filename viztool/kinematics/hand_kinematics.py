"""3D orientation- and scale-invariant hand kinematics with biomechanical curl guards."""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from viztool.tracking.hand_tracker import TrackedHand


@dataclass(frozen=True)
class HandFeatures:
    """Rotation- and distance-invariant geometric features for one hand."""

    handedness: str
    palm_size_3d: float
    pointer_xy: tuple[float, float]       # Stable knuckle anchor in [0..1] image coords
    pointer_z: float                      # Metric Z of index fingertip
    palm_center_xy: tuple[float, float]
    landmarks_2d: np.ndarray              # shape (21, 2) normalized [0..1] for translucent HUD

    # Normalized 3D pinch ratios (distance / palm_size_3d)
    thumb_index_ratio: float
    thumb_middle_ratio: float
    thumb_ring_ratio: float
    thumb_pinky_ratio: float

    # Biomechanical curl guards: True only if finger is reaching out, NOT tucked into palm
    index_reaching: bool
    middle_reaching: bool
    ring_reaching: bool

    # 3D joint extension states (orientation-invariant)
    thumb_straight: bool
    index_straight: bool
    middle_straight: bool
    ring_straight: bool
    pinky_straight: bool


def _angle_deg(v1: np.ndarray, v2: np.ndarray) -> float:
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    cos_theta = float(np.dot(v1, v2) / (n1 * n2))
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return float(np.degrees(np.arccos(cos_theta)))


def _is_finger_straight_3d(pts: np.ndarray, mcp: int, pip: int, dip: int, tip: int) -> bool:
    """Check if a finger is extended in 3D space regardless of hand rotation."""
    v1 = pts[pip] - pts[mcp]
    v2 = pts[dip] - pts[pip]
    v3 = pts[tip] - pts[dip]
    a1 = _angle_deg(v1, v2)
    a2 = _angle_deg(v2, v3)
    return (a1 + a2) < 62.0


def _is_finger_reaching(pts: np.ndarray, mcp: int, tip: int, palm_size: float) -> bool:
    """Guard against closed-fist/curled-finger false pinches.

    A finger curled into the palm sits close to the wrist/MCP; a finger reaching
    to pinch the thumb stays noticeably farther from wrist than its MCP knuckle.
    """
    wrist_to_mcp = float(np.linalg.norm(pts[mcp] - pts[0]))
    wrist_to_tip = float(np.linalg.norm(pts[tip] - pts[0]))
    mcp_to_tip = float(np.linalg.norm(pts[tip] - pts[mcp]))
    return wrist_to_tip > wrist_to_mcp * 1.12 and mcp_to_tip > palm_size * 0.45


def _weighted_pinch_ratio(p1: np.ndarray, p2: np.ndarray, palm_size: float) -> float:
    """3D distance with dampened Z-noise for reliable pinching at any tilt angle."""
    dx = float(p1[0] - p2[0])
    dy = float(p1[1] - p2[1])
    dz = float(p1[2] - p2[2]) * 0.40
    return math.sqrt(dx * dx + dy * dy + dz * dz) / palm_size


def extract_hand_features(hand: TrackedHand) -> HandFeatures:
    """Convert raw 21 landmarks into 3D rotation- & scale-invariant HandFeatures."""
    w = hand.world_landmarks
    img = hand.image_landmarks

    palm_size = float(np.linalg.norm(w[9] - w[0]))
    if palm_size < 1e-4:
        palm_size = 0.08

    thumb_tip = w[4]
    ti_ratio = _weighted_pinch_ratio(thumb_tip, w[8], palm_size)
    tm_ratio = _weighted_pinch_ratio(thumb_tip, w[12], palm_size)
    tr_ratio = _weighted_pinch_ratio(thumb_tip, w[16], palm_size)
    tp_ratio = _weighted_pinch_ratio(thumb_tip, w[20], palm_size)

    index_reaching = _is_finger_reaching(w, 5, 8, palm_size)
    middle_reaching = _is_finger_reaching(w, 9, 12, palm_size)
    ring_reaching = _is_finger_reaching(w, 13, 16, palm_size)

    thumb_straight = _angle_deg(w[2] - w[1], w[4] - w[3]) < 45.0
    index_straight = _is_finger_straight_3d(w, 5, 6, 7, 8)
    middle_straight = _is_finger_straight_3d(w, 9, 10, 11, 12)
    ring_straight = _is_finger_straight_3d(w, 13, 14, 15, 16)
    pinky_straight = _is_finger_straight_3d(w, 17, 18, 19, 20)

    # Knuckle Anchor (Index MCP 5 + Middle MCP 9)
    px = float(0.60 * img[5, 0] + 0.40 * img[9, 0])
    py = float(0.60 * img[5, 1] + 0.40 * img[9, 1])
    pz = float(w[8, 2])
    cx, cy = float(img[9, 0]), float(img[9, 1])

    return HandFeatures(
        handedness=hand.handedness,
        palm_size_3d=palm_size,
        pointer_xy=(px, py),
        pointer_z=pz,
        palm_center_xy=(cx, cy),
        landmarks_2d=img[:, :2].copy(),
        thumb_index_ratio=ti_ratio,
        thumb_middle_ratio=tm_ratio,
        thumb_ring_ratio=tr_ratio,
        thumb_pinky_ratio=tp_ratio,
        index_reaching=index_reaching,
        middle_reaching=middle_reaching,
        ring_reaching=ring_reaching,
        thumb_straight=thumb_straight,
        index_straight=index_straight,
        middle_straight=middle_straight,
        ring_straight=ring_straight,
        pinky_straight=pinky_straight,
    )
