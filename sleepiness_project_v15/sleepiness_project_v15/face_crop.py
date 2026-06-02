"""
face_crop.py — Crop face với padding bằng copyMakeBorder (v17).

DRY: cùng logic cắt mặt vuông + đệm biên đen được dùng ở 3 file
(prepare_faces.py, predict_sleepiness.py, webcam_sleepiness.py).
"""

from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np


def crop_face_with_padding(
    img_bgr: np.ndarray,
    bbox: Tuple[int, int, int, int],
    padding: float = 0.25,
) -> Optional[np.ndarray]:
    """
    Cắt vùng khuôn mặt vuông quanh bbox với padding tỉ lệ.

    Args:
        img_bgr: Ảnh BGR uint8.
        bbox:    (x, y, w, h) bounding box gốc.
        padding: Tỉ lệ đệm thêm 4 phía (mặc định 25%).

    Returns:
        Ảnh BGR vuông đã đệm biên đen, hoặc None nếu bbox vô hiệu.
    """
    if img_bgr is None or img_bgr.size == 0:
        return None
    h_img, w_img = img_bgr.shape[:2]
    x, y, w, h = bbox
    if w <= 0 or h <= 0:
        return None

    cx = x + w // 2
    cy = y + h // 2
    desired_side = max(w + int(w * padding * 2), h + int(h * padding * 2))
    half = desired_side // 2

    x1, y1 = cx - half, cy - half
    x2, y2 = cx + half, cy + half

    pad_top    = max(0, -y1)
    pad_bottom = max(0, y2 - h_img)
    pad_left   = max(0, -x1)
    pad_right  = max(0, x2 - w_img)

    x1c = max(0, x1)
    y1c = max(0, y1)
    x2c = max(0, min(w_img, x2))
    y2c = max(0, min(h_img, y2))
    if x2c <= x1c or y2c <= y1c:
        return None

    valid = img_bgr[y1c:y2c, x1c:x2c]
    if valid is None or valid.size == 0:
        return None

    out = cv2.copyMakeBorder(
        valid, pad_top, pad_bottom, pad_left, pad_right,
        borderType=cv2.BORDER_CONSTANT, value=[0, 0, 0],
    )
    return out if out.size > 0 else None
