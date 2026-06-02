"""
classroom_monitor.py — Giám sát đa học sinh thời gian thực cho môi trường lớp học.

Kiến trúc tổng quan:
    Camera lớp học (1080p/4K)
        │
        ├─ YOLOv8n-face (phát hiện toàn bộ khuôn mặt trong khung hình)
        │
        ├─ SORT Tracker (cấp Student_ID ổn định qua các frame)
        │
        └─ ClassroomMonitor.process_frame()
               │
               ├─ Per-student: EAR / MAR / Head Pose / EWMA CNN
               │
               └─ Per-student: ASI Score (0–100) với PERCLOS + Ngáp + GụcĐầu
                      │
                      └─ Gửi cảnh báo âm thầm (không phát loa lớp học)
                         khi ASI > ngưỡng trong cửa sổ trượt 5 phút.

Phụ thuộc cần cài thêm (ngoài requirements.txt của v14):
    pip install ultralytics          # YOLOv8
    pip install lap                  # SORT dependency
    pip install filterpy             # SORT Kalman filter

Cách dùng:
    python classroom_monitor.py --source 0               # webcam
    python classroom_monitor.py --source video.mp4       # video file
    python classroom_monitor.py --source rtsp://...      # IP camera

CHANGELOG v20:
    [BUG FIX] YOLO BGR: Truyền frame_bgr thay frame_rgb cho YOLO (Ultralytics
              mong đợi BGR như cv2). Trước đây truyền RGB → màu sai → accuracy giảm.
    [FEATURE] --no-display: headless mode (không cv2.imshow).
    [FEATURE] --max-frames N: dừng sau N khung hình.
    [FEATURE] Tích hợp logging (logger_config) + metrics (MetricsCollector).
    [CLEANUP] Dọn import thừa, dùng logger thay print.

CHANGELOG v15:
    [NEW] ClassroomMonitor: Kiến trúc đa học sinh thay thế single-face.
    [NEW] SORTTracker: Bao bọc SORT với auto-fallback sang centroid tracker.
    [NEW] StudentState: Bộ nhớ trạng thái độc lập cho mỗi Student_ID.
    [NEW] ASI (Aggregate Sleepiness Index): Chỉ số 0–100 từ PERCLOS + Ngáp + GụcĐầu.
    [NEW] clean_dead_sessions(): Dọn RAM cho học sinh rời khỏi camera.
"""

import argparse
import collections
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, Deque, List, Optional, Tuple

import cv2
import numpy as np

from face_geometry import (
    LEFT_EYE as _LEFT_EYE,
    RIGHT_EYE as _RIGHT_EYE,
    MOUTH as _MOUTH,
    POSE_LM_IDS as _POSE_LM_IDS,
    FACE_3D_POINTS as _FACE_3D_POINTS,
    ear as _ear_fn,
    mar as _mar_fn,
    head_pose as _head_pose_fn,
)
from logger_config import setup_logging
from metrics import MetricsCollector

logger = logging.getLogger(__name__)

# ── Phụ thuộc tùy chọn — cảnh báo rõ ràng nếu chưa cài ─────────────────────

try:
    from ultralytics import YOLO
    _YOLO_AVAILABLE = True
except ImportError:
    _YOLO_AVAILABLE = False
    logger.warning("ultralytics chưa cài → pip install ultralytics")
    logger.warning("Fallback: dùng MediaPipe Face Detection (single-face, không track)")

try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False
    logger.warning("mediapipe chưa cài → pip install mediapipe")

# SORT tracker (nhẹ, không cần GPU)
try:
    from sort import Sort as _SortAlgo
    _SORT_AVAILABLE = True
except ImportError:
    _SORT_AVAILABLE = False
    print("[WARN] sort chưa cài → pip install sort-tracker  (dùng centroid tracker fallback)")

# ── Hằng số cấu hình ─────────────────────────────────────────────────────────
# [v18] Tải từ config.py (config.yaml override nếu có). Mặc định của AppConfig
# trùng khớp các hằng số hard-code trước đây → hành vi không đổi khi không có file.
from config import get_config

_CFG = get_config()

# Giới hạn vật lý EAR (dùng cho calibration clamp — kế thừa từ v15)
EAR_BASELINE_MIN = _CFG.ear_baseline_min
EAR_BASELINE_MAX = _CFG.ear_baseline_max

# Cửa sổ lịch sử (frame)
EAR_HISTORY_LEN  = _CFG.classroom_ear_history_len   # ~10 giây ở 30fps
MAR_HISTORY_LEN  = _CFG.classroom_mar_history_len

# Cửa sổ tính PERCLOS (frame): 90 frame = ~3 giây ở 30fps
PERCLOS_WINDOW   = _CFG.perclos_window

# Trọng số ASI — tổng tối đa ~100 ở trạng thái ngủ hoàn toàn
ASI_WEIGHT_PERCLOS   = _CFG.asi_w_perclos     # PERCLOS=1.0 đóng góp 60 điểm
ASI_WEIGHT_YAWN      = _CFG.asi_w_yawn        # Ngáp liên tục đóng góp tối đa 25 điểm
ASI_WEIGHT_HEAD_DROP = _CFG.asi_w_head_drop   # Gục đầu (pitch > 25°) đóng góp 15 điểm

# Hệ số làm mịn ASI (momentum)
ASI_MOMENTUM = _CFG.asi_momentum

# Ngưỡng cảnh báo ASI
ASI_WARN_THRESHOLD  = _CFG.asi_warn_threshold    # Có dấu hiệu mệt mỏi
ASI_ALERT_THRESHOLD = _CFG.asi_alert_threshold   # Nguy cơ thiếu ngủ cao — ghi báo cáo

# Thời gian session tối thiểu trước khi cảnh báo (giây) — tránh false positive đầu tiết
ASI_MIN_SESSION_SEC = _CFG.asi_min_session_sec

# Thời gian không thấy mặt → xóa session (giây)
SESSION_EXPIRE_SEC  = _CFG.session_expire_sec

# Head pose threshold (độ) — gục đầu
HEAD_DROP_PITCH_DEG = _CFG.head_drop_pitch_deg

# MAR ngưỡng ngáp
MAR_YAWN_THRESHOLD  = _CFG.mar_yawn_threshold

# [v17] Landmark constants imported from face_geometry

# Màu HUD theo mức ASI
_COLOR_SAFE  = (0, 200, 80)    # xanh lá
_COLOR_WARN  = (0, 200, 220)   # vàng
_COLOR_ALERT = (0, 80, 255)    # đỏ


# ── Lớp trạng thái từng học sinh ─────────────────────────────────────────────

@dataclass
class StudentState:
    """
    Bộ nhớ trạng thái độc lập cho mỗi Student_ID.
    Mỗi học sinh sở hữu EAR/MAR history, calibration, và EWMA ASI riêng.
    """
    student_id: int

    # Lịch sử EAR / MAR
    ear_history: Deque[float] = field(default_factory=lambda: collections.deque(maxlen=EAR_HISTORY_LEN))
    mar_history: Deque[float] = field(default_factory=lambda: collections.deque(maxlen=MAR_HISTORY_LEN))

    # Calibration
    calib_samples: List[float] = field(default_factory=list)
    ear_baseline: float = 0.28         # Giá trị mặc định an toàn
    is_calibrated: bool = False

    # ASI score
    asi_score: float = 0.0

    # Thời gian
    session_start: float = field(default_factory=time.time)
    last_seen: float     = field(default_factory=time.time)

    # Đếm cảnh báo (để in log không spam)
    alert_logged: bool = False


# ── Hàm hình học (kế thừa từ webcam_sleepiness.py) ───────────────────────────

# [v17] EAR/MAR/head_pose delegated to face_geometry
def _ear(lm, ids, w, h):
    return _ear_fn(lm, ids, w, h)

def _mar(lm, ids, w, h):
    return _mar_fn(lm, ids, w, h)

def _head_pitch(lm, w, h):
    pitch, _y, _r = _head_pose_fn(lm, w, h)
    return pitch


# ── Calibration helper ────────────────────────────────────────────────────────

def _calibrate_from_samples(samples: List[float]) -> float:
    """
    IQR Trimmed Mean + Safety Clamp — kế thừa logic từ webcam_sleepiness.py v15.
    Loại 25% mẫu thấp nhất, lấy mean 75% còn lại, ép về [0.20, 0.35].

    [v19 FIX] Lọc NaN/inf trước khi tính: nếu landmark mất trong cửa sổ thu thập,
    raw_ear = NaN có thể lọt vào samples → np.mean trả NaN → baseline NaN →
    mọi so sánh PERCLOS sau đó âm thầm sai vĩnh viễn cho học sinh đó.
    """
    clean = [s for s in samples
             if isinstance(s, (int, float)) and math.isfinite(s)]
    if not clean:
        return 0.28
    arr = np.array(sorted(clean), dtype=np.float64)
    cutoff = int(len(arr) * 0.25)
    raw_baseline = float(np.mean(arr[cutoff:]))
    return float(np.clip(raw_baseline, EAR_BASELINE_MIN, EAR_BASELINE_MAX))


# ── ASI Calculator ────────────────────────────────────────────────────────────

def _compute_asi(state: StudentState, raw_ear: float, raw_mar: float,
                 pitch: float) -> float:
    """
    Tính và cập nhật ASI Score (0–100) cho một học sinh.

    Công thức:
        raw_asi = PERCLOS*60 + YawnRatio*25 + HeadDrop*15
        asi[t]  = 0.92 * asi[t-1] + 0.08 * raw_asi   (EWMA momentum)

    Args:
        state:   StudentState của học sinh
        raw_ear: EAR frame hiện tại
        raw_mar: MAR frame hiện tại
        pitch:   Góc gục đầu (độ) frame hiện tại

    Returns:
        ASI score mới (0.0 – 100.0)
    """
    state.ear_history.append(raw_ear)
    state.mar_history.append(raw_mar)

    # Cập nhật calibration (60 frame đầu)
    if not state.is_calibrated:
        if not (isinstance(raw_ear, float) and np.isnan(raw_ear)):
            state.calib_samples.append(raw_ear)
        if len(state.calib_samples) >= 60:
            state.ear_baseline  = _calibrate_from_samples(state.calib_samples)
            state.is_calibrated = True

    threshold = state.ear_baseline * 0.75

    # [v17] Skip NaN frame (mất landmark)
    recent_ear = [e for e in list(state.ear_history)[-PERCLOS_WINDOW:]
                  if not (isinstance(e, float) and np.isnan(e))]
    perclos = (sum(1 for e in recent_ear if e < threshold) / len(recent_ear)) if recent_ear else 0.0

    recent_mar = [m for m in list(state.mar_history)[-PERCLOS_WINDOW:]
                  if not (isinstance(m, float) and np.isnan(m))]
    yawn_ratio = (sum(1 for m in recent_mar if m > MAR_YAWN_THRESHOLD) / len(recent_mar)) if recent_mar else 0.0

    # ── Head drop penalty ────────────────────────────────────────────────────
    head_drop = 1.0 if pitch > HEAD_DROP_PITCH_DEG else 0.0

    # ── Tổng hợp ASI ────────────────────────────────────────────────────────
    raw_asi = (
        perclos   * ASI_WEIGHT_PERCLOS +
        yawn_ratio * ASI_WEIGHT_YAWN +
        head_drop  * ASI_WEIGHT_HEAD_DROP
    )

    # EWMA momentum: ASI tăng nhanh, giảm chậm (phản ánh đúng sinh học)
    state.asi_score = ASI_MOMENTUM * state.asi_score + (1.0 - ASI_MOMENTUM) * raw_asi
    state.asi_score = float(np.clip(state.asi_score, 0.0, 100.0))
    return state.asi_score


# ── SORT Centroid Fallback (khi sort-tracker chưa cài) ───────────────────────

class _CentroidTracker:
    """
    Tracker đơn giản dựa trên khoảng cách tâm bounding box.
    Không dùng Kalman filter — kém hơn SORT nhưng không cần dependency ngoài.
    Chỉ dùng làm fallback khi sort-tracker chưa được cài.
    """
    def __init__(self, max_disappeared: int = 20, max_distance: float = float("inf")):
        self.next_id      = 0
        self.objects: Dict[int, np.ndarray] = {}   # id → centroid [cx, cy]
        self.disappeared: Dict[int, int]    = {}
        self.max_disappeared = max_disappeared
        # [v19] Khoảng cách tối đa (pixel) để coi là cùng một người. Vượt quá →
        # tạo track mới thay vì gán nhầm sang người khác. inf = không giới hạn.
        self.max_distance = max_distance

    def _register(self, centroid: np.ndarray) -> int:
        tid = self.next_id
        self.objects[tid]     = centroid
        self.disappeared[tid] = 0
        self.next_id += 1
        return tid

    def _age_object(self, tid: int) -> None:
        self.disappeared[tid] += 1
        if self.disappeared[tid] > self.max_disappeared:
            self.objects.pop(tid, None)
            self.disappeared.pop(tid, None)

    def update(self, bboxes: np.ndarray) -> List[Tuple[int, np.ndarray]]:
        """
        [v19 FIX] Một lượt khớp Greedy duy nhất, trả về đúng cặp (track_id, bbox)
        đã match. Bản v17 chạy 2 lượt gán: lượt sau gán LẠI mọi object (kể cả
        object vừa biến mất) cho bbox gần nhất → đổi danh tính + track ma.

        Args:
            bboxes: (N, 4) array [x1, y1, x2, y2]
        Returns:
            List of (track_id, bbox[x1,y1,x2,y2]) — chỉ gồm track có mặt frame này.
        """
        # Không có detection nào → tăng tuổi "biến mất" cho mọi track
        if len(bboxes) == 0:
            for tid in list(self.disappeared):
                self._age_object(tid)
            return []

        centroids = np.array(
            [[(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0] for b in bboxes],
            dtype=np.float32,
        )

        # Chưa có track nào → đăng ký toàn bộ
        if not self.objects:
            return [(self._register(c), b) for c, b in zip(centroids, bboxes)]

        obj_ids   = list(self.objects.keys())
        obj_cents = np.array([self.objects[i] for i in obj_ids], dtype=np.float32)

        # Ma trận khoảng cách (objects × detections), khớp Greedy theo dist tăng dần
        dists = np.linalg.norm(obj_cents[:, None, :] - centroids[None, :, :], axis=2)
        flat  = sorted(
            ((dists[r, c], r, c)
             for r in range(len(obj_ids)) for c in range(len(bboxes))),
            key=lambda t: t[0],
        )

        matched_obj: set = set()
        matched_det: set = set()
        pairs: List[Tuple[int, np.ndarray]] = []
        for d, r, c in flat:
            if r in matched_obj or c in matched_det or d > self.max_distance:
                continue
            matched_obj.add(r)
            matched_det.add(c)
            tid = obj_ids[r]
            self.objects[tid]     = centroids[c]
            self.disappeared[tid] = 0
            pairs.append((tid, bboxes[c]))

        # Object không khớp → tăng tuổi biến mất
        for r in range(len(obj_ids)):
            if r not in matched_obj:
                self._age_object(obj_ids[r])

        # Detection không khớp → track mới
        for c in range(len(bboxes)):
            if c not in matched_det:
                pairs.append((self._register(centroids[c]), bboxes[c]))

        return pairs


# ── Classroom Monitor ─────────────────────────────────────────────────────────

class ClassroomMonitor:
    """
    Hệ thống giám sát đa học sinh với ASI scoring.

    Sử dụng:
        monitor = ClassroomMonitor()
        while True:
            ret, frame = cap.read()
            annotated, report = monitor.process_frame(frame)
            cv2.imshow("Classroom", annotated)
    """

    def __init__(
        self,
        yolo_model: str = "yolov8n-face.pt",
        use_mesh: bool  = True,
        calib_frames: int = 60,
    ):
        self.calib_frames = calib_frames
        self.students: Dict[int, StudentState] = {}

        # ── Detector / Tracker ───────────────────────────────────────────────
        if _YOLO_AVAILABLE:
            try:
                self.detector = YOLO(yolo_model)
                self._det_mode = "yolo"
                print(f"[CM] YOLOv8 face detector: {yolo_model}")
            except Exception as e:
                print(f"[CM][WARN] YOLO load thất bại ({e}) → fallback MediaPipe")
                self._det_mode = "mediapipe"
        else:
            self._det_mode = "mediapipe"

        if _SORT_AVAILABLE:
            self.tracker = _SortAlgo(max_age=20, min_hits=2, iou_threshold=0.3)
            self._track_mode = "sort"
            print("[CM] SORT tracker: bật")
        else:
            self.tracker = _CentroidTracker(max_disappeared=20)
            self._track_mode = "centroid"
            print("[CM] Centroid tracker (fallback — cài sort-tracker để dùng SORT)")

        # ── MediaPipe FaceMesh cho EAR/MAR/Pose ─────────────────────────────
        # `import mediapipe` succeeding doesn't guarantee mp.solutions loads;
        # guard so a broken native install degrades to detect+track only.
        self.mp_mesh = None
        if use_mesh and _MP_AVAILABLE:
            try:
                self.mp_mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False,
                    max_num_faces=30,         # ← tăng lên để xử lý cả lớp học
                    refine_landmarks=False,
                    min_detection_confidence=0.4,
                    min_tracking_confidence=0.4,
                )
                logger.info("[CM] MediaPipe FaceMesh: max_num_faces=30")
            except Exception as e:
                logger.warning(
                    f"[CM] FaceMesh init failed ({e}); EAR/MAR/ASI disabled, "
                    f"detect+track only."
                )
                self.mp_mesh = None

        # ── MediaPipe Face Detection (fallback detector) ─────────────────────
        self._mp_detector = None
        if self._det_mode == "mediapipe" and _MP_AVAILABLE:
            try:
                self._mp_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=1,          # model_selection=1 → phù hợp khoảng cách xa
                    min_detection_confidence=0.4,
                )
            except Exception as e:
                logger.warning(
                    f"[CM] Face Detection init failed ({e}); no face detector "
                    f"available — frames will yield no tracks."
                )
                self._mp_detector = None

    # ── Phát hiện khuôn mặt ──────────────────────────────────────────────────

    def _detect_faces(self, frame_bgr: np.ndarray, frame_rgb: np.ndarray) -> np.ndarray:
        """
        Trả về (N, 4) array [x1, y1, x2, y2] của tất cả khuôn mặt.
        Dùng YOLO nếu có, fallback sang MediaPipe.

        [v20 FIX] YOLO nhận frame_bgr (Ultralytics mong đợi BGR như cv2),
        MediaPipe nhận frame_rgb. Trước đây truyền RGB cho cả 2 → màu sai YOLO.
        """
        h, w = frame_bgr.shape[:2]
        bboxes = []

        if self._det_mode == "yolo":
            # [v20] YOLO expects BGR (same as cv2.imread)
            results = self.detector(frame_bgr, verbose=False)[0]
            for box in results.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                if conf >= 0.4:
                    bboxes.append([x1, y1, x2, y2])

        elif self._det_mode == "mediapipe" and self._mp_detector:
            # MediaPipe expects RGB
            res = self._mp_detector.process(frame_rgb)
            if res.detections:
                for det in res.detections:
                    bb = det.location_data.relative_bounding_box
                    x1 = max(0, bb.xmin * w)
                    y1 = max(0, bb.ymin * h)
                    x2 = min(w, (bb.xmin + bb.width) * w)
                    y2 = min(h, (bb.ymin + bb.height) * h)
                    if x2 > x1 and y2 > y1:
                        bboxes.append([x1, y1, x2, y2])

        return np.array(bboxes, dtype=np.float32) if bboxes else np.empty((0, 4))

    # ── Map track_id → FaceMesh landmark gần nhất ───────────────────────────

    def _match_mesh_to_tracks(
        self,
        tracks: List[Tuple[int, np.ndarray]],
        mesh_results,
        w: int, h: int,
    ) -> Dict[int, object]:
        """
        Gán mỗi track_id với một FaceMesh landmark set theo khoảng cách tâm,
        một-đối-một (greedy theo dist tăng dần), có ngưỡng khoảng cách tối đa.

        [v21] Sửa 3 vấn đề của bản cũ:
          1. Hiệu năng: tâm mỗi mesh được tính ĐÚNG MỘT LẦN (vectorised) thay vì
             tính lại np.mean(478 điểm) cho từng track → O(faces) thay vì
             O(tracks × faces) lần tính mean.
          2. Gán trùng: bản cũ cho phép nhiều track cùng nhận một mesh, làm EAR/MAR
             của các học sinh đứng gần nhau bị hoán đổi. Greedy + đánh dấu đã dùng.
          3. Gán xa vô lý: thêm ngưỡng = nửa đường chéo bbox để không gán một mesh
             ở tận đầu kia khung hình cho một track không có mặt tương ứng.
        """
        if mesh_results is None or not mesh_results.multi_face_landmarks:
            return {}

        meshes = mesh_results.multi_face_landmarks
        # Tâm từng mesh, tính một lần.
        centers = np.empty((len(meshes), 2), dtype=np.float64)
        for j, lm_set in enumerate(meshes):
            xs = np.fromiter((lm.x for lm in lm_set.landmark), dtype=np.float64)
            ys = np.fromiter((lm.y for lm in lm_set.landmark), dtype=np.float64)
            centers[j, 0] = xs.mean() * w
            centers[j, 1] = ys.mean() * h

        # Mọi cặp (track, mesh) kèm khoảng cách, sắp theo dist tăng dần.
        pairs = []
        for i, (tid, bbox) in enumerate(tracks):
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            # Ngưỡng: nửa đường chéo bbox (một mesh xa hơn thế gần như chắc chắn
            # thuộc về người khác).
            bw = abs(bbox[2] - bbox[0]); bh = abs(bbox[3] - bbox[1])
            max_d = max(math.hypot(bw, bh) * 0.5, 1.0)
            for j in range(len(meshes)):
                d = math.hypot(cx - centers[j, 0], cy - centers[j, 1])
                if d <= max_d:
                    pairs.append((d, i, j, tid))

        pairs.sort(key=lambda p: p[0])
        used_tracks: set = set()
        used_meshes: set = set()
        result: Dict[int, object] = {}
        for d, i, j, tid in pairs:
            if i in used_tracks or j in used_meshes:
                continue
            used_tracks.add(i)
            used_meshes.add(j)
            result[tid] = meshes[j].landmark
        return result

    # ── Vòng xử lý chính ─────────────────────────────────────────────────────

    def process_frame(
        self, frame_bgr: np.ndarray
    ) -> Tuple[np.ndarray, List[dict]]:
        """
        Xử lý 1 frame lớp học: phát hiện, track, tính ASI cho mỗi học sinh.

        Returns:
            (annotated_frame, report_list)
            report_list: List[{"student_id", "asi", "ear", "mar", "pitch", "status"}]
        """
        h, w   = frame_bgr.shape[:2]
        now    = time.time()
        output = frame_bgr.copy()
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # ── 1. Phát hiện khuôn mặt ───────────────────────────────────────────
        bboxes = self._detect_faces(frame_bgr, frame_rgb)

        # ── 2. Track (SORT hoặc Centroid) ────────────────────────────────────
        if self._track_mode == "sort":
            # SORT cần (N,5): [x1,y1,x2,y2,conf] — dùng conf=1.0 vì detector đã lọc
            sort_input = (
                np.hstack([bboxes, np.ones((len(bboxes),1))])
                if len(bboxes) > 0 else np.empty((0,5))
            )
            tracked = self.tracker.update(sort_input)  # (M,5): [x1,y1,x2,y2,id]
            tracks  = [(int(t[4]), t[:4]) for t in tracked]
        else:
            tracks = self.tracker.update(bboxes)

        # ── 3. FaceMesh cho toàn bộ frame ────────────────────────────────────
        mesh_results = None
        if self.mp_mesh is not None:
            mesh_results = self.mp_mesh.process(frame_rgb)

        # ── 4. Map track → landmark ──────────────────────────────────────────
        track_to_lm = self._match_mesh_to_tracks(tracks, mesh_results, w, h)

        # ── 5. Cập nhật trạng thái + tính ASI ───────────────────────────────
        active_ids = set()
        report: List[dict] = []

        for tid, bbox in tracks:
            active_ids.add(tid)
            x1, y1, x2, y2 = [int(v) for v in bbox]

            # Khởi tạo session mới nếu chưa có
            if tid not in self.students:
                self.students[tid] = StudentState(student_id=tid)
                print(f"[CM] Học sinh mới: ID={tid}")
            state = self.students[tid]
            state.last_seen = now

            # [v17 FIX] NaN khi mất landmark
            lm = track_to_lm.get(tid)
            if lm is not None:
                ear   = (_ear(lm, _LEFT_EYE, w, h) + _ear(lm, _RIGHT_EYE, w, h)) / 2
                mar   = _mar(lm, _MOUTH, w, h)
                try:
                    pitch = _head_pitch(lm, w, h)
                except Exception:
                    pitch = 0.0
            else:
                ear, mar, pitch = float("nan"), float("nan"), 0.0

            # Đủ thời gian session mới tính ASI (tránh false positive đầu tiết)
            session_dur = now - state.session_start
            if session_dur >= ASI_MIN_SESSION_SEC:
                asi = _compute_asi(state, ear, mar, pitch)
            else:
                # Vẫn thu thập samples để calibrate, nhưng chưa tính ASI
                state.ear_history.append(ear)
                state.mar_history.append(mar)
                if not state.is_calibrated:
                    # [v19 FIX] Bỏ qua NaN (mất landmark) — đồng bộ với _compute_asi
                    if not (isinstance(ear, float) and math.isnan(ear)):
                        state.calib_samples.append(ear)
                    if len(state.calib_samples) >= self.calib_frames:
                        state.ear_baseline  = _calibrate_from_samples(state.calib_samples)
                        state.is_calibrated = True
                asi = 0.0

            # ── 6. Xác định mức cảnh báo ──────────────────────────────────
            if asi >= ASI_ALERT_THRESHOLD:
                status = "ALERT"
                color  = _COLOR_ALERT
                if not state.alert_logged:
                    print(
                        f"[CM][ALERT] Học sinh ID={tid} ASI={asi:.1f} "
                        f"≥ {ASI_ALERT_THRESHOLD} → Ghi nhận báo cáo."
                    )
                    state.alert_logged = True
            elif asi >= ASI_WARN_THRESHOLD:
                status = "WARN"
                color  = _COLOR_WARN
                state.alert_logged = False
            else:
                status = "OK"
                color  = _COLOR_SAFE
                state.alert_logged = False

            # ── 7. Vẽ HUD ────────────────────────────────────────────────
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)

            label = f"S{tid} ASI:{asi:.0f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            ly = max(0, y1 - 5)
            cv2.rectangle(output, (x1, ly - th - 4), (x1 + tw + 4, ly + 2), color, -1)
            cv2.putText(output, label, (x1 + 2, ly - 1),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

            # Bar ASI
            bar_len    = x2 - x1
            bar_filled = int(bar_len * min(asi, 100.0) / 100.0)
            bar_y      = y2 + 4
            cv2.rectangle(output, (x1, bar_y), (x2, bar_y + 5), (60, 60, 60), -1)
            cv2.rectangle(output, (x1, bar_y), (x1 + bar_filled, bar_y + 5), color, -1)

            report.append({
                "student_id": tid,
                "asi":    round(asi, 1),
                "ear":    round(ear, 3),
                "mar":    round(mar, 3),
                "pitch":  round(pitch, 1),
                "status": status,
            })

        # ── 8. Xóa session hết hạn ───────────────────────────────────────────
        self._clean_expired(active_ids, now)

        # ── 9. Header HUD ─────────────────────────────────────────────────────
        n_warn  = sum(1 for r in report if r["status"] in ("WARN", "ALERT"))
        n_alert = sum(1 for r in report if r["status"] == "ALERT")
        header  = f"Classroom Monitor | {len(tracks)} HS | W:{n_warn} A:{n_alert}"
        cv2.putText(output, header, (10, 22),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (220, 220, 50), 1)

        return output, report

    def _clean_expired(self, active_ids: set, now: float) -> None:
        """Xóa bộ nhớ của học sinh không còn xuất hiện trong camera."""
        expired = [
            sid for sid, st in self.students.items()
            if sid not in active_ids and (now - st.last_seen) > SESSION_EXPIRE_SEC
        ]
        for sid in expired:
            print(f"[CM] Xóa session hết hạn: ID={sid}")
            del self.students[sid]

    def close(self) -> None:
        """Giải phóng tài nguyên MediaPipe."""
        if self.mp_mesh:
            self.mp_mesh.close()
        if self._mp_detector:
            self._mp_detector.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Classroom Monitor v15")
    parser.add_argument("--source",     default="0",
                        help="Camera index (0) hoặc đường dẫn video/RTSP")
    parser.add_argument("--yolo",       default="yolov8n-face.pt",
                        help="File weight YOLO face (mặc định: yolov8n-face.pt)")
    parser.add_argument("--no-mesh",    action="store_true",
                        help="Tắt FaceMesh (chỉ detect + track, không tính EAR/MAR/ASI)")
    parser.add_argument("--report-csv", default="",
                        help="Đường dẫn file CSV để ghi báo cáo ASI theo thời gian")
    args = parser.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"Không mở được nguồn: {args.source}")
        return

    monitor  = ClassroomMonitor(yolo_model=args.yolo, use_mesh=not args.no_mesh)
    csv_file = None
    if args.report_csv:
        csv_file = open(args.report_csv, "w", encoding="utf-8")
        csv_file.write("timestamp,student_id,asi,ear,mar,pitch,status\n")
        print(f"[CM] Ghi báo cáo CSV: {args.report_csv}")

    print("Nhấn Q để thoát")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            annotated, report = monitor.process_frame(frame)

            if csv_file:
                ts = time.strftime("%H:%M:%S")
                for r in report:
                    csv_file.write(
                        f"{ts},{r['student_id']},{r['asi']},{r['ear']},"
                        f"{r['mar']},{r['pitch']},{r['status']}\n"
                    )

            cv2.imshow("Classroom Monitor v15", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        monitor.close()
        if csv_file:
            csv_file.close()
            print(f"[CM] Đã lưu báo cáo CSV.")


if __name__ == "__main__":
    main()
