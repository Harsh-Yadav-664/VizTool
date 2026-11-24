# GIAS (Gesture-Based Input Abstraction System) — Product Requirements & Architecture Specification

**Version:** 3.0.0 (Product & Open-Source Release Blueprint)  
**Target OS:** Windows 10 / 11 (x64, CPU-only, runs on low-spec laptops)  
**Startup & Runtime:** Always-on background daemon (Windows Startup + System Tray + Translucent Micro-Widget)  
**Resource Budget ("Rainmeter-Light" Standard):** RAM < 75 MB | Active CPU < 8% | Idle/Standby CPU < 1.2% | Latency < 25 ms  

---

## 1. Vision & Product Identity

GIAS is a **lightweight, always-on, hardware-independent spatial input platform** for Windows. It turns any standard webcam into a fluid, zero-fatigue mouse, virtual keyboard, window manager, and sci-fi ("Iron Man") spatial controller—without a visible camera window and without hogging system resources.

### Core Non-Negotiables
1. **Invisible Camera, Visible Intent:** Never show a raw webcam feed during normal use. Feedback appears only as a sleek, translucent on-screen overlay (fingertip cursor, click ripples, gesture badge, radial menu).
2. **Any-Angle Hand Independence:** Must work naturally whether your hand is resting on your desk/lap, tilted 45°, or rotated sideways—never forcing a flat palm toward the camera.
3. **Zero Bounce / Zero Jitter / Zero Drift:** Eliminates cursor tremor, click-drift ("Midas Touch"), and accidental double/triple clicks mathematically via 1€ filtering, Schmitt-trigger hysteresis, and Pinch-Anchor locking.
4. **Rainmeter-Light Footprint:** Always running from Windows boot without slowing down other apps or games.
5. **Extensible Abstraction Pipeline:** Cleanly layered so new gestures, modes, virtual keyboards, or future local ML classifiers plug in without rewriting the core engine.

---

## 2. Root Cause Autopsy (Why V1 Failed)

| Failure | V1 Cause | V3.0 Solution |
| :--- | :--- | :--- |
| **Cursor Jitter** | Constant-alpha EMA (`0.7 * prev + 0.3 * cur`) | **Dual-Axis 1€ (One Euro) Filter**: Adaptive velocity-based cutoff ($f_c = f_{min} + \beta \|\dot{x}\|$). Rock-solid at rest, instant on fast flicks. |
| **Laggy FPS & High CPU** | Synchronous 1280×720 `cap.read()` + `cv2.imshow` | **Threaded DirectShow (`CAP_DSHOW`) at 640×480** (`BUFFERSIZE=1`) + **MediaPipe Tasks `LIVE_STREAM` / Lite (`complexity=0`)** + headless execution. |
| **Mouse Stutter** | `pyautogui.moveTo()` (built-in delays & overhead) | **Native Win32 `SendInput` via `ctypes`**: Sub-millisecond C-struct injection across multi-monitor virtual desktops. |
| **Multi-Click / Bounce Bug** | Level-triggered `if dist < thresh: click()` | **Schmitt Trigger Hysteresis + Edge-Triggered State Machine**: Enter `< 0.28`, Exit `> 0.38`. Fires `DOWN` once, `UP` once. |
| **Click Drift ("Midas Touch")** | Fingertip tracked while bending to pinch | **Pinch-Anchor Lock**: Freezes cursor coordinates at pinch onset so clicks hit the exact pixel aimed at. |
| **Flat-Palm Restriction** | Naive 2D `tip.y < pip.y` checks | **3D Hand-Local Coordinates + Bone Vector Angles**: Uses MediaPipe 3D World Landmarks normalized by palm size. |

---

## 3. Any-Angle 3D Kinematics & Depth Utilization

### 3.1 Orientation & Scale Invariance
Instead of checking `y < pip_y` in 2D image space (which breaks as soon as the hand tilts), GIAS converts MediaPipe's **21 3D World Landmarks** (`hand_world_landmarks`, metric coordinates centered at wrist) into invariant features:
- **Scale Reference:** $S = \|\text{Wrist}(0) - \text{Middle\_MCP}(9)\|_3$ (3D Euclidean palm size).
- **3D Finger Flexion Angles:** Dot product angles between consecutive phalanx bone vectors:
  $$\theta = \arccos\left(\text{clip}\left(\frac{\vec{b}_1 \cdot \vec{b}_2}{\|\vec{b}_1\|\|\vec{b}_2\|}, -1, 1\right)\right)$$
  This accurately detects bent vs. extended fingers at **any 3D rotation or camera angle**.
- **Normalized 3D Pinch Ratios:** $r = \|\text{Thumb\_Tip}(4) - \text{Finger\_Tip}(i)\|_3 / S$. Works whether facing the camera or turned sideways.

### 3.2 Monocular Depth (Z-Axis) Features
1. **Interaction Depth Gate:** Filters out background people or resting hands outside the active palm-size / Z-depth band.
2. **Air-Poke (Z-Tap) Detection:** Tracks forward $\Delta z$ impulse velocity of the index fingertip (`z_vel < -thresh`) for tapping virtual keyboard keys or UI buttons without pinching.
3. **Ergonomic Resting Posture:** Supports resting the forearm/wrist on the desk or lap (Apple Vision Pro / Ultraleap ergonomics) using subtle micro-pinches instead of tiring "Gorilla Arm" mid-air holds.

---

## 4. Ergonomic Gesture Vocabulary & "Iron Man" Feature Set

All gestures pass through **Schmitt-Trigger Hysteresis** + **Edge-Triggered State Machine** to guarantee zero accidental multi-clicks.

### 4.1 Fundamental Mouse & Navigation (Single-Handed)
| Gesture | Intent | OS Action |
| :--- | :--- | :--- |
| **Index Point / Relaxed Hover** | `POINTER_MOVE` | Smooth 1€-filtered cursor movement within active 70% ROI + acceleration curve. |
| **Index + Thumb Pinch (Quick < 250ms)** | `PRIMARY_CLICK` | Left Click (with Pinch-Anchor coordinate lock). |
| **Index + Thumb Pinch (Hold ≥ 250ms)** | `PRIMARY_DRAG` | Left Mouse Down → Drag → Release on unpinch. |
| **Middle + Thumb Pinch** | `SECONDARY_CLICK` | Right Click. |
| **Ring + Thumb Pinch** | `MIDDLE_CLICK` | Middle Click / Open link in new tab. |
| **Index + Middle Extended (2-Finger)** | `SCROLL_PAN` | Smooth vertical & horizontal inertial scrolling (like a trackpad). |
| **Pinky + Thumb Pinch (Hold 400ms)** | `RADIAL_MENU` | Opens translucent **Iron Man Radial Wheel** around cursor to switch modes instantly. |

### 4.2 Window Management & "Iron Man" Bimanual / Compound Gestures
Supports **`max_num_hands=2`**, where the secondary hand acts as a **spatial modifier** (like `Ctrl`/`Shift`) or enables two-handed manipulation:
| Gesture | Intent | OS Action |
| :--- | :--- | :--- |
| **Open Palm → Fist** (within 1.5s, 1 hand) | `WINDOW_MINIMIZE` | Minimizes active window (`Win + Down` / `SW_MINIMIZE`). |
| **Open Palm → Fist + 2nd Hand Open Palm** | `WINDOW_CLOSE` | Closes active window (`Alt + F4`), guarded by protected-app whitelist (IDEs, GIAS). |
| **2-Hand Pinch & Spread / Pull** | `SPATIAL_ZOOM` | Zoom In / Zoom Out (`Ctrl + Scroll`) in browsers, Figma, PDFs, 3D apps. |
| **Wrist Flick Left / Right** | `NAVIGATE_HISTORY` | Browser Back / Forward (`Alt + Left/Right`) or Snap Window (`Win + Left/Right`). |
| **2-Handed Swipe Left / Right** | `WORKSPACE_SWITCH` | Switch Windows Virtual Desktops (`Ctrl + Win + Left/Right`). |
| **Both Palms Down / Push Away** | `EMERGENCY_SLEEP` | Instantly pauses tracking / locks input so you can talk or use physical mouse safely. |

### 4.3 Pluggable Modes (via Radial Menu or Corner Widget)
1. **Mouse Mode (Default):** Full OS cursor, clicks, drag-drop, inertial scroll, window gestures.
2. **Virtual Keyboard Mode:**
   - Spawns a **translucent, non-focus-stealing floating keyboard (`WS_EX_NOACTIVATE`)** so typing goes directly into whichever app (Browser, Notepad, Terminal) is currently focused!
   - **Magnetic Key Snapping:** Cursor gently snaps to the nearest key center to prevent mistyping.
   - **Dual Input Methods:** Pinch-to-Type OR Dwell-to-Type (hover 550ms with circular fill ring) OR Air-Poke (Z-tap).
   - **Swipe Gestures:** Quick left-swipe on keyboard = Backspace; down-swipe = Hide Keyboard.
3. **Media & Spatial HUD Mode:**
   - Vertical Pinch-Drag = System Volume (with translucent radial arc HUD).
   - Horizontal Swipe = Next / Previous Track.
   - Open Palm Tap = Play / Pause.
4. **Presentation / Laser Pointer Mode:**
   - Translucent glowing laser dot + fading motion trail on screen; wrist flicks advance/rewind slides.

---

## 5. Translucent Overlay & Movable Corner Widget (`ui/`)

1. **Full-Screen Translucent Feedback Layer:**
   - Native Win32 layered window: `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW`.
   - Completely **click-through**—never blocks mouse clicks or interferes with fullscreen apps.
   - Per-pixel alpha rendering via `UpdateLayeredWindow` (32-bit DIB / GDI+): draws fingertip tracking dot, pinch-ready ring, click ripple animation, laser trail, and radial pie menu at < 8 MB RAM.
2. **Movable Mini-Widget (Rainmeter-Style Corner Dock):**
   - Small, sleek translucent pill anchored to any screen corner/edge (draggable with mouse or gesture).
   - Displays: Active Mode icon, Hand Tracking status LED (Green = Active, Amber = Standby, Gray = Paused), and quick toggle buttons.
   - Clicking/Pinching the pill expands a compact settings & gesture cheat-sheet drawer (toggle Windows Startup, adjust sensitivity/1€ filter, calibrate ROI, toggle debug skeleton).
3. **System Tray & Windows Startup:**
   - Minimal tray icon (`pystray` / Win32 `Shell_NotifyIcon`) + Registry auto-start option (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).

---

## 6. System Architecture & Module Layout

Strict unidirectional 9-layer pipeline—each layer depends only on the layer above it:

```
gias/
├── capture/       # Threaded DirectShow (640x480, BUFFERSIZE=1) + Power Governor (5Hz idle / 30-60Hz active)
├── tracking/      # MediaPipe Tasks HandLandmarker (LIVE_STREAM / Lite, max_num_hands=2)
├── kinematics/    # 3D World Landmark normalization, bone vectors, joint angles, 1€ Filter, ROI + accel curve
├── gestures/      # Stateless geometric & Z-velocity gesture detector with Schmitt-trigger hysteresis
├── intent/        # Semantic intent resolver (POINTER_MOVE, PRIMARY_CLICK, WINDOW_MINIMIZE, etc.)
├── state/         # Deterministic edge-triggered state machine + Pinch-Anchor lock + cooldowns
├── modes/         # Mode Dispatcher (Mouse, VirtualKeyboard, Media, Presentation, RadialMenu)
├── backends/      # Win32 SendInput (ctypes) for mouse/keyboard/shortcuts + protected-app guard
└── ui/            # Win32 layered click-through overlay, movable mini-widget, floating keyboard, tray icon
```

---

## 7. Phased Build Plan (No Half-Built Abandonment)

Each phase produces a **fully working, testable, daily-usable milestone**:

- **Phase 1 — Ultra-Light Core & Zero-Jitter Mouse:**
  - Threaded DirectShow capture + Power Governor + MediaPipe Lite + 3D landmarks + 1€ Filter + Win32 `SendInput` + Pinch-Anchor click/drag + Schmitt-trigger hysteresis (kills multi-click & jitter forever).
- **Phase 2 — Translucent Overlay & Movable Corner Widget:**
  - Native Win32 click-through overlay (fingertip dot, click ripples, gesture badge) + draggable Rainmeter-style corner pill + System Tray + Windows Startup toggle.
- **Phase 3 — Any-Angle 3D Gestures, Scroll & "Iron Man" Window Control:**
  - 3D bone-angle orientation invariance, 2-finger inertial scroll, bimanual compound gestures (Open→Fist minimize, 2nd-hand-open close, 2-hand zoom, desktop swipe).
- **Phase 4 — Radial Menu, Media Mode & Floating Virtual Keyboard:**
  - Translucent `WS_EX_NOACTIVATE` floating keyboard (magnetic snapping + pinch/dwell/air-poke), Radial Pie Menu, Media/Volume HUD, and Presentation Laser mode.
