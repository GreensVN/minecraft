# Sleepiness Detection v17

Hệ thống phát hiện buồn ngủ real-time qua webcam, tích hợp MediaPipe FaceMesh +
MobileNetV2 CNN + ONNX Runtime.

**v17** sửa hàng loạt bug đã phát hiện khi review toàn bộ codebase và đồng bộ
hoá pipeline giữa ONNX, PyTorch, và Classroom path.

---

## Thay đổi v17

### Bug fixes

| Lỗi | File | Mô tả | Fix |
|-----|------|-------|-----|
| PyTorch path thiếu EWMA | `webcam_sleepiness.py` | Trước đây ONNX có EWMAPredictor, PyTorch dùng lambda → HUD nhảy nhót | Bọc PyTorch model trong `TorchPredictor` + `EWMAPredictor` |
| P(ngủ) sai khi >2 class | `webcam_sleepiness.py` | So sánh chuỗi `cnn_label != "binh_thuong"` rồi gán confidence top-1 ≠ P(ngủ) | Dùng `predict_all_probs()` + `get_normal_class_idx()`: `P_sleep = 1 - probs[normal_idx]` |
| `predictor.reset()` chỉ chạy ONNX | `webcam_sleepiness.py` | PyTorch path không reset state | Reset cả 2 path |
| EAR waveform nhảy giả khi mất mặt | `webcam_sleepiness.py` | Push 1.0 → đường EAR nhảy lên đỉnh | Push NaN; vẽ waveform skip NaN segments |
| BPM Frozen Fix trigger nhầm sau calib | `webcam_sleepiness.py` | `_last_blink_time = time.time()` khi chưa có blink | Init `None`, chỉ check khi đã có blink đầu tiên |
| CNN worker silent fail | `webcam_sleepiness.py` | Exception bị swallow vô hạn | Đếm 5 lỗi liên tiếp → tự dừng + log |
| Lỗi class mismatch khó debug | `utils_model.py` | ValueError không chỉ ra file nào sai | In rõ `model_path` + `classes_path` + shape |
| pygame.mixer init lúc import | `audio_warning.py` | Side effect headless/CI | Defer `pgmixer.init()` đến lần đầu cần |
| `predict_image()` load model mỗi lần | `predict_sleepiness.py` | Load `.pth` từ disk mỗi gọi | Cache module-level singleton |
| Centroid tracker gán cùng bbox cho 2 track | `classroom_monitor.py` | `argmin` không loại trừ | Greedy assignment + mark-used |
| ASI tính sai khi mất landmark | `classroom_monitor.py` | Default `ear=0.28` đẩy PERCLOS giảm giả | Đẩy NaN, skip NaN trong PERCLOS/yawn |
| `_rand_bbox_eye_region` không guard | `train_sleepiness.py` | `eye_frac=0` → `eye_h_max=0` | Fallback toàn ảnh |
| Calibration quantize dùng random | `quantize_onnx.py` | Gaussian không match phân phối ảnh | CLI `--calib-dir data/val` dùng ảnh thực |
| `prepare_faces.py` không resume | `prepare_faces.py` | Chạy lại ghi đè tất cả | Skip ảnh đã tồn tại trừ `--force` |

### Tính năng mới

| Tính năng | Mô tả |
|-----------|-------|
| **face_geometry.py** | Tách EAR/MAR/Head Pose ra module dùng chung (DRY giữa webcam + classroom) |
| **face_crop.py** | DRY `crop_face_with_padding(img, bbox, padding)` thay 3 bản sao copyMakeBorder |
| **config.py** | Dataclass `AppConfig` + `AppConfig.load("config.yaml")` để override magic numbers |
| **Hotkeys** | `Q`=quit, `M`=mute audio, `S`=snapshot, `R`=reset EWMA + BPM |
| **HUD upgrades** | FPS counter + Audio mute indicator (OK/MUTE/OFF) |
| **`OnnxPredictor.predict_all_probs`** | Alias khớp interface `EWMAPredictor.predict_all_probs` |
| **`TorchPredictor.predict_all_probs`** | Cho phép EWMA hoạt động trên PyTorch path |
| **Train resume** | `--resume`, `--epochs`, `--lr`, `--batch-size`, `--backbone` argparse |
| **Train checkpoint epoch** | Lưu `epoch` vào checkpoint để resume |
| **AudioWarner.test()** | Phát thử cấp 1 + 2 cho CLI debug |
| **Export verify L1 + KL** | Thêm L1 norm + KL divergence cạnh L∞ |
| **CSV epoch timestamp** | `classroom_monitor` ghi cả epoch timestamp |

---

## Cài đặt

```bash
pip install -r requirements.txt
```

**Tùy chọn thêm:**
```bash
pip install pygame        # Âm thanh đa nền tảng (khuyến nghị)
pip install onnxruntime-gpu   # CUDA GPU inference (thay onnxruntime)
```

---

## Quy trình chạy

### 1. Chuẩn bị dữ liệu
```bash
python prepare_faces.py
```

### 2. Huấn luyện mô hình
```bash
python train_sleepiness.py
```

### 3. Xuất ONNX (khuyến nghị)
```bash
python export_onnx.py --verify
```

### 4. Chạy webcam

**Chế độ ONNX (nhanh hơn 2–5x, khuyến nghị):**
```bash
python webcam_sleepiness.py --onnx
```

**Chế độ PyTorch:**
```bash
python webcam_sleepiness.py
```

### 5. (Tùy chọn) Quantize INT8
```bash
python quantize_onnx.py --verify --benchmark
# Sau đó chạy với model INT8:
python webcam_sleepiness.py --onnx --onnx-path sleepiness_model_int8.onnx
```

---

## Kiến trúc hệ thống

```
webcam frame
    │
    ├─ MediaPipe FaceMesh ──► EAR / MAR / Head Pose (EPnP)
    │                              │
    │                         IQR Calibration
    │
    └─ Face Crop
           │
        CLAHE ──► ONNX (EPProvider auto) ──► EWMAPredictor
                                                    │
                                          Multi-stage Alert (0/1/2)
                                                    │
                                          AudioWarner.warn(level)
```

---

## Điều khiển

| Phím | Hành động |
|------|-----------|
| `Q` | Thoát chương trình |

---

## Cấu trúc thư mục

```
sleepiness_project_v14/
├── webcam_sleepiness.py    # Main: phát hiện real-time
├── train_sleepiness.py     # Huấn luyện MobileNetV2
├── utils_model.py          # OnnxPredictor, EWMAPredictor, build_model
├── prepare_faces.py        # Cắt khuôn mặt từ raw_data
├── export_onnx.py          # Xuất PyTorch → ONNX
├── audio_warning.py        # [v14] Cảnh báo âm thanh
├── classroom_monitor.py    # [v15] Giám sát đa học sinh (YOLOv8 + SORT + ASI)
├── quantize_onnx.py        # [v14] FP32 → INT8
├── requirements.txt
├── data/
│   ├── train/
│   │   ├── binh_thuong/
│   │   └── thieu_ngu/
│   └── val/
│       ├── binh_thuong/
│       └── thieu_ngu/
└── raw_data/               # Ảnh gốc chưa xử lý
```
