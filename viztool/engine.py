"""Main VizTool pipeline orchestrator with Adaptive Power Governor."""

from __future__ import annotations

import time

from viztool.backends.win32_input import Win32InputBackend
from viztool.capture.camera_stream import CameraStream
from viztool.config import VizConfig, load_config
from viztool.gestures.gesture_detector import GestureDetector
from viztool.intent.intent_resolver import resolve_intent
from viztool.kinematics.coordinate_mapper import CoordinateMapper
from viztool.kinematics.hand_kinematics import extract_hand_features
from viztool.state.state_machine import InteractionStateMachine
from viztool.tracking.hand_tracker import HandTracker
from viztool.ui.overlay import TranslucentOverlay


class VizToolEngine:
    """Connects all 9 pipeline layers with zero-camera-window execution."""

    def __init__(self, cfg: VizConfig) -> None:
        self._cfg = cfg
        self._camera = CameraStream(cfg.camera)
        self._tracker = HandTracker(cfg.tracking)
        self._backend = Win32InputBackend()
        self._mapper = CoordinateMapper(
            cfg.kinematics, self._backend.get_virtual_screen_bounds()
        )
        self._detector = GestureDetector(cfg.gestures)
        self._state_machine = InteractionStateMachine(
            cfg.gestures, self._mapper, self._backend
        )
        self._overlay = TranslucentOverlay(cfg.ui)
        self._running = False

    def run(self) -> None:
        """Start camera, overlay, and main processing loop until interrupted."""
        self._camera.start()
        self._overlay.start()
        self._running = True

        last_hand_seen = time.perf_counter()
        is_idle = False

        print("VizTool Phase 1 Engine active (headless mode, no camera window).")
        print("Press Ctrl+C in this terminal to stop.")

        try:
            while self._running:
                frame, ts = self._camera.read_latest(timeout=0.25)
                if frame is None:
                    continue

                hands = self._tracker.process(frame)
                now = ts if ts > 0 else time.perf_counter()

                if hands:
                    last_hand_seen = now
                    if is_idle:
                        is_idle = False
                        self._camera.set_idle_mode(False)

                    # Primary hand (first detected; bimanual chord added in Phase 3)
                    features = extract_hand_features(hands[0])
                    gframe = self._detector.detect(features)
                    intent = resolve_intent(gframe)
                else:
                    self._detector.reset()
                    intent = resolve_intent(None)
                    if not is_idle and (now - last_hand_seen) >= self._cfg.camera.idle_timeout_sec:
                        is_idle = True
                        self._camera.set_idle_mode(True)

                feedback = self._state_machine.step(now, intent)
                self._overlay.update(feedback)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self._overlay.stop()
        self._camera.stop()
        self._tracker.close()


def main() -> None:
    cfg = load_config("config.json")
    engine = VizToolEngine(cfg)
    engine.run()
