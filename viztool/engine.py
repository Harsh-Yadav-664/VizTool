"""Main VizTool pipeline orchestrator with Adaptive Power Governor, Tray, MiniWidget & Keyboard."""

from __future__ import annotations

from dataclasses import replace
import time

from viztool.backends.win32_input import Win32InputBackend
from viztool.capture.camera_stream import CameraStream
from viztool.config import VizConfig, load_config
from viztool.gestures.gesture_detector import GestureDetector
from viztool.intent.intent_resolver import resolve_intent
from viztool.kinematics.coordinate_mapper import CoordinateMapper
from viztool.kinematics.hand_kinematics import extract_hand_features
from viztool.modes.mode_types import AppMode, RADIAL_SLICES
from viztool.state.state_machine import InteractionState, InteractionStateMachine, StateFeedback
from viztool.tracking.hand_tracker import HandTracker
from viztool.ui.keyboard_overlay import VirtualKeyboardOverlay
from viztool.ui.mini_widget import CornerMiniWidget
from viztool.ui.overlay import TranslucentOverlay
from viztool.ui.settings_window import open_settings_window
from viztool.ui.tray import VizTray


class VizToolEngine:
    """Connects all pipeline layers with zero-camera-window execution."""

    def __init__(self, cfg: VizConfig) -> None:
        self._cfg = cfg
        self._camera = CameraStream(cfg.camera)
        self._tracker = HandTracker(cfg.tracking)
        self._backend = Win32InputBackend()
        self._mapper = CoordinateMapper(
            cfg.kinematics, self._backend.get_virtual_screen_bounds()
        )
        self._detector = GestureDetector(cfg.gestures)
        self._keyboard = VirtualKeyboardOverlay(
            self._backend, on_hide=self._on_keyboard_hide
        )
        self._state_machine = InteractionStateMachine(
            cfg.gestures,
            self._mapper,
            self._backend,
            on_mode_changed=self._on_mode_changed,
            is_point_on_keyboard=self._keyboard.contains_point,
        )
        self._overlay = TranslucentOverlay(cfg.ui)
        self._mini_widget = (
            CornerMiniWidget(
                on_cycle_mode=self.cycle_mode,
                on_open_settings=self.open_settings,
            )
            if cfg.ui.show_status_pill
            else None
        )
        self._tray = (
            VizTray(
                on_toggle_pause=self.toggle_pause,
                on_toggle_mode=self.toggle_tracking_mode,
                on_open_settings=self.open_settings,
                on_exit=self.request_stop,
            )
            if cfg.ui.tray_enabled
            else None
        )
        self._running = False
        self._paused = False

    def _on_mode_changed(self, mode: AppMode) -> None:
        self._keyboard.set_visible(mode == AppMode.KEYBOARD)

    def _on_keyboard_hide(self) -> None:
        self._state_machine.set_mode(AppMode.MOUSE)

    def cycle_mode(self) -> None:
        cur = self._state_machine.mode
        idx = (RADIAL_SLICES.index(cur) + 1) % len(RADIAL_SLICES) if cur in RADIAL_SLICES else 0
        self._state_machine.set_mode(RADIAL_SLICES[idx])

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        self._camera.set_idle_mode(self._paused)
        if self._paused:
            fb = StateFeedback(
                state=InteractionState.SLEEP_IDLE,
                mode=self._state_machine.mode,
                cursor_px=(0, 0),
                gesture_label="PAUSED",
            )
            self._overlay.update(fb)
            if self._mini_widget is not None:
                self._mini_widget.update(fb)
        return self._paused

    def toggle_tracking_mode(self) -> str:
        cur = self._cfg.kinematics.tracking_mode
        nxt = "absolute" if cur == "relative" else "relative"
        self._cfg.kinematics.tracking_mode = nxt
        self._mapper.reset()
        return nxt

    def request_stop(self) -> None:
        self._running = False

    def open_settings(self) -> None:
        open_settings_window(self._cfg, on_applied=self._apply_live_settings)

    def _apply_live_settings(self) -> None:
        self._mapper = CoordinateMapper(
            self._cfg.kinematics, self._backend.get_virtual_screen_bounds()
        )
        self._detector = GestureDetector(self._cfg.gestures)
        self._state_machine._mapper = self._mapper
        self._state_machine._cfg = self._cfg.gestures

    def run(self) -> None:
        """Start camera, overlays, mini-widget, tray, and processing loop."""
        self._camera.start()
        self._overlay.start()
        self._keyboard.start()
        if self._mini_widget is not None:
            self._mini_widget.start()
        if self._tray is not None:
            self._tray.start()
        self._running = True

        last_hand_seen = time.perf_counter()
        is_idle = False

        print(f"VizTool active ({self._cfg.kinematics.tracking_mode} mode, headless).")
        print("Pinky+Thumb Pinch = Iron-Man Radial Menu | System Tray / Ctrl+C to stop.")

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
                    landmarks_tuple = (primary_feat.landmarks_2d,)
                    if len(hands) > 1:
                        sec_feat = extract_hand_features(hands[1])
                        sec_g = self._detector.detect(sec_feat)
                        landmarks_tuple = (primary_feat.landmarks_2d, sec_feat.landmarks_2d)
                    intent = resolve_intent(primary_g, sec_g)
                else:
                    self._detector.reset()
                    landmarks_tuple = ()
                    intent = resolve_intent(None)
                    if not is_idle and (now - last_hand_seen) >= self._cfg.camera.idle_timeout_sec:
                        is_idle = True
                        self._camera.set_idle_mode(True)

                feedback = replace(
                    self._state_machine.step(now, intent),
                    hand_landmarks_2d=landmarks_tuple,
                )
                self._overlay.update(feedback)
                if self._mini_widget is not None:
                    self._mini_widget.update(feedback)
                if feedback.mode == AppMode.KEYBOARD:
                    self._keyboard.update_cursor(
                        feedback.cursor_px,
                        pinched_click=(feedback.clicked_event == "KEY_PINCH"),
                    )
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        if self._tray is not None:
            self._tray.stop()
        if self._mini_widget is not None:
            self._mini_widget.stop()
        self._keyboard.stop()
        self._overlay.stop()
        self._camera.stop()
        self._tracker.close()


def main() -> None:
    cfg = load_config("config.json")
    engine = VizToolEngine(cfg)
    engine.run()
