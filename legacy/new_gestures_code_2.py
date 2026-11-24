import cv2
import pyautogui
from cvzone.HandTrackingModule import HandDetector
import time

# Webcam
cap = cv2.VideoCapture(0)
cap.set(3, 1280)
cap.set(4, 720)

detector = HandDetector(detectionCon=0.8, maxHands=1)

# State variables
state = "IDLE"
current_action = "NONE"
click_cooldown = 0.3  # seconds
last_click_time = 0

smooth_x, smooth_y = 0, 0
alpha = 0.2

# Distance helper (3D stable)
def dist3D(p1, p2):
    return ((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2 + (p1[2]-p2[2])**2) ** 0.5

while True:
    success, frame = cap.read()
    frame = cv2.flip(frame, 1)  # keep mirrored
    
    hands, frame = detector.findHands(frame, flipType=False)

    if hands:
        hand = hands[0]
        lmList = hand["lmList"]  # 21 landmarks
        fingers = detector.fingersUp(hand)

        # Convert to (x, y, z)
        landmarks_3d = [(lm[0], lm[1], lm[2]) for lm in lmList]

        # fingertip IDs
        index_tip = landmarks_3d[8]
        middle_tip = landmarks_3d[12]
        ring_tip = landmarks_3d[16]
        thumb_tip = landmarks_3d[4]

        now = time.time()

        # --- Cursor Movement (index+thumb pinch)
        if dist3D(index_tip, thumb_tip) < 40:
            ix, iy = index_tip[0], index_tip[1]
            screen_w, screen_h = pyautogui.size()
            x = int((ix / 1280) * screen_w)
            y = int((iy / 720) * screen_h)
            
            pyautogui.moveTo(x, y)
            state = "CURSOR"
            current_action = "MOVING"

        # --- Left Click (thumb + middle pinch)
        elif dist3D(middle_tip, thumb_tip) < 40:
            if now - last_click_time > click_cooldown:
                pyautogui.click()
                last_click_time = now
                current_action = "LEFT CLICK"
            state = "CLICK MODE"

        # --- Right Click (thumb + ring pinch)
        elif dist3D(ring_tip, thumb_tip) < 40:
            if now - last_click_time > click_cooldown:
                pyautogui.click(button="right")
                last_click_time = now
                current_action = "RIGHT CLICK"
            state = "CLICK MODE"

        # --- Scroll (thumb + index + middle together)
        elif dist3D(index_tip, thumb_tip) < 40 and dist3D(middle_tip, thumb_tip) < 40:
            pyautogui.scroll(-50)
            state = "SCROLL"
            current_action = "SCROLLING"

        # --- Screenshot (make fist)
        elif fingers == [0,0,0,0,0]:
            pyautogui.screenshot("screenshot.png")
            state = "SCREENSHOT"
            current_action = "CAPTURED"

        # --- Close window (all fingers pinch then open to palm)
        elif fingers == [1,1,1,1,1]:
            if now - last_click_time > 1:  # avoid spam
                pyautogui.hotkey("alt", "f4")
                last_click_time = now
                state = "WINDOW CLOSE"
                current_action = "CLOSED"

        else:
            state = "IDLE"
            current_action = "NONE"

    # Overlay
    cv2.putText(frame, f"STATE: {state}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                0.9, (0, 255, 0), 2)
    cv2.putText(frame, f"ACTION: {current_action}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 
                0.9, (0, 255, 255), 2)

    cv2.imshow("Hand Gesture Mouse", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
