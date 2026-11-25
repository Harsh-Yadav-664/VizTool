"""Ultra-lightweight Win32 click-through translucent overlay (no camera window).

Draws real-time fingertip tracking ring, click ripples, Iron-Man Radial Pie Menu,
Laser Pointer fading trail, and Media Volume HUD using native GDI.
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

CHROMA_KEY = 0x00010101
TRANSPARENT_BK = 1
PS_SOLID = 0
NULL_BRUSH = 5
DT_CENTER = 0x0001
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


class TranslucentOverlay:
    """Click-through translucent HUD showing reticle, ripples, radial wheel, and laser trail."""

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
        self._ripple_color: int = _rgb(0, 230, 160)
        self._toast_text: str = ""
        self._toast_until: float = 0.0
        self._laser_trail: Deque[tuple[int, int]] = deque(maxlen=12)
        self._wndproc_ref = None

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
                self._ripple_until = time.perf_counter() + 0.25
                if feedback.clicked_event == "RIGHT":
                    self._ripple_color = _rgb(80, 180, 255)
                elif feedback.clicked_event == "MIDDLE":
                    self._ripple_color = _rgb(200, 120, 255)
                else:
                    self._ripple_color = _rgb(0, 235, 150)

                if feedback.clicked_event not in ("LEFT", "RIGHT", "MIDDLE", "KEY_PINCH"):
                    self._toast_text = feedback.clicked_event
                    self._toast_until = time.perf_counter() + 1.1
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
        user32.SetLayeredWindowAttributes(hwnd, CHROMA_KEY, 220, LWA_COLORKEY | LWA_ALPHA)
        user32.ShowWindow(hwnd, 8)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        gdi32.DeleteObject(bg_brush)

    def _draw_radial_menu(
        self, mem_dc: int, origin: tuple[int, int], selected: Optional[AppMode]
    ) -> None:
        ox, oy = origin
        outer_r = 105
        # Outer dark ring
        bg_b = gdi32.CreateSolidBrush(_rgb(18, 22, 30))
        border_p = gdi32.CreatePen(PS_SOLID, 2, _rgb(0, 210, 255))
        old_b = gdi32.SelectObject(mem_dc, bg_b)
        old_p = gdi32.SelectObject(mem_dc, border_p)
        gdi32.Ellipse(mem_dc, ox - outer_r, oy - outer_r, ox + outer_r, oy + outer_r)
        gdi32.SelectObject(mem_dc, old_b)
        gdi32.SelectObject(mem_dc, old_p)
        gdi32.DeleteObject(bg_b)
        gdi32.DeleteObject(border_p)

        # 4 directional slices
        slices = [
            (AppMode.MOUSE, ox, oy - 68),
            (AppMode.MEDIA, ox + 66, oy),
            (AppMode.KEYBOARD, ox, oy + 68),
            (AppMode.LASER, ox - 66, oy),
        ]
        gdi32.SetBkMode(mem_dc, TRANSPARENT_BK)
        for mode, sx, sy in slices:
            is_sel = mode == selected
            col = _rgb(0, 235, 160) if is_sel else _rgb(190, 205, 225)
            if is_sel:
                hl_b = gdi32.CreateSolidBrush(_rgb(35, 55, 70))
                hl_p = gdi32.CreatePen(PS_SOLID, 2, col)
                ob = gdi32.SelectObject(mem_dc, hl_b)
                op = gdi32.SelectObject(mem_dc, hl_p)
                gdi32.RoundRect(mem_dc, sx - 40, sy - 16, sx + 40, sy + 16, 10, 10)
                gdi32.SelectObject(mem_dc, ob)
                gdi32.SelectObject(mem_dc, op)
                gdi32.DeleteObject(hl_b)
                gdi32.DeleteObject(hl_p)
            gdi32.SetTextColor(mem_dc, col)
            rc = wintypes.RECT(sx - 40, sy - 14, sx + 40, sy + 14)
            user32.DrawTextW(mem_dc, mode.value, len(mode.value), ctypes.byref(rc), DT_CENTER | DT_VCENTER | DT_SINGLELINE)

    def _on_paint(self, hwnd: int, bg_brush: int) -> None:
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)

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
            toast_text = self._toast_text
            toast_until = self._toast_until
            trail = list(self._laser_trail)

        now = time.perf_counter()

        # 1. Laser Pointer Trail
        if fb.mode == AppMode.LASER and len(trail) > 1:
            for i, (tx, ty) in enumerate(trail):
                r = max(2, int(2 + (i / len(trail)) * 8))
                lp = gdi32.CreateSolidBrush(_rgb(255, 60, 80))
                ob = gdi32.SelectObject(mem_dc, lp)
                gdi32.Ellipse(mem_dc, tx - r, ty - r, tx + r, ty + r)
                gdi32.SelectObject(mem_dc, ob)
                gdi32.DeleteObject(lp)

        # 2. Radial Pie Menu
        if fb.state == InteractionState.RADIAL_MENU and fb.radial_origin_px is not None:
            self._draw_radial_menu(mem_dc, fb.radial_origin_px, fb.radial_selection)

        # 3. Sci-Fi Concentric Cursor Reticle
        if self._cfg.show_cursor_ring and fb.state != InteractionState.SLEEP_IDLE:
            cx, cy = fb.cursor_px
            if fb.state == InteractionState.PINCH_LOCK:
                ring_color = _rgb(255, 200, 40)
                radius = 12
            elif fb.state == InteractionState.DRAGGING:
                ring_color = _rgb(255, 90, 90)
                radius = 15
            elif fb.state in (InteractionState.SCROLLING, InteractionState.ZOOMING, InteractionState.MEDIA_VOLUME):
                ring_color = _rgb(80, 190, 255)
                radius = 17
            elif fb.state == InteractionState.CLUTCH:
                ring_color = _rgb(140, 150, 165)
                radius = 10
            elif fb.mode == AppMode.LASER:
                ring_color = _rgb(255, 60, 80)
                radius = 12
            else:
                ring_color = _rgb(0, 235, 160)
                radius = 14

            pen = gdi32.CreatePen(PS_SOLID, 2, ring_color)
            old_pen = gdi32.SelectObject(mem_dc, pen)
            old_brush = gdi32.SelectObject(mem_dc, gdi32.GetStockObject(NULL_BRUSH))
            gdi32.Ellipse(mem_dc, cx - radius, cy - radius, cx + radius, cy + radius)
            dot_b = gdi32.CreateSolidBrush(ring_color)
            gdi32.SelectObject(mem_dc, dot_b)
            gdi32.Ellipse(mem_dc, cx - 2, cy - 2, cx + 2, cy + 2)
            gdi32.SelectObject(mem_dc, old_brush)
            gdi32.SelectObject(mem_dc, old_pen)
            gdi32.DeleteObject(dot_b)
            gdi32.DeleteObject(pen)

        # 4. Click Ripple Animation
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

        # 5. Action Toast Banner (e.g., MINIMIZE, CLOSE, VOL+, MODE:MEDIA)
        if now < toast_until and toast_text:
            tx1, ty1 = sw // 2 - 95, 22
            tx2, ty2 = sw // 2 + 95, 56
            tb = gdi32.CreateSolidBrush(_rgb(22, 26, 34))
            tp = gdi32.CreatePen(PS_SOLID, 2, _rgb(0, 220, 255))
            ob = gdi32.SelectObject(mem_dc, tb)
            op = gdi32.SelectObject(mem_dc, tp)
            gdi32.RoundRect(mem_dc, tx1, ty1, tx2, ty2, 16, 16)
            gdi32.SelectObject(mem_dc, ob)
            gdi32.SelectObject(mem_dc, op)
            gdi32.DeleteObject(tb)
            gdi32.DeleteObject(tp)
            gdi32.SetBkMode(mem_dc, TRANSPARENT_BK)
            gdi32.SetTextColor(mem_dc, _rgb(240, 248, 255))
            tr = wintypes.RECT(tx1, ty1, tx2, ty2)
            user32.DrawTextW(mem_dc, toast_text, len(toast_text), ctypes.byref(tr), DT_CENTER | DT_VCENTER | DT_SINGLELINE)

        gdi32.BitBlt(hdc, 0, 0, sw, sh, mem_dc, 0, 0, 0x00CC0020)
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.EndPaint(hwnd, ctypes.byref(ps))
