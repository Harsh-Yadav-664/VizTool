"""Native Win32 SendInput backend via ctypes.

Replaces PyAutoGUI/pynput with direct C-struct event injection for
sub-millisecond cursor movement, clicks, scrolling, and hotkeys.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from enum import Enum

user32 = ctypes.windll.user32

# Ensure DPI awareness so GetSystemMetrics returns true physical pixels
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class MouseButton(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KeybdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", _MouseInput),
        ("ki", _KeybdInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", _InputUnion),
    ]


_BUTTON_FLAGS = {
    MouseButton.LEFT: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    MouseButton.RIGHT: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    MouseButton.MIDDLE: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


class Win32InputBackend:
    """High-speed Windows SendInput injector supporting virtual desktops."""

    def __init__(self) -> None:
        self._extra = ctypes.c_ulong(0)
        self._extra_ptr = ctypes.pointer(self._extra)

    @staticmethod
    def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
        """Return (left, top, width, height) of the entire virtual desktop."""
        left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or user32.GetSystemMetrics(1)
        return left, top, width, height

    def _send_mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> None:
        mi = _MouseInput(
            dx=dx,
            dy=dy,
            mouseData=ctypes.c_ulong(data).value,
            dwFlags=flags,
            time=0,
            dwExtraInfo=self._extra_ptr,
        )
        inp = _Input(type=INPUT_MOUSE, ii=_InputUnion(mi=mi))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))

    def move_cursor_abs(self, x_px: int, y_px: int) -> None:
        """Move cursor to absolute virtual-screen pixel coordinates."""
        vx, vy, vw, vh = self.get_virtual_screen_bounds()
        norm_x = max(0, min(65535, int(((x_px - vx) * 65535) / max(1, vw - 1))))
        norm_y = max(0, min(65535, int(((y_px - vy) * 65535) / max(1, vh - 1))))
        self._send_mouse(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            dx=norm_x,
            dy=norm_y,
        )

    def mouse_down(self, button: MouseButton = MouseButton.LEFT) -> None:
        down_flag, _ = _BUTTON_FLAGS[button]
        self._send_mouse(down_flag)

    def mouse_up(self, button: MouseButton = MouseButton.LEFT) -> None:
        _, up_flag = _BUTTON_FLAGS[button]
        self._send_mouse(up_flag)

    def mouse_click(self, button: MouseButton = MouseButton.LEFT) -> None:
        down_flag, up_flag = _BUTTON_FLAGS[button]
        inputs = (_Input * 2)(
            _Input(
                type=INPUT_MOUSE,
                ii=_InputUnion(mi=_MouseInput(0, 0, 0, down_flag, 0, self._extra_ptr)),
            ),
            _Input(
                type=INPUT_MOUSE,
                ii=_InputUnion(mi=_MouseInput(0, 0, 0, up_flag, 0, self._extra_ptr)),
            ),
        )
        user32.SendInput(2, inputs, ctypes.sizeof(_Input))

    def scroll(self, delta_y: int = 0, delta_x: int = 0) -> None:
        """Send vertical and/or horizontal mouse wheel events (120 = 1 notch)."""
        if delta_y:
            self._send_mouse(MOUSEEVENTF_WHEEL, data=delta_y)
        if delta_x:
            self._send_mouse(MOUSEEVENTF_HWHEEL, data=delta_x)

    def send_hotkey(self, *vk_codes: int) -> None:
        """Press and release a combination of Win32 virtual-key codes."""
        if not vk_codes:
            return
        n = len(vk_codes)
        inputs = (_Input * (n * 2))()
        for i, vk in enumerate(vk_codes):
            inputs[i] = _Input(
                type=INPUT_KEYBOARD,
                ii=_InputUnion(ki=_KeybdInput(vk, 0, 0, 0, self._extra_ptr)),
            )
        for i, vk in enumerate(reversed(vk_codes)):
            inputs[n + i] = _Input(
                type=INPUT_KEYBOARD,
                ii=_InputUnion(ki=_KeybdInput(vk, 0, KEYEVENTF_KEYUP, 0, self._extra_ptr)),
            )
        user32.SendInput(n * 2, inputs, ctypes.sizeof(_Input))
