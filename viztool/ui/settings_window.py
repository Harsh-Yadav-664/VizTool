"""On-demand dark Settings window (0 MB RAM when closed, live-reloads config.json)."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from viztool.config import VizConfig, save_config
from viztool.ui.tray import is_startup_enabled, set_startup_enabled


def open_settings_window(cfg: VizConfig, on_applied: Callable[[], None]) -> None:
    """Launch a lightweight dark-mode settings dialog in its own thread."""

    def _run() -> None:
        root = tk.Tk()
        root.title("VizTool Settings")
        root.geometry("360x410")
        root.resizable(False, False)
        root.configure(bg="#141820")
        root.attributes("-topmost", True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TLabel", background="#141820", foreground="#E6EEF8", font=("Segoe UI", 10))
        style.configure("TCheckbutton", background="#141820", foreground="#E6EEF8", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10, "bold"))

        pad = {"padx": 16, "pady": 6}

        ttk.Label(root, text="Tracking Mode:").pack(anchor="w", **pad)
        mode_var = tk.StringVar(value=cfg.kinematics.tracking_mode)
        mode_box = ttk.Combobox(root, textvariable=mode_var, values=["relative", "absolute"], state="readonly")
        mode_box.pack(fill="x", padx=16)

        ttk.Label(root, text="Trackpad Sensitivity (1.0 - 4.5):").pack(anchor="w", **pad)
        sens_var = tk.DoubleVar(value=cfg.kinematics.relative_sensitivity)
        tk.Scale(
            root, from_=1.0, to=4.5, resolution=0.1, orient="horizontal",
            variable=sens_var, bg="#141820", fg="#00EBA0", highlightthickness=0
        ).pack(fill="x", padx=16)

        ttk.Label(root, text="1€ Jitter Smoothing (min_cutoff, lower = smoother):").pack(anchor="w", **pad)
        cutoff_var = tk.DoubleVar(value=cfg.kinematics.filter_min_cutoff)
        tk.Scale(
            root, from_=0.4, to=3.0, resolution=0.05, orient="horizontal",
            variable=cutoff_var, bg="#141820", fg="#00EBA0", highlightthickness=0
        ).pack(fill="x", padx=16)

        ttk.Label(root, text="Pinch Sensitivity (enter ratio):").pack(anchor="w", **pad)
        pinch_var = tk.DoubleVar(value=cfg.gestures.pinch_enter_ratio)
        tk.Scale(
            root, from_=0.20, to=0.45, resolution=0.01, orient="horizontal",
            variable=pinch_var, bg="#141820", fg="#00EBA0", highlightthickness=0
        ).pack(fill="x", padx=16)

        startup_var = tk.BooleanVar(value=is_startup_enabled())
        ttk.Checkbutton(root, text="Run automatically at Windows Startup", variable=startup_var).pack(anchor="w", padx=16, pady=12)

        def _save_and_close() -> None:
            cfg.kinematics.tracking_mode = mode_var.get()
            cfg.kinematics.relative_sensitivity = float(sens_var.get())
            cfg.kinematics.filter_min_cutoff = float(cutoff_var.get())
            cfg.gestures.pinch_enter_ratio = float(pinch_var.get())
            cfg.gestures.pinch_exit_ratio = round(cfg.gestures.pinch_enter_ratio + 0.12, 2)
            save_config(cfg, "config.json")
            set_startup_enabled(bool(startup_var.get()))
            on_applied()
            root.destroy()

        ttk.Button(root, text="Save & Apply", command=_save_and_close).pack(pady=14)
        root.mainloop()

    threading.Thread(target=_run, daemon=True, name="VizSettingsUI").start()
