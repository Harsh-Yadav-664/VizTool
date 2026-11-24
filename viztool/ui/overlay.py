"""Ultra-lightweight Win32 click-through translucent overlay (no camera window).

Draws real-time fingertip tracking ring, click ripple animations, and a subtle
corner status pill using native GDI + WS_EX_LAYERED | WS_EX_TRANSPARENT.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import time
from typing import Optional

from viztool.config import UIConfig
from viztool.state.state_machine import InteractionState, StateFeedback

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002

WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_APP_REDRAW = 0x8001

CHROMA_KEY = 0x00010101  # RGB(1, 1, 1) treated as 100% transparent
TRANSPARENT_BK = 1
PS_SOLID = 0
NULL_BRUSH = 5

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


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


def _rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


class TranslucentOverlay:
    """Click-through translucent HUD showing fingertip ring, ripples, and status."""

    def __init__(self, cfg: UIConfig) -> None:
        self._cfg = cfg
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._feedback = StateFeedback(
            state=InteractionState.SLEEP_IDLE,
            cursor_px=(0, 0),
            gesture_label="STANDBY",
        )
        self._ripple_until: float = 0.0
        self._ripple_pos: tuple[int, int] = (0, 0)
        self._ripple_color: int = _rgb(0, 230, 160)
        self._wndproc_ref = None

    def start(self) -> None:
        if not self._cfg.overlay_enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="VizOverlay")
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            self._hwnd = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def update(self, feedback: StateFeedback) -> None:
        if not self._cfg.overlay_enabled or not self._hwnd:
            return
        with self._lock:
            self._feedback = feedback
            if feedback.clicked_event is not None:
                self._ripple_pos = feedback.cursor_px
                self._ripple_until = time.perf_counter() + 0.25
                if feedback.clicked_event == "RIGHT":
                    self._ripple_color = _rgb(80, 180, 255)
                elif feedback.clicked_event == "MIDDLE":
                    self._ripple_color = _rgb(200, 120, 255)
                else:
                    self._ripple_color = _rgb(0, 235, 150)
        user32.PostMessageW(self._hwnd, WM_APP_REDRAW, 0, 0)

    def _ui_loop(self) -> None:
        h_inst = kernel32.GetModuleHandleW(None)
        cls_name = f"VizToolOverlay_{id(self)}"
        bg_brush = gdi32.CreateSolidBrush(CHROMA_KEY)

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_APP_REDRAW:
                user32.InvalidateRect(hwnd, None, False)
                return 0
            if msg == WM_PAINT:
                self._on_paint(hwnd, bg_brush)
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
        wc.hBrush = bg_brush
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
            ex_style,
            cls_name,
            "VizTool HUD",
            WS_POPUP | WS_VISIBLE,
            0,
            0,
            sw,
            sh,
            None,
            None,
            h_inst,
            None,
        )
        self._hwnd = hwnd
        user32.SetLayeredWindowAttributes(hwnd, CHROMA_KEY, 215, LWA_COLORKEY | LWA_ALPHA)
        user32.ShowWindow(hwnd, 8)  # SW_SHOWNA
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        gdi32.DeleteObject(bg_brush)

    def _on_paint(self, hwnd: int, bg_brush: int) -> None:
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)

        # Double-buffer in memory DC to prevent any flicker
        mem_dc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, sw, sh)
        old_bmp = gdi32.SelectObject(mem_dc, bmp)

        full_rect = wintypes.RECT(0, 0, sw, sh)
        user32.FillRect(mem_dc, ctypes.byref(full_rect), bg_brush)

        with self._lock:
            fb = self._feedback
            ripple_until = self._ripple_until
            ripple_pos = self._ripple_pos
            ripple_color = self._ripple_color

        now = time.perf_counter()

        # 1. Draw fingertip cursor ring when active
        if self._cfg.show_cursor_ring and fb.state != InteractionState.SLEEP_IDLE:
            cx, cy = fb.cursor_px
            if fb.state == InteractionState.PINCH_LOCK:
                ring_color = _rgb(255, 200, 40)
                radius = 12
            elif fb.state == InteractionState.DRAGGING:
                ring_color = _rgb(255, 90, 90)
                radius = 15
            elif fb.state == InteractionState.SCROLLING:
                ring_color = _rgb(80, 180, 255)
                radius = 16
            else:
                ring_color = _rgb(0, 235, 160)
                radius = 14

            pen = gdi32.CreatePen(PS_SOLID, 2, ring_color)
            old_pen = gdi32.SelectObject(mem_dc, pen)
            old_brush = gdi32.SelectObject(mem_dc, gdi32.GetStockObject(NULL_BRUSH))
            gdi32.Ellipse(mem_dc, cx - radius, cy - radius, cx + radius, cy + radius)
            gdi32.SelectObject(mem_dc, old_brush)
            gdi32.SelectObject(mem_dc, old_pen)
            gdi32.DeleteObject(pen)

        # 2. Draw click ripple animation
        if now < ripple_until:
            rx, ry = ripple_pos
            progress = 1.0 - (ripple_until - now) / 0.25
            r = int(12 + progress * 22)
            pen = gdi32.CreatePen(PS_SOLID, 2, ripple_color)
            old_pen = gdi32.SelectObject(mem_dc, pen)
            old_brush = gdi32.SelectObject(mem_dc, gdi32.GetStockObject(NULL_BRUSH))
            gdi32.Ellipse(mem_dc, rx - r, ry - r, rx + r, ry + r)
            gdi32.SelectObject(mem_dc, old_brush)
            gdi32.SelectObject(mem_dc, old_pen)
            gdi32.DeleteObject(pen)

        # 3. Draw compact top-right status pill
        if self._cfg.show_status_pill:
            pill_w, pill_h = 190, 32
            px1, py1 = sw - pill_w - 18, 16
            px2, py2 = sw - 18, 16 + pill_h

            pill_bg = gdi32.CreateSolidBrush(_rgb(22, 26, 34))
            pill_pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(60, 75, 95))
            old_b = gdi32.SelectObject(mem_dc, pill_bg)
            old_p = gdi32.SelectObject(mem_dc, pill_pen)
            gdi32.RoundRect(mem_dc, px1, py1, px2, py2, 16, 16)
            gdi32.SelectObject(mem_dc, old_b)
            gdi32.SelectObject(mem_dc, old_p)
            gdi32.DeleteObject(pill_bg)
            gdi32.DeleteObject(pill_pen)

            # Status dot
            dot_color = _rgb(120, 130, 145) if fb.state == InteractionState.SLEEP_IDLE else _rgb(0, 235, 160)
            dot_brush = gdi32.CreateSolidBrush(dot_color)
            old_db = gdi32.SelectObject(mem_dc, dot_brush)
            gdi32.Ellipse(mem_dc, px1 + 12, py1 + 11, px1 + 22, py1 + 21)
            gdi32.SelectObject(mem_dc, old_db)
            gdi32.DeleteObject(dot_brush)

            gdi32.SetBkMode(mem_dc, TRANSPARENT_BK)
            gdi32.SetTextColor(mem_dc, _rgb(235, 240, 248))
            text_rect = wintypes.RECT(px1 + 30, py1 + 7, px2 - 10, py2 - 4)
            label = f"VizTool | {fb.gesture_label}"
            user32.DrawTextW(mem_dc, label, len(label), ctypes.byref(text_rect), 0x0000)

        gdi32.BitBlt(hdc, 0, 0, sw, sh, mem_dc, 0, 0, 0x00CC0020)  # SRCCOPY
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.EndPaint(hwnd, ctypes.byref(ps))
