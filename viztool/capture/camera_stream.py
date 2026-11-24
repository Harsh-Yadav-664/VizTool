"""Threaded DirectShow camera capture with size-1 buffer and power governor."""

from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from viztool.config import CameraConfig


class CameraStream:
    """Non-blocking threaded webcam reader optimized for low CPU and zero queue lag."""

    def __init__(self, cfg: CameraConfig) -> None:
        self._cfg = cfg
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Adaptive Power Governor state
        self._is_idle = False

    def start(self) -> None:
        """Open camera via DirectShow and start background capture thread."""
        if self._running:
            return

        # CAP_DSHOW avoids Windows MSMF initialization & buffering stalls
        cap = cv2.VideoCapture(self._cfg.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(self._cfg.index)
        if not cap.isOpened():
            raise RuntimeError(f"Unable to open camera index {self._cfg.index}")

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cfg.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FPS, self._cfg.active_fps)

        self._cap = cap
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="VizCamCapture")
        self._thread.start()

    def stop(self) -> None:
        """Stop capture thread and release webcam."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def set_idle_mode(self, idle: bool) -> None:
        """Throttle capture polling when no hand is present to save CPU."""
        self._is_idle = idle

    def _capture_loop(self) -> None:
        assert self._cap is not None
        while self._running:
            target_fps = self._cfg.idle_fps if self._is_idle else self._cfg.active_fps
            frame_interval = 1.0 / max(1, target_fps)
            t0 = time.perf_counter()

            ok, frame = self._cap.read()
            if ok and frame is not None:
                # Mirror horizontally once here so all downstream layers stay consistent
                mirrored = cv2.flip(frame, 1)
                now = time.perf_counter()
                with self._lock:
                    self._latest_frame = mirrored
                    self._latest_ts = now
                self._frame_event.set()

            elapsed = time.perf_counter() - t0
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

    def read_latest(self, timeout: float = 0.1) -> Tuple[Optional[np.ndarray], float]:
        """Wait for and return the newest mirrored BGR frame and its timestamp."""
        if not self._frame_event.wait(timeout=timeout):
            return None, 0.0
        self._frame_event.clear()
        with self._lock:
            return self._latest_frame, self._latest_ts
