"""
export_onnx.py — Xuất mô hình PyTorch sang ONNX Runtime.

Chạy một lần sau khi huấn luyện xong:
    python export_onnx.py

Sau đó chạy webcam với ONNX (2-5x nhanh hơn trên CPU, không cần PyTorch):
    python webcam_sleepiness.py --onnx

Kiểm tra mô hình đầu ra:
    python export_onnx.py --verify

Yêu cầu:
    pip install onnx onnxruntime          # CPU inference
    pip install onnxruntime-gpu           # CUDA inference (thay onnxruntime)
"""

import argparse
import json
import logging
import os
import time

import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")


def export(
    model_path: str,
    output_path: str,
    img_size: int,
    opset: int,
) -> None:
    from utils_model import load_model, export_to_onnx

    logging.info(f"Nạp checkpoint: {model_path}")
    model, class_names = load_model(model_path=model_path)
    model.eval()

    logging.info(f"Số lớp phân loại: {len(class_names)} → {class_names}")
    logging.info(f"Xuất ONNX opset={opset}, img_size={img_size} ...")

    t0 = time.time()
    export_to_onnx(model, output_path, img_size=img_size, opset_version=opset)
    elapsed = time.time() - t0

    size_mb = os.path.getsize(output_path) / (1024 ** 2)
    logging.info(f"✅ Hoàn tất trong {elapsed:.1f}s → '{output_path}' ({size_mb:.1f} MB)")


def verify(onnx_path: str, classes_path: str, img_size: int) -> None:
    """
    So sánh đầu ra PyTorch vs ONNX trên 3 tensor ngẫu nhiên.
    Thành công nếu sai số L∞ < 1e-4 trên tất cả các mẫu.
    """
    import torch
    from utils_model import load_model, OnnxPredictor

    logging.info("=== Kiểm tra tính nhất quán PyTorch ↔ ONNX ===")

    model, class_names = load_model()
    model.eval()

    with open(classes_path, "r", encoding="utf-8") as f:
        onnx_class_names = json.load(f)

    predictor = OnnxPredictor(onnx_path, onnx_class_names, img_size=img_size)

    max_diff = 0.0
    n_tests  = 3

    for i in range(n_tests):
        # Ảnh ngẫu nhiên uint8 BGR (giống đầu vào webcam)
        fake_bgr = np.random.randint(0, 256, (img_size, img_size, 3), dtype=np.uint8)

        # ONNX path
        onnx_label, onnx_conf = predictor.predict(fake_bgr)

        # PyTorch path
        import cv2
        from PIL import Image
        from utils_model import get_transform
        tfm = get_transform(img_size)
        face_rgb = cv2.cvtColor(fake_bgr, cv2.COLOR_BGR2RGB)
        x = tfm(Image.fromarray(face_rgb)).unsqueeze(0).to("cpu")
        with torch.inference_mode():
            logits_pt = model(x)
        probs_pt = torch.softmax(logits_pt, dim=1)[0].numpy()

        # ONNX softmax probs (reconstruct)
        import onnxruntime as ort
        x_np = x.numpy()
        logits_onnx = predictor.session.run(None, {predictor.input_name: x_np})[0][0]
        exp = np.exp(logits_onnx - logits_onnx.max())
        probs_onnx = exp / exp.sum()

        diff_linf = float(np.abs(probs_pt - probs_onnx).max())
        diff_l1   = float(np.abs(probs_pt - probs_onnx).sum())
        eps = 1e-12
        kl = float(np.sum(probs_pt * np.log((probs_pt + eps) / (probs_onnx + eps))))
        max_diff = max(max_diff, diff_linf)
        logging.info(
            f"  Test {i+1}: PyTorch={class_names[np.argmax(probs_pt)]}({probs_pt.max():.4f})  "
            f"ONNX={onnx_label}({onnx_conf:.4f})  Linf={diff_linf:.2e} L1={diff_l1:.2e} KL={kl:.2e}"
        )

    if max_diff < 1e-4:
        logging.info(f"✅ PASS — Sai số tối đa L∞ = {max_diff:.2e} < 1e-4")
    else:
        logging.warning(
            f"⚠️  WARN — Sai số L∞ = {max_diff:.2e} ≥ 1e-4. "
            f"Kiểm tra lại phiên bản ONNX opset hoặc normalization."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export PyTorch → ONNX")
    parser.add_argument("--model",   default="sleepiness_model.pth",  help="Checkpoint đầu vào")
    parser.add_argument("--output",  default="sleepiness_model.onnx", help="File ONNX đầu ra")
    parser.add_argument("--classes", default="class_names.json",      help="File nhãn")
    parser.add_argument("--img-size", type=int, default=224,          help="Kích thước ảnh (px)")
    parser.add_argument("--opset",   type=int, default=17,            help="ONNX opset version")
    parser.add_argument("--verify",  action="store_true",
                        help="Kiểm tra sai số PyTorch vs ONNX sau khi xuất")
    args = parser.parse_args()

    export(args.model, args.output, args.img_size, args.opset)

    if args.verify:
        verify(args.output, args.classes, args.img_size)


if __name__ == "__main__":
    main()
