"""Configuration loader and typed defaults for VizTool."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    active_fps: int = 30
    idle_fps: int = 6
    idle_timeout_sec: float = 2.5


@dataclass
class TrackingConfig:
    model_path: str = "models/hand_landmarker.task"
    max_num_hands: int = 2
    model_complexity: int = 0
    min_detection_confidence: float = 0.60
    min_tracking_confidence: float = 0.60


@dataclass
class KinematicsConfig:
    tracking_mode: str = "relative"  # "relative" (ergonomic air-trackpad) or "absolute"
    relative_sensitivity: float = 2.4
    accel_gamma: float = 1.35
    filter_min_cutoff: float = 1.25
    filter_beta: float = 0.012
    filter_d_cutoff: float = 1.0
    roi_margin_x: float = 0.16
    roi_margin_y: float = 0.16
    deadzone_px: float = 0.8


@dataclass
class GestureConfig:
    pinch_enter_ratio: float = 0.34
    pinch_exit_ratio: float = 0.46
    drag_hold_sec: float = 0.24
    click_cooldown_sec: float = 0.18
    scroll_sensitivity: int = 1400
    scroll_deadzone: float = 0.006
    palm_fist_window_sec: float = 1.4
    protected_apps: List[str] = field(
        default_factory=lambda: [
            "code",
            "visual studio",
            "pycharm",
            "powershell",
            "cmd",
            "windowsterminal",
            "viztool",
        ]
    )


@dataclass
class UIConfig:
    overlay_enabled: bool = True
    show_cursor_ring: bool = True
    show_status_pill: bool = True
    tray_enabled: bool = True


@dataclass
class VizConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    kinematics: KinematicsConfig = field(default_factory=KinematicsConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _merge_dataclass(cls: type, data: dict[str, Any] | None) -> Any:
    if not data:
        return cls()
    valid_keys = {f for f in cls.__dataclass_fields__}
    filtered = {k: v for k, v in data.items() if k in valid_keys}
    return cls(**filtered)


def load_config(path: str | Path = "config.json") -> VizConfig:
    """Load configuration from JSON file, falling back to safe defaults."""
    cfg_path = Path(path)
    if not cfg_path.exists():
        return VizConfig()

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    return VizConfig(
        camera=_merge_dataclass(CameraConfig, raw.get("camera")),
        tracking=_merge_dataclass(TrackingConfig, raw.get("tracking")),
        kinematics=_merge_dataclass(KinematicsConfig, raw.get("kinematics")),
        gestures=_merge_dataclass(GestureConfig, raw.get("gestures")),
        ui=_merge_dataclass(UIConfig, raw.get("ui")),
    )


def save_config(cfg: VizConfig, path: str | Path = "config.json") -> None:
    """Persist configuration to JSON."""
    with Path(path).open("w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
