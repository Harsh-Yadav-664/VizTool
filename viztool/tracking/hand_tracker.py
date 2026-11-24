"""Lightweight MediaPipe hand landmark tracker outputting 2D & 3D world points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import cv2
import mediapipe as mp
import numpy as np

from viztool.config import TrackingConfig


@dataclass(frozen=True)
class TrackedHand:
    """Normalized image landmarks (21x3) and metric 3D world landmarks (21x3)."""

    handedness: str  # "Left" or "Right"
    score: float
    image_landmarks: np.ndarray  # shape (21, 3) normalized [0..1]
    world_landmarks: np.ndarray  # shape (21, 3) metric meters centered at wrist


class HandTracker:
    """CPU-optimized MediaPipe Hands wrapper (model_complexity=0 by default)."""

    def __init__(self, cfg: TrackingConfig) -> None:
        self._mp_hands = mp.solutions.hands
        self._hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.max_num_hands,
            model_complexity=cfg.model_complexity,
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )

    def process(self, bgr_frame: np.ndarray) -> List[TrackedHand]:
        """Run hand landmark inference on a mirrored BGR frame."""
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)

        if not results.multi_hand_landmarks:
            return []

        tracked: List[TrackedHand] = []
        world_list = results.multi_hand_world_landmarks or []
        handed_list = results.multi_handedness or []

        for idx, hand_lms in enumerate(results.multi_hand_landmarks):
            img_pts = np.array([[lm.x, lm.y, lm.z] for lm in hand_lms.landmark], dtype=np.float32)

            if idx < len(world_list):
                w_pts = np.array(
                    [[lm.x, lm.y, lm.z] for lm in world_list[idx].landmark],
                    dtype=np.float32,
                )
            else:
                w_pts = img_pts.copy()

            label = "Right"
            score = 1.0
            if idx < len(handed_list) and handed_list[idx].classification:
                cls = handed_list[idx].classification[0]
                label = cls.label
                score = float(cls.score)

            tracked.append(
                TrackedHand(
                    handedness=label,
                    score=score,
                    image_landmarks=img_pts,
                    world_landmarks=w_pts,
                )
            )

        return tracked

    def close(self) -> None:
        self._hands.close()
