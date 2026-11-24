# VizTool (GIAS)

**An ultra-lightweight, always-on spatial input & gesture abstraction engine for Windows.**

VizTool turns a standard webcam into a zero-jitter, zero-lag mouse, virtual keyboard, window manager, and "Iron Man" spatial controller—running silently in the background with a **Rainmeter-light footprint** (< 75 MB RAM, < 1.2% idle CPU) and a **translucent click-through HUD** instead of a camera window.

> See [PRD.md](./PRD.md) for the full technical architecture, 3D kinematics math, and phased roadmap.

## Core Highlights
- **Zero Jitter & Zero Lag:** Dual-axis **1€ (One Euro) Adaptive Filter** + Threaded DirectShow (`CAP_DSHOW`) capture + native Win32 `SendInput` via `ctypes`.
- **Zero Multi-Click / Drift Bugs:** Schmitt-trigger hysteresis + edge-triggered state machine + Pinch-Anchor coordinate lock.
- **Any-Angle 3D Hand Tracking:** Uses MediaPipe 3D World Landmarks & bone-vector angles—works naturally even when your hand is tilted or resting on a desk.
- **No Camera Window:** Sleek translucent click-through Win32 overlay for fingertip cursor, click ripples, and radial menus, plus a movable corner mini-widget.
- **Bimanual "Iron Man" Gestures:** Single-hand minimize, 2-hand close (with protected-app guard), spatial zoom, virtual desktop swipe, and translucent non-focus-stealing virtual keyboard.

## Status
- [x] Architecture & Technical Specification ([PRD.md](./PRD.md))
- [x] Legacy prototypes archived in `legacy/`
- [ ] Phase 1: Ultra-Light Core & Zero-Jitter Mouse
- [ ] Phase 2: Translucent Overlay & Movable Corner Widget
- [ ] Phase 3: Any-Angle 3D Gestures, Scroll & Window Control
- [ ] Phase 4: Radial Menu, Media Mode & Floating Virtual Keyboard
