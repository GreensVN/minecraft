"""
metrics.py — Performance metrics and monitoring (v18, extended v20).

Provides:
- FPS tracking with moving average
- Latency measurements (avg / p95 / p99 / max, context-manager API)
- Memory usage monitoring (psutil-optional, degrades to 0.0)
- Alert statistics
- Session statistics (incl. personalized calibration thresholds)
- Export to CSV/JSON (auto-creates parent directories)
"""

from __future__ import annotations

import time
import os
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Deque, Dict, Iterator, List, Optional, Any
import json
import csv
from datetime import datetime

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False


@dataclass
class FrameMetrics:
    """Metrics for a single frame."""
    timestamp: float
    fps: float
    detection_time_ms: float
    inference_time_ms: float
    total_time_ms: float
    num_faces: int
    memory_mb: float


@dataclass
class SessionStatistics:
    """Statistics for an entire session."""
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    total_frames: int = 0
    total_alerts_level1: int = 0
    total_alerts_level2: int = 0
    total_faces_detected: int = 0
    avg_fps: float = 0.0
    avg_detection_time_ms: float = 0.0
    avg_inference_time_ms: float = 0.0
    peak_memory_mb: float = 0.0
    calibration_ear: Optional[float] = None
    calibration_mar: Optional[float] = None

    def duration_sec(self) -> float:
        """Get session duration in seconds."""
        end = self.end_time or time.time()
        return end - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class MetricsCollector:
    """Collects and aggregates performance metrics."""

    def __init__(self, window_size: int = 100):
        """
        Initialize metrics collector.

        Args:
            window_size: Number of recent frames to keep for moving averages
        """
        self.window_size = window_size
        self.frame_metrics: Deque[FrameMetrics] = deque(maxlen=window_size)

        # FPS tracking
        self.fps_history: Deque[float] = deque(maxlen=window_size)
        self.frame_times: Deque[float] = deque(maxlen=30)
        self.last_frame_time: Optional[float] = None

        # Timing
        self.detection_times: Deque[float] = deque(maxlen=window_size)
        self.inference_times: Deque[float] = deque(maxlen=window_size)

        # Counters
        self.total_frames = 0
        self.total_faces = 0
        self.alert_counts = {0: 0, 1: 0, 2: 0}

        # Memory
        self.process = psutil.Process(os.getpid()) if _PSUTIL_AVAILABLE else None
        self.peak_memory_mb = 0.0

        # Session
        self.session_start = time.time()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # [v20] Personalized calibration thresholds (set once after calibration)
        self.calibration_ear: Optional[float] = None
        self.calibration_mar: Optional[float] = None

    def record_calibration(self, ear: Optional[float], mar: Optional[float]) -> None:
        """[v20] Store personalized calibration thresholds for the session report."""
        self.calibration_ear = ear
        self.calibration_mar = mar

    def record_frame(
        self,
        detection_time_ms: float = 0.0,
        inference_time_ms: float = 0.0,
        num_faces: int = 0,
        alert_level: int = 0,
    ) -> None:
        """
        Record metrics for a frame.

        Args:
            detection_time_ms: Time spent on face detection
            inference_time_ms: Time spent on CNN inference
            num_faces: Number of faces detected
            alert_level: Alert level (0, 1, 2)
        """
        now = time.time()

        # Calculate FPS
        if self.last_frame_time is not None:
            frame_delta = now - self.last_frame_time
            if frame_delta > 0:
                fps = 1.0 / frame_delta
                self.fps_history.append(fps)
                self.frame_times.append(frame_delta)

        self.last_frame_time = now

        # Record timings
        self.detection_times.append(detection_time_ms)
        self.inference_times.append(inference_time_ms)

        # Update counters
        self.total_frames += 1
        self.total_faces += num_faces
        if alert_level in self.alert_counts:
            self.alert_counts[alert_level] += 1

        # Memory
        memory_mb = self.get_memory_usage_mb()
        self.peak_memory_mb = max(self.peak_memory_mb, memory_mb)

        # Store frame metrics
        total_time = detection_time_ms + inference_time_ms
        metrics = FrameMetrics(
            timestamp=now,
            fps=self.get_current_fps(),
            detection_time_ms=detection_time_ms,
            inference_time_ms=inference_time_ms,
            total_time_ms=total_time,
            num_faces=num_faces,
            memory_mb=memory_mb,
        )
        self.frame_metrics.append(metrics)

    def get_current_fps(self) -> float:
        """Get current FPS (moving average)."""
        if not self.fps_history:
            return 0.0
        return sum(self.fps_history) / len(self.fps_history)

    def get_avg_detection_time(self) -> float:
        """Get average detection time in ms."""
        if not self.detection_times:
            return 0.0
        return sum(self.detection_times) / len(self.detection_times)

    def get_avg_inference_time(self) -> float:
        """Get average inference time in ms."""
        if not self.inference_times:
            return 0.0
        return sum(self.inference_times) / len(self.inference_times)

    def get_memory_usage_mb(self) -> float:
        """Get current memory usage in MB (0.0 if psutil unavailable)."""
        if self.process is None:
            return 0.0
        return self.process.memory_info().rss / (1024 * 1024)

    def get_session_statistics(self) -> SessionStatistics:
        """Get complete session statistics."""
        return SessionStatistics(
            session_id=self.session_id,
            start_time=self.session_start,
            end_time=time.time(),
            total_frames=self.total_frames,
            total_alerts_level1=self.alert_counts[1],
            total_alerts_level2=self.alert_counts[2],
            total_faces_detected=self.total_faces,
            avg_fps=self.get_current_fps(),
            avg_detection_time_ms=self.get_avg_detection_time(),
            avg_inference_time_ms=self.get_avg_inference_time(),
            peak_memory_mb=self.peak_memory_mb,
            calibration_ear=self.calibration_ear,
            calibration_mar=self.calibration_mar,
        )

    def get_summary(self) -> str:
        """Get human-readable summary."""
        stats = self.get_session_statistics()
        duration = stats.duration_sec()
        total_alerts = stats.total_alerts_level1 + stats.total_alerts_level2
        alerts_per_min = (total_alerts / (duration / 60.0)) if duration > 0 else 0.0

        lines = [
            "=" * 60,
            "SESSION METRICS SUMMARY",
            "=" * 60,
            f"Session ID      : {stats.session_id}",
            f"Duration        : {duration:.1f}s ({duration/60:.1f}m)",
            f"Total Frames    : {stats.total_frames}",
            f"Faces Detected  : {stats.total_faces_detected}",
            "",
            "Performance:",
            f"  Avg FPS       : {stats.avg_fps:.1f}",
            f"  Detection     : {stats.avg_detection_time_ms:.2f}ms",
            f"  Inference     : {stats.avg_inference_time_ms:.2f}ms",
            f"  Peak Memory   : {stats.peak_memory_mb:.1f}MB",
            "",
            "Alerts:",
            f"  Level 1 (Warn): {stats.total_alerts_level1}",
            f"  Level 2 (Alert): {stats.total_alerts_level2}",
            f"  Total         : {total_alerts}  ({alerts_per_min:.1f}/min)",
        ]
        if stats.calibration_ear is not None or stats.calibration_mar is not None:
            lines += [
                "",
                "Calibration:",
                f"  EAR threshold : {stats.calibration_ear}",
                f"  MAR threshold : {stats.calibration_mar}",
            ]
        lines.append("=" * 60)
        return "\n".join(lines)

    def export_to_json(self, filepath: str) -> None:
        """Export session statistics to JSON (creates parent dirs as needed)."""
        parent = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(parent, exist_ok=True)
        stats = self.get_session_statistics()
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(stats.to_dict(), f, indent=2)

    def export_frame_metrics_to_csv(self, filepath: str) -> None:
        """Export detailed frame metrics to CSV (creates parent dirs as needed)."""
        if not self.frame_metrics:
            return

        parent = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(parent, exist_ok=True)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'timestamp', 'fps', 'detection_time_ms', 'inference_time_ms',
                'total_time_ms', 'num_faces', 'memory_mb'
            ])
            writer.writeheader()
            for metrics in self.frame_metrics:
                writer.writerow(asdict(metrics))

    def reset(self) -> None:
        """Reset all metrics."""
        self.frame_metrics.clear()
        self.fps_history.clear()
        self.frame_times.clear()
        self.detection_times.clear()
        self.inference_times.clear()
        self.total_frames = 0
        self.total_faces = 0
        self.alert_counts = {0: 0, 1: 0, 2: 0}
        self.peak_memory_mb = 0.0
        self.last_frame_time = None
        self.calibration_ear = None
        self.calibration_mar = None
        self.session_start = time.time()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")


class LatencyTracker:
    """Track latency for specific operations."""

    def __init__(self, name: str, window_size: int = 100):
        """
        Initialize latency tracker.

        Args:
            name: Name of the operation being tracked
            window_size: Number of samples to keep
        """
        self.name = name
        self.latencies: Deque[float] = deque(maxlen=window_size)
        self.start_time: Optional[float] = None

    def start(self) -> None:
        """Start timing."""
        self.start_time = time.perf_counter()

    def stop(self) -> float:
        """
        Stop timing and record latency.

        Returns:
            Latency in milliseconds
        """
        if self.start_time is None:
            return 0.0

        elapsed = (time.perf_counter() - self.start_time) * 1000
        self.latencies.append(elapsed)
        self.start_time = None
        return elapsed

    def get_avg(self) -> float:
        """Get average latency in ms."""
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    def get_percentile(self, pct: float) -> float:
        """Get an arbitrary percentile latency in ms (pct in [0, 100])."""
        if not self.latencies:
            return 0.0
        pct = min(100.0, max(0.0, float(pct)))
        sorted_latencies = sorted(self.latencies)
        # Clamp the index so pct == 100 (or rounding) never walks off the end.
        idx = int(len(sorted_latencies) * pct / 100.0)
        idx = min(idx, len(sorted_latencies) - 1)
        return sorted_latencies[idx]

    def get_p95(self) -> float:
        """Get 95th percentile latency in ms."""
        return self.get_percentile(95.0)

    def get_p99(self) -> float:
        """Get 99th percentile latency in ms."""
        return self.get_percentile(99.0)

    def get_max(self) -> float:
        """Get maximum latency in ms."""
        if not self.latencies:
            return 0.0
        return max(self.latencies)

    def reset(self) -> None:
        """Clear all recorded latencies."""
        self.latencies.clear()
        self.start_time = None

    @contextmanager
    def measure(self) -> Iterator[None]:
        """Context manager wrapper around start()/stop().

        Usage:
            tracker = LatencyTracker("inference")
            with tracker.measure():
                run_model()
        """
        self.start()
        try:
            yield
        finally:
            self.stop()


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def reset_metrics() -> None:
    """Reset global metrics collector."""
    global _metrics_collector
    if _metrics_collector is not None:
        _metrics_collector.reset()
