"""Translucent, non-focus-stealing floating Virtual Keyboard (WS_EX_NOACTIVATE)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import time
from typing import Callable, List, Optional, Tuple

from viztool.backends.win32_input import VK_BACK, VK_RETURN, Win32InputBackend

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

LWA_ALPHA = 0x00000002
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_APP_REDRAW = 0x8002
WM_APP_VIS = 0x8003
PS_SOLID = 0
TRANSPARENT_BK = 1
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


_ROWS: List[List[Tuple[str, float]]] = [
    [(c, 1.0) for c in "QWERTYUIOP"] + [("BACK", 1.6)],
    [(c, 1.0) for c in "ASDFGHJKL"] + [("ENTER", 1.8)],
    [(c, 1.0) for c in "ZXCVBNM"] + [(",", 1.0), (".", 1.0), ("HIDE", 1.8)],
    [("SPACE", 6.5)],
]


class VirtualKeyboardOverlay:
    """Floating translucent QWERTY keyboard supporting Pinch-to-Type and Dwell-to-Type."""

    DWELL_SEC = 0.70

    def __init__(self, backend: Win32InputBackend, on_hide: Callable[[], None]) -> None:
        self._backend = backend
        self._on_hide = on_hide
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._visible = False
        self._lock = threading.Lock()
        self._wndproc_ref = None

        self._win_rect = (0, 0, 760, 260)
        self._keys: List[Tuple[str, int, int, int, int]] = []
        self._hovered_key: Optional[str] = None
        self._hover_start: float = 0.0
        self._dwell_fired = False
        self._build_layout()

    def _build_layout(self) -> None:
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        kw, kh = 760, 250
        kx = max(10, (sw - kw) // 2)
        ky = max(10, sh - kh - 48)
        self._win_rect = (kx, ky, kw, kh)

        self._keys.clear()
        pad_x, pad_y = 14, 14
        gap = 6
        row_h = (kh - 2 * pad_y - gap * (len(_ROWS) - 1)) // len(_ROWS)

        for r_idx, row in enumerate(_ROWS):
            total_units = sum(u for _, u in row)
            avail_w = kw - 2 * pad_x - gap * (len(row) - 1)
            unit_w = avail_w / total_units
            cur_x = float(pad_x)
            y1 = pad_y + r_idx * (row_h + gap)
            y2 = y1 + row_h
            for label, units in row:
                w = units * unit_w
                self._keys.append((label, int(cur_x), y1, int(cur_x + w), y2))
                cur_x += w + gap

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="VizKeyboard")
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, 0x0010, 0, 0)
            self._hwnd = None
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None

    def set_visible(self, visible: bool) -> None:
        if self._visible == visible:
            return
        self._visible = visible
        self._hovered_key = None
        self._dwell_fired = False
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_APP_VIS, 1 if visible else 0, 0)

    def _emit_key(self, label: str) -> None:
        if label == "HIDE":
            self.set_visible(False)
            self._on_hide()
        elif label == "BACK":
            self._backend.send_key(VK_BACK)
        elif label == "ENTER":
            self._backend.send_key(VK_RETURN)
        elif label == "SPACE":
            self._backend.send_unicode_char(" ")
        else:
            self._backend.send_unicode_char(label.lower())

    def update_cursor(self, cursor_px: tuple[int, int], pinched_click: bool) -> None:
        if not self._visible or not self._hwnd:
            return

        kx, ky, _, _ = self._win_rect
        lx = cursor_px[0] - kx
        ly = cursor_px[1] - ky
        now = time.perf_counter()

        hit: Optional[str] = None
        for label, x1, y1, x2, y2 in self._keys:
            if x1 <= lx <= x2 and y1 <= ly <= y2:
                hit = label
                break

        with self._lock:
            if hit != self._hovered_key:
                self._hovered_key = hit
                self._hover_start = now
                self._dwell_fired = False
            elif hit is not None and not self._dwell_fired:
                if (now - self._hover_start) >= self.DWELL_SEC:
                    self._dwell_fired = True
                    self._emit_key(hit)

            if pinched_click and hit is not None:
                self._dwell_fired = True
                self._emit_key(hit)

        user32.PostMessageW(self._hwnd, WM_APP_REDRAW, 0, 0)

    def _ui_loop(self) -> None:
        h_inst = kernel32.GetModuleHandleW(None)
        cls_name = f"VizKeyboard_{id(self)}"
        bg_brush = gdi32.CreateSolidBrush(_rgb(18, 22, 30))

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_APP_VIS:
                user32.ShowWindow(hwnd, 8 if wparam else 0)
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

        kx, ky, kw, kh = self._win_rect
        ex_style = (
            WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        hwnd = user32.CreateWindowExW(
            ex_style, cls_name, "VizTool Keyboard", WS_POPUP,
            kx, ky, kw, kh, None, None, h_inst, None,
        )
        self._hwnd = hwnd
        user32.SetLayeredWindowAttributes(hwnd, 0, 215, LWA_ALPHA)
        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        gdi32.DeleteObject(bg_brush)

    def _on_paint(self, hwnd: int, bg_brush: int) -> None:
        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        _, _, kw, kh = self._win_rect

        mem_dc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, kw, kh)
        old_bmp = gdi32.SelectObject(mem_dc, bmp)
        user32.FillRect(mem_dc, ctypes.byref(wintypes.RECT(0, 0, kw, kh)), bg_brush)

        with self._lock:
            hovered = self._hovered_key
            hover_start = self._hover_start
            dwell_fired = self._dwell_fired

        now = time.perf_counter()
        gdi32.SetBkMode(mem_dc, TRANSPARENT_BK)

        for label, x1, y1, x2, y2 in self._keys:
            is_hov = label == hovered
            fill_col = _rgb(38, 62, 78) if is_hov else _rgb(30, 36, 48)
            border_col = _rgb(0, 235, 160) if is_hov else _rgb(70, 85, 105)
            kb = gdi32.CreateSolidBrush(fill_col)
            kp = gdi32.CreatePen(PS_SOLID, 2 if is_hov else 1, border_col)
            ob = gdi32.SelectObject(mem_dc, kb)
            op = gdi32.SelectObject(mem_dc, kp)
            gdi32.RoundRect(mem_dc, x1, y1, x2, y2, 10, 10)
            gdi32.SelectObject(mem_dc, ob)
            gdi32.SelectObject(mem_dc, op)
            gdi32.DeleteObject(kb)
            gdi32.DeleteObject(kp)

            # Dwell progress bar
            if is_hov and not dwell_fired:
                prog = min(1.0, max(0.0, (now - hover_start) / self.DWELL_SEC))
                bar_w = int((x2 - x1 - 8) * prog)
                if bar_w > 0:
                    pb = gdi32.CreateSolidBrush(_rgb(0, 235, 160))
                    user32.FillRect(mem_dc, ctypes.byref(wintypes.RECT(x1 + 4, y2 - 6, x1 + 4 + bar_w, y2 - 3)), pb)
                    gdi32.DeleteObject(pb)

            gdi32.SetTextColor(mem_dc, _rgb(240, 248, 255))
            rc = wintypes.RECT(x1, y1, x2, y2)
            user32.DrawTextW(mem_dc, label, len(label), ctypes.byref(rc), DT_CENTER | DT_VCENTER | DT_SINGLELINE)

        gdi32.BitBlt(hdc, 0, 0, kw, kh, mem_dc, 0, 0, 0x00CC0020)
        gdi32.SelectObject(mem_dc, old_bmp)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem_dc)
        user32.EndPaint(hwnd, ctypes.byref(ps))
