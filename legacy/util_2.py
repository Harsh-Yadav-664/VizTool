import numpy as np

def get_angle(a,b,c):
    radians=np.arctan2(c[1] - b[1] ,c[0]- b[0]) - np.arctan2(a[1]-b[1], a[0] -b[0])
    angle=np.abs(np.degrees(radians))
    return angle
import math

def get_distance(point_pair):
    # works with (x, y, z) too
    if len(point_pair[0]) == 3 and len(point_pair[1]) == 3:
        (x1, y1, z1), (x2, y2, z2) = point_pair[0], point_pair[1]
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
    else:  # fallback for (x, y)
        (x1, y1), (x2, y2) = point_pair[0], point_pair[1]
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
