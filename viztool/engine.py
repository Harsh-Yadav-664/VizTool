"""Main VizTool pipeline orchestrator with Adaptive Power Governor & System Tray."""

from __future__ import annotations

import time

from viztool.backends.win32_input import Win32InputBackend
from viztool.capture.camera_stream import CameraStream
from viztool.config import VizConfig, load_config
from viztool.gestures.gesture_detector import GestureDetector
from viztool.intent.intent_resolver import resolve_intent
from viztool.kinematics.coordinate_mapper import CoordinateMapper
from viztool.kinematics.hand_kinematics import extract_hand_features
from viztool.state.state_machine import InteractionState, InteractionStateMachine, StateFeedback
from viztool.tracking.hand_tracker import HandTracker
from viztool.ui.overlay import TranslucentOverlay
from viztool.ui.tray import VizTray


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
        self._tray = (
            VizTray(
                on_toggle_pause=self.toggle_pause,
                on_toggle_mode=self.toggle_tracking_mode,
                on_exit=self.request_stop,
            )
            if cfg.ui.tray_enabled
            else None
        )
        self._running = False
        self._paused = False

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        self._camera.set_idle_mode(self._paused)
        if self._paused:
            self._overlay.update(
                StateFeedback(
                    state=InteractionState.SLEEP_IDLE,
                    cursor_px=(0, 0),
                    gesture_label="PAUSED",
                )
            )
        return self._paused

    def toggle_tracking_mode(self) -> str:
        cur = self._cfg.kinematics.tracking_mode
        nxt = "absolute" if cur == "relative" else "relative"
        self._cfg.kinematics.tracking_mode = nxt
        self._mapper.reset()
        return nxt

    def request_stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """Start camera, overlay, tray, and main processing loop until interrupted."""
        self._camera.start()
        self._overlay.start()
        if self._tray is not None:
            self._tray.start()
        self._running = True

        last_hand_seen = time.perf_counter()
        is_idle = False

        print(f"VizTool active ({self._cfg.kinematics.tracking_mode} mode, headless).")
        print("Use the System Tray icon or press Ctrl+C in this terminal to stop.")

        try:
            while self._running:
                if self._paused:
                    time.sleep(0.15)
                    continue

                frame, ts = self._camera.read_latest(timeout=0.25)
                if frame is None:
                    continue

                hands = self._tracker.process(frame, ts)
                now = ts if ts > 0 else time.perf_counter()

                if hands:
                    last_hand_seen = now
                    if is_idle:
                        is_idle = False
                        self._camera.set_idle_mode(False)

                    primary_feat = extract_hand_features(hands[0])
                    primary_g = self._detector.detect(primary_feat)
                    sec_g = None
                    if len(hands) > 1:
                        sec_feat = extract_hand_features(hands[1])
                        sec_g = self._detector.detect(sec_feat)
                    intent = resolve_intent(primary_g, sec_g)
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
        if self._tray is not None:
            self._tray.stop()
        self._overlay.stop()
        self._camera.stop()
        self._tracker.close()


def main() -> None:
    cfg = load_config("config.json")
    engine = VizToolEngine(cfg)
    engine.run()
