import cv2
import pyautogui
from pynput.mouse import Button, Controller
import mediapipe as mp
import time
import math

# ---------------------- System / Input Setup ----------------------
pyautogui.PAUSE = 0
mouse = Controller()
screen_width, screen_height = pyautogui.size()

# ---------------------- Cursor Smoothing / Scaling ----------------------
prev_x, prev_y = 0, 0
ALPHA = 0.7       # smoothing factor
SCALE_X = 1.5     # horizontal scaling
SCALE_Y = 1.7     # vertical scaling (boost bottom reach)
SAFE_MARGIN = 2

# ---------------------- MediaPipe Hands ----------------------
mpHands = mp.solutions.hands
hands = mpHands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)
mpDraw = mp.solutions.drawing_utils

# ---------------------- Utility Functions ----------------------
def distance_3d(p1, p2):
    return math.sqrt((p2.x - p1.x)**2 + (p2.y - p1.y)**2 + (p2.z - p1.z)**2)

def finger_states(hand_landmarks):
    # Returns [thumb, index, middle, ring, pinky], True if extended
    tips = [4, 8, 12, 16, 20]
    mcp = [2, 5, 9, 13, 17]
    states = []
    for tip_idx, mcp_idx in zip(tips, mcp):
        if tip_idx == 4:  # thumb: x relative to mcp
            states.append(hand_landmarks.landmark[tip_idx].x < hand_landmarks.landmark[mcp_idx].x)
        else:  # others: y relative to mcp
            states.append(hand_landmarks.landmark[tip_idx].y < hand_landmarks.landmark[mcp_idx].y)
    return states

def move_cursor(index_tip, middle_tip):
    global prev_x, prev_y
    x = (index_tip.x + middle_tip.x)/2 * screen_width
    y = (index_tip.y + middle_tip.y)/2 * screen_height

    # Scale around screen center
    cx, cy = screen_width//2, screen_height//2
    x = (x - cx) * SCALE_X + cx
    y = (y - cy) * SCALE_Y + cy

    # EMA smoothing
    sm_x = int(prev_x * ALPHA + x * (1-ALPHA))
    sm_y = int(prev_y * ALPHA + y * (1-ALPHA))

    # Clamp
    sm_x = max(SAFE_MARGIN, min(screen_width-1-SAFE_MARGIN, sm_x))
    sm_y = max(SAFE_MARGIN, min(screen_height-1-SAFE_MARGIN, sm_y))

    pyautogui.moveTo(sm_x, sm_y)
    prev_x, prev_y = sm_x, sm_y

# ---------------------- Click Debounce ----------------------
_last_click = 0
CLICK_DEBOUNCE = 0.2
def can_click():
    global _last_click
    now = time.perf_counter()
    if now - _last_click > CLICK_DEBOUNCE:
        _last_click = now
        return True
    return False

# ---------------------- Main Gesture Detection ----------------------
def detect_gestures(frame, hand_landmarks):
    states = finger_states(hand_landmarks)
    thumb, index, middle, ring, pinky = states

    index_tip = hand_landmarks.landmark[8]
    middle_tip = hand_landmarks.landmark[12]
    ring_tip = hand_landmarks.landmark[16]
    thumb_tip = hand_landmarks.landmark[4]

    # ---------------------- Cursor Movement ----------------------
    # Index+middle straight and close, others folded
    if index and middle and not ring and not pinky:
        if distance_3d(index_tip, middle_tip) < 0.05:  # tips close
            move_cursor(index_tip, middle_tip)
            cv2.putText(frame,"CURSOR MOVING",(50,50),cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,0),2)
            return

    # ---------------------- Left Click (pinch index+thumb, ignore others) ----------------------
    if index and thumb:
        if distance_3d(index_tip, thumb_tip) < 0.04 and can_click():
            mouse.press(Button.left); mouse.release(Button.left)
            cv2.putText(frame,"LEFT CLICK",(50,50),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),2)
            return

    # ---------------------- Right Click (pinch middle+thumb, ignore index) ----------------------
    if middle and thumb and not index:
        if distance_3d(middle_tip, thumb_tip) < 0.04 and can_click():
            mouse.press(Button.right); mouse.release(Button.right)
            cv2.putText(frame,"RIGHT CLICK",(50,50),cv2.FONT_HERSHEY_SIMPLEX,1,(255,0,0),2)
            return

    # ---------------------- Scroll (index+middle+ring extended) ----------------------
    if index and middle and ring and not thumb and not pinky:
        y_avg = (index_tip.y + middle_tip.y + ring_tip.y)/3
        move_amount = int((0.5 - y_avg) * 100)
        pyautogui.scroll(move_amount)
        cv2.putText(frame,"SCROLLING",(50,50),cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,255),2)
        return

# ---------------------- Main Loop ----------------------
def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT,720)

    while True:
        ret, frame = cap.read()
        if not ret: break
        frame = cv2.flip(frame,1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb)

        if results.multi_hand_landmarks:
            handLms = results.multi_hand_landmarks[0]
            mpDraw.draw_landmarks(frame, handLms, mpHands.HAND_CONNECTIONS)
            detect_gestures(frame, handLms)

        cv2.imshow("Hand Mouse 3D", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__=="__main__":
    main()