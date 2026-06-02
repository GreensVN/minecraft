"""
predict_sleepiness.py — Dự đoán buồn ngủ từ 1 ảnh tĩnh (v17).

CHANGELOG v17:
    [FIX] Cache model + transform module-level → predict_image() không load
          lại từ disk mỗi lần gọi.
    [DRY] Dùng face_crop.crop_face_with_padding thay 2 bản sao copyMakeBorder.

v15: CLAHE sync với webcam pipeline.
v4 : copyMakeBorder thay max_half_side.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Tuple

import cv2
import numpy as np
import torch
from PIL import Image

from utils_model import load_model, get_transform, DEVICE
from face_crop import crop_face_with_padding

# ─── CLAHE (sync với webcam_sleepiness) ──────────────────────────────────
_CLAHE_PRED = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def _apply_clahe_pred(face_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    return cv2.cvtColor(cv2.merge([_CLAHE_PRED.apply(l), a, b]), cv2.COLOR_LAB2BGR)


# ─── MediaPipe / Haar detectors (init 1 lần) ─────────────────────────────
# `import mediapipe` succeeding doesn't guarantee `mp.solutions` loads — some
# wheels raise AttributeError on first access. Catch broadly so the module
# always imports and falls back to Haar.
try:
    import mediapipe as mp
    _DETECTOR_MP = mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    )
    _MP_AVAILABLE = True
except Exception:
    _MP_AVAILABLE = False
    _DETECTOR_MP = None

try:
    _DETECTOR_HAAR = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    _HAAR_AVAILABLE = not _DETECTOR_HAAR.empty()
except Exception:
    _DETECTOR_HAAR = None
    _HAAR_AVAILABLE = False


FACE_PADDING = 0.25


# ─── [v17] Model singleton cache ─────────────────────────────────────────
_MODEL = None
_CLASS_NAMES = None
_TFM = None


def _get_cached_model():
    """Nạp model + class names + transform 1 lần, reuse cho mọi predict_image."""
    global _MODEL, _CLASS_NAMES, _TFM
    if _MODEL is None:
        _MODEL, _CLASS_NAMES = load_model()
        _TFM = get_transform()
    return _MODEL, _CLASS_NAMES, _TFM


def clear_cache() -> None:
    """[v17] Cho test/dev: clear cached model."""
    global _MODEL, _CLASS_NAMES, _TFM
    _MODEL = _CLASS_NAMES = _TFM = None


# ─── Face detection helper ───────────────────────────────────────────────
def _detect_largest_bbox(img_bgr: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    h_img, w_img = img_bgr.shape[:2]

    if _MP_AVAILABLE and _DETECTOR_MP:
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        res = _DETECTOR_MP.process(img_rgb)
        if res.detections:
            best = max(
                res.detections,
                key=lambda d: d.location_data.relative_bounding_box.width
                            * d.location_data.relative_bounding_box.height,
            )
            bb = best.location_data.relative_bounding_box
            x = int(bb.xmin * w_img)
            y = int(bb.ymin * h_img)
            w = int(bb.width * w_img)
            h = int(bb.height * h_img)
            if w > 0 and h > 0:
                return (x, y, w, h)

    if _HAAR_AVAILABLE and _DETECTOR_HAAR is not None:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        faces = _DETECTOR_HAAR.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) > 0:
            x, y, w, h = max(faces, key=lambda b: b[2] * b[3])
            return (int(x), int(y), int(w), int(h))

    return None


# ─── Predict ─────────────────────────────────────────────────────────────
@torch.inference_mode()
def predict_image(image_path: str):
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Không tìm thấy file ảnh: {image_path}")

    model, class_names, tfm = _get_cached_model()

    img_bgr = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img_bgr is None:
        raise ValueError(f"Không đọc được ảnh: {image_path}")

    bbox = _detect_largest_bbox(img_bgr)
    if bbox is not None:
        crop = crop_face_with_padding(img_bgr, bbox, padding=FACE_PADDING)
        if crop is None or crop.size == 0:
            face_bgr = img_bgr
            print("[WARN] Crop suy biến → dùng toàn ảnh.")
        else:
            face_bgr = crop
    else:
        face_bgr = img_bgr
        print("[WARN] Không tìm thấy khuôn mặt → dùng toàn bộ ảnh (có thể dự đoán sai).")

    # CLAHE sync với webcam pipeline
    face_bgr = _apply_clahe_pred(face_bgr)
    img_pil = Image.fromarray(cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB))

    x = tfm(img_pil).unsqueeze(0).to(DEVICE)
    probs = torch.softmax(model(x), dim=1)[0]
    pred_idx = int(torch.argmax(probs).item())

    results = {cls: float(probs[i].item()) for i, cls in enumerate(class_names)}
    return class_names[pred_idx], float(probs[pred_idx].item()), results


# ─── Main ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        image_path = sys.argv[1].strip('"').strip("'")
    else:
        image_path = input("Nhập đường dẫn ảnh: ").strip().strip('"').strip("'")

    try:
        pred_class, confidence, all_probs = predict_image(image_path)
        print(f"\nDự đoán  : {pred_class}")
        print(f"Độ tin cậy: {confidence:.2%}")
        print("\nXác suất từng lớp:")
        for cls, prob in sorted(all_probs.items(), key=lambda x: -x[1]):
            bar = "#" * int(prob * 30)
            print(f"  {cls:<15} {prob:.2%}  {bar}")
    finally:
        if _MP_AVAILABLE and _DETECTOR_MP:
            _DETECTOR_MP.close()
