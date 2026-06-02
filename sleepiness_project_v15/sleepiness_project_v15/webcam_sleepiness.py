"""
webcam_sleepiness.py — Phát hiện buồn ngủ real-time qua webcam.

UPGRADES v21:
  ✅ [BUG FIX]  Thread-safe CLAHE: Sử dụng ThreadSafeCLAHE từ utils_model thay vì
                shared cv2.CLAHE instance để tránh race conditions.
  ✅ [BUG FIX]  CNN worker auto-restart: Implement exponential backoff và health monitoring.
  ✅ [FEATURE]  Graceful shutdown: Handle SIGTERM/SIGINT properly.

UPGRADES v20:
  ✅ [FEATURE]  --source: nhận webcam index HOẶC đường dẫn video file (chạy offline).
  ✅ [FEATURE]  --no-display / show_window=False: chế độ headless (server, CI, video
                batch) — không gọi cv2.imshow, vẫn chạy đủ pipeline + xuất metrics.
  ✅ [FEATURE]  --max-frames N: dừng sau N khung hình (bounded runs / smoke test).
  ✅ [FEATURE]  --preset / --config: nạp cấu hình qua AppConfig.load_full (preset →
                YAML → env). --no-mirror tắt lật gương (đúng cho video file).
  ✅ [FEATURE]  Tích hợp MetricsCollector: đo detection/inference latency, FPS, alert
                counts; --metrics-json / --metrics-csv xuất báo cáo session khi thoát.
  ✅ [FEATURE]  Tích hợp logging tập trung (logger_config.setup_logging) + --log-file.
  ✅ [BUG FIX]  Worker death surface: khi CNN worker chết (>=5 lỗi liên tiếp) HUD hiện
                "CNN OFF" và log ERROR thay vì âm thầm đứng hình với prediction cũ.
  ✅ [CLEANUP]  Gỡ _predict_face_torch() chết + import thừa (torch/PIL/get_transform/
                DEVICE/math). Worker dùng predictor.predict_all_probs.

UPGRADES v15:
  ✅ [BUG FIX]  Calibration Safety Clamp: ép ear_baseline về [0.20, 0.35].
  ✅ [BUG FIX]  Double CLAHE Fix: CLAHE chỉ áp 1 lần trong vòng lặp chính.

UPGRADES v14:
  ✅ IQR calibration | BPM Frozen Fix | solvePnP EPnP | EWMA | CLAHE | Audio Warning.

UPGRADES v13 được giữ nguyên:
  ✅ Zero-latency deque | Adaptive Calibration | Head Pose | Multi-stage Alert |
     BPM Counter | EAR Waveform | torch.inference_mode() | ONNX Runtime.
"""

import argparse
import collections
import logging
import math
import os
import signal
import sys
import threading
import time
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False

from utils_model import (
    OnnxPredictor, TorchPredictor, EWMAPredictor,
    load_model, get_normal_class_idx, ThreadSafeCLAHE,
)
from audio_warning import get_warner
from metrics import MetricsCollector, LatencyTracker
from logger_config import setup_logging
from face_geometry import (
    LEFT_EYE as _LEFT_EYE,
    RIGHT_EYE as _RIGHT_EYE,
    MOUTH as _MOUTH,
    FACE_OVAL_IDS as _FACE_OVAL_IDS,
    POSE_LM_IDS as _POSE_LM_IDS,
    FACE_3D_POINTS as _FACE_3D_POINTS,
    ear as _ear_fn,
    mar as _mar_fn,
    head_pose as _head_pose_fn,
)

logger = logging.getLogger(__name__)

# ─── Cấu hình ────────────────────────────────────────────────────────────────
# [v18] Tải từ config.py (config.yaml override nếu có). Giá trị mặc định của
# AppConfig trùng khớp với hằng số hard-code trước đây → hành vi không đổi khi
# không có config.yaml.
from config import AppConfig, get_config, set_config

# Module-level tunables. Bound from AppConfig by _apply_config() so that a config
# supplied on the CLI (--config/--preset/env) can be layered in *before* main()
# reads them. Declared here with defaults for import-time safety.
_CFG = get_config()

_DEFAULT_EAR_THRESHOLD = _CFG.ear_threshold_default
_DEFAULT_MAR_THRESHOLD = _CFG.mar_threshold_default
EAR_CALIB_ALPHA = _CFG.ear_calib_alpha
MAR_CALIB_BETA = _CFG.mar_calib_beta
EAR_WARN_FRAMES = _CFG.ear_warn_frames
EAR_ALERT_FRAMES = _CFG.ear_alert_frames
VOTE_RATIO = _CFG.vote_ratio
CNN_SKIP = _CFG.cnn_skip
NO_FACE_RESET_FRAMES = _CFG.no_face_reset_frames
FACE_PADDING = _CFG.face_padding
CAMERA_INDEX = _CFG.camera_index
CALIB_DURATION_SEC = _CFG.calib_duration_sec
CALIB_MIN_SAMPLES = _CFG.calib_min_samples
BPM_WINDOW_SEC = _CFG.bpm_window_sec
BPM_LOW_THRESH = _CFG.bpm_low_thresh
BPM_HIGH_THRESH = _CFG.bpm_high_thresh
BPM_BLINK_TIMEOUT_SEC = _CFG.bpm_blink_timeout_sec
POSE_YAW_IGNORE_DEG = _CFG.pose_yaw_ignore_deg
EWMA_ALPHA = _CFG.ewma_alpha
CLAHE_CLIP_LIMIT = _CFG.clahe_clip_limit
CLAHE_TILE_GRID = tuple(_CFG.clahe_tile_grid)
EAR_BASELINE_MIN = _CFG.ear_baseline_min
EAR_BASELINE_MAX = _CFG.ear_baseline_max

# [v21] Thread-safe CLAHE instance (created once, reused). Rebuilt by _apply_config()
# if the clip limit / tile grid change.
_CLAHE = ThreadSafeCLAHE(clip_limit=CLAHE_CLIP_LIMIT, tile_grid_size=CLAHE_TILE_GRID)


def _apply_config(cfg: AppConfig) -> None:
    """Rebind module-level tunables from an AppConfig and refresh derived objects.

    Lets the CLI build a config (preset → YAML → env) and have it take effect
    before main() runs, without threading every value through call signatures.
    """
    global _CFG, _DEFAULT_EAR_THRESHOLD, _DEFAULT_MAR_THRESHOLD
    global EAR_CALIB_ALPHA, MAR_CALIB_BETA, EAR_WARN_FRAMES, EAR_ALERT_FRAMES
    global VOTE_RATIO, CNN_SKIP, NO_FACE_RESET_FRAMES, FACE_PADDING, CAMERA_INDEX
    global CALIB_DURATION_SEC, CALIB_MIN_SAMPLES, BPM_WINDOW_SEC
    global BPM_LOW_THRESH, BPM_HIGH_THRESH, BPM_BLINK_TIMEOUT_SEC
    global POSE_YAW_IGNORE_DEG, EWMA_ALPHA, CLAHE_CLIP_LIMIT, CLAHE_TILE_GRID
    global EAR_BASELINE_MIN, EAR_BASELINE_MAX, _CLAHE

    _CFG = cfg
    set_config(cfg)
    _DEFAULT_EAR_THRESHOLD = cfg.ear_threshold_default
    _DEFAULT_MAR_THRESHOLD = cfg.mar_threshold_default
    EAR_CALIB_ALPHA = cfg.ear_calib_alpha
    MAR_CALIB_BETA = cfg.mar_calib_beta
    EAR_WARN_FRAMES = cfg.ear_warn_frames
    EAR_ALERT_FRAMES = cfg.ear_alert_frames
    VOTE_RATIO = cfg.vote_ratio
    CNN_SKIP = cfg.cnn_skip
    NO_FACE_RESET_FRAMES = cfg.no_face_reset_frames
    FACE_PADDING = cfg.face_padding
    CAMERA_INDEX = cfg.camera_index
    CALIB_DURATION_SEC = cfg.calib_duration_sec
    CALIB_MIN_SAMPLES = cfg.calib_min_samples
    BPM_WINDOW_SEC = cfg.bpm_window_sec
    BPM_LOW_THRESH = cfg.bpm_low_thresh
    BPM_HIGH_THRESH = cfg.bpm_high_thresh
    BPM_BLINK_TIMEOUT_SEC = cfg.bpm_blink_timeout_sec
    POSE_YAW_IGNORE_DEG = cfg.pose_yaw_ignore_deg
    EWMA_ALPHA = cfg.ewma_alpha
    CLAHE_CLIP_LIMIT = cfg.clahe_clip_limit
    CLAHE_TILE_GRID = tuple(cfg.clahe_tile_grid)
    EAR_BASELINE_MIN = cfg.ear_baseline_min
    EAR_BASELINE_MAX = cfg.ear_baseline_max
    _CLAHE.reconfigure(clip_limit=CLAHE_CLIP_LIMIT, tile_grid_size=CLAHE_TILE_GRID)


# [v17] EAR/MAR delegated to face_geometry
def _ear(lm, ids, w, h):
    return _ear_fn(lm, ids, w, h)

def _mar(lm, ids, w, h):
    return _mar_fn(lm, ids, w, h)


# [v17] head pose delegated to face_geometry
def _get_head_pose(lm, w, h):
    return _head_pose_fn(lm, w, h)


# ─── [v14] CLAHE Preprocessing ───────────────────────────────────────────────

def _apply_clahe(face_bgr: np.ndarray) -> np.ndarray:
    """
    Áp dụng CLAHE (Contrast Limited Adaptive Histogram Equalization) trên ảnh khuôn mặt.

    Lợi ích:
        - Trong điều kiện thiếu sáng (lập trình ban đêm, lái xe trong tối),
          ảnh webcam có noise hạt và độ tương phản thấp.
        - CLAHE cân bằng histogram CỤC BỘ theo từng ô 8×8 pixel, làm nổi bật
          chi tiết mắt mà không khuếch đại noise toàn cục.
        - Áp dụng trên kênh L (luminance) trong không gian LAB để không làm lệch màu.

    Args:
        face_bgr: Ảnh khuôn mặt BGR uint8 (bất kỳ kích thước).
    Returns:
        Ảnh BGR uint8 đã tăng tương phản cục bộ.
    """
    lab = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_clahe = _CLAHE.apply(l)
    lab_clahe = cv2.merge([l_clahe, a, b])
    return cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)


# ─── [v14] Calibration với IQR Filter ───────────────────────────────────────

def run_calibration(
    cap: cv2.VideoCapture,
    mp_face_mesh,
    duration_sec: float = None,
    min_samples: int = None,
    show_window: bool = True,
    mirror: bool = True,
) -> Tuple[float, float]:
    """
    Màn hình hiệu chuẩn 5 giây: thu thập EAR/MAR khi người dùng nhìn thẳng.

    [v20] show_window=False → headless (không cv2.imshow, tự động chạy hết duration).
    [v20] mirror=False → không lật frame (đúng cho video file đã quay sẵn).

    [v14] IQR Filter thay np.median:
        EAR: Loại bỏ 25% mẫu THẤP NHẤT (nghi ngờ do chớp mắt/nheo mắt tình cờ).
             Lấy trung bình 75% giá trị cao hơn → EAR_baseline chính xác hơn.
        MAR: Loại bỏ 25% mẫu CAO NHẤT (nghi ngờ do há miệng tình cờ).
             Lấy trung bình 75% giá trị thấp hơn → MAR_baseline chính xác hơn.

    Tại sao IQR tốt hơn median?
        Median chỉ loại bỏ ảnh hưởng của outlier về mặt thống kê, nhưng
        vẫn có thể bị kéo bởi một cụm nhỏ giá trị bất thường liên tiếp
        (VD: nheo mắt 1 giây liên tục).
        Trimmed mean (IQR) loại bỏ HOÀN TOÀN các mẫu bất thường,
        tính trung bình từ phân phối sạch hơn.

    Returns:
        (ear_threshold, mar_threshold) đã cá nhân hóa theo từng người dùng.
    """
    # Resolve defaults from module globals (which may have been rebound by _apply_config).
    if duration_sec is None:
        duration_sec = CALIB_DURATION_SEC
    if min_samples is None:
        min_samples = CALIB_MIN_SAMPLES

    ear_samples: List[float] = []
    mar_samples: List[float] = []
    t_start = time.time()

    # [v19] Guard chống chia cho 0 nếu gọi với duration_sec <= 0.
    duration_sec = max(float(duration_sec), 1e-3)

    if show_window:
        logger.info("[CALIB] Hãy nhìn thẳng vào camera, mắt mở bình thường ...")
    else:
        logger.info(f"[CALIB] Headless calibration: {duration_sec:.1f}s, min_samples={min_samples}")

    while True:
        elapsed   = time.time() - t_start
        remaining = max(0.0, duration_sec - elapsed)

        ret, frame = cap.read()
        if not ret:
            break

        if mirror:
            frame = cv2.flip(frame, 1)
        h_f, w_f = frame.shape[:2]
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        has_face = False
        if mp_face_mesh is not None:
            res = mp_face_mesh.process(frame_rgb)
            if res.multi_face_landmarks:
                has_face = True
                lm = res.multi_face_landmarks[0].landmark
                ear_l = _ear(lm, _LEFT_EYE,  w_f, h_f)
                ear_r = _ear(lm, _RIGHT_EYE, w_f, h_f)
                ear_samples.append((ear_l + ear_r) / 2.0)
                mar_samples.append(_mar(lm, _MOUTH, w_f, h_f))

        if show_window:
            # HUD
            bar_w  = int((1.0 - remaining / duration_sec) * (w_f - 40))
            bar_h  = 18
            bar_y  = h_f - 50
            cv2.rectangle(frame, (20, bar_y), (w_f - 20, bar_y + bar_h), (80, 80, 80), -1)
            cv2.rectangle(frame, (20, bar_y), (20 + bar_w, bar_y + bar_h), (0, 200, 80), -1)

            msg    = f"HIEU CHUAN: {remaining:.1f}s con lai  |  Mau: {len(ear_samples)}"
            status = "Tim thay khuon mat ✓" if has_face else "Chua tim thay mat — di chuyen lai!"
            color  = (0, 200, 80) if has_face else (0, 80, 200)

            cv2.putText(frame, "SLEEPINESS DETECTION v20 — CALIBRATION",
                        (w_f // 2 - 300, 40), cv2.FONT_HERSHEY_DUPLEX, 0.8, (200, 200, 50), 2)
            cv2.putText(frame, "Nhin thang vao camera, mo mat binh thuong",
                        (w_f // 2 - 250, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)
            cv2.putText(frame, msg,    (20, bar_y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)
            cv2.putText(frame, status, (20, bar_y - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)

            cv2.imshow("Sleepiness Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                return _DEFAULT_EAR_THRESHOLD, _DEFAULT_MAR_THRESHOLD

        if elapsed >= duration_sec:
            break

    if len(ear_samples) < min_samples:
        logger.warning(
            f"[CALIB] Không đủ mẫu ({len(ear_samples)} < {min_samples}). "
            f"Dùng ngưỡng mặc định EAR={_DEFAULT_EAR_THRESHOLD}, MAR={_DEFAULT_MAR_THRESHOLD}."
        )
        return _DEFAULT_EAR_THRESHOLD, _DEFAULT_MAR_THRESHOLD

    # ── [v14] IQR Trimmed Mean (thay np.median của v13) ─────────────────────
    # [v21] Lọc NaN/inf trước khi sort và guard slice rỗng. Với min_samples nhỏ
    # (calibration ngắn) hoặc landmark chập chờn, cutoff có thể tạo slice rỗng →
    # np.mean([]) = NaN (kèm RuntimeWarning) → baseline NaN làm mọi so sánh EAR
    # sau đó âm thầm sai. nanmean_safe trả default khi không có mẫu hợp lệ.
    from validators import nanmean_safe

    # EAR: Lấy 75% giá trị CAO NHẤT (loại chớp mắt tình cờ → giá trị thấp)
    ear_sorted = sorted(s for s in ear_samples if math.isfinite(s))
    cutoff_low = int(len(ear_sorted) * 0.25)         # cắt 25% đáy
    valid_ear  = ear_sorted[cutoff_low:] or ear_sorted  # giữ top 75%, fallback toàn bộ
    ear_baseline = nanmean_safe(valid_ear, default=_DEFAULT_EAR_THRESHOLD)

    # MAR: Lấy 75% giá trị THẤP NHẤT (loại ngáp tình cờ → giá trị cao)
    mar_sorted  = sorted(s for s in mar_samples if math.isfinite(s))
    cutoff_high = int(len(mar_sorted) * 0.75)         # giữ bottom 75%
    valid_mar   = mar_sorted[:cutoff_high] or mar_sorted  # fallback toàn bộ nếu slice rỗng
    mar_baseline = nanmean_safe(valid_mar, default=_DEFAULT_MAR_THRESHOLD / MAR_CALIB_BETA)
    # ────────────────────────────────────────────────────────────────────────

    # [v15 FIX] Safety Clamp: Chống Calibration Bias khi người dùng buồn ngủ
    # ngay lúc hiệu chuẩn (mắt lờ đờ, mở không hết cỡ → baseline thấp bất thường).
    #   EAR_MIN=0.20: Giới hạn dưới vật lý — mắt người tỉnh táo không thể < 0.20
    #   EAR_MAX=0.35: Giới hạn trên — mắt mở to nhất (~0.32-0.35 với MediaPipe 680lm)
    _EAR_BASELINE_MIN, _EAR_BASELINE_MAX = EAR_BASELINE_MIN, EAR_BASELINE_MAX
    ear_baseline_raw = ear_baseline
    ear_baseline = float(np.clip(ear_baseline, _EAR_BASELINE_MIN, _EAR_BASELINE_MAX))
    if ear_baseline != ear_baseline_raw:
        logger.warning(
            f"[CALIB] EAR baseline thô={ear_baseline_raw:.3f} nằm ngoài khoảng "
            f"an toàn [{_EAR_BASELINE_MIN}, {_EAR_BASELINE_MAX}] → ép về {ear_baseline:.3f}. "
            f"Kiểm tra ánh sáng hoặc góc camera. Nếu cảnh báo này thường xuyên xuất hiện, "
            f"hãy tăng CALIB_DURATION_SEC lên 8-10 giây."
        )

    ear_thresh = round(EAR_CALIB_ALPHA * ear_baseline, 4)
    mar_thresh = round(MAR_CALIB_BETA  * mar_baseline, 4)

    logger.info(
        f"[CALIB] Hoàn tất! EAR baseline={ear_baseline:.3f} (IQR+clamp) → ngưỡng={ear_thresh:.3f}  |  "
        f"MAR baseline={mar_baseline:.3f} (IQR) → ngưỡng={mar_thresh:.3f}"
    )
    return ear_thresh, mar_thresh


# ─── Vẽ overlay ──────────────────────────────────────────────────────────────

def _draw_status_box(frame: np.ndarray, label: str, color: tuple,
                     x: int, y: int, w: int, h: int) -> None:
    h_f, w_f = frame.shape[:2]
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
    (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    text_w = tw + 10
    text_h = th + baseline + 10
    x_box  = max(0, min(x, w_f - text_w))
    y_top  = y - th - 15 - baseline

    if y_top < 0:
        y_box = max(0, y)
        cv2.rectangle(frame, (x_box, y_box),
                      (x_box + text_w, min(h_f, y_box + text_h)), color, -1)
        cv2.putText(frame, label, (x_box + 5, min(h_f - 2, y_box + th + 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)
    else:
        y_box = max(0, y_top)
        cv2.rectangle(frame, (x_box, y_box),
                      (x_box + text_w, min(h_f, y_box + text_h)), color, -1)
        cv2.putText(frame, label, (x_box + 5, min(h_f - 2, y_box + th + 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)


def _draw_hud(
    frame: np.ndarray,
    ear: float, mar: float,
    ear_frames: int,
    ewma_prob: float,
    pitch: float, yaw: float, roll: float,
    bpm: float,
    ear_threshold: float, mar_threshold: float,
    ear_consec_frames: int,
    has_landmarks: bool = True,
) -> None:
    ear_str  = f"EAR:{ear:.3f}(thr {ear_threshold:.3f})" if has_landmarks else "EAR:N/A(Haar)"
    mar_str  = f"MAR:{mar:.3f}(thr {mar_threshold:.3f})" if has_landmarks else "MAR:N/A(Haar)"
    pose_str = f"Pose Y:{yaw:+.0f}° P:{pitch:+.0f}° R:{roll:+.0f}°" if has_landmarks else "Pose:N/A"
    bpm_warn = ""
    if bpm < BPM_LOW_THRESH:
        bpm_warn = " [mat chan!]" if bpm > 0 else " [ngu gat?]"
    elif bpm > BPM_HIGH_THRESH:
        bpm_warn = " [mat moi!]"
    bpm_str = f"BPM:{bpm:.0f}{bpm_warn}"

    lines = [
        ear_str,
        mar_str,
        f"Nham mat:{ear_frames}/{ear_consec_frames}f",
        f"EWMA sleep:{ewma_prob:.0%}",   # [v14] hiển thị EWMA thay vote %
        pose_str,
        bpm_str,
    ]
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (10, 25 + i * 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200, 200, 200), 1)


def _draw_ear_waveform(
    frame: np.ndarray, ear_history: Deque[float], ear_threshold: float
) -> None:
    if len(ear_history) < 2:
        return
    h_f, w_f = frame.shape[:2]
    pw, ph   = 180, 60
    px, py   = w_f - pw - 10, h_f - ph - 10

    overlay = frame.copy()
    cv2.rectangle(overlay, (px, py), (px + pw, py + ph), (30, 30, 30), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
    cv2.rectangle(frame, (px, py), (px + pw, py + ph), (80, 80, 80), 1)

    y_min, y_max = 0.0, 0.50
    def _to_px(val: float) -> int:
        clamped = max(y_min, min(y_max, val))
        return py + ph - int((clamped - y_min) / (y_max - y_min) * ph)

    thr_py = _to_px(ear_threshold)
    cv2.line(frame, (px, thr_py), (px + pw, thr_py), (0, 80, 200), 1)

    data = list(ear_history)[-pw:]
    step = pw / max(len(data) - 1, 1)
    # [v17] Skip NaN segments
    for i in range(len(data) - 1):
        v0, v1 = data[i], data[i + 1]
        if v0 != v0 or v1 != v1:
            continue
        p0 = (int(px + i * step), _to_px(v0))
        p1 = (int(px + (i + 1) * step), _to_px(v1))
        col = (0, 200, 80) if v0 >= ear_threshold else (0, 80, 255)
        cv2.line(frame, p0, p1, col, 1)

    cv2.putText(frame, "EAR", (px + 4, py + 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 180, 180), 1)


def _draw_alert_border(frame: np.ndarray, level: int, blink_on: bool) -> None:
    if level == 0:
        return
    h_f, w_f = frame.shape[:2]
    color = (0, 220, 220) if level == 1 else (0, 0, 255)
    if level == 2 and not blink_on:
        return
    thickness = 6 if level == 2 else 4
    cv2.rectangle(frame, (0, 0), (w_f - 1, h_f - 1), color, thickness)


# ─── Main loop ───────────────────────────────────────────────────────────────

def main(
    source: str = "0",
    use_onnx: bool = False,
    onnx_path: str = "sleepiness_model.onnx",
    show_window: bool = True,
    mirror: bool = True,
    max_frames: Optional[int] = None,
    metrics_json: Optional[str] = None,
    metrics_csv: Optional[str] = None,
) -> None:
    """
    [v20] Main detection loop với headless + video file + metrics export.

    Args:
        source:       Camera index (vd "0") hoặc đường dẫn video file.
        use_onnx:     Dùng ONNX Runtime thay PyTorch.
        onnx_path:    Đường dẫn file ONNX.
        show_window:  False → headless (không cv2.imshow).
        mirror:       False → không lật frame (đúng cho video file).
        max_frames:   Dừng sau N khung hình (None = chạy vô hạn).
        metrics_json: Đường dẫn xuất session stats JSON (None = không xuất).
        metrics_csv:  Đường dẫn xuất frame metrics CSV (None = không xuất).
    """
    if not _MP_AVAILABLE:
        logger.warning("MediaPipe chưa cài → pip install mediapipe")

    # ── Metrics ──────────────────────────────────────────────────────────────
    metrics = MetricsCollector(window_size=_CFG.metrics_window)
    detect_tracker = LatencyTracker("detection")
    infer_tracker = LatencyTracker("inference")

    # ── Nạp mô hình ──────────────────────────────────────────────────────────
    if use_onnx:
        import json
        if not os.path.exists("class_names.json"):
            raise FileNotFoundError("Cần class_names.json")
        with open("class_names.json", "r", encoding="utf-8") as f:
            class_names = json.load(f)
        base_predictor = OnnxPredictor(onnx_path, class_names)
        predictor = EWMAPredictor(base_predictor, class_names, alpha=EWMA_ALPHA)
        logger.info(f"ONNX + EWMA (alpha={EWMA_ALPHA}): {onnx_path}")
    else:
        model, class_names = load_model()
        base_predictor = TorchPredictor(model, class_names)
        predictor = EWMAPredictor(base_predictor, class_names, alpha=EWMA_ALPHA)
        logger.info(f"PyTorch + EWMA (alpha={EWMA_ALPHA})")

    normal_idx = get_normal_class_idx(class_names)

    # ── [v21] Memory monitor + alert rate limiter + snapshot quota ───────────
    from resource_manager import get_memory_monitor
    from security import get_alert_rate_limiter, get_quota_manager

    # Thresholds sized for a torch + onnxruntime process (the torch import alone
    # is ~600-700MB); 500MB would warn on every healthy startup.
    mem_monitor = get_memory_monitor()
    mem_monitor.warning_threshold = 1500.0
    mem_monitor.critical_threshold = 2500.0
    mem_monitor.set_warning_callback(
        lambda mb: logger.warning(f"[MEM] High memory usage: {mb:.0f}MB")
    )
    mem_monitor.start()
    alert_limiter = get_alert_rate_limiter()
    quota_manager = get_quota_manager()

    # ── Audio ────────────────────────────────────────────────────────────────
    warner = get_warner()

    # ── Mở source (camera hoặc video file) ──────────────────────────────────
    # [v21] Validate the source before opening: a camera index is bounds-checked,
    # a file path is checked for traversal and allowed extension. Network streams
    # (rtsp://, http://) are passed through untouched.
    from security import InputValidator

    is_network_stream = "://" in source
    if source.isdigit():
        is_valid, _kind, cam_index = InputValidator.validate_camera_source(source)
        if not is_valid:
            raise ValueError(f"Invalid camera index: {source!r}")
        cap = cv2.VideoCapture(cam_index)
        is_camera = True
    elif is_network_stream:
        cap = cv2.VideoCapture(source)
        is_camera = True  # treat as unbounded live stream (skip rewind)
        logger.info(f"Network stream source: {source}")
    else:
        try:
            safe_path = InputValidator.validate_file_path(
                source,
                allowed_extensions=InputValidator.ALLOWED_VIDEO_EXTENSIONS,
                must_exist=True,
            )
        except ValueError as e:
            raise ValueError(f"Invalid video source {source!r}: {e}") from e
        cap = cv2.VideoCapture(safe_path)
        is_camera = False
        if not mirror:
            logger.info(f"Video file source: {safe_path} (mirror disabled)")
    if not cap.isOpened():
        raise RuntimeError(f"Không mở được source: {source}")

    # ── MediaPipe FaceMesh ───────────────────────────────────────────────────
    # `import mediapipe` succeeding does NOT guarantee `mp.solutions` is usable —
    # some wheels/environments fail to load the native solution graphs only when
    # first accessed. Guard the construction and fall back to the Haar cascade so
    # the pipeline degrades instead of crashing.
    mp_face_mesh = None
    if _MP_AVAILABLE:
        try:
            mp_face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=False,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        except Exception as e:
            logger.warning(
                f"[MP] FaceMesh init failed ({e}); falling back to Haar cascade. "
                f"EAR/MAR/pose disabled — only CNN + face box available."
            )
            mp_face_mesh = None

    # ── Haar fallback ────────────────────────────────────────────────────────
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    haar = cv2.CascadeClassifier(cascade_path)

    # ── Calibration ──────────────────────────────────────────────────────────
    # Live calibration consumes frames from the capture. For a camera the stream
    # is unbounded so that's fine, but for a finite video file it would silently
    # eat the first N seconds of footage (and on short clips leave nothing for
    # the main loop). For video files we therefore calibrate, then rewind the
    # capture to frame 0 so the whole clip is actually processed. If rewind isn't
    # supported (e.g. RTSP), we skip calibration entirely and use defaults.
    if is_camera:
        ear_threshold, mar_threshold = run_calibration(
            cap, mp_face_mesh, show_window=show_window, mirror=mirror
        )
    else:
        ear_threshold, mar_threshold = run_calibration(
            cap, mp_face_mesh, show_window=show_window, mirror=mirror
        )
        if not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):
            logger.warning(
                "[CALIB] Could not rewind video source after calibration; "
                "the calibrated prefix will not be re-processed."
            )
        else:
            logger.info("[CALIB] Rewound video to frame 0 after calibration.")
    metrics.record_calibration(ear_threshold, mar_threshold)
    ear_consec_frames = EAR_ALERT_FRAMES

    logger.info(f"Ngưỡng cá nhân hóa: EAR={ear_threshold:.3f} | MAR={mar_threshold:.3f}")
    if show_window:
        logger.info("Hotkeys: Q=quit  M=mute  S=snapshot  R=reset | Sleepiness v20")
    else:
        logger.info("Headless mode: chạy đến hết video hoặc max_frames")

    # ── Trạng thái ───────────────────────────────────────────────────────────
    ear_counter    = 0
    cnn_label, cnn_conf    = "binh_thuong", 1.0
    frame_idx      = 0
    no_face_frames = 0

    # BPM tracking
    blink_timestamps: Deque[float] = collections.deque()
    _was_closed     = False
    bpm             = 0.0
    _last_blink_time = None

    # EAR history
    ear_history: Deque[float] = collections.deque(maxlen=150)

    # Head pose
    pitch = yaw = roll = 0.0

    # Nhấp nháy cảnh báo
    blink_timer = 0

    # EWMA prob for sleep class
    ewma_sleep_prob = 0.0

    # FPS + snapshot dir (từ config)
    _fps_t0 = time.time()
    _fps_frames = 0
    fps = 0.0
    _snapshot_dir = _CFG.snapshot_dir
    os.makedirs(_snapshot_dir, exist_ok=True)

    # ── Zero-latency async inference với auto-restart ───────────────────────
    _frame_deque:  Deque = collections.deque(maxlen=1)
    _result_deque: Deque = collections.deque(maxlen=1)
    _running = True
    _worker_alive = [True]  # [v20] Track worker liveness
    _worker_restart_count = [0]  # [v21] Track restart attempts
    _worker_lock = threading.Lock()  # [v21] Protect worker state
    _worker_last_ok = [time.time()]  # [v21] Last successful inference timestamp

    def _cnn_worker() -> None:
        """
        [v21] Background CNN inference với auto-restart và exponential backoff.

        Khi gặp lỗi, worker sẽ:
        1. Log error với full traceback
        2. Đợi exponential backoff (1s, 2s, 4s, 8s, max 30s)
        3. Tự restart nếu _running vẫn True
        4. Sau 5 lần restart liên tiếp thất bại → đánh dấu worker dead
        """
        consecutive_errors = 0
        max_consecutive_errors = 5
        base_backoff = 1.0  # seconds
        max_backoff = 30.0  # seconds

        while _running:
            try:
                if _frame_deque:
                    try:
                        crop_img = _frame_deque.popleft()
                        with infer_tracker.measure():
                            probs = predictor.predict_all_probs(crop_img)
                        _result_deque.append(probs)
                        consecutive_errors = 0  # Reset on success
                        _worker_last_ok[0] = time.time()  # [v21] liveness beacon
                    except Exception as e:
                        consecutive_errors += 1
                        logger.error(
                            f"[CNN WORKER] Inference error ({consecutive_errors}/{max_consecutive_errors}): {e}",
                            exc_info=True
                        )

                        if consecutive_errors >= max_consecutive_errors:
                            logger.error(
                                f"[CNN WORKER] Too many consecutive errors ({consecutive_errors}), "
                                f"marking worker as dead."
                            )
                            with _worker_lock:
                                _worker_alive[0] = False
                            return

                        # Exponential backoff
                        backoff = min(base_backoff * (2 ** (consecutive_errors - 1)), max_backoff)
                        logger.warning(f"[CNN WORKER] Backing off for {backoff:.1f}s before retry...")
                        time.sleep(backoff)
                else:
                    time.sleep(0.002)

            except Exception as e:
                consecutive_errors += 1
                logger.error(
                    f"[CNN WORKER][FATAL] Unhandled exception ({consecutive_errors}/{max_consecutive_errors}): {e}",
                    exc_info=True
                )

                if consecutive_errors >= max_consecutive_errors:
                    with _worker_lock:
                        _worker_alive[0] = False
                    return

                backoff = min(base_backoff * (2 ** (consecutive_errors - 1)), max_backoff)
                time.sleep(backoff)

    def _start_cnn_worker() -> threading.Thread:
        """[v21] Start CNN worker thread."""
        worker = threading.Thread(target=_cnn_worker, daemon=True, name="CNNWorker")
        worker.start()
        logger.info("[CNN WORKER] Started")
        return worker

    worker = _start_cnn_worker()

    # [v21] Worker health monitor.
    #
    # `worker` is held in a single-element list rather than rebound via
    # `nonlocal`: a mid-body `nonlocal` is fragile (must precede first use) and
    # rebinding a closure variable from another thread is easy to get wrong.
    # A list cell is an explicit, thread-visible handle.
    _worker_handle = [worker]
    _RESTART_BUDGET = 3
    _RECOVERY_SEC = 10.0  # healthy for this long → restore one restart credit

    def _monitor_worker_health() -> None:
        """Monitor worker health and attempt restart if needed."""
        last_check = time.time()
        check_interval = 5.0  # seconds

        while _running:
            time.sleep(1.0)
            now = time.time()
            if now - last_check < check_interval:
                continue
            last_check = now

            with _worker_lock:
                if not _worker_alive[0]:
                    if _worker_restart_count[0] < _RESTART_BUDGET:
                        _worker_restart_count[0] += 1
                        logger.warning(
                            f"[HEALTH MONITOR] Worker dead, attempting restart "
                            f"({_worker_restart_count[0]}/{_RESTART_BUDGET})..."
                        )
                        _worker_alive[0] = True
                        _worker_last_ok[0] = now
                        _worker_handle[0] = _start_cnn_worker()
                    else:
                        logger.error(
                            "[HEALTH MONITOR] Worker restart budget exhausted "
                            f"({_RESTART_BUDGET}); leaving CNN OFF."
                        )
                else:
                    # Worker has stayed alive and produced results recently →
                    # gradually restore the restart budget so that isolated
                    # transient failures don't permanently disable inference.
                    if (_worker_restart_count[0] > 0
                            and now - _worker_last_ok[0] >= _RECOVERY_SEC):
                        _worker_restart_count[0] -= 1
                        _worker_last_ok[0] = now
                        logger.info(
                            "[HEALTH MONITOR] Worker healthy; restored one "
                            f"restart credit (now {_worker_restart_count[0]})."
                        )

    health_monitor = threading.Thread(target=_monitor_worker_health, daemon=True, name="HealthMonitor")
    health_monitor.start()

    # [v21] Graceful shutdown handler.
    #
    # signal.signal() only works in the main thread of the main interpreter; when
    # main() is driven from a worker thread (e.g. the API server) installing a
    # handler raises ValueError. Guard so the detection loop still runs — the
    # caller is then responsible for its own shutdown signalling.
    _shutdown_requested = [False]

    def _signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"[SHUTDOWN] Received {sig_name}, initiating graceful shutdown...")
        _shutdown_requested[0] = True

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    else:
        logger.info(
            "[SHUTDOWN] main() not on the main thread → skipping signal handlers; "
            "caller controls shutdown."
        )

    try:
        while True:
            # [v21] Check shutdown request
            if _shutdown_requested[0]:
                logger.info("[SHUTDOWN] Shutdown requested, exiting main loop...")
                break

            # [v20] Check max_frames bound
            if max_frames is not None and frame_idx >= max_frames:
                logger.info(f"Reached max_frames={max_frames}, exiting.")
                break

            ret, frame = cap.read()
            if not ret:
                if not is_camera:
                    logger.info("Video file ended.")
                break

            if mirror:
                frame = cv2.flip(frame, 1)
            h_f, w_f   = frame.shape[:2]
            frame_rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_idx += 1
            now        = time.time()

            faces_bbox: list = []
            ear = 1.0; mar = 0.0
            has_landmarks = False
            pitch = yaw = roll = 0.0

            # ── MediaPipe FaceMesh ───────────────────────────────────────────
            detect_tracker.start()
            if _MP_AVAILABLE and mp_face_mesh:
                res = mp_face_mesh.process(frame_rgb)
                if res.multi_face_landmarks:
                    has_landmarks = True
                    lm = res.multi_face_landmarks[0].landmark

                    ear_l = _ear(lm, _LEFT_EYE,  w_f, h_f)
                    ear_r = _ear(lm, _RIGHT_EYE, w_f, h_f)
                    ear   = (ear_l + ear_r) / 2.0
                    mar   = _mar(lm, _MOUTH, w_f, h_f)

                    try:
                        pitch, yaw, roll = _get_head_pose(lm, w_f, h_f)
                    except Exception:
                        pass

                    xs = []; ys = []
                    for i in _FACE_OVAL_IDS:
                        pt = lm[i]; xs.append(pt.x); ys.append(pt.y)
                    raw_x = int(min(xs) * w_f); raw_y = int(min(ys) * h_f)
                    raw_w = int(max(xs) * w_f) - raw_x
                    raw_h = int(max(ys) * h_f) - raw_y
                    cx = raw_x + raw_w // 2; cy = raw_y + raw_h // 2
                    side = max(raw_w + int(raw_w * FACE_PADDING * 2),
                               raw_h + int(raw_h * FACE_PADDING * 2))
                    faces_bbox.append((cx - side // 2, cy - side // 2, side, side))

            # ── Haar fallback ────────────────────────────────────────────────
            if not faces_bbox and haar is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                dets = haar.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
                if len(dets) > 0:
                    x_h, y_h, w_h, h_h = max(dets, key=lambda b: b[2] * b[3])
                    cx = x_h + w_h // 2; cy = y_h + h_h // 2
                    side = max(w_h + int(w_h * FACE_PADDING * 2),
                               h_h + int(h_h * FACE_PADDING * 2))
                    faces_bbox.append((cx - side // 2, cy - side // 2, side, side))

            detection_ms = detect_tracker.stop()

            # ── EAR counter ──────────────────────────────────────────────────
            yaw_deg_abs = abs(yaw)
            ear_valid = has_landmarks and yaw_deg_abs <= POSE_YAW_IGNORE_DEG
            ear_history.append(ear if has_landmarks else float('nan'))

            if ear_valid:
                is_closed = ear < ear_threshold
                ear_counter = ear_counter + 1 if is_closed else 0

                # BPM: phát hiện sự kiện chớp mắt (nhắm → mở)
                if _was_closed and not is_closed:
                    blink_timestamps.append(now)
                    _last_blink_time = now
                _was_closed = is_closed
            else:
                ear_counter = max(0, ear_counter - 2)

            # Dọn blink timestamps cũ
            while blink_timestamps and now - blink_timestamps[0] > BPM_WINDOW_SEC:
                blink_timestamps.popleft()

            # BPM Frozen Fix
            if (has_landmarks and _was_closed and _last_blink_time is not None
                    and (now - _last_blink_time) > BPM_BLINK_TIMEOUT_SEC):
                bpm = 0.0
            else:
                bpm = len(blink_timestamps) * (60.0 / BPM_WINDOW_SEC)

            # ── CNN inference ────────────────────────────────────────────────
            inference_ms = 0.0
            if faces_bbox:
                no_face_frames = 0
                x, y, w, h = max(faces_bbox, key=lambda b: b[2] * b[3])
                dx = max(0, x); dy = max(0, y)
                dw = min(w_f, x + w) - dx; dh = min(h_f, y + h) - dy

                if frame_idx % CNN_SKIP == 0:
                    pad_top    = max(0, -y);        pad_bottom = max(0, (y + h) - h_f)
                    pad_left   = max(0, -x);        pad_right  = max(0, (x + w) - w_f)
                    y0 = max(0, y); y1 = max(0, min(h_f, y + h))
                    x0 = max(0, x); x1 = max(0, min(w_f, x + w))
                    if y1 > y0 and x1 > x0:
                        crop_valid = frame[y0:y1, x0:x1]
                        if crop_valid is not None and crop_valid.size > 0:
                            face_crop = cv2.copyMakeBorder(
                                crop_valid, pad_top, pad_bottom, pad_left, pad_right,
                                borderType=cv2.BORDER_CONSTANT, value=[0, 0, 0]
                            )
                            face_crop = _apply_clahe(face_crop)
                            _frame_deque.append(face_crop)

                # Retrieve CNN result (inference timing tracked in worker)
                if _result_deque:
                    probs = _result_deque.popleft()
                    cnn_label = class_names[int(np.argmax(probs))]
                    cnn_conf  = float(probs.max())
                    ewma_sleep_prob = float(1.0 - probs[normal_idx])
                    inference_ms = infer_tracker.get_avg()  # Use avg from tracker

                # ── Multi-stage Alert Logic ──────────────────────────────────
                mar_alert  = mar > mar_threshold
                cnn_alert  = ewma_sleep_prob >= VOTE_RATIO
                bpm_alert  = has_landmarks and (bpm < BPM_LOW_THRESH)

                if ear_counter >= ear_consec_frames:
                    alert_level = 2
                    blink_timer = (blink_timer + 1) % 20
                    status = f"!!! NGU GAT !!! ({ear_counter}f)"
                    border_color = (0, 0, 255)
                elif ear_counter >= EAR_WARN_FRAMES or mar_alert or (cnn_alert and bpm_alert):
                    alert_level = 1
                    blink_timer = 0
                    if mar_alert:
                        status = f"NGAP! MAR={mar:.2f}"
                    elif cnn_alert:
                        status = f"THIEU NGU {ewma_sleep_prob:.0%}"
                    else:
                        status = f"ME MOI ({ear_counter}f)"
                    border_color = (0, 220, 220)
                else:
                    alert_level = 0
                    blink_timer = 0
                    status = f"BINH THUONG  {(1 - ewma_sleep_prob) * 100:.0f}%"
                    border_color = (0, 200, 80)

                # [v21] Check worker liveness (thread-safe)
                with _worker_lock:
                    worker_is_alive = _worker_alive[0]

                if not worker_is_alive:
                    status = "CNN OFF (worker died)"
                    border_color = (128, 128, 128)
                    alert_level = 0  # Don't trigger alerts when worker is dead

                # [v21] Rate-limit audible alerts so a sustained level-1/2 state
                # doesn't replay the buzzer every single frame. The HUD/border
                # still reflect the true level; only the sound is throttled.
                if alert_level == 0 or alert_limiter.should_alert(alert_level):
                    warner.warn(alert_level)

                if show_window:
                    _draw_status_box(frame, status, border_color, dx, dy, dw, dh)
                    _draw_alert_border(frame, alert_level, blink_timer < 10)

                    if alert_level == 2:
                        cv2.putText(frame, "!!! NGU GAT !!!",
                                    (w_f // 2 - 165, h_f // 2),
                                    cv2.FONT_HERSHEY_DUPLEX, 1.5, (0, 0, 255), 3)
                    elif alert_level == 1:
                        cv2.putText(frame, "Hay tap trung!",
                                    (w_f // 2 - 145, h_f // 2),
                                    cv2.FONT_HERSHEY_DUPLEX, 1.2, (0, 180, 180), 2)

                    if yaw_deg_abs > POSE_YAW_IGNORE_DEG:
                        cv2.putText(frame, f"EAR tam tat (Yaw {yaw:+.0f}deg)",
                                    (w_f // 2 - 180, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 1)
            else:
                cnn_label, cnn_conf = "khong_ro", 0.0
                ear_counter = 0; blink_timer = 0
                no_face_frames += 1
                if no_face_frames >= NO_FACE_RESET_FRAMES:
                    no_face_frames = 0
                    ewma_sleep_prob = 0.0
                    if hasattr(predictor, "reset"):
                        predictor.reset()
                alert_level = 0

            # ── Record metrics ───────────────────────────────────────────────
            metrics.record_frame(
                detection_time_ms=detection_ms,
                inference_time_ms=inference_ms,
                num_faces=1 if faces_bbox else 0,
                alert_level=alert_level,
            )

            # ── Display ──────────────────────────────────────────────────────
            if show_window:
                _draw_hud(
                    frame, ear, mar, ear_counter, ewma_sleep_prob,
                    pitch, yaw, roll, bpm,
                    ear_threshold, mar_threshold, ear_consec_frames,
                    has_landmarks=has_landmarks,
                )
                _draw_ear_waveform(frame, ear_history, ear_threshold)

                # FPS + audio status
                _fps_frames += 1
                if _fps_frames >= 15:
                    fps = _fps_frames / max(time.time() - _fps_t0, 1e-6)
                    _fps_t0 = time.time(); _fps_frames = 0
                audio_status = "MUTE" if warner.muted else ("OK" if warner.is_available else "OFF")
                cv2.putText(frame, f"FPS:{fps:.1f}  Audio:{audio_status}",
                            (w_f - 220, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (200, 200, 200), 1)

                cv2.imshow("Sleepiness Detection", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                elif key == ord("m"):
                    warner.toggle_mute()
                    logger.info(f"Audio mute = {warner.muted}")
                elif key == ord("s"):
                    # [v21] Enforce snapshot quota: if the directory is over its
                    # size/count limit, prune the oldest snapshots before writing
                    # so an operator leaning on 'S' can't fill the disk.
                    ok, msg = quota_manager.check_snapshot_quota(_snapshot_dir)
                    if not ok:
                        logger.warning(f"[SNAPSHOT] Quota: {msg}; pruning oldest.")
                        quota_manager.cleanup_old_snapshots(_snapshot_dir, keep_count=100)
                    snap = os.path.join(_snapshot_dir, f"snap_{int(time.time())}.jpg")
                    cv2.imwrite(snap, frame)
                    logger.info(f"Snapshot → {snap}")
                elif key == ord("r"):
                    if hasattr(predictor, "reset"):
                        predictor.reset()
                    ear_counter = 0
                    blink_timestamps.clear()
                    _last_blink_time = None
                    logger.info("EWMA + BPM state reset")

    finally:
        _running = False
        try:
            mem_monitor.stop()  # [v21] stop background memory monitor thread
        except Exception:
            pass
        warner.close()
        if cap is not None and cap.isOpened():
            cap.release()
        if show_window:
            cv2.destroyAllWindows()
        if mp_face_mesh is not None:
            mp_face_mesh.close()

        # ── Export metrics ───────────────────────────────────────────────────
        logger.info(metrics.get_summary())
        if metrics_json:
            metrics.export_to_json(metrics_json)
            logger.info(f"Metrics JSON → {metrics_json}")
        if metrics_csv:
            metrics.export_frame_metrics_to_csv(metrics_csv)
            logger.info(f"Frame metrics CSV → {metrics_csv}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sleepiness Detection v20 — Real-time drowsiness detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python webcam_sleepiness.py                          # webcam 0, live display
  python webcam_sleepiness.py --source video.mp4      # video file
  python webcam_sleepiness.py --no-display --max-frames 300  # headless 300 frames
  python webcam_sleepiness.py --preset strict --config my.yaml  # custom config
  python webcam_sleepiness.py --metrics-json out.json --metrics-csv frames.csv
        """
    )
    parser.add_argument(
        "--source", default="0",
        help="Camera index (0, 1, ...) hoặc đường dẫn video file (mặc định: 0)"
    )
    parser.add_argument(
        "--onnx", action="store_true",
        help="Dùng ONNX Runtime thay PyTorch (cần export_onnx.py trước)"
    )
    parser.add_argument(
        "--onnx-path", default="sleepiness_model.onnx",
        help="Đường dẫn file ONNX (mặc định: sleepiness_model.onnx)"
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Headless mode: không hiển thị cửa sổ (cho server/CI/batch video)"
    )
    parser.add_argument(
        "--no-mirror", action="store_true",
        help="Không lật gương frame (đúng cho video file đã quay sẵn)"
    )
    parser.add_argument(
        "--max-frames", type=int, default=None,
        help="Dừng sau N khung hình (None = chạy vô hạn)"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Đường dẫn file YAML config (mặc định: config.yaml)"
    )
    parser.add_argument(
        "--preset", choices=["strict", "balanced", "relaxed"], default=None,
        help="Preset cấu hình: strict (nhạy), balanced (mặc định), relaxed (ít nhạy)"
    )
    parser.add_argument(
        "--metrics-json", default=None,
        help="Xuất session statistics ra file JSON (None = không xuất)"
    )
    parser.add_argument(
        "--metrics-csv", default=None,
        help="Xuất frame metrics ra file CSV (None = không xuất)"
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Ghi log ra file (None = chỉ console)"
    )
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Mức độ log (mặc định: INFO)"
    )
    args = parser.parse_args()

    # ── Setup logging ────────────────────────────────────────────────────────
    setup_logging(
        level=args.log_level,
        log_to_file=args.log_file is not None,
        log_file_path=args.log_file or "sleepiness.log",
        use_colors=True,
        use_json=False,
    )

    # ── Load config (preset → YAML → env) ───────────────────────────────────
    cfg = AppConfig.load_full(
        path=args.config,
        preset=args.preset,
        use_env=True,
        validate=True,
    )
    _apply_config(cfg)
    logger.info(f"Config loaded: preset={args.preset}, file={args.config}")

    # ── Run main ─────────────────────────────────────────────────────────────
    try:
        main(
            source=args.source,
            use_onnx=args.onnx,
            onnx_path=args.onnx_path,
            show_window=not args.no_display,
            mirror=not args.no_mirror,
            max_frames=args.max_frames,
            metrics_json=args.metrics_json,
            metrics_csv=args.metrics_csv,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C)")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        raise

