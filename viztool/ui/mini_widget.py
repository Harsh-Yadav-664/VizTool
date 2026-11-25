"""Movable Rainmeter-style corner mini-widget pill (WS_EX_NOACTIVATE)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

from viztool.modes.mode_types import AppMode
from viztool.state.state_machine import InteractionState, StateFeedback

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

LWA_ALPHA = 0x00000002
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONUP = 0x0205
WM_NCLBUTTONDOWN = 0x00A1
HTCAPTION = 2
WM_APP_REDRAW = 0x8004

PS_SOLID = 0
TRANSPARENT_BK = 1
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020

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


class CornerMiniWidget:
    """Draggable translucent corner pill: drag to reposition, click right-side to cycle modes."""

    PILL_W = 220
    PILL_H = 36

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
        cls_name = f"VizMiniWidget_{id(self)}"
        bg_brush = gdi32.CreateSolidBrush(_rgb(20, 24, 32))

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_RBUTTONUP and self._on_open_settings is not None:
                self._on_open_settings()
                return 0
            if msg == WM_LBUTTONDOWN:
                x_pos = lparam & 0xFFFF
                if x_pos >= self.PILL_W - 68:
                    self._on_cycle_mode()
                else:
                    user32.ReleaseCapture()
                    user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
                return 0
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
        ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        hwnd = user32.CreateWindowExW(
            ex_style,
            cls_name,
            "VizTool Pill",
            WS_POPUP | WS_VISIBLE,
            sw - self.PILL_W - 18,
            16,
            self.PILL_W,
            self.PILL_H,
            None,
            None,
            h_inst,
            None,
        )
        self._hwnd = hwnd
        user32.SetLayeredWindowAttributes(hwnd, 0, 225, LWA_ALPHA)
        user32.ShowWindow(hwnd, 8)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        gdi32.DeleteObject(bg_brush)

    def _on_paint(self, hwnd: int, bg_brush: int) -> None:
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        mem_dc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, self.PILL_W, self.PILL_H)
        old_bmp = gdi32.SelectObject(mem_dc, bmp)
        user32.FillRect(mem_dc, ctypes.byref(wintypes.RECT(0, 0, self.PILL_W, self.PILL_H)), bg_brush)

        border_pen = gdi32.CreatePen(PS_SOLID, 1, _rgb(60, 78, 98))
        old_pen = gdi32.SelectObject(mem_dc, border_pen)
        old_brush = gdi32.SelectObject(mem_dc, gdi32.GetStockObject(5))
        gdi32.Rectangle(mem_dc, 0, 0, self.PILL_W, self.PILL_H)
        gdi32.SelectObject(mem_dc, old_brush)
        gdi32.SelectObject(mem_dc, old_pen)
        gdi32.DeleteObject(border_pen)

        with self._lock:
            fb = self._feedback

        dot_col = _rgb(125, 135, 150) if fb.state == InteractionState.SLEEP_IDLE else _rgb(0, 235, 160)
        dot_b = gdi32.CreateSolidBrush(dot_col)
        ob = gdi32.SelectObject(mem_dc, dot_b)
        gdi32.Ellipse(mem_dc, 10, 13, 20, 23)
        gdi32.SelectObject(mem_dc, ob)
        gdi32.DeleteObject(dot_b)

        gdi32.SetBkMode(mem_dc, TRANSPARENT_BK)
        gdi32.SetTextColor(mem_dc, _rgb(235, 242, 250))
        left_rc = wintypes.RECT(26, 2, self.PILL_W - 72, self.PILL_H - 2)
        user32.DrawTextW(mem_dc, fb.gesture_label, len(fb.gesture_label), ctypes.byref(left_rc), DT_VCENTER | DT_SINGLELINE)

        # Mode pill button on right side
        btn_b = gdi32.CreateSolidBrush(_rgb(32, 46, 62))
        user32.FillRect(mem_dc, ctypes.byref(wintypes.RECT(self.PILL_W - 68, 5, self.PILL_W - 6, self.PILL_H - 5)), btn_b)
        gdi32.DeleteObject(btn_b)
        gdi32.SetTextColor(mem_dc, _rgb(0, 225, 180))
        mode_rc = wintypes.RECT(self.PILL_W - 66, 5, self.PILL_W - 8, self.PILL_H - 5)
        user32.DrawTextW(mem_dc, fb.mode.value, len(fb.mode.value), ctypes.byref(mode_rc), 0x0001 | DT_VCENTER | DT_SINGLELINE)

        gdi32.BitBlt(hdc, 0, 0, self.PILL_W, self.PILL_H, mem_dc, 0, 0, 0x00CC0020)
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.EndPaint(hwnd, ctypes.byref(ps))
