import cv2
import pyautogui
from pynput.mouse import Button, Controller
import mediapipe as mp
import numpy as np
import time, math

# ---------------------- Globals ----------------------
screen_width, screen_height = pyautogui.size()
current_mode = "none"
drawing_points = []
ALPHA = 0.5  # smoothing for drawing

# MediaPipe hands
mpHands = mp.solutions.hands
hands = mpHands.Hands(False, 1, 1, 0.7, 0.7)
mpDraw = mp.solutions.drawing_utils

# ---------------------- Utils ----------------------
def distance_3d(p1, p2):
    return math.sqrt((p2.x - p1.x)**2 + (p2.y - p1.y)**2 + (p2.z - p1.z)**2)

def smooth_point(prev, new, alpha=ALPHA):
    return (int(prev[0]*alpha + new[0]*(1-alpha)),
            int(prev[1]*alpha + new[1]*(1-alpha)))

def finger_states(hand_landmarks):
    tips = [4, 8, 12, 16, 20]
    mcp = [2, 5, 9, 13, 17]
    states = []
    for tip_idx, mcp_idx in zip(tips, mcp):
        if tip_idx == 4:  
            states.append(hand_landmarks.landmark[tip_idx].x < hand_landmarks.landmark[mcp_idx].x)
        else:
            states.append(hand_landmarks.landmark[tip_idx].y < hand_landmarks.landmark[mcp_idx].y)
    return states

# ---------------------- UI System ----------------------
def draw_ui(frame):
    buttons = [("DRAW", (50, 50, 200, 120)),
               ("SCROLL", (50, 140, 200, 210)),
               ("SAVE", (50, 230, 200, 300))]
    for text, (x1, y1, x2, y2) in buttons:
        color = (0,255,0) if current_mode == text.lower() else (255,0,0)
        cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
        cv2.putText(frame,text,(x1+20,y1+50),cv2.FONT_HERSHEY_SIMPLEX,1,color,2)
    return buttons

def check_ui_click(x, y, buttons):
    global current_mode
    for text, (x1, y1, x2, y2) in buttons:
        if x1 <= x <= x2 and y1 <= y <= y2:
            current_mode = text.lower()

# ---------------------- Gesture Detection ----------------------
_last_click = 0
def can_click():
    global _last_click
    now = time.perf_counter()
    if now - _last_click > 0.25:
        _last_click = now
        return True
    return False

def detect(frame, hand):
    global drawing_points

    states = finger_states(hand)
    thumb,index,middle,ring,pinky = states
    index_tip = hand.landmark[8]
    middle_tip = hand.landmark[12]
    thumb_tip = hand.landmark[4]

    h, w, _ = frame.shape
    ix, iy = int(index_tip.x*w), int(index_tip.y*h)

    # ---- UI Interaction Mode ----
    buttons = draw_ui(frame)
    if thumb and index and distance_3d(index_tip, thumb_tip)<0.04 and can_click():
        check_ui_click(ix, iy, buttons)

    # ---- Drawing Mode ----
    if current_mode=="draw":
        if index and not middle and not ring and not pinky:
            if len(drawing_points)==0:
                drawing_points.append((ix, iy))
            else:
                sm = smooth_point(drawing_points[-1], (ix,iy))
                drawing_points.append(sm)

        for i in range(1,len(drawing_points)):
            cv2.line(frame, drawing_points[i-1], drawing_points[i], (0,0,255), 3, cv2.LINE_AA)

    # ---- Save Gesture ----
    if current_mode=="draw" and pinky and thumb and distance_3d(hand.landmark[20], thumb_tip)<0.05:
        if can_click():
            canvas = np.ones((h,w,3),dtype=np.uint8)*255
            for i in range(1,len(drawing_points)):
                cv2.line(canvas, drawing_points[i-1], drawing_points[i], (0,0,0), 3, cv2.LINE_AA)
            filename=f"drawing_{int(time.time())}.png"
            cv2.imwrite(filename,canvas)
            print("Saved:", filename)
            drawing_points=[]

# ---------------------- Main ----------------------
def main():
    cap=cv2.VideoCapture(0)
    cap.set(3,1280); cap.set(4,720)

    while True:
        ret,frame=cap.read()
        if not ret: break
        frame=cv2.flip(frame,1)
        rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
        res=hands.process(rgb)

        if res.multi_hand_landmarks:
            hand=res.multi_hand_landmarks[0]
            mpDraw.draw_landmarks(frame,hand,mpHands.HAND_CONNECTIONS)
            detect(frame, hand)

        cv2.imshow("Gesture UI",frame)
        if cv2.waitKey(1)&0xFF==ord('q'): break

    cap.release(); cv2.destroyAllWindows()

if __name__=="__main__":
    main()
