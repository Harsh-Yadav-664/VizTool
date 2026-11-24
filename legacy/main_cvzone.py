import cv2
from cvzone.HandTrackingModule import HandDetector
import pyautogui
import random

# Setup
cap = cv2.VideoCapture(0)
cap.set(3, 1280)  # width
cap.set(4, 720)   # height

detector = HandDetector(detectionCon=0.8, maxHands=1)

# Screen size for mapping
screen_w, screen_h = pyautogui.size()

# Move mouse with pyautogui
def move_mouse(x, y):
    scr_x = int(x / 1280 * screen_w)
    scr_y = int(y / 720 * screen_h)
    pyautogui.moveTo(scr_x, scr_y)

while True:
    success, img = cap.read()
    if not success:
        break

    hands, img = detector.findHands(img)

    if hands:
        hand = hands[0]
        lmList = hand["lmList"]
        fingers = detector.fingersUp(hand)

        # -------- Move Mode --------
        if fingers == [0, 1, 0, 0, 0]:  # Only index up
            x, y = lmList[8][:2]  # Index fingertip
            move_mouse(x, y)

            # Left Click (Index + Thumb close)
            length, _, _ = detector.findDistance(lmList[4], lmList[8], img)
            if length < 40:
                pyautogui.click()

        # -------- Right Click --------
        elif fingers == [0, 1, 1, 0, 0]:
            pyautogui.rightClick()

        # -------- Double Click --------
        elif fingers == [0, 1, 1, 1, 0]:
            pyautogui.doubleClick()

        # -------- Screenshot --------
        elif fingers == [1, 1, 1, 1, 1]:
            pyautogui.screenshot(f"ss_{random.randint(1,1000)}.png")

    cv2.imshow("Hand Gesture Mouse", img)

    key = cv2.waitKey(1) & 0xFF
    if key == 27:  # ESC key
        break

cap.release()
cv2.destroyAllWindows()
