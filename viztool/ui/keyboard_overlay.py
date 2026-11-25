"""GDI+ glassmorphic non-focus-stealing floating Virtual Keyboard (WS_EX_NOACTIVATE).

Features:
- Stays open until the user pinches/clicks the top-right 'X' button or switches modes.
- Normal mouse clicks continue working everywhere OUTSIDE the keyboard bounds!
- Key-Lock on Pinch: locks the hovered key on pinch onset so typing never slips.
- Dwell-to-Type is disabled by default (opt-in) to prevent accidental typing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
import time
from typing import Callable, List, Optional, Tuple

from viztool.backends.win32_input import VK_BACK, VK_RETURN, Win32InputBackend
from viztool.ui.gdiplus_canvas import LayeredCanvas, argb

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

WM_DESTROY = 0x0002
WM_APP_REDRAW = 0x8002
WM_APP_VIS = 0x8003

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


_ROWS: List[List[Tuple[str, float]]] = [
    [(c, 1.0) for c in "QWERTYUIOP"] + [("BACK", 1.7)],
    [(c, 1.0) for c in "ASDFGHJKL"] + [("ENTER", 1.9)],
    [(c, 1.0) for c in "ZXCVBNM"] + [(",", 1.0), (".", 1.0), ("?", 1.0), ("/", 1.0)],
    [("SPACE", 7.0)],
]


class VirtualKeyboardOverlay:
    """Glassmorphic floating QWERTY keyboard with X close button and Key-Lock."""

    DWELL_SEC = 0.85

    def __init__(
        self,
        backend: Win32InputBackend,
        on_hide: Callable[[], None],
        dwell_enabled: bool = False,
    ) -> None:
        self._backend = backend
        self._on_hide = on_hide
        self.dwell_enabled = dwell_enabled
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._visible = False
        self._lock = threading.Lock()
        self._wndproc_ref = None
        self._canvas: Optional[LayeredCanvas] = None

        self._win_rect = (0, 0, 820, 290)
        self._keys: List[Tuple[str, int, int, int, int]] = []
        self._hovered_key: Optional[str] = None
        self._hover_start: float = 0.0
        self._dwell_fired = False
        self._build_layout()

    def _build_layout(self) -> None:
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        kw, kh = 820, 290
        kx = max(10, (sw - kw) // 2)
        ky = max(10, sh - kh - 56)
        self._win_rect = (kx, ky, kw, kh)

        self._keys.clear()
        # Top bar 'X' close button in top-right
        self._keys.append(("CLOSE_X", kw - 44, 8, kw - 12, 34))

        pad_x, top_bar, pad_y = 14, 42, 12
        gap = 7
        row_h = (kh - top_bar - pad_y - gap * (len(_ROWS) - 1)) // len(_ROWS)

        for r_idx, row in enumerate(_ROWS):
            total_units = sum(u for _, u in row)
            avail_w = kw - 2 * pad_x - gap * (len(row) - 1)
            unit_w = avail_w / total_units
            cur_x = float(pad_x)
            y1 = top_bar + r_idx * (row_h + gap)
            y2 = y1 + row_h
            for label, units in row:
                w = units * unit_w
                self._keys.append((label, int(cur_x), y1, int(cur_x + w), y2))
                cur_x += w + gap

    def contains_point(self, px: int, py: int) -> bool:
        """Return True if screen pixel (px, py) lies inside the visible keyboard."""
        if not self._visible:
            return False
        kx, ky, kw, kh = self._win_rect
        return kx <= px <= (kx + kw) and ky <= py <= (ky + kh)

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
        if label == "CLOSE_X":
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
            elif self.dwell_enabled and hit is not None and not self._dwell_fired:
                if (now - self._hover_start) >= self.DWELL_SEC:
                    self._dwell_fired = True
                    self._emit_key(hit)

            if pinched_click and hit is not None:
                self._dwell_fired = True
                self._emit_key(hit)

        user32.PostMessageW(self._hwnd, WM_APP_REDRAW, 0, 0)

    def _ui_loop(self) -> None:
        h_inst = kernel32.GetModuleHandleW(None)
        cls_name = f"VizGdiKeyboard_{id(self)}"

        def wnd_proc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_APP_VIS:
                user32.ShowWindow(hwnd, 8 if wparam else 0)
                if wparam:
                    self._render(hwnd)
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
        self._canvas = LayeredCanvas(kw, kh)
        self._render(hwnd)
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
        kx, ky, kw, kh = self._win_rect
        c.clear()

        # Glassmorphic panel
        c.fill_round_rect(
            1.0, 1.0, kw - 2.0, kh - 2.0, 18.0,
            argb(218, 14, 18, 28), argb(180, 0, 210, 240), 1.6,
        )
        c.draw_text(
            "VizTool Air-Keyboard  (Click outside anywhere to focus target app)",
            16.0, 8.0, kw - 72.0, 26.0, argb(200, 165, 190, 215), 9.5, bold=False, center=False,
        )

        with self._lock:
            hovered = self._hovered_key
            hover_start = self._hover_start
            dwell_fired = self._dwell_fired

        now = time.perf_counter()

        for label, x1, y1, x2, y2 in self._keys:
            is_hov = label == hovered
            w, h = float(x2 - x1), float(y2 - y1)
            if label == "CLOSE_X":
                fill = argb(230, 185, 45, 55) if is_hov else argb(190, 110, 35, 42)
                border = argb(255, 255, 100, 110) if is_hov else argb(160, 220, 90, 100)
                c.fill_round_rect(float(x1), float(y1), w, h, 8.0, fill, border, 1.3)
                c.draw_text("X", float(x1), float(y1), w, h, argb(255, 255, 255, 255), 10.5, bold=True)
                continue

            fill = argb(230, 22, 68, 82) if is_hov else argb(195, 28, 35, 48)
            border = argb(255, 0, 240, 180) if is_hov else argb(120, 80, 105, 135)
            c.fill_round_rect(float(x1), float(y1), w, h, 10.0, fill, border, 1.8 if is_hov else 1.0)

            if self.dwell_enabled and is_hov and not dwell_fired:
                prog = min(1.0, max(0.0, (now - hover_start) / self.DWELL_SEC))
                if prog > 0.02:
                    c.fill_round_rect(float(x1 + 4), float(y2 - 6), (w - 8.0) * prog, 3.0, 1.5, argb(240, 0, 240, 180))

            c.draw_text(label, float(x1), float(y1), w, h, argb(255, 240, 248, 255), 11.0, bold=is_hov)

        c.present(hwnd, kx, ky)
