"""
circuit_breaker.py — Circuit breaker pattern & graceful degradation (v21 NEW).

Implements circuit breaker pattern for fault tolerance and graceful degradation
when external dependencies fail.

Features:
- Circuit breaker with configurable thresholds
- Automatic fallback mechanisms
- Health check system
- Retry logic with exponential backoff
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Any, Dict

logger = logging.getLogger(__name__)


# ─── Circuit Breaker States ──────────────────────────────────────────────────

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    success_threshold: int = 2          # Successes to close from half-open
    timeout_seconds: float = 60.0       # Time before trying half-open
    half_open_max_calls: int = 3        # Max calls in half-open state


# ─── Circuit Breaker ─────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    [v21 NEW] Circuit breaker pattern implementation.

    Prevents cascading failures by stopping calls to failing services.
    Automatically recovers when service becomes healthy again.

    Usage:
        breaker = CircuitBreaker(name="cnn_inference")

        try:
            with breaker:
                result = expensive_operation()
        except CircuitBreakerOpen:
            result = fallback_operation()
    """

    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        fallback: Optional[Callable] = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Circuit breaker name (for logging)
            config: Configuration
            fallback: Optional fallback function when circuit is open
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.fallback = fallback

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = threading.Lock()

        # Statistics
        self._total_calls = 0
        self._total_failures = 0
        self._total_fallbacks = 0

    def __enter__(self):
        """Context manager entry."""
        with self._lock:
            self._total_calls += 1

            if self._state == CircuitState.OPEN:
                # Check if timeout expired
                if self._should_attempt_reset():
                    logger.info(f"[{self.name}] Circuit breaker: OPEN -> HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                else:
                    raise CircuitBreakerOpen(f"Circuit breaker {self.name} is OPEN")

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpen(f"Circuit breaker {self.name} is HALF_OPEN (max calls)")
                self._half_open_calls += 1

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        with self._lock:
            if exc_type is None:
                # Success
                self._on_success()
            else:
                # Failure
                self._on_failure()

        return False  # Don't suppress exceptions

    def _on_success(self) -> None:
        """Handle successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                logger.info(f"[{self.name}] Circuit breaker: HALF_OPEN -> CLOSED")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self._state == CircuitState.CLOSED:
            # Reset failure count on success
            self._failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed call."""
        self._total_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Failed in half-open -> back to open
            logger.warning(f"[{self.name}] Circuit breaker: HALF_OPEN -> OPEN (failure)")
            self._state = CircuitState.OPEN
            self._success_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.config.failure_threshold:
                logger.error(
                    f"[{self.name}] Circuit breaker: CLOSED -> OPEN "
                    f"({self._failure_count} failures)"
                )
                self._state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """Check if should attempt reset from OPEN to HALF_OPEN."""
        if self._last_failure_time is None:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout_seconds

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Call function with circuit breaker protection.

        Args:
            func: Function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result or fallback result

        Raises:
            CircuitBreakerOpen: If circuit is open and no fallback
        """
        try:
            with self:
                return func(*args, **kwargs)
        except CircuitBreakerOpen:
            if self.fallback is not None:
                self._total_fallbacks += 1
                logger.warning(f"[{self.name}] Using fallback")
                return self.fallback(*args, **kwargs)
            raise

    def get_state(self) -> CircuitState:
        """Get current state."""
        with self._lock:
            return self._state

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics."""
        with self._lock:
            return {
                'name': self.name,
                'state': self._state.value,
                'total_calls': self._total_calls,
                'total_failures': self._total_failures,
                'total_fallbacks': self._total_fallbacks,
                'failure_count': self._failure_count,
                'success_count': self._success_count,
                'failure_rate': (
                    self._total_failures / self._total_calls
                    if self._total_calls > 0 else 0.0
                ),
            }

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED."""
        with self._lock:
            logger.info(f"[{self.name}] Circuit breaker manually reset")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


# ─── Retry Logic ─────────────────────────────────────────────────────────────

class RetryConfig:
    """Configuration for retry logic."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        """
        Initialize retry configuration.

        Args:
            max_attempts: Maximum retry attempts
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            exponential_base: Base for exponential backoff
            jitter: Add random jitter to delays
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter


def retry_with_backoff(
    func: Callable,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> Any:
    """
    Retry function with exponential backoff.

    Args:
        func: Function to retry
        config: Retry configuration
        on_retry: Callback on retry (attempt_num, exception)

    Returns:
        Function result

    Raises:
        Last exception if all retries fail
    """
    import random

    config = config or RetryConfig()
    last_exception = None

    for attempt in range(config.max_attempts):
        try:
            return func()
        except Exception as e:
            last_exception = e

            if attempt < config.max_attempts - 1:
                # Calculate delay
                delay = min(
                    config.base_delay * (config.exponential_base ** attempt),
                    config.max_delay
                )

                # Add jitter
                if config.jitter:
                    delay *= (0.5 + random.random())

                logger.warning(
                    f"Retry attempt {attempt + 1}/{config.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )

                if on_retry:
                    on_retry(attempt + 1, e)

                time.sleep(delay)
            else:
                logger.error(f"All {config.max_attempts} retry attempts failed")

    raise last_exception


# ─── Health Check System ─────────────────────────────────────────────────────

class HealthStatus(Enum):
    """Health check status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result from health check."""
    component: str
    status: HealthStatus
    message: str
    latency_ms: float
    timestamp: float


class HealthChecker:
    """
    [v21 NEW] Health check system for monitoring component health.

    Usage:
        checker = HealthChecker()
        checker.register("database", check_database_health)
        checker.register("api", check_api_health)

        # Run all checks
        results = checker.check_all()
        overall = checker.get_overall_status()
    """

    def __init__(self):
        """Initialize health checker."""
        self._checks: Dict[str, Callable[[], bool]] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._lock = threading.Lock()

    def register(self, component: str, check_func: Callable[[], bool]) -> None:
        """
        Register a health check.

        Args:
            component: Component name
            check_func: Function that returns True if healthy
        """
        with self._lock:
            self._checks[component] = check_func
            logger.info(f"Registered health check for: {component}")

    def unregister(self, component: str) -> None:
        """Unregister a health check."""
        with self._lock:
            self._checks.pop(component, None)
            self._last_results.pop(component, None)

    def check(self, component: str) -> HealthCheckResult:
        """
        Run health check for a component.

        Args:
            component: Component name

        Returns:
            HealthCheckResult
        """
        with self._lock:
            check_func = self._checks.get(component)

        if check_func is None:
            return HealthCheckResult(
                component=component,
                status=HealthStatus.UNHEALTHY,
                message="Component not registered",
                latency_ms=0.0,
                timestamp=time.time()
            )

        start_time = time.perf_counter()
        try:
            is_healthy = check_func()
            latency = (time.perf_counter() - start_time) * 1000

            status = HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY
            message = "OK" if is_healthy else "Check failed"

            result = HealthCheckResult(
                component=component,
                status=status,
                message=message,
                latency_ms=latency,
                timestamp=time.time()
            )

        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            result = HealthCheckResult(
                component=component,
                status=HealthStatus.UNHEALTHY,
                message=f"Exception: {e}",
                latency_ms=latency,
                timestamp=time.time()
            )

        with self._lock:
            self._last_results[component] = result

        return result

    def check_all(self) -> Dict[str, HealthCheckResult]:
        """
        Run all health checks.

        Returns:
            Dict of component -> HealthCheckResult
        """
        with self._lock:
            components = list(self._checks.keys())

        results = {}
        for component in components:
            results[component] = self.check(component)

        return results

    def get_overall_status(self) -> HealthStatus:
        """
        Get overall system health status.

        Returns:
            HEALTHY if all healthy, UNHEALTHY if any unhealthy, DEGRADED otherwise
        """
        with self._lock:
            if not self._last_results:
                return HealthStatus.UNHEALTHY

            statuses = [r.status for r in self._last_results.values()]

            if all(s == HealthStatus.HEALTHY for s in statuses):
                return HealthStatus.HEALTHY
            elif any(s == HealthStatus.UNHEALTHY for s in statuses):
                return HealthStatus.UNHEALTHY
            else:
                return HealthStatus.DEGRADED

    def get_last_results(self) -> Dict[str, HealthCheckResult]:
        """Get last health check results."""
        with self._lock:
            return dict(self._last_results)


# ─── Graceful Degradation Manager ────────────────────────────────────────────

class DegradationLevel(Enum):
    """System degradation levels."""
    FULL = "full"              # All features enabled
    REDUCED = "reduced"        # Some features disabled
    MINIMAL = "minimal"        # Only core features
    EMERGENCY = "emergency"    # Bare minimum


class GracefulDegradationManager:
    """
    [v21 NEW] Manage graceful degradation of system features.

    Automatically disables non-critical features when system is under stress.
    """

    def __init__(self):
        """Initialize degradation manager."""
        self._level = DegradationLevel.FULL
        self._disabled_features: set = set()
        self._lock = threading.Lock()

        # Feature priorities (lower = more critical)
        self._feature_priorities = {
            'face_detection': 1,
            'ear_calculation': 1,
            'cnn_inference': 2,
            'bpm_tracking': 3,
            'head_pose': 3,
            'metrics_collection': 4,
            'audio_warning': 2,
            'video_display': 5,
        }

    def set_level(self, level: DegradationLevel) -> None:
        """
        Set degradation level.

        Args:
            level: New degradation level
        """
        with self._lock:
            old_level = self._level
            self._level = level

            # Update disabled features based on level
            if level == DegradationLevel.FULL:
                self._disabled_features.clear()
            elif level == DegradationLevel.REDUCED:
                self._disable_features_above_priority(4)
            elif level == DegradationLevel.MINIMAL:
                self._disable_features_above_priority(2)
            elif level == DegradationLevel.EMERGENCY:
                self._disable_features_above_priority(1)

            if old_level != level:
                logger.warning(
                    f"Degradation level changed: {old_level.value} -> {level.value}. "
                    f"Disabled features: {self._disabled_features}"
                )

    def _disable_features_above_priority(self, max_priority: int) -> None:
        """Disable features with priority > max_priority."""
        self._disabled_features = {
            feature for feature, priority in self._feature_priorities.items()
            if priority > max_priority
        }

    def is_feature_enabled(self, feature: str) -> bool:
        """
        Check if feature is enabled.

        Args:
            feature: Feature name

        Returns:
            True if enabled
        """
        with self._lock:
            return feature not in self._disabled_features

    def get_level(self) -> DegradationLevel:
        """Get current degradation level."""
        with self._lock:
            return self._level

    def get_disabled_features(self) -> set:
        """Get set of disabled features."""
        with self._lock:
            return set(self._disabled_features)


# ─── Global Instances ────────────────────────────────────────────────────────

_health_checker: Optional[HealthChecker] = None
_degradation_manager: Optional[GracefulDegradationManager] = None


def get_health_checker() -> HealthChecker:
    """Get global health checker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


def get_degradation_manager() -> GracefulDegradationManager:
    """Get global degradation manager instance."""
    global _degradation_manager
    if _degradation_manager is None:
        _degradation_manager = GracefulDegradationManager()
    return _degradation_manager
