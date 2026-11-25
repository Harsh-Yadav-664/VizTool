"""Lightweight Windows System Tray controller & Startup registry helper."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
from typing import Callable, Optional
import winreg

from PIL import Image, ImageDraw
import pystray

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "VizTool"


def is_startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enable: bool) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                python_exe = Path(sys.executable)
                pythonw = python_exe.with_name("pythonw.exe")
                exe = str(pythonw if pythonw.exists() else python_exe)
                script = str(Path(__file__).resolve().parents[2] / "run.py")
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, f'"{exe}" "{script}"')
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


def _create_tray_icon(active: bool = True) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ring = (0, 235, 160, 255) if active else (140, 150, 165, 255)
    draw.ellipse((6, 6, 58, 58), fill=(22, 26, 34, 240), outline=ring, width=5)
    draw.ellipse((24, 24, 40, 40), fill=ring)
    return img


class VizTray:
    """Windows System Tray menu for pausing, mode switching, startup, and exit."""

    def __init__(
        self,
        on_toggle_pause: Callable[[], bool],
        on_toggle_mode: Callable[[], str],
        on_open_settings: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_toggle_pause = on_toggle_pause
        self._on_toggle_mode = on_toggle_mode
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit
        self._paused = False
        self._mode_label = "Relative Trackpad"
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda _: "Resume Tracking" if self._paused else "Pause Tracking",
                self._handle_pause,
            ),
            pystray.MenuItem(
                lambda _: f"Mode: {self._mode_label} (Switch)",
                self._handle_mode,
            ),
            pystray.MenuItem(
                "Run at Windows Startup",
                self._handle_startup,
                checked=lambda _: is_startup_enabled(),
            ),
            pystray.MenuItem("Settings...", self._handle_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit VizTool", self._handle_exit),
        )
        self._icon = pystray.Icon("VizTool", _create_tray_icon(True), "VizTool Spatial Input", menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="VizTray")
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def _handle_pause(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._paused = self._on_toggle_pause()
        icon.icon = _create_tray_icon(not self._paused)

    def _handle_mode(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        mode = self._on_toggle_mode()
        self._mode_label = "Relative Trackpad" if mode == "relative" else "Absolute Pointer"

    def _handle_startup(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        set_startup_enabled(not is_startup_enabled())

    def _handle_settings(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_open_settings()

    def _handle_exit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._on_exit()
