"""
async_face_detection.py — Async MediaPipe processing (v21 NEW).

Provides asynchronous face detection and landmark extraction to prevent
blocking the main thread. Uses producer-consumer pattern with threading
for better performance.

Features:
- Non-blocking MediaPipe processing
- Frame dropping strategy when overloaded
- Optimized landmark extraction
- Batch processing support
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Deque, List, Optional, Tuple

import cv2
import numpy as np
from collections import deque

logger = logging.getLogger(__name__)

try:
    import mediapipe as mp
    _MP_AVAILABLE = True
except ImportError:
    _MP_AVAILABLE = False
    logger.warning("MediaPipe not available")


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class DetectionRequest:
    """Request for face detection."""
    frame_id: int
    frame_rgb: np.ndarray
    timestamp: float


@dataclass
class DetectionResult:
    """Result from face detection."""
    frame_id: int
    landmarks: Optional[Any]  # MediaPipe landmarks
    bbox: Optional[Tuple[int, int, int, int]]  # (x, y, w, h)
    processing_time_ms: float
    timestamp: float
    dropped: bool = False


# ─── Async Face Detector ─────────────────────────────────────────────────────

class AsyncFaceDetector:
    """
    [v21 NEW] Asynchronous face detector using MediaPipe.

    Runs MediaPipe FaceMesh in a background thread to avoid blocking
    the main loop. Implements frame dropping when processing falls behind.

    Usage:
        detector = AsyncFaceDetector(max_num_faces=1)
        detector.start()

        # Submit frame
        detector.submit(frame_id, frame_rgb)

        # Get result (non-blocking)
        result = detector.get_result(timeout=0.01)
        if result:
            print(f"Landmarks: {result.landmarks}")

        detector.stop()
    """

    def __init__(
        self,
        max_num_faces: int = 1,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        queue_size: int = 2,
        drop_strategy: str = "oldest",
    ):
        """
        Initialize async face detector.

        Args:
            max_num_faces: Maximum number of faces to detect
            min_detection_confidence: Minimum detection confidence
            min_tracking_confidence: Minimum tracking confidence
            queue_size: Maximum queue size (larger = more latency, smaller = more drops)
            drop_strategy: "oldest" or "newest" when queue is full
        """
        if not _MP_AVAILABLE:
            raise ImportError("MediaPipe not available")

        self.max_num_faces = max_num_faces
        self.min_detection_confidence = min_detection_confidence
        self.min_tracking_confidence = min_tracking_confidence
        self.queue_size = queue_size
        self.drop_strategy = drop_strategy

        # Queues
        self._request_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._result_queue: queue.Queue = queue.Queue(maxsize=queue_size)

        # Worker thread
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._face_mesh: Optional[Any] = None

        # Statistics
        self._frames_submitted = 0
        self._frames_processed = 0
        self._frames_dropped = 0
        self._total_processing_time = 0.0

    def start(self) -> None:
        """Start the async detector."""
        if self._running:
            logger.warning("AsyncFaceDetector already running")
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AsyncFaceDetector"
        )
        self._worker_thread.start()
        logger.info(f"AsyncFaceDetector started (max_faces={self.max_num_faces}, queue_size={self.queue_size})")

    def stop(self) -> None:
        """Stop the async detector."""
        self._running = False
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)

        # Cleanup MediaPipe
        if self._face_mesh is not None:
            try:
                self._face_mesh.close()
            except Exception as e:
                logger.warning(f"Error closing FaceMesh: {e}")
            self._face_mesh = None

        logger.info(
            f"AsyncFaceDetector stopped. Stats: submitted={self._frames_submitted}, "
            f"processed={self._frames_processed}, dropped={self._frames_dropped}"
        )

    def submit(self, frame_id: int, frame_rgb: np.ndarray) -> bool:
        """
        Submit a frame for processing.

        Args:
            frame_id: Unique frame identifier
            frame_rgb: RGB frame

        Returns:
            True if submitted, False if dropped
        """
        self._frames_submitted += 1

        request = DetectionRequest(
            frame_id=frame_id,
            frame_rgb=frame_rgb,
            timestamp=time.time()
        )

        try:
            self._request_queue.put_nowait(request)
            return True
        except queue.Full:
            # Queue full - drop frame according to strategy
            self._frames_dropped += 1

            if self.drop_strategy == "oldest":
                # Drop oldest frame and add new one
                try:
                    self._request_queue.get_nowait()
                    self._request_queue.put_nowait(request)
                    logger.debug(f"Dropped oldest frame, added frame {frame_id}")
                    return True
                except (queue.Empty, queue.Full):
                    pass
            # else: drop newest (current frame)

            logger.debug(f"Dropped frame {frame_id} (queue full)")
            return False

    def get_result(self, timeout: float = 0.0) -> Optional[DetectionResult]:
        """
        Get detection result (non-blocking by default).

        Args:
            timeout: Timeout in seconds (0 = non-blocking)

        Returns:
            DetectionResult or None if no result available
        """
        try:
            return self._result_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_statistics(self) -> dict:
        """Get processing statistics."""
        avg_time = (
            self._total_processing_time / self._frames_processed
            if self._frames_processed > 0
            else 0.0
        )

        drop_rate = (
            self._frames_dropped / self._frames_submitted
            if self._frames_submitted > 0
            else 0.0
        )

        return {
            'frames_submitted': self._frames_submitted,
            'frames_processed': self._frames_processed,
            'frames_dropped': self._frames_dropped,
            'drop_rate': drop_rate,
            'avg_processing_time_ms': avg_time,
            'queue_size': self._request_queue.qsize(),
        }

    def _worker_loop(self) -> None:
        """Background worker loop."""
        # Initialize MediaPipe in worker thread
        try:
            self._face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=self.max_num_faces,
                refine_landmarks=False,
                min_detection_confidence=self.min_detection_confidence,
                min_tracking_confidence=self.min_tracking_confidence,
            )
        except Exception as e:
            logger.error(f"Failed to initialize FaceMesh: {e}")
            self._running = False
            return

        while self._running:
            try:
                # Get request with timeout
                request = self._request_queue.get(timeout=0.1)

                # Process frame
                start_time = time.perf_counter()
                result = self._process_frame(request)
                processing_time = (time.perf_counter() - start_time) * 1000

                result.processing_time_ms = processing_time
                self._total_processing_time += processing_time
                self._frames_processed += 1

                # Put result
                try:
                    self._result_queue.put_nowait(result)
                except queue.Full:
                    # Result queue full - drop oldest result
                    try:
                        self._result_queue.get_nowait()
                        self._result_queue.put_nowait(result)
                    except (queue.Empty, queue.Full):
                        pass

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                time.sleep(0.1)

    def _process_frame(self, request: DetectionRequest) -> DetectionResult:
        """Process a single frame."""
        try:
            results = self._face_mesh.process(request.frame_rgb)

            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark
                bbox = self._extract_bbox(landmarks, request.frame_rgb.shape)

                return DetectionResult(
                    frame_id=request.frame_id,
                    landmarks=landmarks,
                    bbox=bbox,
                    processing_time_ms=0.0,  # Set by caller
                    timestamp=time.time()
                )
            else:
                return DetectionResult(
                    frame_id=request.frame_id,
                    landmarks=None,
                    bbox=None,
                    processing_time_ms=0.0,
                    timestamp=time.time()
                )

        except Exception as e:
            logger.error(f"Frame processing error: {e}")
            return DetectionResult(
                frame_id=request.frame_id,
                landmarks=None,
                bbox=None,
                processing_time_ms=0.0,
                timestamp=time.time()
            )

    def _extract_bbox(self, landmarks, shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
        """Extract bounding box from landmarks."""
        h, w = shape[:2]

        # Use face oval landmarks for bbox
        from face_geometry import FACE_OVAL_IDS

        xs = [landmarks[i].x * w for i in FACE_OVAL_IDS]
        ys = [landmarks[i].y * h for i in FACE_OVAL_IDS]

        x_min, x_max = int(min(xs)), int(max(xs))
        y_min, y_max = int(min(ys)), int(max(ys))

        return (x_min, y_min, x_max - x_min, y_max - y_min)


# ─── Batch Face Detector ─────────────────────────────────────────────────────

class BatchFaceDetector:
    """
    [v21 NEW] Batch face detector for processing multiple frames at once.

    Useful for offline video processing or when multiple camera streams
    need to be processed together.
    """

    def __init__(
        self,
        max_num_faces: int = 1,
        min_detection_confidence: float = 0.5,
        batch_size: int = 4,
    ):
        """
        Initialize batch face detector.

        Args:
            max_num_faces: Maximum faces per frame
            min_detection_confidence: Minimum detection confidence
            batch_size: Number of frames to process together
        """
        if not _MP_AVAILABLE:
            raise ImportError("MediaPipe not available")

        self.max_num_faces = max_num_faces
        self.min_detection_confidence = min_detection_confidence
        self.batch_size = batch_size

        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,  # Better for batch processing
            max_num_faces=max_num_faces,
            refine_landmarks=False,
            min_detection_confidence=min_detection_confidence,
        )

    def process_batch(self, frames_rgb: List[np.ndarray]) -> List[DetectionResult]:
        """
        Process a batch of frames.

        Args:
            frames_rgb: List of RGB frames

        Returns:
            List of DetectionResults
        """
        results = []

        for i, frame in enumerate(frames_rgb):
            start_time = time.perf_counter()

            try:
                mp_results = self._face_mesh.process(frame)
                processing_time = (time.perf_counter() - start_time) * 1000

                if mp_results.multi_face_landmarks:
                    landmarks = mp_results.multi_face_landmarks[0].landmark
                    bbox = self._extract_bbox(landmarks, frame.shape)

                    result = DetectionResult(
                        frame_id=i,
                        landmarks=landmarks,
                        bbox=bbox,
                        processing_time_ms=processing_time,
                        timestamp=time.time()
                    )
                else:
                    result = DetectionResult(
                        frame_id=i,
                        landmarks=None,
                        bbox=None,
                        processing_time_ms=processing_time,
                        timestamp=time.time()
                    )

                results.append(result)

            except Exception as e:
                logger.error(f"Batch processing error for frame {i}: {e}")
                results.append(DetectionResult(
                    frame_id=i,
                    landmarks=None,
                    bbox=None,
                    processing_time_ms=0.0,
                    timestamp=time.time()
                ))

        return results

    def _extract_bbox(self, landmarks, shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
        """Extract bounding box from landmarks."""
        h, w = shape[:2]

        from face_geometry import FACE_OVAL_IDS

        xs = [landmarks[i].x * w for i in FACE_OVAL_IDS]
        ys = [landmarks[i].y * h for i in FACE_OVAL_IDS]

        x_min, x_max = int(min(xs)), int(max(xs))
        y_min, y_max = int(min(ys)), int(max(ys))

        return (x_min, y_min, x_max - x_min, y_max - y_min)

    def close(self) -> None:
        """Close the detector."""
        if self._face_mesh is not None:
            try:
                self._face_mesh.close()
            except Exception as e:
                logger.warning(f"Error closing FaceMesh: {e}")
            self._face_mesh = None


# ─── Optimized Landmark Extractor ────────────────────────────────────────────

class OptimizedLandmarkExtractor:
    """
    [v21 NEW] Optimized landmark extraction.

    Pre-computes indices and uses vectorized operations for faster
    EAR/MAR/pose calculations.
    """

    def __init__(self):
        """Initialize optimized extractor."""
        from face_geometry import LEFT_EYE, RIGHT_EYE, MOUTH, POSE_LM_IDS

        self.left_eye_ids = np.array(LEFT_EYE, dtype=np.int32)
        self.right_eye_ids = np.array(RIGHT_EYE, dtype=np.int32)
        self.mouth_ids = np.array(MOUTH, dtype=np.int32)
        self.pose_ids = np.array(POSE_LM_IDS, dtype=np.int32)

    def extract_all(
        self, landmarks, w: int, h: int
    ) -> Tuple[float, float, float, Tuple[float, float, float]]:
        """
        Extract all metrics at once (optimized).

        Args:
            landmarks: MediaPipe landmarks
            w: Frame width
            h: Frame height

        Returns:
            (ear, mar, yaw, (pitch, yaw, roll))
        """
        # Convert landmarks to numpy array for vectorized operations
        lm_array = np.array([[lm.x * w, lm.y * h] for lm in landmarks], dtype=np.float32)

        # EAR (average of left and right)
        ear_left = self._compute_ear(lm_array[self.left_eye_ids])
        ear_right = self._compute_ear(lm_array[self.right_eye_ids])
        ear = (ear_left + ear_right) / 2.0

        # MAR
        mar = self._compute_mar(lm_array[self.mouth_ids])

        # Head pose
        try:
            from face_geometry import head_pose
            pitch, yaw, roll = head_pose(landmarks, w, h)
        except Exception:
            pitch, yaw, roll = 0.0, 0.0, 0.0

        return ear, mar, abs(yaw), (pitch, yaw, roll)

    def _compute_ear(self, eye_points: np.ndarray) -> float:
        """Compute EAR from eye points (vectorized)."""
        # eye_points shape: (6, 2)
        p1, p2, p3, p4, p5, p6 = eye_points

        # Vertical distances
        a = np.linalg.norm(p2 - p6)
        b = np.linalg.norm(p3 - p5)

        # Horizontal distance
        c = np.linalg.norm(p1 - p4)

        if c < 1e-6:
            return 1.0

        return (a + b) / (2.0 * c)

    def _compute_mar(self, mouth_points: np.ndarray) -> float:
        """Compute MAR from mouth points (vectorized)."""
        # mouth_points shape: (6, 2)
        p1, p2, p3, p4, p5, p6 = mouth_points

        # Vertical distances
        vert = np.linalg.norm(p3 - p4) + np.linalg.norm(p5 - p6)

        # Horizontal distance
        horiz = np.linalg.norm(p1 - p2)

        if horiz < 1e-6:
            return 0.0

        return vert / (2.0 * horiz)
