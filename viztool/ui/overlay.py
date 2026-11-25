"""Ultra-lightweight GDI+ anti-aliased click-through HUD overlay (no camera window).

Renders mirror-like translucent 5/10-finger hologram nodes & skeleton lines,
sci-fi concentric circular reticle, click ripples, Radial Pie Menu, and Laser trail.
"""

from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
import threading
import time
from typing import Deque, Optional

from viztool.config import UIConfig
from viztool.modes.mode_types import AppMode
from viztool.state.state_machine import InteractionState, StateFeedback
from viztool.ui.gdiplus_canvas import LayeredCanvas, argb

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_APP_REDRAW = 0x8001

_HAND_BONES = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)
_FINGERTIPS = (4, 8, 12, 16, 20)

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HICON),
        ("hBrush", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class TranslucentOverlay:
    """Anti-aliased GDI+ layered overlay showing all 5/10 fingers, circular reticle, & radial menu."""

    def __init__(self, cfg: UIConfig) -> None:
        self._cfg = cfg
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._feedback = StateFeedback(
            state=InteractionState.SLEEP_IDLE,
            mode=AppMode.MOUSE,
            cursor_px=(0, 0),
            gesture_label="STANDBY",
        )
        self._ripple_until: float = 0.0
        self._ripple_pos: tuple[int, int] = (0, 0)
        self._ripple_color: int = argb(230, 0, 235, 170)
        self._toast_text: str = ""
        self._toast_until: float = 0.0
        self._laser_trail: Deque[tuple[int, int]] = deque(maxlen=14)
        self._wndproc_ref = None
        self._canvas: Optional[LayeredCanvas] = None

    def start(self) -> None:
        if not self._cfg.overlay_enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="VizOverlay")
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, 0x0010, 0, 0)
            self._hwnd = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def update(self, feedback: StateFeedback) -> None:
        if not self._cfg.overlay_enabled or not self._hwnd:
            return
        with self._lock:
            self._feedback = feedback
            if feedback.mode == AppMode.LASER and feedback.state == InteractionState.HOVER:
                self._laser_trail.append(feedback.cursor_px)
            else:
                self._laser_trail.clear()

            if feedback.clicked_event is not None:
                self._ripple_pos = feedback.cursor_px
                self._ripple_until = time.perf_counter() + 0.28
                if feedback.clicked_event == "RIGHT":
                    self._ripple_color = argb(235, 70, 185, 255)
                elif feedback.clicked_event == "MIDDLE":
                    self._ripple_color = argb(235, 195, 120, 255)
                else:
                    self._ripple_color = argb(235, 0, 238, 168)

                if feedback.clicked_event not in ("LEFT", "RIGHT", "MIDDLE", "KEY_PINCH"):
                    self._toast_text = feedback.clicked_event
                    self._toast_until = time.perf_counter() + 1.15
        user32.PostMessageW(self._hwnd, WM_APP_REDRAW, 0, 0)

    def _ui_loop(self) -> None:
        h_inst = kernel32.GetModuleHandleW(None)
        cls_name = f"VizToolGdiPlusOverlay_{id(self)}"

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_APP_REDRAW:
                self._render(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = WNDPROC(wnd_proc)
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = h_inst
        wc.lpszClassName = cls_name
        user32.RegisterClassExW(ctypes.byref(wc))

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        ex_style = (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        hwnd = user32.CreateWindowExW(
            ex_style, cls_name, "VizTool HUD", WS_POPUP | WS_VISIBLE,
            0, 0, sw, sh, None, None, h_inst, None,
        )
        self._hwnd = hwnd
        self._canvas = LayeredCanvas(sw, sh)
        self._render(hwnd)
        user32.ShowWindow(hwnd, 8)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._canvas is not None:
            self._canvas.dispose()
            self._canvas = None

    def _draw_hand_hologram(self, c: LayeredCanvas, sw: int, sh: int, hand_pts_list: tuple) -> None:
        """Render all 5 or 10 fingers + faint mirror skeleton translucently on screen."""
        for pts in hand_pts_list:
            # Faint sci-fi skeleton bones
            for a, b in _HAND_BONES:
                x1, y1 = float(pts[a, 0]) * sw, float(pts[a, 1]) * sh
                x2, y2 = float(pts[b, 0]) * sw, float(pts[b, 1]) * sh
                c.draw_line(x1, y1, x2, y2, argb(72, 0, 215, 255), 1.6)

            # Circular nodes for all 5 fingertips
            for idx in _FINGERTIPS:
                fx, fy = float(pts[idx, 0]) * sw, float(pts[idx, 1]) * sh
                if idx == 8:
                    c.draw_circle(fx, fy, 11.0, argb(190, 0, 240, 175), 2.0)
                    c.fill_circle(fx, fy, 3.8, argb(230, 0, 255, 195))
                elif idx == 4:
                    c.draw_circle(fx, fy, 9.5, argb(175, 0, 200, 255), 1.8)
                    c.fill_circle(fx, fy, 3.2, argb(215, 90, 225, 255))
                else:
                    c.draw_circle(fx, fy, 7.5, argb(120, 150, 220, 255), 1.4)
                    c.fill_circle(fx, fy, 2.5, argb(175, 190, 235, 255))

    def _draw_radial_menu(self, c: LayeredCanvas, origin: tuple[int, int], selected: Optional[AppMode]) -> None:
        ox, oy = float(origin[0]), float(origin[1])
        # Glassmorphic outer ring + inner core
        c.fill_circle(ox, oy, 118.0, argb(205, 14, 18, 28))
        c.draw_circle(ox, oy, 118.0, argb(220, 0, 220, 255), 2.2)
        c.draw_circle(ox, oy, 36.0, argb(130, 0, 220, 255), 1.4)

        slices = [
            (AppMode.MOUSE, ox, oy - 74.0),
            (AppMode.MEDIA, ox + 72.0, oy),
            (AppMode.KEYBOARD, ox, oy + 74.0),
            (AppMode.LASER, ox - 72.0, oy),
        ]
        for mode, sx, sy in slices:
            is_sel = mode == selected
            if is_sel:
                c.fill_round_rect(
                    sx - 44.0, sy - 17.0, 88.0, 34.0, 12.0,
                    argb(230, 15, 75, 78), argb(255, 0, 240, 180), 2.0,
                )
                txt_col = argb(255, 0, 255, 195)
            else:
                c.fill_round_rect(
                    sx - 44.0, sy - 17.0, 88.0, 34.0, 12.0,
                    argb(140, 26, 33, 46), argb(90, 120, 150, 180), 1.0,
                )
                txt_col = argb(220, 200, 215, 235)
            c.draw_text(mode.value, sx - 44.0, sy - 17.0, 88.0, 34.0, txt_col, 9.5, bold=is_sel)

    def _render(self, hwnd: int) -> None:
        c = self._canvas
        if c is None:
            return
        sw, sh = c.width, c.height
        c.clear()

        with self._lock:
            fb = self._feedback
            ripple_until = self._ripple_until
            ripple_pos = self._ripple_pos
            ripple_color = self._ripple_color
            toast_text = self._toast_text
            toast_until = self._toast_until
            trail = list(self._laser_trail)

        now = time.perf_counter()

        # 1. All 5/10 fingers mirror hologram (hidden in LASER mode where 1 dot suffices)
        if fb.state != InteractionState.SLEEP_IDLE and fb.mode != AppMode.LASER and fb.hand_landmarks_2d:
            self._draw_hand_hologram(c, sw, sh, fb.hand_landmarks_2d)

        # 2. Laser Pointer fading trail
        if fb.mode == AppMode.LASER and len(trail) > 1:
            n = len(trail)
            for i, (tx, ty) in enumerate(trail):
                frac = (i + 1) / n
                c.fill_circle(float(tx), float(ty), 2.0 + frac * 7.5, argb(int(40 + frac * 195), 255, 55, 80))

        # 3. Radial Pie Menu
        if fb.state == InteractionState.RADIAL_MENU and fb.radial_origin_px is not None:
            self._draw_radial_menu(c, fb.radial_origin_px, fb.radial_selection)

        # 4. Circular Sci-Fi Cursor Reticle
        if self._cfg.show_cursor_ring and fb.state != InteractionState.SLEEP_IDLE:
            cx, cy = float(fb.cursor_px[0]), float(fb.cursor_px[1])
            if fb.state == InteractionState.PINCH_LOCK:
                ring_col, r = argb(245, 255, 200, 50), 14.0
            elif fb.state == InteractionState.DRAGGING:
                ring_col, r = argb(245, 255, 85, 95), 17.0
            elif fb.state in (InteractionState.SCROLLING, InteractionState.ZOOMING, InteractionState.MEDIA_VOLUME):
                ring_col, r = argb(245, 65, 195, 255), 19.0
            elif fb.state == InteractionState.CLUTCH:
                ring_col, r = argb(160, 150, 165, 185), 11.0
            elif fb.mode == AppMode.LASER:
                ring_col, r = argb(250, 255, 55, 80), 13.0
            else:
                ring_col, r = argb(235, 0, 238, 170), 16.0

            c.draw_circle(cx, cy, r + 5.0, (ring_col & 0x00FFFFFF) | 0x45000000, 1.5)
            c.draw_circle(cx, cy, r, ring_col, 2.2)
            c.fill_circle(cx, cy, 3.0, ring_col)

        # 5. Click Ripple Animation
        if now < ripple_until:
            rx, ry = float(ripple_pos[0]), float(ripple_pos[1])
            prog = 1.0 - (ripple_until - now) / 0.28
            rr = 14.0 + prog * 28.0
            alpha = max(10, int(230 * (1.0 - prog)))
            c.draw_circle(rx, ry, rr, (ripple_color & 0x00FFFFFF) | (alpha << 24), 2.4)

        # 6. Glassmorphic Action Toast Banner
        if now < toast_until and toast_text:
            tw, th = 210.0, 38.0
            tx, ty = (sw - tw) / 2.0, 20.0
            c.fill_round_rect(tx, ty, tw, th, 18.0, argb(215, 16, 22, 32), argb(230, 0, 220, 255), 1.8)
            c.draw_text(toast_text, tx, ty, tw, th, argb(255, 240, 248, 255), 11.0, bold=True)

        c.present(hwnd, 0, 0)
