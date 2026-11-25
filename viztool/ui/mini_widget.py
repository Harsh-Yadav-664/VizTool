"""GDI+ glassmorphic movable corner mini-widget pill (WS_EX_NOACTIVATE)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

from viztool.modes.mode_types import AppMode
from viztool.state.state_machine import InteractionState, StateFeedback
from viztool.ui.gdiplus_canvas import LayeredCanvas, argb

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONUP = 0x0205
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
WM_APP_REDRAW = 0x8004

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


class CornerMiniWidget:
    """Draggable anti-aliased glass pill: drag left side, click mode badge, right-click settings."""

    PILL_W = 248
    PILL_H = 42

    def __init__(
        self,
        on_cycle_mode: Callable[[], None],
        on_open_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_cycle_mode = on_cycle_mode
        self._on_open_settings = on_open_settings
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
        self._wndproc_ref = None
        self._canvas: Optional[LayeredCanvas] = None
        self._pos = (0, 16)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="VizMiniWidget")
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
        if not self._hwnd:
            return
        with self._lock:
            self._feedback = feedback
        user32.PostMessageW(self._hwnd, WM_APP_REDRAW, 0, 0)

    def _ui_loop(self) -> None:
        h_inst = kernel32.GetModuleHandleW(None)
        cls_name = f"VizGdiMiniWidget_{id(self)}"

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_RBUTTONUP and self._on_open_settings is not None:
                self._on_open_settings()
                return 0
            if msg == WM_LBUTTONDOWN:
                x_pos = lparam & 0xFFFF
                if x_pos >= self.PILL_W - 86:
                    self._on_cycle_mode()
                else:
                    user32.ReleaseCapture()
                    user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                return 0
            if msg == 0x0003:  # WM_MOVE
                self._pos = (ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value)
                return 0
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
        self._pos = (sw - self.PILL_W - 18, 16)
        ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = user32.CreateWindowExW(
            ex_style, cls_name, "VizTool Pill", WS_POPUP | WS_VISIBLE,
            self._pos[0], self._pos[1], self.PILL_W, self.PILL_H,
            None, None, h_inst, None,
        )
        self._hwnd = hwnd
        self._canvas = LayeredCanvas(self.PILL_W, self.PILL_H)
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

    def _render(self, hwnd: int) -> None:
        c = self._canvas
        if c is None:
            return
        with self._lock:
            fb = self._feedback

        c.clear()
        c.fill_round_rect(
            1.0, 1.0, self.PILL_W - 2.0, self.PILL_H - 2.0, 19.0,
            argb(215, 16, 21, 30), argb(180, 65, 95, 125), 1.4,
        )

        # Status LED
        if fb.state == InteractionState.SLEEP_IDLE:
            dot_col = argb(220, 130, 140, 155)
        elif fb.state in (InteractionState.PINCH_LOCK, InteractionState.RADIAL_MENU):
            dot_col = argb(255, 255, 200, 50)
        else:
            dot_col = argb(255, 0, 238, 170)

        c.fill_circle(19.0, self.PILL_H / 2.0, 5.5, dot_col)
        c.draw_circle(19.0, self.PILL_H / 2.0, 8.5, (dot_col & 0x00FFFFFF) | 0x55000000, 1.4)

        # Gesture Label
        c.draw_text(
            fb.gesture_label, 34.0, 2.0, self.PILL_W - 124.0, self.PILL_H - 4.0,
            argb(245, 235, 242, 252), 9.5, bold=False, center=False,
        )

        # Mode Pill Button
        c.fill_round_rect(
            self.PILL_W - 86.0, 6.0, 78.0, self.PILL_H - 12.0, 13.0,
            argb(220, 26, 44, 58), argb(160, 0, 220, 180), 1.2,
        )
        c.draw_text(
            fb.mode.value, self.PILL_W - 86.0, 6.0, 78.0, self.PILL_H - 12.0,
            argb(255, 0, 240, 185), 9.0, bold=True, center=True,
        )

        c.present(hwnd, self._pos[0], self._pos[1])
