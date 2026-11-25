"""Edge-triggered state machine with Pinch-Anchor, Clutch, and Iron-Man shortcuts."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

from viztool.backends.win32_input import MouseButton, Win32InputBackend
from viztool.config import GestureConfig
from viztool.intent.intent_resolver import IntentFrame, IntentType
from viztool.kinematics.coordinate_mapper import CoordinateMapper


class InteractionState(str, Enum):
    SLEEP_IDLE = "SLEEP_IDLE"
    HOVER = "HOVER"
    CLUTCH = "CLUTCH"
    PINCH_LOCK = "PINCH_LOCK"
    DRAGGING = "DRAGGING"
    SCROLLING = "SCROLLING"
    ZOOMING = "ZOOMING"


@dataclass(frozen=True)
class StateFeedback:
    """Visual state emitted to the translucent overlay each tick."""

    state: InteractionState
    cursor_px: tuple[int, int]
    gesture_label: str
    clicked_event: Optional[str] = None  # "LEFT", "RIGHT", "MIDDLE", "MINIMIZE", "CLOSE", "BLOCKED"


class InteractionStateMachine:
    """Prevents double-click bounce, cursor drift, and handles Iron-Man window gestures."""

    def __init__(
        self,
        cfg: GestureConfig,
        mapper: CoordinateMapper,
        backend: Win32InputBackend,
    ) -> None:
        self._cfg = cfg
        self._mapper = mapper
        self._backend = backend

        self.state = InteractionState.SLEEP_IDLE
        self._cursor_px: tuple[int, int] = (0, 0)
        self._hover_history: Deque[tuple[int, int]] = deque(maxlen=5)
        self._pinch_start_t: float = 0.0
        self._anchor_px: tuple[int, int] = (0, 0)
        self._last_click_t: float = -10.0

        # Edge-trigger latches
        self._prev_secondary = False
        self._prev_middle = False
        self._prev_fist = False

        # Open-palm -> Fist window gesture timer
        self._palm_ready_until: float = 0.0
        self._last_window_cmd_t: float = -10.0

        # Scroll & Bimanual zoom tracking
        self._prev_scroll_y: Optional[float] = None
        self._prev_zoom_span: Optional[float] = None

    def _can_click(self, now: float) -> bool:
        return (now - self._last_click_t) >= self._cfg.click_cooldown_sec

    def step(self, now: float, intent_frame: IntentFrame) -> StateFeedback:
        intent = intent_frame.intent
        clicked_event: Optional[str] = None

        # Hand lost -> release any active drag cleanly
        if intent == IntentType.NO_HAND:
            if self.state == InteractionState.DRAGGING:
                self._backend.mouse_up(MouseButton.LEFT)
            self.state = InteractionState.SLEEP_IDLE
            self._hover_history.clear()
            self._prev_secondary = False
            self._prev_middle = False
            self._prev_fist = False
            self._prev_scroll_y = None
            self._prev_zoom_span = None
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="STANDBY",
            )

        # Wake from sleep -> sync with OS cursor and reset filter (zero jump)
        if self.state == InteractionState.SLEEP_IDLE:
            try:
                cur = self._backend.get_cursor_pos()
                self._mapper.set_cursor_px(*cur)
                self._cursor_px = cur
            except Exception:
                pass
            self._mapper.reset()
            self.state = InteractionState.HOVER

        # --- Iron-Man Bimanual Zoom ---
        if intent == IntentType.BIMANUAL_ZOOM:
            self.state = InteractionState.ZOOMING
            if self._prev_zoom_span is not None:
                d_span = intent_frame.bimanual_span - self._prev_zoom_span
                if abs(d_span) > 0.008:
                    self._backend.ctrl_scroll(int(d_span * 1800))
            self._prev_zoom_span = intent_frame.bimanual_span
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="2-HAND ZOOM",
            )
        self._prev_zoom_span = None

        # --- Open Palm -> Fist (Minimize / Bimanual Close) + Fist Clutch ---
        if intent == IntentType.PALM_READY:
            self._palm_ready_until = now + self._cfg.palm_fist_window_sec
            self._prev_fist = False
            # Open palm also acts as a comfortable pause/clutch so cursor stays still
            self._mapper.reset()
            self.state = InteractionState.CLUTCH
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="PALM READY" + (" (+2ND)" if intent_frame.secondary_open_palm else ""),
            )

        if intent == IntentType.FIST_ACTIVATE:
            is_rising_fist = not self._prev_fist
            self._prev_fist = True
            if is_rising_fist and now <= self._palm_ready_until and (now - self._last_window_cmd_t) > 1.2:
                self._palm_ready_until = 0.0
                self._last_window_cmd_t = now
                if intent_frame.secondary_open_palm:
                    closed = self._backend.close_foreground_window(self._cfg.protected_apps)
                    clicked_event = "CLOSE" if closed else "BLOCKED"
                else:
                    self._backend.minimize_foreground_window()
                    clicked_event = "MINIMIZE"

            # Fist acts as Trackpad Clutch (re-center your hand comfortably!)
            self._mapper.reset()
            self.state = InteractionState.CLUTCH
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="CLUTCH",
                clicked_event=clicked_event,
            )
        self._prev_fist = False

        # Re-entering hover from Clutch resets filter cleanly
        if self.state == InteractionState.CLUTCH:
            self._mapper.reset()
            self.state = InteractionState.HOVER

        # Update smoothed pointer coordinates
        mapped_px = self._mapper.map_to_screen(
            now, intent_frame.pointer_xy[0], intent_frame.pointer_xy[1]
        )

        # --- Secondary & Middle clicks: strict rising-edge triggers ---
        is_sec = intent == IntentType.SECONDARY_TRIGGER
        if is_sec and not self._prev_secondary and self._can_click(now):
            self._backend.mouse_click(MouseButton.RIGHT)
            self._last_click_t = now
            clicked_event = "RIGHT"
        self._prev_secondary = is_sec

        is_mid = intent == IntentType.MIDDLE_TRIGGER
        if is_mid and not self._prev_middle and self._can_click(now):
            self._backend.mouse_click(MouseButton.MIDDLE)
            self._last_click_t = now
            clicked_event = "MIDDLE"
        self._prev_middle = is_mid

        # --- Primary Pinch: Pinch-Anchor Lock + Click vs Drag ---
        if intent == IntentType.PRIMARY_HOLD:
            self._prev_scroll_y = None
            if self.state in (InteractionState.HOVER, InteractionState.SCROLLING):
                if self._hover_history:
                    self._anchor_px = self._hover_history[0]
                else:
                    self._anchor_px = self._cursor_px if self._cursor_px != (0, 0) else mapped_px
                self._pinch_start_t = now
                self.state = InteractionState.PINCH_LOCK
            elif self.state == InteractionState.PINCH_LOCK:
                if (now - self._pinch_start_t) >= self._cfg.drag_hold_sec:
                    self._backend.mouse_down(MouseButton.LEFT)
                    self.state = InteractionState.DRAGGING
                    self._cursor_px = mapped_px
                    self._backend.move_cursor_abs(*self._cursor_px)
            elif self.state == InteractionState.DRAGGING:
                self._cursor_px = mapped_px
                self._backend.move_cursor_abs(*self._cursor_px)

            return StateFeedback(
                state=self.state,
                cursor_px=self._anchor_px if self.state == InteractionState.PINCH_LOCK else self._cursor_px,
                gesture_label=intent_frame.gesture_label,
                clicked_event=clicked_event,
            )

        # Pinch released
        if self.state == InteractionState.PINCH_LOCK:
            if self._can_click(now):
                self._backend.move_cursor_abs(*self._anchor_px)
                self._backend.mouse_click(MouseButton.LEFT)
                self._last_click_t = now
                clicked_event = "LEFT"
            self.state = InteractionState.HOVER
        elif self.state == InteractionState.DRAGGING:
            self._backend.mouse_up(MouseButton.LEFT)
            self.state = InteractionState.HOVER

        # --- Scroll Mode ---
        if intent == IntentType.SCROLL_PAN:
            self.state = InteractionState.SCROLLING
            cur_y = intent_frame.scroll_anchor_y
            if self._prev_scroll_y is not None:
                dy = self._prev_scroll_y - cur_y
                if abs(dy) > self._cfg.scroll_deadzone:
                    wheel_delta = int(dy * self._cfg.scroll_sensitivity)
                    if wheel_delta != 0:
                        self._backend.scroll(delta_y=wheel_delta)
            self._prev_scroll_y = cur_y
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="SCROLL",
                clicked_event=clicked_event,
            )

        # --- Default Hover Cursor Movement ---
        self._prev_scroll_y = None
        self.state = InteractionState.HOVER
        self._cursor_px = mapped_px
        self._hover_history.append(self._cursor_px)
        if not (is_sec or is_mid):
            self._backend.move_cursor_abs(*self._cursor_px)

        return StateFeedback(
            state=self.state,
            cursor_px=self._cursor_px,
            gesture_label=intent_frame.gesture_label,
            clicked_event=clicked_event,
        )
