"""Edge-triggered state machine with Pinch-Anchor lock & click/drag separation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from viztool.backends.win32_input import MouseButton, Win32InputBackend
from viztool.config import GestureConfig
from viztool.intent.intent_resolver import IntentFrame, IntentType
from viztool.kinematics.coordinate_mapper import CoordinateMapper


class InteractionState(str, Enum):
    SLEEP_IDLE = "SLEEP_IDLE"
    HOVER = "HOVER"
    PINCH_LOCK = "PINCH_LOCK"
    DRAGGING = "DRAGGING"
    SCROLLING = "SCROLLING"


@dataclass(frozen=True)
class StateFeedback:
    """Visual state emitted to the translucent overlay each tick."""

    state: InteractionState
    cursor_px: tuple[int, int]
    gesture_label: str
    clicked_event: Optional[str] = None  # "LEFT", "RIGHT", "MIDDLE", or None


class InteractionStateMachine:
    """Prevents double-click bounce and cursor drift during pinch clicks."""

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
        self._pinch_start_t: float = 0.0
        self._anchor_px: tuple[int, int] = (0, 0)
        self._last_click_t: float = 0.0

        # Edge-trigger latches for secondary/middle pinches
        self._prev_secondary = False
        self._prev_middle = False

        # Scroll tracking
        self._prev_scroll_y: Optional[float] = None

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
            self._prev_secondary = False
            self._prev_middle = False
            self._prev_scroll_y = None
            return StateFeedback(
                state=self.state,
                cursor_px=self._cursor_px,
                gesture_label="STANDBY",
            )

        # Wake from sleep -> reset filter so cursor doesn't jump from stale coords
        if self.state == InteractionState.SLEEP_IDLE:
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
                # Freeze cursor at exact onset pixel to eliminate click-drift
                self._anchor_px = self._cursor_px if self._cursor_px != (0, 0) else mapped_px
                self._pinch_start_t = now
                self.state = InteractionState.PINCH_LOCK
            elif self.state == InteractionState.PINCH_LOCK:
                if (now - self._pinch_start_t) >= self._cfg.drag_hold_sec:
                    # Transition to drag: press left button & unfreeze cursor
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
        if not (is_sec or is_mid):
            self._backend.move_cursor_abs(*self._cursor_px)

        return StateFeedback(
            state=self.state,
            cursor_px=self._cursor_px,
            gesture_label=intent_frame.gesture_label,
            clicked_event=clicked_event,
        )
