"""Modern MediaPipe HandLandmarker (VIDEO mode) with fallback to legacy Solutions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import List, Optional

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
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
    """CPU-optimized MediaPipe HandLandmarker wrapper with temporal VIDEO tracking."""

    def __init__(self, cfg: TrackingConfig) -> None:
        self._cfg = cfg
        self._use_tasks = Path(cfg.model_path).exists()
        self._last_ts_ms = 0

        if self._use_tasks:
            base_opts = mp_python.BaseOptions(model_asset_path=cfg.model_path)
            opts = vision.HandLandmarkerOptions(
                base_options=base_opts,
                running_mode=vision.RunningMode.VIDEO,
                num_hands=cfg.max_num_hands,
                min_hand_detection_confidence=cfg.min_detection_confidence,
                min_hand_presence_confidence=cfg.min_detection_confidence,
                min_tracking_confidence=cfg.min_tracking_confidence,
            )
            self._landmarker: Optional[vision.HandLandmarker] = (
                vision.HandLandmarker.create_from_options(opts)
            )
            self._legacy_hands = None
        else:
            self._landmarker = None
            self._legacy_hands = mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=cfg.max_num_hands,
                model_complexity=cfg.model_complexity,
                min_detection_confidence=cfg.min_detection_confidence,
                min_tracking_confidence=cfg.min_tracking_confidence,
            )

    def _next_timestamp_ms(self, ts_sec: Optional[float]) -> int:
        ms = int((ts_sec if ts_sec and ts_sec > 0 else time.perf_counter()) * 1000)
        if ms <= self._last_ts_ms:
            ms = self._last_ts_ms + 1
        self._last_ts_ms = ms
        return ms

    def process(self, bgr_frame: np.ndarray, ts_sec: Optional[float] = None) -> List[TrackedHand]:
        """Run hand landmark inference on a mirrored BGR frame."""
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

        if self._use_tasks and self._landmarker is not None:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = self._next_timestamp_ms(ts_sec)
            result = self._landmarker.detect_for_video(mp_image, ts_ms)
            if not result.hand_landmarks:
                return []

            tracked: List[TrackedHand] = []
            for idx, lms in enumerate(result.hand_landmarks):
                img_pts = np.array([[lm.x, lm.y, lm.z] for lm in lms], dtype=np.float32)
                if idx < len(result.hand_world_landmarks):
                    w_pts = np.array(
                        [[lm.x, lm.y, lm.z] for lm in result.hand_world_landmarks[idx]],
                        dtype=np.float32,
                    )
                else:
                    w_pts = img_pts.copy()

                label = "Right"
                score = 1.0
                if idx < len(result.handedness) and result.handedness[idx]:
                    cat = result.handedness[idx][0]
                    label = cat.category_name or "Right"
                    score = float(cat.score)

                tracked.append(
                    TrackedHand(
                        handedness=label,
                        score=score,
                        image_landmarks=img_pts,
                        world_landmarks=w_pts,
                    )
                )
            return tracked

        # Legacy fallback
        assert self._legacy_hands is not None
        rgb.flags.writeable = False
        results = self._legacy_hands.process(rgb)
        if not results.multi_hand_landmarks:
            return []

        tracked = []
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
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
        if self._legacy_hands is not None:
            self._legacy_hands.close()
            self._legacy_hands = None
