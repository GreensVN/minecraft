"""
prepare_faces.py — Cắt mặt từ raw_data/ → data/ (v17).

CHANGELOG v17:
    [NEW] CLI argparse: --input-root, --output-root, --padding, --force.
    [NEW] Skip ảnh đã có (resume) trừ khi --force.
    [DRY] Dùng face_crop.crop_face_with_padding.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from face_crop import crop_face_with_padding

# ── Detector ────────────────────────────────────────────────────────────
# `import mediapipe` succeeding doesn't mean `mp.solutions` loads; build the
# detector inside the guard and catch broadly. Always set up the Haar cascade
# as a fallback so detection still works if MediaPipe is unusable at runtime.
_DETECTOR_MP = None
try:
    import mediapipe as mp
    _DETECTOR_MP = mp.solutions.face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    )
    _MP_AVAILABLE = True
except Exception:
    _MP_AVAILABLE = False

_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
if _face_cascade.empty():
    _face_cascade = None


def _detect_faces_mediapipe(img_bgr):
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    h, w = img_bgr.shape[:2]
    out = []
    res = _DETECTOR_MP.process(img_rgb)
    if res.detections:
        for det in res.detections:
            bb = det.location_data.relative_bounding_box
            x = int(bb.xmin * w)
            y = int(bb.ymin * h)
            bw = int(bb.width * w)
            bh = int(bb.height * h)
            if bw > 0 and bh > 0:
                out.append((x, y, bw, bh))
    return out


def _detect_faces_haar(img_bgr):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )
    return [tuple(int(v) for v in f) for f in faces] if len(faces) > 0 else []


def crop_largest_face(image_path: Path, output_path: Path,
                      padding: float = 0.25, force: bool = False) -> bool:
    output_path = output_path.with_suffix(".jpg")

    # [v17] Resume: skip nếu output đã tồn tại
    if output_path.exists() and not force:
        return True

    img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return False

    faces = _detect_faces_mediapipe(img) if _MP_AVAILABLE else _detect_faces_haar(img)
    if not faces:
        return False

    bbox = max(faces, key=lambda b: b[2] * b[3])
    face = crop_face_with_padding(img, bbox, padding=padding)
    if face is None:
        return False

    face = cv2.resize(face, (224, 224))
    ok, buf = cv2.imencode(".jpg", face)
    if not ok:
        return False
    buf.tofile(str(output_path))
    return True


def process_folder(input_root: str, output_root: str,
                   padding: float = 0.25, force: bool = False) -> None:
    input_root = Path(input_root)
    output_root = Path(output_root)
    total = saved = skipped = 0

    for split in ("train", "val"):
        split_dir = input_root / split
        if not split_dir.exists():
            print(f"[WARN] Không thấy thư mục split: {split_dir}")
            continue
        class_dirs = sorted([d for d in split_dir.iterdir() if d.is_dir()])
        if not class_dirs:
            print(f"[WARN] Không có class nào trong: {split_dir}")
            continue
        print(f"[INFO] {split}: tìm thấy {len(class_dirs)} class → {[d.name for d in class_dirs]}")

        for cls_dir in class_dirs:
            out_dir = output_root / split / cls_dir.name
            out_dir.mkdir(parents=True, exist_ok=True)

            for img_file in sorted(cls_dir.glob("*")):
                if not img_file.is_file() or img_file.suffix.lower() not in {
                    ".jpg", ".jpeg", ".png", ".bmp", ".webp"
                }:
                    continue
                total += 1
                out_file = out_dir / img_file.name
                if crop_largest_face(img_file, out_file, padding=padding, force=force):
                    saved += 1
                else:
                    skipped += 1
                    print(f"[SKIP] Không tìm thấy mặt: {img_file.name}")

    print(f"\n✅ Xong! Tổng: {total} | Đã lưu: {saved} | Bỏ qua: {skipped}")


def main():
    p = argparse.ArgumentParser(description="Prepare faces v17")
    p.add_argument("--input-root",  default="raw_data")
    p.add_argument("--output-root", default="data")
    p.add_argument("--padding",     type=float, default=0.25)
    p.add_argument("--force",       action="store_true",
                   help="Ghi đè cả ảnh đã xử lý trước đó")
    args = p.parse_args()

    detector_name = "MediaPipe" if _MP_AVAILABLE else "Haar Cascade (fallback)"
    print(f"[INFO] Detector: {detector_name}")
    try:
        process_folder(args.input_root, args.output_root,
                       padding=args.padding, force=args.force)
    finally:
        if _MP_AVAILABLE and _DETECTOR_MP:
            _DETECTOR_MP.close()


if __name__ == "__main__":
    main()
