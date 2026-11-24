"""Unit tests for VizTool Phase 1 core pipeline (no webcam required)."""

import unittest
from unittest.mock import MagicMock

import numpy as np

from viztool.config import GestureConfig, KinematicsConfig, load_config
from viztool.gestures.gesture_detector import GestureDetector, GestureType, SchmittTrigger
from viztool.intent.intent_resolver import IntentType, resolve_intent
from viztool.kinematics.coordinate_mapper import CoordinateMapper
from viztool.kinematics.hand_kinematics import extract_hand_features
from viztool.kinematics.one_euro_filter import OneEuroFilter
from viztool.state.state_machine import InteractionState, InteractionStateMachine
from viztool.tracking.hand_tracker import TrackedHand


def _make_straight_hand_world() -> np.ndarray:
    """Create a synthetic 21x3 open hand in metric world coordinates."""
    pts = np.zeros((21, 3), dtype=np.float32)
    # Wrist at (0,0,0), Middle MCP at (0, -0.08, 0) -> palm_size = 0.08
    pts[0] = [0.0, 0.0, 0.0]
    # Thumb
    pts[1] = [-0.02, -0.02, 0.0]
    pts[2] = [-0.04, -0.04, 0.0]
    pts[3] = [-0.05, -0.06, 0.0]
    pts[4] = [-0.06, -0.08, 0.0]
    # Index
    pts[5] = [-0.03, -0.08, 0.0]
    pts[6] = [-0.03, -0.11, 0.0]
    pts[7] = [-0.03, -0.13, 0.0]
    pts[8] = [-0.03, -0.15, 0.0]
    # Middle
    pts[9] = [0.0, -0.08, 0.0]
    pts[10] = [0.0, -0.12, 0.0]
    pts[11] = [0.0, -0.14, 0.0]
    pts[12] = [0.0, -0.16, 0.0]
    # Ring
    pts[13] = [0.025, -0.08, 0.0]
    pts[14] = [0.025, -0.11, 0.0]
    pts[15] = [0.025, -0.13, 0.0]
    pts[16] = [0.025, -0.15, 0.0]
    # Pinky
    pts[17] = [0.045, -0.075, 0.0]
    pts[18] = [0.045, -0.10, 0.0]
    pts[19] = [0.045, -0.115, 0.0]
    pts[20] = [0.045, -0.13, 0.0]
    return pts


class TestVizToolCore(unittest.TestCase):
    def test_config_loads(self) -> None:
        cfg = load_config("config.json")
        self.assertEqual(cfg.camera.width, 640)
        self.assertEqual(cfg.tracking.model_complexity, 0)

    def test_one_euro_filter_suppresses_jitter(self) -> None:
        f = OneEuroFilter(min_cutoff=1.0, beta=0.007)
        t = 0.0
        outputs = []
        # Oscillating +/-0.01 jitter around 0.5
        for i in range(30):
            t += 1.0 / 30.0
            noisy = 0.5 + (0.01 if i % 2 == 0 else -0.01)
            outputs.append(f.filter(t, noisy))
        # Filtered variance should be far smaller than input amplitude
        self.assertLess(max(outputs[-10:]) - min(outputs[-10:]), 0.006)

    def test_3d_kinematics_rotation_invariant(self) -> None:
        w = _make_straight_hand_world()
        img = np.full((21, 3), 0.5, dtype=np.float32)

        # Rotate hand 90 degrees around Z and 45 degrees around X
        rot_z = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=np.float32)
        c, s = np.cos(np.pi / 4), np.sin(np.pi / 4)
        rot_x = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)
        w_rot = (w @ rot_z.T) @ rot_x.T

        f_orig = extract_hand_features(TrackedHand("Right", 0.99, img, w))
        f_rot = extract_hand_features(TrackedHand("Right", 0.99, img, w_rot))

        self.assertTrue(f_orig.index_straight)
        self.assertTrue(f_rot.index_straight)
        self.assertAlmostEqual(f_orig.thumb_index_ratio, f_rot.thumb_index_ratio, places=4)

    def test_schmitt_trigger_prevents_bounce(self) -> None:
        trig = SchmittTrigger(enter_thresh=0.30, exit_thresh=0.42)
        self.assertFalse(trig.update(0.35))  # Not entered yet
        self.assertTrue(trig.update(0.28))   # Entered
        # Fluctuates around 0.35 (boundary noise) -> stays active, NO bounce!
        self.assertTrue(trig.update(0.33))
        self.assertTrue(trig.update(0.39))
        self.assertFalse(trig.update(0.45))  # Clean exit

    def test_pinch_anchor_and_single_click_no_multiclick(self) -> None:
        cfg = GestureConfig(drag_hold_sec=0.25, click_cooldown_sec=0.1)
        mapper = CoordinateMapper(KinematicsConfig(deadzone_px=0.0), (0, 0, 1920, 1080))
        backend = MagicMock()
        sm = InteractionStateMachine(cfg, mapper, backend)

        # Hover at (0.5, 0.5)
        sm.step(1.00, resolve_intent(None))  # start idle
        hover = resolve_intent(
            MagicMock(
                primary_gesture=GestureType.HOVER,
                pointer_xy=(0.5, 0.5),
                palm_center_xy=(0.5, 0.5),
            )
        )
        fb1 = sm.step(1.10, hover)
        self.assertEqual(fb1.state, InteractionState.HOVER)
        anchored_pos = fb1.cursor_px

        # Pinch held for 3 frames while finger drifts to (0.55, 0.55)
        for dt in (1.13, 1.16, 1.19):
            pinch = resolve_intent(
                MagicMock(
                    primary_gesture=GestureType.INDEX_PINCH,
                    pointer_xy=(0.55, 0.55),
                    palm_center_xy=(0.5, 0.5),
                )
            )
            fb_p = sm.step(dt, pinch)
            self.assertEqual(fb_p.state, InteractionState.PINCH_LOCK)
            # Cursor MUST stay frozen at anchored_pos!
            self.assertEqual(fb_p.cursor_px, anchored_pos)

        # Still 0 clicks fired while held
        backend.mouse_click.assert_not_called()

        # Release before drag_hold_sec -> fires EXACTLY ONE left click
        fb_rel = sm.step(1.22, hover)
        self.assertEqual(fb_rel.clicked_event, "LEFT")
        backend.mouse_click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
