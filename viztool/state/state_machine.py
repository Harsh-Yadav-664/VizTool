"""Edge-triggered state machine with Pinch-Anchor, Radial Menu, and Multi-Mode support."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
import math
from typing import Callable, Deque, Optional

from viztool.backends.win32_input import (
    VK_CONTROL,
    VK_LEFT,
    VK_LWIN,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MENU,
    VK_RIGHT,
    VK_VOLUME_DOWN,
    VK_VOLUME_UP,
    MouseButton,
    Win32InputBackend,
)
from viztool.config import GestureConfig
from viztool.intent.intent_resolver import IntentFrame, IntentType
from viztool.kinematics.coordinate_mapper import CoordinateMapper
from viztool.modes.mode_types import AppMode


class InteractionState(str, Enum):
    SLEEP_IDLE = "SLEEP_IDLE"
    HOVER = "HOVER"
    CLUTCH = "CLUTCH"
    PINCH_LOCK = "PINCH_LOCK"
    DRAGGING = "DRAGGING"
    SCROLLING = "SCROLLING"
    ZOOMING = "ZOOMING"
    RADIAL_MENU = "RADIAL_MENU"
    MEDIA_VOLUME = "MEDIA_VOLUME"


@dataclass(frozen=True)
class StateFeedback:
    """Visual state emitted to the translucent overlay each tick."""

    state: InteractionState
    mode: AppMode
    cursor_px: tuple[int, int]
    gesture_label: str
    clicked_event: Optional[str] = None
    radial_origin_px: Optional[tuple[int, int]] = None
    radial_selection: Optional[AppMode] = None
    hand_landmarks_2d: tuple = ()  # tuple of (21, 2) float arrays for up to 2 hands (5/10 fingers)


def _pick_radial_slice(dx: float, dy: float) -> Optional[AppMode]:
    """Map radial offset (dx, dy) from wheel center to one of the 4 AppModes."""
    if math.hypot(dx, dy) < 42.0:
        return None
    angle = math.degrees(math.atan2(dy, dx))  # -180 .. +180
    if -135.0 <= angle < -45.0:
        return AppMode.MOUSE
    if -45.0 <= angle < 45.0:
        return AppMode.MEDIA
    if 45.0 <= angle < 135.0:
        return AppMode.KEYBOARD
    return AppMode.LASER


class InteractionStateMachine:
    """Prevents double-click bounce, cursor drift, and orchestrates modes & Iron-Man gestures."""

    def __init__(
        self,
        cfg: GestureConfig,
        mapper: CoordinateMapper,
        backend: Win32InputBackend,
        on_mode_changed: Optional[Callable[[AppMode], None]] = None,
        is_point_on_keyboard: Optional[Callable[[int, int], bool]] = None,
    ) -> None:
        self._cfg = cfg
        self._mapper = mapper
        self._backend = backend
        self._on_mode_changed = on_mode_changed
        self._is_point_on_keyboard = is_point_on_keyboard

        self.mode = AppMode.MOUSE
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

        # Scroll, Zoom, Radial, Media Volume, Air-Swipe tracking
        self._prev_scroll_y: Optional[float] = None
        self._prev_scroll_x: Optional[float] = None
        self._prev_zoom_span: Optional[float] = None
        self._radial_origin_px: tuple[int, int] = (0, 0)
        self._radial_selection: Optional[AppMode] = None
        self._volume_anchor_y: Optional[float] = None
        self._palm_anchor_x: Optional[float] = None
        self._last_swipe_t: float = -10.0

    def set_mode(self, mode: AppMode) -> None:
        if mode != self.mode:
            self.mode = mode
            if self._on_mode_changed is not None:
                self._on_mode_changed(mode)

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
            self._prev_scroll_x = None
            self._prev_zoom_span = None
            self._radial_selection = None
            self._volume_anchor_y = None
            self._palm_anchor_x = None
            return StateFeedback(
                state=self.state,
                mode=self.mode,
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

        # --- Iron-Man Radial Pie Menu (Pinky + Thumb Pinch) ---
        if intent == IntentType.RADIAL_HOLD:
            mapped_px = self._mapper.map_to_screen(
                now, intent_frame.pointer_xy[0], intent_frame.pointer_xy[1]
            )
            if self.state != InteractionState.RADIAL_MENU:
                self._radial_origin_px = self._cursor_px if self._cursor_px != (0, 0) else mapped_px
                self._radial_selection = None
                self.state = InteractionState.RADIAL_MENU
            else:
                self._cursor_px = mapped_px
                dx = self._cursor_px[0] - self._radial_origin_px[0]
                dy = self._cursor_px[1] - self._radial_origin_px[1]
                self._radial_selection = _pick_radial_slice(dx, dy)
            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="RADIAL MENU",
                radial_origin_px=self._radial_origin_px,
                radial_selection=self._radial_selection,
            )

        if self.state == InteractionState.RADIAL_MENU:
            if self._radial_selection is not None:
                self.set_mode(self._radial_selection)
                clicked_event = f"MODE:{self.mode.value}"
            self._radial_selection = None
            self.state = InteractionState.HOVER
            self._mapper.reset()

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
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="2-HAND ZOOM",
            )
        self._prev_zoom_span = None

        # --- Open Palm -> Fist (Minimize / Bimanual Close) + 2-Hand Virtual Desktop Swipe ---
        if intent == IntentType.PALM_READY:
            self._palm_ready_until = now + self._cfg.palm_fist_window_sec
            self._prev_fist = False
            self._mapper.reset()
            self.state = InteractionState.CLUTCH

            # Phase 5: 2-Hand Open-Palm Horizontal Swipe -> Switch Windows Virtual Desktop
            cur_px = intent_frame.pointer_xy[0]
            if intent_frame.secondary_open_palm and (now - self._last_swipe_t) > 0.75:
                if self._palm_anchor_x is None:
                    self._palm_anchor_x = cur_px
                else:
                    dx_palm = cur_px - self._palm_anchor_x
                    if abs(dx_palm) > 0.14:
                        self._last_swipe_t = now
                        self._palm_anchor_x = cur_px
                        vk_dir = VK_RIGHT if dx_palm > 0 else VK_LEFT
                        self._backend.send_hotkey(VK_CONTROL, VK_LWIN, vk_dir)
                        clicked_event = "DESKTOP >" if dx_palm > 0 else "< DESKTOP"
            else:
                self._palm_anchor_x = None

            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="PALM READY" + (" (+2ND)" if intent_frame.secondary_open_palm else ""),
                clicked_event=clicked_event,
            )
        self._palm_anchor_x = None

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

            self._mapper.reset()
            self.state = InteractionState.CLUTCH
            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="CLUTCH",
                clicked_event=clicked_event,
            )
        self._prev_fist = False

        if self.state == InteractionState.CLUTCH:
            self._mapper.reset()
            self.state = InteractionState.HOVER

        mapped_px = self._mapper.map_to_screen(
            now, intent_frame.pointer_xy[0], intent_frame.pointer_xy[1]
        )

        # --- Mode-Specific Secondary / Middle Pinches ---
        is_sec = intent == IntentType.SECONDARY_TRIGGER
        if is_sec and not self._prev_secondary and self._can_click(now):
            self._last_click_t = now
            if self.mode == AppMode.MEDIA:
                self._backend.send_key(VK_MEDIA_PLAY_PAUSE)
                clicked_event = "PLAY/PAUSE"
            elif self.mode == AppMode.LASER:
                self._backend.send_key(VK_RIGHT)
                clicked_event = "NEXT SLIDE"
            else:
                self._backend.mouse_click(MouseButton.RIGHT)
                clicked_event = "RIGHT"
        self._prev_secondary = is_sec

        is_mid = intent == IntentType.MIDDLE_TRIGGER
        if is_mid and not self._prev_middle and self._can_click(now):
            self._last_click_t = now
            if self.mode == AppMode.MEDIA:
                self._backend.send_key(VK_MEDIA_NEXT_TRACK)
                clicked_event = "NEXT TRACK"
            elif self.mode == AppMode.LASER:
                self._backend.send_key(VK_LEFT)
                clicked_event = "PREV SLIDE"
            else:
                self._backend.mouse_click(MouseButton.MIDDLE)
                clicked_event = "MIDDLE"
        self._prev_middle = is_mid

        # --- Media Volume Slider on Primary Pinch ---
        if self.mode == AppMode.MEDIA and intent == IntentType.PRIMARY_HOLD:
            self.state = InteractionState.MEDIA_VOLUME
            cur_y = intent_frame.scroll_anchor_y
            if self._volume_anchor_y is None:
                self._volume_anchor_y = cur_y
            else:
                dy = self._volume_anchor_y - cur_y
                if abs(dy) > 0.025:
                    self._backend.send_key(VK_VOLUME_UP if dy > 0 else VK_VOLUME_DOWN)
                    self._volume_anchor_y = cur_y
                    clicked_event = "VOL+" if dy > 0 else "VOL-"
            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="VOLUME",
                clicked_event=clicked_event,
            )
        self._volume_anchor_y = None

        # --- Primary Pinch: Pinch-Anchor Lock + Click vs Drag ---
        if intent == IntentType.PRIMARY_HOLD and self.mode != AppMode.LASER:
            self._prev_scroll_y = None
            if self.state in (InteractionState.HOVER, InteractionState.SCROLLING):
                if self._hover_history:
                    self._anchor_px = self._hover_history[0]
                else:
                    self._anchor_px = self._cursor_px if self._cursor_px != (0, 0) else mapped_px
                self._pinch_start_t = now
                self.state = InteractionState.PINCH_LOCK
            elif self.state == InteractionState.PINCH_LOCK:
                on_kb = (
                    self.mode == AppMode.KEYBOARD
                    and self._is_point_on_keyboard is not None
                    and self._is_point_on_keyboard(*self._anchor_px)
                )
                if not on_kb and (now - self._pinch_start_t) >= self._cfg.drag_hold_sec:
                    self._backend.mouse_down(MouseButton.LEFT)
                    self.state = InteractionState.DRAGGING
                    self._cursor_px = mapped_px
                    self._backend.move_cursor_abs(*self._cursor_px)
            elif self.state == InteractionState.DRAGGING:
                self._cursor_px = mapped_px
                self._backend.move_cursor_abs(*self._cursor_px)

            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._anchor_px if self.state == InteractionState.PINCH_LOCK else self._cursor_px,
                gesture_label=intent_frame.gesture_label,
                clicked_event=clicked_event,
            )

        # Pinch released
        if self.state == InteractionState.PINCH_LOCK:
            if self._can_click(now):
                self._last_click_t = now
                on_kb = (
                    self.mode == AppMode.KEYBOARD
                    and self._is_point_on_keyboard is not None
                    and self._is_point_on_keyboard(*self._anchor_px)
                )
                if on_kb:
                    clicked_event = "KEY_PINCH"
                else:
                    # Normal clicks always work everywhere outside the floating keyboard!
                    self._backend.move_cursor_abs(*self._anchor_px)
                    self._backend.mouse_click(MouseButton.LEFT)
                    clicked_event = "LEFT"
            self.state = InteractionState.HOVER
        elif self.state == InteractionState.DRAGGING:
            self._backend.mouse_up(MouseButton.LEFT)
            self.state = InteractionState.HOVER

        # --- Scroll & Phase 5 2-Finger Air-Swipe Back/Forward ---
        if intent == IntentType.SCROLL_PAN:
            self.state = InteractionState.SCROLLING
            cur_y = intent_frame.scroll_anchor_y
            cur_x = intent_frame.pointer_xy[0]
            if self._prev_scroll_y is not None:
                dy = self._prev_scroll_y - cur_y
                if abs(dy) > self._cfg.scroll_deadzone:
                    wheel_delta = int(dy * self._cfg.scroll_sensitivity)
                    if wheel_delta != 0:
                        self._backend.scroll(delta_y=wheel_delta)
            if self._prev_scroll_x is not None and (now - self._last_swipe_t) > 0.70:
                dx = cur_x - self._prev_scroll_x
                if abs(dx) > 0.085:
                    self._last_swipe_t = now
                    vk_nav = VK_RIGHT if dx > 0 else VK_LEFT
                    self._backend.send_hotkey(VK_MENU, vk_nav)
                    clicked_event = "FORWARD >" if dx > 0 else "< BACK"
            self._prev_scroll_y = cur_y
            self._prev_scroll_x = cur_x
            return StateFeedback(
                state=self.state,
                mode=self.mode,
                cursor_px=self._cursor_px,
                gesture_label="SCROLL",
                clicked_event=clicked_event,
            )

        # --- Default Hover Cursor Movement ---
        self._prev_scroll_y = None
        self._prev_scroll_x = None
        self.state = InteractionState.HOVER
        self._cursor_px = mapped_px
        self._hover_history.append(self._cursor_px)
        if not (is_sec or is_mid):
            self._backend.move_cursor_abs(*self._cursor_px)

        if (
            self.mode == AppMode.KEYBOARD
            and intent_frame.air_poke
            and self._is_point_on_keyboard is not None
            and self._is_point_on_keyboard(*self._cursor_px)
            and self._can_click(now)
        ):
            self._last_click_t = now
            clicked_event = "KEY_PINCH"

        return StateFeedback(
            state=self.state,
            mode=self.mode,
            cursor_px=self._cursor_px,
            gesture_label=intent_frame.gesture_label,
            clicked_event=clicked_event,
        )
