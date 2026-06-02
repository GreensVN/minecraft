"""
batch_inference.py — Batch inference optimization (v21 NEW).

Provides optimized batch inference for:
- Multiple faces in single frame (classroom)
- Multiple frames from video file
- GPU memory pooling
- Dynamic batching with timeout

Features:
- Automatic batch size optimization
- GPU memory management
- Preprocessing pipeline optimization
- ONNX/PyTorch batch support
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class InferenceRequest:
    """Single inference request."""
    request_id: int
    face_bgr: np.ndarray
    timestamp: float


@dataclass
class InferenceResult:
    """Single inference result."""
    request_id: int
    probabilities: np.ndarray
    latency_ms: float
    timestamp: float


# ─── Batch Inference Engine ──────────────────────────────────────────────────

class BatchInferenceEngine:
    """
    [v21 NEW] Batch inference engine with dynamic batching.

    Collects multiple inference requests and processes them together
    for better GPU utilization and throughput.

    Usage:
        engine = BatchInferenceEngine(predictor, batch_size=8)
        engine.start()

        # Submit request
        future = engine.submit(face_bgr)

        # Get result (blocking)
        result = future.get(timeout=1.0)

        engine.stop()
    """

    def __init__(
        self,
        predictor: Any,  # OnnxPredictor or TorchPredictor
        batch_size: int = 8,
        timeout_ms: float = 50.0,
        queue_size: int = 100,
    ):
        """
        Initialize batch inference engine.

        Args:
            predictor: Base predictor (ONNX or PyTorch)
            batch_size: Maximum batch size
            timeout_ms: Max wait time to fill batch (milliseconds)
            queue_size: Request queue size
        """
        self.predictor = predictor
        self.batch_size = batch_size
        self.timeout_ms = timeout_ms
        self.queue_size = queue_size

        # Queues
        self._request_queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._pending_requests: List[Tuple[InferenceRequest, InferenceFuture]] = []

        # Worker thread
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Statistics
        self._total_requests = 0
        self._total_batches = 0
        self._total_inference_time = 0.0

        # Request ID counter
        self._next_request_id = 0
        self._id_lock = threading.Lock()

    def start(self) -> None:
        """Start the batch inference engine."""
        if self._running:
            logger.warning("BatchInferenceEngine already running")
            return

        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="BatchInferenceEngine"
        )
        self._worker_thread.start()
        logger.info(
            f"BatchInferenceEngine started (batch_size={self.batch_size}, "
            f"timeout={self.timeout_ms}ms)"
        )

    def stop(self) -> None:
        """Stop the batch inference engine."""
        self._running = False
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2.0)

        logger.info(
            f"BatchInferenceEngine stopped. Stats: "
            f"requests={self._total_requests}, batches={self._total_batches}, "
            f"avg_batch_size={self._total_requests / max(self._total_batches, 1):.1f}"
        )

    def submit(self, face_bgr: np.ndarray) -> InferenceFuture:
        """
        Submit inference request.

        Args:
            face_bgr: Face image (BGR)

        Returns:
            InferenceFuture for getting result

        Raises:
            queue.Full: If queue is full
        """
        with self._id_lock:
            request_id = self._next_request_id
            self._next_request_id += 1

        request = InferenceRequest(
            request_id=request_id,
            face_bgr=face_bgr,
            timestamp=time.time()
        )

        future = InferenceFuture()

        try:
            self._request_queue.put_nowait((request, future))
            self._total_requests += 1
            return future
        except queue.Full:
            raise queue.Full("Batch inference queue is full")

    def get_statistics(self) -> dict:
        """Get processing statistics."""
        avg_batch_size = (
            self._total_requests / self._total_batches
            if self._total_batches > 0
            else 0.0
        )

        avg_inference_time = (
            self._total_inference_time / self._total_batches
            if self._total_batches > 0
            else 0.0
        )

        return {
            'total_requests': self._total_requests,
            'total_batches': self._total_batches,
            'avg_batch_size': avg_batch_size,
            'avg_inference_time_ms': avg_inference_time,
            'queue_size': self._request_queue.qsize(),
        }

    def _worker_loop(self) -> None:
        """Background worker loop."""
        while self._running:
            try:
                # Collect batch
                batch = self._collect_batch()

                if not batch:
                    time.sleep(0.001)
                    continue

                # Process batch
                self._process_batch(batch)

            except Exception as e:
                logger.error(f"Batch inference error: {e}", exc_info=True)
                time.sleep(0.1)

    def _collect_batch(self) -> List[Tuple[InferenceRequest, InferenceFuture]]:
        """
        Collect a batch of requests.

        Returns:
            List of (request, future) tuples
        """
        batch = []
        deadline = time.time() + (self.timeout_ms / 1000.0)

        while len(batch) < self.batch_size and time.time() < deadline:
            try:
                timeout = max(0.001, deadline - time.time())
                item = self._request_queue.get(timeout=timeout)
                batch.append(item)
            except queue.Empty:
                break

        return batch

    def _process_batch(self, batch: List[Tuple[InferenceRequest, InferenceFuture]]) -> None:
        """
        Process a batch of requests.

        Args:
            batch: List of (request, future) tuples
        """
        if not batch:
            return

        try:
            # Extract faces
            faces = [req.face_bgr for req, _ in batch]

            # Batch inference
            start_time = time.perf_counter()
            results = self._batch_predict(faces)
            inference_time = (time.perf_counter() - start_time) * 1000

            self._total_batches += 1
            self._total_inference_time += inference_time

            # Distribute results
            for (req, future), probs in zip(batch, results):
                result = InferenceResult(
                    request_id=req.request_id,
                    probabilities=probs,
                    latency_ms=inference_time / len(batch),
                    timestamp=time.time()
                )
                future.set_result(result)

        except Exception as e:
            logger.error(f"Batch processing error: {e}", exc_info=True)
            # Set exception for all futures
            for _, future in batch:
                future.set_exception(e)

    def _batch_predict(self, faces: List[np.ndarray]) -> List[np.ndarray]:
        """
        Perform batch prediction.

        Args:
            faces: List of face images

        Returns:
            List of probability arrays
        """
        # Check if predictor supports batch inference
        if hasattr(self.predictor, 'predict_batch'):
            return self.predictor.predict_batch(faces)

        # Fallback: sequential inference
        results = []
        for face in faces:
            probs = self.predictor.predict_probs(face)
            results.append(probs)
        return results


class InferenceFuture:
    """
    [v21 NEW] Future for async inference result.

    Similar to concurrent.futures.Future but simpler.
    """

    def __init__(self):
        """Initialize future."""
        self._result: Optional[InferenceResult] = None
        self._exception: Optional[Exception] = None
        self._done = False
        self._condition = threading.Condition()

    def set_result(self, result: InferenceResult) -> None:
        """Set result."""
        with self._condition:
            self._result = result
            self._done = True
            self._condition.notify_all()

    def set_exception(self, exception: Exception) -> None:
        """Set exception."""
        with self._condition:
            self._exception = exception
            self._done = True
            self._condition.notify_all()

    def get(self, timeout: Optional[float] = None) -> InferenceResult:
        """
        Get result (blocking).

        Args:
            timeout: Timeout in seconds

        Returns:
            InferenceResult

        Raises:
            TimeoutError: If timeout
            Exception: If inference failed
        """
        with self._condition:
            if not self._done:
                if not self._condition.wait(timeout=timeout):
                    raise TimeoutError("Inference timeout")

            if self._exception is not None:
                raise self._exception

            return self._result

    def done(self) -> bool:
        """Check if done."""
        with self._condition:
            return self._done


# ─── Batch Predictor Wrappers ────────────────────────────────────────────────

class BatchOnnxPredictor:
    """
    [v21 NEW] ONNX predictor with batch support.

    Wraps OnnxPredictor to add efficient batch inference.
    """

    def __init__(self, base_predictor):
        """
        Initialize batch ONNX predictor.

        Args:
            base_predictor: OnnxPredictor instance
        """
        self.base = base_predictor
        self.session = base_predictor.session
        self.input_name = base_predictor.input_name
        self.img_size = base_predictor.img_size
        self._mean = base_predictor._mean
        self._std = base_predictor._std

    def predict_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        """Single prediction (for compatibility)."""
        return self.base.predict_probs(face_bgr)

    def predict_batch(self, faces: List[np.ndarray]) -> List[np.ndarray]:
        """
        Batch prediction.

        Args:
            faces: List of face images (BGR)

        Returns:
            List of probability arrays
        """
        if not faces:
            return []

        # Preprocess all faces
        batch = self._preprocess_batch(faces)

        # Batch inference
        logits = self.session.run(None, {self.input_name: batch})[0]

        # Softmax
        exp_logits = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = exp_logits / exp_logits.sum(axis=1, keepdims=True)

        # Split into list
        return [probs[i].astype(np.float32) for i in range(len(faces))]

    def _preprocess_batch(self, faces: List[np.ndarray]) -> np.ndarray:
        """
        Preprocess batch of faces.

        Args:
            faces: List of face images

        Returns:
            Batch tensor (N, C, H, W)
        """
        from utils_model import _preprocess_face

        batch = []
        for face in faces:
            x = _preprocess_face(face, self.img_size, self._mean, self._std)
            batch.append(x[0])  # Remove batch dimension

        return np.stack(batch, axis=0)


class BatchTorchPredictor:
    """
    [v21 NEW] PyTorch predictor with batch support.

    Wraps TorchPredictor to add efficient batch inference.
    """

    def __init__(self, base_predictor):
        """
        Initialize batch PyTorch predictor.

        Args:
            base_predictor: TorchPredictor instance
        """
        self.base = base_predictor
        self.model = base_predictor.model
        self.device = base_predictor.device
        self._tfm = base_predictor._tfm

    def predict_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        """Single prediction (for compatibility)."""
        return self.base.predict_probs(face_bgr)

    def predict_batch(self, faces: List[np.ndarray]) -> List[np.ndarray]:
        """
        Batch prediction.

        Args:
            faces: List of face images (BGR)

        Returns:
            List of probability arrays
        """
        if not faces:
            return []

        import torch
        from PIL import Image

        # Preprocess all faces
        batch = []
        for face_bgr in faces:
            face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(face_rgb)
            x = self._tfm(pil_img)
            batch.append(x)

        # Stack into batch
        batch_tensor = torch.stack(batch).to(self.device)

        # Batch inference
        with torch.inference_mode():
            logits = self.model(batch_tensor)
            probs = torch.softmax(logits, dim=1)

        # Convert to numpy and split
        probs_np = probs.cpu().numpy()
        return [probs_np[i].astype(np.float32) for i in range(len(faces))]


# ─── GPU Memory Pool ─────────────────────────────────────────────────────────

class GPUMemoryPool:
    """
    [v21 NEW] GPU memory pool for efficient memory reuse.

    Pre-allocates GPU memory buffers to avoid repeated allocation/deallocation.
    """

    def __init__(self, device: str = "cuda"):
        """
        Initialize GPU memory pool.

        Args:
            device: Device name ("cuda" or "cuda:0")
        """
        self.device = device
        self._buffers: dict = {}  # shape -> buffer

    def get_buffer(self, shape: Tuple[int, ...], dtype=None) -> Any:
        """
        Get or create buffer.

        Args:
            shape: Buffer shape
            dtype: Data type

        Returns:
            Tensor buffer
        """
        import torch

        if dtype is None:
            dtype = torch.float32

        key = (shape, dtype)

        if key not in self._buffers:
            self._buffers[key] = torch.zeros(shape, dtype=dtype, device=self.device)

        return self._buffers[key]

    def clear(self) -> None:
        """Clear all buffers."""
        self._buffers.clear()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"Error clearing GPU cache: {e}")


# ─── Preprocessing Pipeline Optimization ─────────────────────────────────────

class OptimizedPreprocessor:
    """
    [v21 NEW] Optimized preprocessing pipeline.

    Uses vectorized operations and caching for better performance.
    """

    def __init__(self, img_size: int = 224):
        """
        Initialize preprocessor.

        Args:
            img_size: Target image size
        """
        self.img_size = img_size
        self._mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
        self._std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)

    def preprocess_batch(self, faces: List[np.ndarray]) -> np.ndarray:
        """
        Preprocess batch of faces (optimized).

        Args:
            faces: List of face images (BGR)

        Returns:
            Batch tensor (N, C, H, W)
        """
        batch = []

        for face in faces:
            # BGR to RGB
            face_rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)

            # Resize
            face_resized = cv2.resize(
                face_rgb,
                (self.img_size, self.img_size),
                interpolation=cv2.INTER_LINEAR
            )

            # Transpose and normalize
            x = face_resized.transpose(2, 0, 1).astype(np.float32) / 255.0
            batch.append(x)

        # Stack
        batch_array = np.stack(batch, axis=0)

        # Normalize
        batch_array = (batch_array - self._mean) / self._std

        return batch_array.astype(np.float32)


# ─── Utility Functions ───────────────────────────────────────────────────────

def estimate_optimal_batch_size(
    model_size_mb: float,
    available_memory_mb: float,
    img_size: int = 224,
) -> int:
    """
    Estimate optimal batch size based on available memory.

    Args:
        model_size_mb: Model size in MB
        available_memory_mb: Available GPU memory in MB
        img_size: Input image size

    Returns:
        Estimated optimal batch size
    """
    # Estimate memory per image (rough approximation)
    bytes_per_pixel = 4  # float32
    channels = 3
    memory_per_image_mb = (img_size * img_size * channels * bytes_per_pixel) / (1024 * 1024)

    # Reserve memory for model and overhead
    reserved_mb = model_size_mb * 2  # 2x for safety
    usable_mb = max(0, available_memory_mb - reserved_mb)

    # Calculate batch size
    batch_size = int(usable_mb / memory_per_image_mb)

    # Clamp to reasonable range
    batch_size = max(1, min(batch_size, 64))

    logger.info(
        f"Estimated optimal batch size: {batch_size} "
        f"(available={available_memory_mb:.1f}MB, per_image={memory_per_image_mb:.2f}MB)"
    )

    return batch_size
