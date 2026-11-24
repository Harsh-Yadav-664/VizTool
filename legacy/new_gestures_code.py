"""
Stable Virtual Mouse - Final version (per your spec)

Features:
- Cursor moves when you form a strict "L" (index up + thumb out and sufficiently far).
- Left click: bend index (works even if cursor mode is off).
- Right click: bend index + middle together (works even if cursor mode is off).
- Scroll mode: 3 fingers straight up (index+middle+ring). Move hand up/down to scroll.
- Middle click: bend index+middle+ring (three fingers bent).
- Screenshot: bend 4 fingers (index+middle+ring+pinky bent).
- Close window: open palm (all 5 fingers up) -> then fist within 2 seconds closes the active window (alt+F4), with app-protection default.
- Smoothing + cooldowns to minimize accidental actions.
"""

import cv2
import mediapipe as mp
import pyautogui
import time
import math
import numpy as np

# ------------------ TUNABLE PARAMETERS ------------------
CAM_W, CAM_H = 1280, 720              # requested camera capture size
SMOOTH = 7                            # cursor smoothing factor (higher = smoother/slower)
L_RATIO = 0.12                        # L distance threshold as fraction of diagonal
L_VERTICAL_TOL = 0.85                 # allow vertical offset relative to horizontal distance
LEFT_CD = 0.28                        # left click cooldown (s)
RIGHT_CD = 0.45                       # right click cooldown (s)
MIDDLE_CD = 0.6                       # middle click cooldown (s)
SCREENSHOT_CD = 1.2                   # screenshot cooldown (s)
SCROLL_MIN_MOVE_PX = 8                # minimal palm movement to trigger scroll
SCROLL_FACTOR = 6                     # scales scroll sensitivity
CLOSE_TIMEOUT = 2.0                   # seconds to complete palm->fist combo
CLICK_FREEZE = 0.18                   # freeze cursor after click to prevent dragging
PROTECT_KEYWORDS = ["vscode", "visual studio", "code", "pycharm", "spyder", "virtual mouse"]
# --------------------------------------------------------

# Setup
pyautogui.FAILSAFE = False  # optional: set True if you want to allow moving mouse to corner to stop
screen_w, screen_h = pyautogui.size()

# Mediapipe init
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.72, min_tracking_confidence=0.7)

# Camera init
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

# Window (set to camera size to avoid stretching)
ret, tmp = cap.read()
if not ret:
    raise RuntimeError("Cannot read from webcam.")
h_frame, w_frame = tmp.shape[:2]
cv2.namedWindow("Virtual Mouse", cv2.WINDOW_NORMAL)
cv2.resizeWindow("Virtual Mouse", w_frame, h_frame)

# State variables
smoothed_x, smoothed_y = 0.0, 0.0
last_left = last_right = last_middle = last_ss = last_close = 0.0
click_freeze_until = 0.0
prev_palm_y = None
close_ready_time = 0.0

# Helpers
def lm_pixels(hand_landmarks, w, h):
    """Return list of (x,y) pixel coords for 21 landmarks."""
    return [(int(lm.x * w), int(lm.y * h)) for lm in hand_landmarks.landmark]

def is_finger_up_px(lm_list, tip, pip):
    """Return True if tip is above pip (smaller y = higher on image)."""
    return lm_list[tip][1] < lm_list[pip][1]

def active_window_protected():
    """Return True if active window title contains protective keywords (best-effort)."""
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win and win.title:
            title = win.title.lower()
            for k in PROTECT_KEYWORDS:
                if k in title:
                    return True
    except Exception:
        pass
    return False

# Main loop
while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)  # mirror
    h, w = frame.shape[:2]

    # draw status bar background
    cv2.rectangle(frame, (0,0), (w, 30), (0,0,0), -1)

    # process frame
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)

    now = time.time()
    cursor_mode = False  # will set true if strict L formed

    if results.multi_hand_landmarks:
        hand = results.multi_hand_landmarks[0]
        lm_list = lm_pixels(hand, w, h)
        mp_drawing.draw_landmarks(frame, hand, mp_hands.HAND_CONNECTIONS)

        # Compute L thresholds (adaptive)
        diag = math.hypot(w, h)
        L_thresh = int(L_RATIO * diag)  # px

        # Finger states
        thumb_out = abs(lm_list[4][0] - lm_list[3][0]) > 0  # baseline
        index_up = is_finger_up_px(lm_list, 8, 6)
        middle_up = is_finger_up_px(lm_list, 12, 10)
        ring_up = is_finger_up_px(lm_list, 16, 14)
        pinky_up = is_finger_up_px(lm_list, 20, 18)

        # compute thumb-index separation
        thumb_tip = lm_list[4]
        index_tip = lm_list[8]
        dx = abs(thumb_tip[0] - index_tip[0])
        dy = abs(thumb_tip[1] - index_tip[1])

        # STRICT L detection: index up + horizontal gap large enough + limited vertical offset
        if index_up and dx > L_thresh and dy < L_thresh * L_VERTICAL_TOL:
            # If palm fully open, cursor should NOT move (open-palm overrides)
            if not (index_up and middle_up and ring_up and pinky_up and (abs(lm_list[4][0] - lm_list[3][0]) > 0)):
                # apply freeze after recent click to avoid dragging
                if now >= click_freeze_until:
                    # map index tip to screen coords
                    target_x = np.interp(index_tip[0], (0, w), (0, screen_w))
                    target_y = np.interp(index_tip[1], (0, h), (0, screen_h))
                    # smoothing
                    smoothed_x += (target_x - smoothed_x) / SMOOTH
                    smoothed_y += (target_y - smoothed_y) / SMOOTH
                    # move mouse
                    try:
                        pyautogui.moveTo(int(smoothed_x), int(smoothed_y))
                    except Exception:
                        pass
                    cursor_mode = True
                    cv2.putText(frame, "CURSOR MODE", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
        # else: not in cursor mode -> cursor doesn't move

        # ------- CLICK LOGIC (works regardless of cursor mode as requested) -------
        # LEFT CLICK: bend index (index tip below pip)
        if (not index_up) and (now - last_left) > LEFT_CD:
            pyautogui.click()
            last_left = now
            click_freeze_until = now + CLICK_FREEZE
            cv2.putText(frame, "LEFT CLICK", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)

        # RIGHT CLICK: bend index + middle together
        if (not index_up) and (not middle_up) and (now - last_right) > RIGHT_CD:
            pyautogui.rightClick()
            last_right = now
            click_freeze_until = now + CLICK_FREEZE
            cv2.putText(frame, "RIGHT CLICK", (10, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,200,200), 2)

        # MIDDLE CLICK: bend index+middle+ring (three fingers bent)
        if (not index_up) and (not middle_up) and (not ring_up) and (now - last_middle) > MIDDLE_CD:
            pyautogui.middleClick()
            last_middle = now
            click_freeze_until = now + CLICK_FREEZE
            cv2.putText(frame, "MIDDLE CLICK", (10, 124), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (180,120,255), 2)

        # SCREENSHOT: 4-finger bend => index+middle+ring+pinky bent
        if (not index_up) and (not middle_up) and (not ring_up) and (not pinky_up) and (now - last_ss) > SCREENSHOT_CD:
            ts = time.strftime("%Y%m%d-%H%M%S")
            pyautogui.screenshot(f"screenshot_{ts}.png")
            last_ss = now
            cv2.putText(frame, "SCREENSHOT", (10, 156), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200,200,0), 2)

        # SCROLL MODE: three fingers straight up (index+middle+ring up)
        if index_up and middle_up and ring_up:
            palm_y = lm_list[9][1]
            if prev_palm_y is None:
                prev_palm_y = palm_y
            dy_palm = prev_palm_y - palm_y  # positive = hand moved up
            if abs(dy_palm) > SCROLL_MIN_MOVE_PX:
                scroll_amt = int(dy_palm * SCROLL_FACTOR)
                try:
                    pyautogui.scroll(scroll_amt)
                except Exception:
                    pass
                prev_palm_y = palm_y
                last_scroll = now
                cv2.putText(frame, "SCROLL MODE", (10, 188), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,0,0), 2)
        else:
            prev_palm_y = None

        # SAFE CLOSE: open palm sets ready, then fist within timeout closes top window via alt+f4
        all_up = (index_up and middle_up and ring_up and pinky_up and abs(lm_list[4][0] - lm_list[3][0]) > 0)
        all_down = (not index_up and not middle_up and not ring_up and not pinky_up and abs(lm_list[4][0] - lm_list[3][0]) < (L_thresh * 0.35))

        if all_up:
            close_ready_time = now
            cv2.putText(frame, "CLOSE READY (palm open)", (8, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,165,255), 2)

        if close_ready_time and all_down:
            if now - close_ready_time <= CLOSE_TIMEOUT and (now - last_close) > 2.0:
                # do a protected close: block common dev windows by default
                if not active_window_protected():
                    pyautogui.hotkey("alt", "f4")
                    last_close = now
                    cv2.putText(frame, "WINDOW CLOSED", (8, 252), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255), 2)
                else:
                    cv2.putText(frame, "CLOSE BLOCKED (protected)", (8, 252), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,120,255), 2)
            close_ready_time = 0.0

    else:
        # no hands detected
        prev_palm_y = None
        cursor_mode = False

    # helper status texts
    cv2.putText(frame, "ESC to quit", (w - 110, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)

    cv2.imshow("Virtual Mouse", frame)
    if cv2.waitKey(1) & 0xFF == 27:
        break

# cleanup
cap.release()
cv2.destroyAllWindows()
