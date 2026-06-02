"""
face_geometry.py — Landmark constants + EAR/MAR/Head Pose helpers (v17).

DRY: gộp các hằng số và hàm hình học bị trùng giữa webcam_sleepiness.py và
classroom_monitor.py vào một nơi duy nhất.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import cv2
import numpy as np

LEFT_EYE: List[int]  = [362, 385, 387, 263, 373, 380]
RIGHT_EYE: List[int] = [33,  160, 158, 133, 153, 144]
MOUTH: List[int]     = [78, 308, 13, 14, 82, 312]

FACE_OVAL_IDS: List[int] = [
    10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
    397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
    172,  58, 132,  93, 234, 127, 162,  21,  54, 103,  67, 109,
]

POSE_LM_IDS: List[int] = [4, 152, 33, 263, 57, 287]

FACE_3D_POINTS: np.ndarray = np.array([
    [  0.0,    0.0,   0.0],
    [  0.0, -330.0, -65.0],
    [-165.0,  170.0,-135.0],
    [ 165.0,  170.0,-135.0],
    [-150.0, -150.0,-125.0],
    [ 150.0, -150.0,-125.0],
], dtype=np.float64)


def _dist(p1, p2, w: float, h: float) -> float:
    return math.hypot((p1.x - p2.x) * w, (p1.y - p2.y) * h)


def ear(lm, eye_ids: Sequence[int], w: float, h: float) -> float:
    """Eye Aspect Ratio. Trả 1.0 khi đo lường suy biến."""
    p = [lm[i] for i in eye_ids]
    a = _dist(p[1], p[5], w, h)
    b = _dist(p[2], p[4], w, h)
    c = _dist(p[0], p[3], w, h)
    return (a + b) / (2.0 * c) if c > 1e-6 else 1.0


def mar(lm, mouth_ids: Sequence[int], w: float, h: float) -> float:
    """Mouth Aspect Ratio."""
    p = [lm[i] for i in mouth_ids]
    vert  = _dist(p[2], p[3], w, h) + _dist(p[4], p[5], w, h)
    horiz = _dist(p[0], p[1], w, h)
    return vert / (2.0 * horiz) if horiz > 0 else 0.0


def head_pose(lm, w: int, h: int) -> Tuple[float, float, float]:
    """(pitch, yaw, roll) bằng độ. SOLVEPNP_EPNP.

    Trả (0, 0, 0) một cách an toàn khi đầu vào suy biến:
      - frame rỗng (w hoặc h <= 0) → camera matrix vô nghĩa;
      - landmark NaN/inf;
      - các điểm 2D gần như trùng nhau (mặt quá nhỏ/xa) — solvePnP vẫn trả
        ok=True nhưng cho ra góc rác (vd yaw ~90°). Không guard thì giá trị rác
        này lọt vào logic POSE_YAW_IGNORE_DEG và âm thầm vô hiệu hoá EAR.
    """
    if w <= 0 or h <= 0:
        return 0.0, 0.0, 0.0

    try:
        pts_2d = np.array(
            [[lm[i].x * w, lm[i].y * h] for i in POSE_LM_IDS],
            dtype=np.float64,
        )
    except (IndexError, AttributeError, TypeError):
        return 0.0, 0.0, 0.0

    # Lọc đầu vào không hữu hạn.
    if not np.all(np.isfinite(pts_2d)):
        return 0.0, 0.0, 0.0

    # Độ phân tán của các điểm phải đủ lớn so với kích thước frame. Nếu bbox của
    # 6 điểm pose nhỏ hơn ~2% cạnh frame, bài toán PnP suy biến → góc không tin
    # cậy. Ngưỡng nhỏ để không loại nhầm mặt thật ở xa hợp lệ.
    span = pts_2d.max(axis=0) - pts_2d.min(axis=0)
    if span[0] < 0.02 * w or span[1] < 0.02 * h:
        return 0.0, 0.0, 0.0

    focal = float(w)
    cam = np.array(
        [[focal, 0, w / 2.0], [0, focal, h / 2.0], [0, 0, 1]],
        dtype=np.float64,
    )
    try:
        ok, rvec, _ = cv2.solvePnP(
            FACE_3D_POINTS, pts_2d, cam, np.zeros((4, 1)),
            flags=cv2.SOLVEPNP_EPNP,
        )
    except cv2.error:
        return 0.0, 0.0, 0.0
    if not ok:
        return 0.0, 0.0, 0.0
    rot, _ = cv2.Rodrigues(rvec)
    pitch = math.degrees(math.atan2(-rot[2, 0], math.hypot(rot[0, 0], rot[1, 0])))
    yaw   = math.degrees(math.atan2( rot[1, 0], rot[0, 0]))
    roll  = math.degrees(math.atan2( rot[2, 1], rot[2, 2]))
    # Bảo vệ cuối: nếu vẫn không hữu hạn (hiếm) → trung tính.
    if not all(math.isfinite(v) for v in (pitch, yaw, roll)):
        return 0.0, 0.0, 0.0
    return pitch, yaw, roll
