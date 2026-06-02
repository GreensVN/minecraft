"""
resource_manager.py — Resource management utilities (v21 NEW).

Provides context managers and utilities for proper resource cleanup:
- MediaPipe resource management
- Memory monitoring and auto-restart
- Periodic garbage collection
- Resource leak detection
"""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
import weakref
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, Set

logger = logging.getLogger(__name__)

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, memory monitoring disabled")


# ─── MediaPipe Resource Manager ──────────────────────────────────────────────

class MediaPipeResourceManager:
    """
    [v21 NEW] Context manager for MediaPipe resources.

    Ensures proper cleanup of MediaPipe FaceMesh/FaceDetection instances
    to prevent memory leaks.

    Usage:
        with MediaPipeResourceManager() as manager:
            face_mesh = manager.create_face_mesh(max_num_faces=1)
            # Use face_mesh...
        # Automatically closed on exit
    """

    def __init__(self):
        self._resources: Set[Any] = set()
        self._lock = threading.Lock()

    def __enter__(self) -> MediaPipeResourceManager:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
        return False

    def create_face_mesh(self, **kwargs) -> Any:
        """Create and register MediaPipe FaceMesh."""
        try:
            import mediapipe as mp
            face_mesh = mp.solutions.face_mesh.FaceMesh(**kwargs)
            with self._lock:
                self._resources.add(face_mesh)
            return face_mesh
        except ImportError:
            logger.error("MediaPipe not installed")
            raise

    def create_face_detection(self, **kwargs) -> Any:
        """Create and register MediaPipe FaceDetection."""
        try:
            import mediapipe as mp
            face_detection = mp.solutions.face_detection.FaceDetection(**kwargs)
            with self._lock:
                self._resources.add(face_detection)
            return face_detection
        except ImportError:
            logger.error("MediaPipe not installed")
            raise

    def cleanup(self) -> None:
        """Close all registered MediaPipe resources."""
        with self._lock:
            for resource in self._resources:
                try:
                    if hasattr(resource, 'close'):
                        resource.close()
                except Exception as e:
                    logger.warning(f"Error closing MediaPipe resource: {e}")
            self._resources.clear()

        # Force garbage collection after cleanup
        gc.collect()


@contextmanager
def mediapipe_resource(resource_type: str, **kwargs) -> Iterator[Any]:
    """
    [v21 NEW] Context manager for single MediaPipe resource.

    Args:
        resource_type: 'face_mesh' or 'face_detection'
        **kwargs: Arguments passed to MediaPipe constructor

    Usage:
        with mediapipe_resource('face_mesh', max_num_faces=1) as face_mesh:
            result = face_mesh.process(image)
    """
    try:
        import mediapipe as mp

        if resource_type == 'face_mesh':
            resource = mp.solutions.face_mesh.FaceMesh(**kwargs)
        elif resource_type == 'face_detection':
            resource = mp.solutions.face_detection.FaceDetection(**kwargs)
        else:
            raise ValueError(f"Unknown resource type: {resource_type}")

        yield resource
    finally:
        try:
            if hasattr(resource, 'close'):
                resource.close()
        except Exception as e:
            logger.warning(f"Error closing {resource_type}: {e}")
        gc.collect()


# ─── Memory Monitor ──────────────────────────────────────────────────────────

class MemoryMonitor:
    """
    [v21 NEW] Monitor memory usage and trigger actions on thresholds.

    Features:
    - Track current and peak memory usage
    - Trigger callbacks on threshold breach
    - Periodic garbage collection
    - Auto-restart recommendation
    """

    def __init__(
        self,
        warning_threshold_mb: float = 500.0,
        critical_threshold_mb: float = 1000.0,
        check_interval_sec: float = 5.0,
    ):
        """
        Initialize memory monitor.

        Args:
            warning_threshold_mb: Warning threshold in MB
            critical_threshold_mb: Critical threshold in MB (recommend restart)
            check_interval_sec: How often to check memory
        """
        self.warning_threshold = warning_threshold_mb
        self.critical_threshold = critical_threshold_mb
        self.check_interval = check_interval_sec

        self._process = psutil.Process(os.getpid()) if _PSUTIL_AVAILABLE else None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._peak_memory = 0.0
        self._warning_triggered = False
        self._critical_triggered = False

        # Callbacks
        self._warning_callback: Optional[Callable[[float], None]] = None
        self._critical_callback: Optional[Callable[[float], None]] = None

    def get_memory_mb(self) -> float:
        """Get current memory usage in MB."""
        if self._process is None:
            return 0.0
        return self._process.memory_info().rss / (1024 * 1024)

    def get_peak_memory_mb(self) -> float:
        """Get peak memory usage in MB."""
        return self._peak_memory

    def set_warning_callback(self, callback: Callable[[float], None]) -> None:
        """Set callback for warning threshold breach."""
        self._warning_callback = callback

    def set_critical_callback(self, callback: Callable[[float], None]) -> None:
        """Set callback for critical threshold breach."""
        self._critical_callback = callback

    def start(self) -> None:
        """Start monitoring in background thread."""
        if self._running:
            logger.warning("Memory monitor already running")
            return

        if not _PSUTIL_AVAILABLE:
            logger.warning("psutil not available, memory monitoring disabled")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="MemoryMonitor")
        self._thread.start()
        logger.info(f"Memory monitor started (warn={self.warning_threshold}MB, crit={self.critical_threshold}MB)")

    def stop(self) -> None:
        """Stop monitoring."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("Memory monitor stopped")

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._running:
            try:
                current_memory = self.get_memory_mb()
                self._peak_memory = max(self._peak_memory, current_memory)

                # Check warning threshold
                if current_memory >= self.warning_threshold and not self._warning_triggered:
                    self._warning_triggered = True
                    logger.warning(
                        f"Memory usage warning: {current_memory:.1f}MB >= {self.warning_threshold}MB"
                    )
                    if self._warning_callback:
                        try:
                            self._warning_callback(current_memory)
                        except Exception as e:
                            logger.error(f"Warning callback error: {e}")

                # Check critical threshold
                if current_memory >= self.critical_threshold and not self._critical_triggered:
                    self._critical_triggered = True
                    logger.error(
                        f"Memory usage CRITICAL: {current_memory:.1f}MB >= {self.critical_threshold}MB. "
                        f"Consider restarting the application."
                    )
                    if self._critical_callback:
                        try:
                            self._critical_callback(current_memory)
                        except Exception as e:
                            logger.error(f"Critical callback error: {e}")

                # Reset flags if memory drops below thresholds
                if current_memory < self.warning_threshold * 0.9:
                    self._warning_triggered = False
                if current_memory < self.critical_threshold * 0.9:
                    self._critical_triggered = False

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Memory monitor error: {e}", exc_info=True)
                time.sleep(self.check_interval)

    def force_gc(self) -> None:
        """Force garbage collection and log memory change."""
        before = self.get_memory_mb()
        gc.collect()
        after = self.get_memory_mb()
        freed = before - after
        logger.info(f"Garbage collection: {before:.1f}MB -> {after:.1f}MB (freed {freed:.1f}MB)")


# ─── Periodic GC Scheduler ───────────────────────────────────────────────────

class PeriodicGCScheduler:
    """
    [v21 NEW] Schedule periodic garbage collection.

    Helps prevent memory accumulation in long-running processes.
    """

    def __init__(self, interval_sec: float = 60.0):
        """
        Initialize GC scheduler.

        Args:
            interval_sec: How often to run GC (seconds)
        """
        self.interval = interval_sec
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start periodic GC in background thread."""
        if self._running:
            logger.warning("GC scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._gc_loop, daemon=True, name="GCScheduler")
        self._thread.start()
        logger.info(f"Periodic GC started (interval={self.interval}s)")

    def stop(self) -> None:
        """Stop periodic GC."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("Periodic GC stopped")

    def _gc_loop(self) -> None:
        """Background GC loop."""
        while self._running:
            time.sleep(self.interval)
            if self._running:  # Check again after sleep
                try:
                    collected = gc.collect()
                    logger.debug(f"Periodic GC: collected {collected} objects")
                except Exception as e:
                    logger.error(f"GC error: {e}")


# ─── Resource Leak Detector ──────────────────────────────────────────────────

class ResourceLeakDetector:
    """
    [v21 NEW] Detect potential resource leaks using weak references.

    Tracks objects that should be cleaned up and warns if they persist.
    """

    def __init__(self):
        self._tracked: Set[weakref.ref] = set()
        self._lock = threading.Lock()

    def track(self, obj: Any, name: str = "") -> None:
        """
        Track an object for leak detection.

        Args:
            obj: Object to track
            name: Optional name for logging
        """
        def callback(ref):
            with self._lock:
                self._tracked.discard(ref)
            logger.debug(f"Object collected: {name or 'unnamed'}")

        ref = weakref.ref(obj, callback)
        with self._lock:
            self._tracked.add(ref)

    def check_leaks(self) -> int:
        """
        Check for potential leaks.

        Returns:
            Number of objects still alive
        """
        gc.collect()  # Force collection first

        with self._lock:
            alive = [ref for ref in self._tracked if ref() is not None]
            if alive:
                logger.warning(f"Potential leak: {len(alive)} tracked objects still alive")
            return len(alive)

    def clear(self) -> None:
        """Clear all tracked objects."""
        with self._lock:
            self._tracked.clear()


# ─── Global Instances ────────────────────────────────────────────────────────

_memory_monitor: Optional[MemoryMonitor] = None
_gc_scheduler: Optional[PeriodicGCScheduler] = None
_leak_detector: Optional[ResourceLeakDetector] = None


def get_memory_monitor() -> MemoryMonitor:
    """Get global memory monitor instance."""
    global _memory_monitor
    if _memory_monitor is None:
        _memory_monitor = MemoryMonitor()
    return _memory_monitor


def get_gc_scheduler() -> PeriodicGCScheduler:
    """Get global GC scheduler instance."""
    global _gc_scheduler
    if _gc_scheduler is None:
        _gc_scheduler = PeriodicGCScheduler()
    return _gc_scheduler


def get_leak_detector() -> ResourceLeakDetector:
    """Get global leak detector instance."""
    global _leak_detector
    if _leak_detector is None:
        _leak_detector = ResourceLeakDetector()
    return _leak_detector
