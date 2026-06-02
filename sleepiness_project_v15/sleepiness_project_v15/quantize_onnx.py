"""
quantize_onnx.py — Lượng tử hóa mô hình ONNX từ FP32 xuống INT8 (v14).

Lợi ích:
  - Dung lượng file giảm ~4x (từ ~14 MB xuống ~3.5 MB)
  - Tốc độ CPU inference tăng 150–200% nhờ các lệnh SIMD/AVX2 integer
  - Độ chính xác gần như giữ nguyên (mất < 0.5–1% trên tập val)

Yêu cầu:
    pip install onnxruntime onnx

Cách dùng:
    python quantize_onnx.py                            # FP32 → INT8 static
    python quantize_onnx.py --dynamic                  # FP32 → INT8 dynamic (nhanh hơn, kém hơn)
    python quantize_onnx.py --input my_model.onnx      # Chỉ định file đầu vào
    python quantize_onnx.py --verify                   # Kiểm tra sai số sau quantize

Chạy sau khi đã có sleepiness_model.onnx (tạo bởi export_onnx.py).
"""

import argparse
import logging
import os
import time

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ─── Static Quantization (khuyến nghị) ───────────────────────────────────────

def _make_calibration_data_reader(img_size: int = 224, n_samples: int = 100,
                                  calib_dir: str = None):
    """
    [v17] Calibration DataReader.

    Nếu calib_dir tồn tại và chứa ảnh, ưu tiên dùng ảnh thực (resize + normalize
    ImageNet); fallback random Gaussian nếu không.
    """
    try:
        from onnxruntime.quantization import CalibrationDataReader
    except ImportError:
        return None

    real_samples = []
    if calib_dir:
        import os, glob, cv2
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
        std  = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
        paths = []
        for ext in ("*.jpg", "*.jpeg", "*.png"):
            paths.extend(glob.glob(os.path.join(calib_dir, "**", ext), recursive=True))
        np.random.shuffle(paths)
        for p in paths[:n_samples]:
            try:
                img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is None: continue
                img = cv2.resize(img, (img_size, img_size))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                x = img.transpose(2, 0, 1).astype(np.float32) / 255.0
                x = (x - mean) / std
                real_samples.append({"input": np.expand_dims(x, 0)})
            except Exception:
                pass
        logger.info(f"[Quant] Calibration ảnh thực: {len(real_samples)} mẫu từ {calib_dir}")

    if not real_samples:
        logger.info(f"[Quant] Calibration fallback: {n_samples} mẫu random Gaussian")
        real_samples = [
            {"input": np.random.randn(1, 3, img_size, img_size).astype(np.float32)}
            for _ in range(n_samples)
        ]

    class _Reader(CalibrationDataReader):
        def __init__(self, data):
            self._data = data
            self._idx = 0
        def get_next(self):
            if self._idx >= len(self._data):
                return None
            item = self._data[self._idx]
            self._idx += 1
            return item

    return _Reader(real_samples)


def quantize_static(input_path: str, output_path: str, img_size: int = 224, calib_dir: str = None) -> None:
    """
    INT8 Static Quantization — cần calibration data để tính activation range.
    Cho kết quả tốt hơn Dynamic; phù hợp deployment production.
    """
    try:
        from onnxruntime.quantization import quantize_static, QuantType, QuantFormat
        from onnxruntime.quantization.shape_inference import quant_pre_process
    except ImportError:
        raise ImportError(
            "Cần onnxruntime >= 1.14. Cài: pip install --upgrade onnxruntime"
        )

    # Bước 1: Shape inference (cần thiết để quantize hoạt động đúng trên MobileNetV2)
    preprocessed_path = input_path + ".preprocessed.onnx"
    logger.info(f"[Quant] Tiền xử lý shape inference → {preprocessed_path}")
    quant_pre_process(input_path, preprocessed_path, skip_optimization=False)

    # Bước 2: Tạo calibration reader
    logger.info("[Quant] Chuẩn bị calibration data (100 mẫu ngẫu nhiên) ...")
    reader = _make_calibration_data_reader(img_size=img_size, n_samples=100, calib_dir=calib_dir)
    if reader is None:
        logger.warning("[Quant] CalibrationDataReader không khả dụng, fallback sang Dynamic.")
        quantize_dynamic(input_path, output_path)
        return

    # Bước 3: Quantize
    # [v21] `optimize_model` đã bị loại khỏi quantize_static trong onnxruntime
    # mới (tối ưu hoá giờ nằm trong quant_pre_process ở Bước 1). Truyền nó sẽ gây
    # TypeError. Chỉ dùng các tham số còn được hỗ trợ.
    #
    # [v21] per_channel=True có thể vỡ ở khâu quantize_bias_static của lớp Gemm
    # cuối ("operands could not be broadcast (N,) (num_classes,)"). Thử
    # per_channel=True trước (độ chính xác cao hơn) rồi tự hạ xuống False nếu lỗi.
    def _run(per_channel: bool):
        quantize_static(
            model_input=preprocessed_path,
            model_output=output_path,
            calibration_data_reader=reader,
            quant_format=QuantFormat.QOperator,   # QOperator = nhanh nhất trên CPU
            per_channel=per_channel,
            weight_type=QuantType.QInt8,
            activation_type=QuantType.QUInt8,
        )

    t0 = time.time()
    try:
        _run(per_channel=True)
    except ValueError as e:
        logger.warning(
            f"[Quant] per_channel=True thất bại ({e}); thử lại per_channel=False."
        )
        # CalibrationDataReader đã bị tiêu thụ hết → tạo lại trước khi thử lần 2.
        reader = _make_calibration_data_reader(
            img_size=img_size, n_samples=100, calib_dir=calib_dir
        )
        _run(per_channel=False)
    elapsed = time.time() - t0

    # Dọn file trung gian
    if os.path.exists(preprocessed_path):
        os.remove(preprocessed_path)

    _log_size_compare(input_path, output_path, elapsed)


def quantize_dynamic(input_path: str, output_path: str) -> None:
    """
    INT8 Dynamic Quantization — không cần calibration data.
    Nhanh hơn để setup, nhưng runtime inference kém hơn Static một chút.
    Phù hợp khi không có tập dữ liệu calibration.
    """
    try:
        from onnxruntime.quantization import quantize_dynamic as _qd, QuantType
    except ImportError:
        raise ImportError(
            "Cần onnxruntime >= 1.14. Cài: pip install --upgrade onnxruntime"
        )

    logger.info("[Quant] Chế độ: Dynamic Quantization (không cần calibration data)")
    t0 = time.time()
    # [v21] onnxruntime đã loại bỏ `optimize_model` khỏi quantize_dynamic (và một
    # số bản cũ chưa có `per_channel`). Chỉ truyền tham số mà signature thực sự
    # chấp nhận để không vỡ giữa các phiên bản.
    import inspect
    qd_params = set(inspect.signature(_qd).parameters)
    kwargs = {"weight_type": QuantType.QInt8}
    if "per_channel" in qd_params:
        kwargs["per_channel"] = True
    _qd(model_input=input_path, model_output=output_path, **kwargs)
    elapsed = time.time() - t0
    _log_size_compare(input_path, output_path, elapsed)


def _log_size_compare(input_path: str, output_path: str, elapsed: float) -> None:
    size_in  = os.path.getsize(input_path)  / (1024 ** 2)
    size_out = os.path.getsize(output_path) / (1024 ** 2)
    ratio    = size_in / size_out if size_out > 0 else 0
    logger.info(
        f"✅ Hoàn tất trong {elapsed:.1f}s\n"
        f"   FP32: {size_in:.1f} MB → INT8: {size_out:.1f} MB  "
        f"(giảm {ratio:.1f}x)"
    )


# ─── Kiểm tra sai số sau quantize ────────────────────────────────────────────

def verify_accuracy(
    fp32_path: str,
    int8_path: str,
    img_size: int = 224,
    n_tests: int = 50,
) -> float:
    """
    So sánh softmax output của FP32 vs INT8 trên n_tests ảnh ngẫu nhiên.
    Trả về sai số trung bình L∞.
    """
    import onnxruntime as ort

    logger.info(f"[Verify] So sánh {fp32_path} vs {int8_path} trên {n_tests} mẫu ...")

    sess_fp32 = ort.InferenceSession(fp32_path,  providers=["CPUExecutionProvider"])
    sess_int8 = ort.InferenceSession(int8_path,  providers=["CPUExecutionProvider"])
    inp_name  = sess_fp32.get_inputs()[0].name

    diffs = []
    for _ in range(n_tests):
        x = np.random.randn(1, 3, img_size, img_size).astype(np.float32)

        logits_fp32 = sess_fp32.run(None, {inp_name: x})[0][0]
        logits_int8 = sess_int8.run(None, {inp_name: x})[0][0]

        def _softmax(z):
            e = np.exp(z - z.max())
            return e / e.sum()

        diff = float(np.abs(_softmax(logits_fp32) - _softmax(logits_int8)).max())
        diffs.append(diff)

    mean_diff = float(np.mean(diffs))
    max_diff  = float(np.max(diffs))
    logger.info(
        f"[Verify] Sai số L∞ — Trung bình: {mean_diff:.4f}  |  Tối đa: {max_diff:.4f}\n"
        f"         {'✅ PASS (< 0.02)' if max_diff < 0.02 else '⚠️  WARN (> 0.02)'}"
    )
    return mean_diff


# ─── Benchmark tốc độ ────────────────────────────────────────────────────────

def benchmark(path: str, img_size: int = 224, n_runs: int = 200, label: str = "") -> float:
    """Đo thời gian suy luận trung bình (ms/frame) trên CPU."""
    import onnxruntime as ort

    sess     = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name
    x        = np.random.randn(1, 3, img_size, img_size).astype(np.float32)

    # Warm-up
    for _ in range(10):
        sess.run(None, {inp_name: x})

    t0 = time.perf_counter()
    for _ in range(n_runs):
        sess.run(None, {inp_name: x})
    elapsed_ms = (time.perf_counter() - t0) / n_runs * 1000

    logger.info(f"[Bench] {label or path}: {elapsed_ms:.2f} ms/frame (avg {n_runs} runs)")
    return elapsed_ms


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lượng tử hóa mô hình ONNX FP32 → INT8"
    )
    parser.add_argument(
        "--input",  default="sleepiness_model.onnx",
        help="File ONNX FP32 đầu vào (mặc định: sleepiness_model.onnx)"
    )
    parser.add_argument(
        "--output", default="sleepiness_model_int8.onnx",
        help="File ONNX INT8 đầu ra (mặc định: sleepiness_model_int8.onnx)"
    )
    parser.add_argument(
        "--dynamic", action="store_true",
        help="Dùng Dynamic quantization (không cần calibration data, kém hơn Static)"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="So sánh sai số FP32 vs INT8 sau khi quantize"
    )
    parser.add_argument(
        "--benchmark", action="store_true",
        help="Đo tốc độ FP32 vs INT8 sau khi quantize"
    )
    parser.add_argument(
        "--img-size", type=int, default=224,
        help="Kích thước ảnh đầu vào (mặc định: 224)"
    )
    parser.add_argument(
        "--calib-dir", default=None,
        help="[v17] Thư mục ảnh thực dùng cho static calibration (vd: data/val)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error(
            f"Không tìm thấy '{args.input}'. "
            f"Chạy export_onnx.py trước."
        )
        return

    if args.dynamic:
        quantize_dynamic(args.input, args.output)
    else:
        quantize_static(args.input, args.output, img_size=args.img_size, calib_dir=args.calib_dir)

    if args.verify:
        verify_accuracy(args.input, args.output,
                        img_size=args.img_size, n_tests=100)

    if args.benchmark:
        t_fp32 = benchmark(args.input,  args.img_size, label="FP32")
        t_int8 = benchmark(args.output, args.img_size, label="INT8")
        speedup = t_fp32 / t_int8 if t_int8 > 0 else 0
        logger.info(f"[Bench] Tăng tốc: {speedup:.2f}x  ({t_fp32:.1f} ms → {t_int8:.1f} ms)")


if __name__ == "__main__":
    main()
