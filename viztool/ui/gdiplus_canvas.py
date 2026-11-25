"""Ultra-lightweight Windows GDI+ 32-bit BGRA layered canvas for glassmorphic HUDs.

Uses UpdateLayeredWindow + per-pixel alpha (AC_SRC_ALPHA) with SmoothingModeAntiAlias
for crisp, modern sci-fi circles, rounded glass panels, glowing nodes, and Segoe UI text.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
gdiplus = ctypes.windll.gdiplus

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
SMOOTHING_ANTIALIAS = 4
TEXT_HINT_ANTIALIAS = 4


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", wintypes.UINT),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", wintypes.BOOL),
        ("SuppressExternalCodeEnabled", wintypes.BOOL),
    ]


class _RECTF(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
    ]


# Configure critical 64-bit pointer safety for Win32 & GDI+
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.CreateWindowExW.restype = wintypes.HWND
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(_POINT), ctypes.POINTER(_SIZE),
    wintypes.HDC, ctypes.POINTER(_POINT), wintypes.COLORREF, ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD,
]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]

gdiplus.GdiplusStartup.argtypes = [ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(_GdiplusStartupInput), ctypes.c_void_p]
gdiplus.GdipCreateFromHDC.argtypes = [wintypes.HDC, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeleteGraphics.argtypes = [ctypes.c_void_p]
gdiplus.GdipSetSmoothingMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
gdiplus.GdipSetTextRenderingHint.argtypes = [ctypes.c_void_p, ctypes.c_int]
gdiplus.GdipCreateSolidFill.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeleteBrush.argtypes = [ctypes.c_void_p]
gdiplus.GdipCreatePen1.argtypes = [ctypes.c_uint32, ctypes.c_float, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeletePen.argtypes = [ctypes.c_void_p]
gdiplus.GdipCreatePath.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipClosePathFigure.argtypes = [ctypes.c_void_p]
gdiplus.GdipDeletePath.argtypes = [ctypes.c_void_p]
gdiplus.GdipGraphicsClear.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
gdiplus.GdipFillEllipse.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
gdiplus.GdipDrawEllipse.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
gdiplus.GdipDrawLine.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
gdiplus.GdipFillPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
gdiplus.GdipDrawPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
gdiplus.GdipAddPathArc.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float]
gdiplus.GdipDrawString.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_RECTF), ctypes.c_void_p, ctypes.c_void_p]
gdiplus.GdipCreateFontFamilyFromName.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeleteFontFamily.argtypes = [ctypes.c_void_p]
gdiplus.GdipCreateFont.argtypes = [ctypes.c_void_p, ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeleteFont.argtypes = [ctypes.c_void_p]
gdiplus.GdipCreateStringFormat.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
gdiplus.GdipDeleteStringFormat.argtypes = [ctypes.c_void_p]
gdiplus.GdipSetStringFormatAlign.argtypes = [ctypes.c_void_p, ctypes.c_int]
gdiplus.GdipSetStringFormatLineAlign.argtypes = [ctypes.c_void_p, ctypes.c_int]


def argb(a: int, r: int, g: int, b: int) -> int:
    """Pack ARGB uint32 color for GDI+."""
    return ((a & 0xFF) << 24) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


_GDIPLUS_TOKEN: Optional[ctypes.c_ulonglong] = None


def ensure_gdiplus() -> None:
    global _GDIPLUS_TOKEN
    if _GDIPLUS_TOKEN is None:
        tok = ctypes.c_ulonglong(0)
        si = _GdiplusStartupInput()
        si.GdiplusVersion = 1
        gdiplus.GdiplusStartup(ctypes.byref(tok), ctypes.byref(si), None)
        _GDIPLUS_TOKEN = tok


class LayeredCanvas:
    """Reusable 32-bit pre-multiplied DIB surface for flicker-free UpdateLayeredWindow."""

    def __init__(self, width: int, height: int) -> None:
        ensure_gdiplus()
        self.width = width
        self.height = height
        self._hdc_screen = user32.GetDC(None)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        ppv_bits = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(ppv_bits), None, 0
        )
        self._old_bmp = gdi32.SelectObject(self._hdc_mem, self._hbmp)

        self._gfx = ctypes.c_void_p()
        gdiplus.GdipCreateFromHDC(self._hdc_mem, ctypes.byref(self._gfx))
        gdiplus.GdipSetSmoothingMode(self._gfx, SMOOTHING_ANTIALIAS)
        gdiplus.GdipSetTextRenderingHint(self._gfx, TEXT_HINT_ANTIALIAS)

        self._font_family = ctypes.c_void_p()
        gdiplus.GdipCreateFontFamilyFromName("Segoe UI", None, ctypes.byref(self._font_family))
        self._str_fmt_center = ctypes.c_void_p()
        gdiplus.GdipCreateStringFormat(0, 0, ctypes.byref(self._str_fmt_center))
        gdiplus.GdipSetStringFormatAlign(self._str_fmt_center, 1)
        gdiplus.GdipSetStringFormatLineAlign(self._str_fmt_center, 1)

        self._str_fmt_left = ctypes.c_void_p()
        gdiplus.GdipCreateStringFormat(0, 0, ctypes.byref(self._str_fmt_left))
        gdiplus.GdipSetStringFormatAlign(self._str_fmt_left, 0)
        gdiplus.GdipSetStringFormatLineAlign(self._str_fmt_left, 1)

    def clear(self) -> None:
        gdiplus.GdipGraphicsClear(self._gfx, 0x00000000)

    def fill_round_rect(
        self, x: float, y: float, w: float, h: float, r: float, fill_col: int, border_col: int = 0, border_w: float = 1.5
    ) -> None:
        path = ctypes.c_void_p()
        gdiplus.GdipCreatePath(0, ctypes.byref(path))
        d = r * 2.0
        gdiplus.GdipAddPathArc(path, x, y, d, d, 180.0, 90.0)
        gdiplus.GdipAddPathArc(path, x + w - d, y, d, d, 270.0, 90.0)
        gdiplus.GdipAddPathArc(path, x + w - d, y + h - d, d, d, 0.0, 90.0)
        gdiplus.GdipAddPathArc(path, x, y + h - d, d, d, 90.0, 90.0)
        gdiplus.GdipClosePathFigure(path)

        if fill_col:
            brush = ctypes.c_void_p()
            gdiplus.GdipCreateSolidFill(fill_col, ctypes.byref(brush))
            gdiplus.GdipFillPath(self._gfx, brush, path)
            gdiplus.GdipDeleteBrush(brush)

        if border_col:
            pen = ctypes.c_void_p()
            gdiplus.GdipCreatePen1(border_col, border_w, 2, ctypes.byref(pen))
            gdiplus.GdipDrawPath(self._gfx, pen, path)
            gdiplus.GdipDeletePen(pen)

        gdiplus.GdipDeletePath(path)

    def fill_circle(self, cx: float, cy: float, r: float, col: int) -> None:
        brush = ctypes.c_void_p()
        gdiplus.GdipCreateSolidFill(col, ctypes.byref(brush))
        gdiplus.GdipFillEllipse(self._gfx, brush, cx - r, cy - r, r * 2.0, r * 2.0)
        gdiplus.GdipDeleteBrush(brush)

    def draw_circle(self, cx: float, cy: float, r: float, col: int, width: float = 2.0) -> None:
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(col, width, 2, ctypes.byref(pen))
        gdiplus.GdipDrawEllipse(self._gfx, pen, cx - r, cy - r, r * 2.0, r * 2.0)
        gdiplus.GdipDeletePen(pen)

    def draw_line(self, x1: float, y1: float, x2: float, y2: float, col: int, width: float = 1.5) -> None:
        pen = ctypes.c_void_p()
        gdiplus.GdipCreatePen1(col, width, 2, ctypes.byref(pen))
        gdiplus.GdipDrawLine(self._gfx, pen, float(x1), float(y1), float(x2), float(y2))
        gdiplus.GdipDeletePen(pen)

    def draw_text(
        self,
        text: str,
        x: float,
        y: float,
        w: float,
        h: float,
        col: int,
        size: float = 10.5,
        bold: bool = False,
        center: bool = True,
    ) -> None:
        font = ctypes.c_void_p()
        gdiplus.GdipCreateFont(self._font_family, float(size), 1 if bold else 0, 2, ctypes.byref(font))
        brush = ctypes.c_void_p()
        gdiplus.GdipCreateSolidFill(col, ctypes.byref(brush))
        rc = _RECTF(float(x), float(y), float(w), float(h))
        fmt = self._str_fmt_center if center else self._str_fmt_left
        gdiplus.GdipDrawString(self._gfx, text, -1, font, ctypes.byref(rc), fmt, brush)
        gdiplus.GdipDeleteBrush(brush)
        gdiplus.GdipDeleteFont(font)

    def present(self, hwnd: int, dst_x: int = 0, dst_y: int = 0) -> None:
        pt_dst = _POINT(dst_x, dst_y)
        sz = _SIZE(self.width, self.height)
        pt_src = _POINT(0, 0)
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            hwnd,
            self._hdc_screen,
            ctypes.byref(pt_dst),
            ctypes.byref(sz),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

    def dispose(self) -> None:
        if self._str_fmt_center:
            gdiplus.GdipDeleteStringFormat(self._str_fmt_center)
        if self._str_fmt_left:
            gdiplus.GdipDeleteStringFormat(self._str_fmt_left)
        if self._font_family:
            gdiplus.GdipDeleteFontFamily(self._font_family)
        if self._gfx:
            gdiplus.GdipDeleteGraphics(self._gfx)
        gdi32.SelectObject(self._hdc_mem, self._old_bmp)
        gdi32.DeleteObject(self._hbmp)
        gdi32.DeleteDC(self._hdc_mem)
        user32.ReleaseDC(None, self._hdc_screen)
