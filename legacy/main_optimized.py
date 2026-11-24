import cv2
import pyautogui
from pynput.mouse import Button, Controller
import random
import mediapipe as mp
import util
import time

# --- System / input setup ---
pyautogui.PAUSE = 0            # reduce built-in 0.1s delay
# pyautogui.FAILSAFE stays True for safety; we'll clamp away from (0,0)

mouse = Controller()
screen_width, screen_height = pyautogui.size()

# --- Smoothing & scaling (tune these) ---
prev_x, prev_y = 0, 0
ALPHA = 0.7          # 0.5–0.8 = smoother, higher = more laggy feel
SCALE = 1.35         # 1.0 = 1:1, >1 makes edges/corners easier to reach
SAFE_MARGIN = 2      # keep away from (0,0) to avoid failsafe

# --- MediaPipe Hands ---
mpHands = mp.solutions.hands
hands = mpHands.Hands(
    static_image_mode=False,
    model_complexity=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7,
    max_num_hands=1
)

# -----------------------------------------------------------------------------------------------

def find_finger_tip(processed):
    if processed.multi_hand_landmarks:
        hand_landmarks = processed.multi_hand_landmarks[0]
        return hand_landmarks.landmark[mpHands.HandLandmark.INDEX_FINGER_TIP]
    return None

# -----------------------------------------------------------------------------------------------------------

def move_mouse(index_finger_tip):
    global prev_x, prev_y
    if index_finger_tip is None:
        return

    # 1) normalized -> screen
    x = int(index_finger_tip.x * screen_width)
    y = int(index_finger_tip.y * screen_height)

    # 2) increase hand->cursor ratio around screen center (helps edges/corners)
    cx, cy = screen_width // 2, screen_height // 2
    x = int((x - cx) * SCALE + cx)
    y = int((y - cy) * SCALE + cy)

    # 3) anti-jitter smoothing (EMA)
    smoothed_x = int(prev_x * ALPHA + x * (1 - ALPHA))
    smoothed_y = int(prev_y * ALPHA + y * (1 - ALPHA))

    # 4) clamp to safe area (avoid (0,0) which triggers PyAutoGUI failsafe)
    smoothed_x = max(SAFE_MARGIN, min(screen_width - 1 - SAFE_MARGIN, smoothed_x))
    smoothed_y = max(SAFE_MARGIN, min(screen_height - 1 - SAFE_MARGIN, smoothed_y))

    pyautogui.moveTo(smoothed_x, smoothed_y)
    prev_x, prev_y = smoothed_x, smoothed_y

# --------------------------------------------------------------------------------------------

def is_left_click(landmarks_list, thumb_index_dist):
    return (util.get_angle(landmarks_list[5], landmarks_list[6], landmarks_list[8]) < 50 and
            util.get_angle(landmarks_list[9], landmarks_list[10], landmarks_list[12]) > 90 and
            thumb_index_dist > 50)

def is_right_click(landmarks_list, thumb_index_dist):
    return (util.get_angle(landmarks_list[5], landmarks_list[6], landmarks_list[8]) > 90 and
            util.get_angle(landmarks_list[9], landmarks_list[10], landmarks_list[12]) < 50 and
            thumb_index_dist > 50)

def is_double_click(landmarks_list, thumb_index_dist):
    return (util.get_angle(landmarks_list[5], landmarks_list[6], landmarks_list[8]) < 50 and
            util.get_angle(landmarks_list[9], landmarks_list[10], landmarks_list[12]) < 50 and
            thumb_index_dist > 50)

def is_screenshot(landmarks_list, thumb_index_dist):
    return (util.get_angle(landmarks_list[5], landmarks_list[6], landmarks_list[8]) < 50 and
            util.get_angle(landmarks_list[9], landmarks_list[10], landmarks_list[12]) < 50 and
            thumb_index_dist < 50)

# (tiny debounce to avoid accidental multi-clicks; keep your logic intact)
_last_click = 0
CLICK_DEBOUNCE = 0.18

def can_click():
    global _last_click
    now = time.perf_counter()
    if now - _last_click >= CLICK_DEBOUNCE:
        _last_click = now
        return True
    return False

# --------------------------------------------------------------------------------------------------------

def detect_gestures(frame, landmarks_list, processed):
    if len(landmarks_list) < 21:
        return

    index_finger_tip = find_finger_tip(processed)
    thumb_index_dist = util.get_distance([landmarks_list[4], landmarks_list[5]])

    # --- Cursor movement (your original gate) ---
    if thumb_index_dist < 50 and util.get_angle(landmarks_list[5], landmarks_list[6], landmarks_list[8]) > 90:
        move_mouse(index_finger_tip)
        return

    # --- Gestures (unchanged, with small fixes) ---
    if is_left_click(landmarks_list, thumb_index_dist) and can_click():
        mouse.press(Button.left); mouse.release(Button.left)
        cv2.putText(frame, "Left click", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    elif is_right_click(landmarks_list, thumb_index_dist) and can_click():
        mouse.press(Button.right); mouse.release(Button.right)   # FIX: right button
        cv2.putText(frame, "Right click", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    elif is_double_click(landmarks_list, thumb_index_dist) and can_click():
        pyautogui.doubleClick()
        cv2.putText(frame, "DC", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    elif is_screenshot(landmarks_list, thumb_index_dist) and can_click():
        im1 = pyautogui.screenshot()
        label = random.randint(1, 1000)                         # FIX: randint
        im1.save(f"my_screenshot_{label}.png")
        cv2.putText(frame, "SS", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

# -------------------------------------------------------------------------------------------

def main():
    cap = cv2.VideoCapture(0)
    # Request 1280x720; if cam can’t, it’ll fallback silently (that’s normal)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    draw = mp.solutions.drawing_utils

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame = cv2.flip(frame, 1)
            frameRGB = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            processed = hands.process(frameRGB)

            landmarks_list = []
            if processed.multi_hand_landmarks:
                hand_landmarks = processed.multi_hand_landmarks[0]
                draw.draw_landmarks(frame, hand_landmarks, mpHands.HAND_CONNECTIONS)

                for lm in hand_landmarks.landmark:
                    landmarks_list.append((lm.x, lm.y))  # normalized

            detect_gestures(frame, landmarks_list, processed)

            cv2.imshow('Frame', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
