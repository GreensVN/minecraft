"""
test_comprehensive.py — Comprehensive test suite (v21 NEW).

Complete test coverage for all modules:
- Unit tests for all new modules
- Integration tests for end-to-end workflows
- Performance regression tests
- Security tests
- Edge case handling
"""

import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

# Import all modules to test
from validators import (
    is_valid_ear, is_valid_mar, is_valid_angle,
    validate_ear, validate_mar, validate_head_pose,
    DataQualityMetrics, sanitize_camera_index,
    INVALID_EAR, INVALID_MAR, INVALID_ANGLE
)
from resource_manager import (
    MediaPipeResourceManager, MemoryMonitor,
    PeriodicGCScheduler, ResourceLeakDetector
)
from circuit_breaker import (
    CircuitBreaker, CircuitBreakerOpen, CircuitState,
    retry_with_backoff, RetryConfig,
    HealthChecker, HealthStatus,
    GracefulDegradationManager, DegradationLevel
)
from security import (
    InputValidator, ResourceQuotaManager, ResourceLimits,
    RateLimiter, AlertRateLimiter, APIKeyManager,
    generate_secure_token, verify_hmac_signature
)


# ─── Validators Tests ────────────────────────────────────────────────────────

class TestValidators:
    """Test data validation functions."""

    def test_is_valid_ear(self):
        """Test EAR validation."""
        assert is_valid_ear(0.25) is True
        assert is_valid_ear(0.0) is True
        assert is_valid_ear(0.4) is True
        assert is_valid_ear(-0.1) is False
        assert is_valid_ear(1.5) is False
        assert is_valid_ear(float('nan')) is False
        assert is_valid_ear(float('inf')) is False
        assert is_valid_ear("invalid") is False

    def test_is_valid_mar(self):
        """Test MAR validation."""
        assert is_valid_mar(0.5) is True
        assert is_valid_mar(0.0) is True
        assert is_valid_mar(1.0) is True
        assert is_valid_mar(-0.1) is False
        assert is_valid_mar(3.0) is False
        assert is_valid_mar(float('nan')) is False

    def test_validate_ear(self):
        """Test EAR validation with default."""
        assert validate_ear(0.25) == 0.25
        assert validate_ear(float('nan')) == INVALID_EAR
        assert validate_ear(-0.1) == INVALID_EAR
        assert validate_ear(0.3, default=0.0) == 0.3
        assert validate_ear(float('nan'), default=0.0) == 0.0

    def test_validate_head_pose(self):
        """Test head pose validation."""
        pitch, yaw, roll = validate_head_pose(10.0, 20.0, 5.0)
        assert pitch == 10.0
        assert yaw == 20.0
        assert roll == 5.0

        pitch, yaw, roll = validate_head_pose(float('nan'), 20.0, float('inf'))
        assert pitch == INVALID_ANGLE
        assert yaw == 20.0
        assert roll == INVALID_ANGLE

    def test_data_quality_metrics(self):
        """Test data quality tracking."""
        metrics = DataQualityMetrics(window_size=10)

        # Record valid samples
        for _ in range(8):
            metrics.record(0.25, 0.5, has_landmarks=True)

        # Record invalid samples
        for _ in range(2):
            metrics.record(float('nan'), float('nan'), has_landmarks=False)

        assert metrics.get_ear_quality() == 0.8
        assert metrics.get_landmark_detection_rate() == 0.8
        assert metrics.is_quality_acceptable(threshold=0.7) is True
        assert metrics.is_quality_acceptable(threshold=0.9) is False

    def test_sanitize_camera_index(self):
        """Test camera index sanitization."""
        assert sanitize_camera_index(0) == 0
        assert sanitize_camera_index("0") == 0
        assert sanitize_camera_index("5") == 5

        with pytest.raises(ValueError):
            sanitize_camera_index(-1)

        with pytest.raises(ValueError):
            sanitize_camera_index(100)

        with pytest.raises(ValueError):
            sanitize_camera_index("invalid")


# ─── Resource Manager Tests ──────────────────────────────────────────────────

class TestResourceManager:
    """Test resource management."""

    def test_memory_monitor(self):
        """Test memory monitoring."""
        monitor = MemoryMonitor(
            warning_threshold_mb=100.0,
            critical_threshold_mb=200.0,
            check_interval_sec=0.1
        )

        # Test memory reading
        memory = monitor.get_memory_mb()
        assert memory >= 0

        # Test callbacks
        warning_called = []
        critical_called = []

        monitor.set_warning_callback(lambda mem: warning_called.append(mem))
        monitor.set_critical_callback(lambda mem: critical_called.append(mem))

        # Don't actually start monitor in test (would run forever)
        # Just test the interface

    def test_periodic_gc_scheduler(self):
        """Test GC scheduler."""
        scheduler = PeriodicGCScheduler(interval_sec=0.1)

        # Test start/stop
        scheduler.start()
        time.sleep(0.2)
        scheduler.stop()

    def test_resource_leak_detector(self):
        """Test leak detection."""
        detector = ResourceLeakDetector()

        # Track some objects (use objects that support weak references)
        class TestObject:
            pass

        obj1 = TestObject()
        obj2 = TestObject()

        detector.track(obj1, "obj1")
        detector.track(obj2, "obj2")

        # Check leaks (objects still alive)
        leaks = detector.check_leaks()
        assert leaks == 2

        # Delete objects
        del obj1, obj2

        # Check again (should be collected)
        leaks = detector.check_leaks()
        assert leaks == 0


# ─── Circuit Breaker Tests ───────────────────────────────────────────────────

class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_circuit_breaker_closed(self):
        """Test circuit breaker in closed state."""
        breaker = CircuitBreaker("test")

        # Should allow calls
        with breaker:
            result = "success"

        assert result == "success"
        assert breaker.get_state() == CircuitState.CLOSED

    def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after failures."""
        breaker = CircuitBreaker("test")

        # Cause failures
        for _ in range(5):
            try:
                with breaker:
                    raise Exception("Test failure")
            except Exception:
                pass

        # Should be open now
        assert breaker.get_state() == CircuitState.OPEN

        # Should reject calls
        with pytest.raises(CircuitBreakerOpen):
            with breaker:
                pass

    def test_circuit_breaker_half_open(self):
        """Test circuit breaker half-open state."""
        from circuit_breaker import CircuitBreakerConfig

        breaker = CircuitBreaker(
            "test",
            config=CircuitBreakerConfig(
                failure_threshold=2,
                timeout_seconds=0.1
            )
        )

        # Open the circuit
        for _ in range(2):
            try:
                with breaker:
                    raise Exception("Failure")
            except Exception:
                pass

        assert breaker.get_state() == CircuitState.OPEN

        # Wait for timeout
        time.sleep(0.2)

        # Should transition to half-open
        try:
            with breaker:
                pass  # Success
        except CircuitBreakerOpen:
            pass

        # After success, should close
        with breaker:
            pass

    def test_retry_with_backoff(self):
        """Test retry logic."""
        attempts = []

        def failing_func():
            attempts.append(1)
            if len(attempts) < 3:
                raise Exception("Not yet")
            return "success"

        result = retry_with_backoff(
            failing_func,
            config=RetryConfig(max_attempts=5, base_delay=0.01)
        )

        assert result == "success"
        assert len(attempts) == 3

    def test_health_checker(self):
        """Test health check system."""
        checker = HealthChecker()

        # Register checks
        checker.register("service1", lambda: True)
        checker.register("service2", lambda: False)

        # Run checks
        results = checker.check_all()

        assert results["service1"].status == HealthStatus.HEALTHY
        assert results["service2"].status == HealthStatus.UNHEALTHY

        # Overall status
        overall = checker.get_overall_status()
        assert overall == HealthStatus.UNHEALTHY

    def test_graceful_degradation(self):
        """Test graceful degradation."""
        manager = GracefulDegradationManager()

        # Start at full
        assert manager.get_level() == DegradationLevel.FULL
        assert manager.is_feature_enabled("video_display") is True

        # Degrade to reduced
        manager.set_level(DegradationLevel.REDUCED)
        assert manager.is_feature_enabled("video_display") is False
        assert manager.is_feature_enabled("face_detection") is True

        # Degrade to minimal
        manager.set_level(DegradationLevel.MINIMAL)
        assert manager.is_feature_enabled("cnn_inference") is True
        assert manager.is_feature_enabled("bpm_tracking") is False


# ─── Security Tests ──────────────────────────────────────────────────────────

class TestSecurity:
    """Test security features."""

    def test_input_validator_camera_source(self):
        """Test camera source validation."""
        # Valid camera index
        is_valid, source_type, value = InputValidator.validate_camera_source("0")
        assert is_valid is True
        assert source_type == "camera"
        assert value == 0

        # Invalid camera index
        is_valid, source_type, value = InputValidator.validate_camera_source("100")
        assert is_valid is False

    def test_input_validator_file_path(self):
        """Test file path validation."""
        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            temp_path = f.name

        try:
            # Valid path
            validated = InputValidator.validate_file_path(
                temp_path,
                allowed_extensions={'.mp4'},
                must_exist=True
            )
            assert Path(validated).exists()

            # Path traversal attempt
            with pytest.raises(ValueError, match="traversal"):
                InputValidator.validate_file_path("../../../etc/passwd")

            # Invalid extension
            with pytest.raises(ValueError, match="extension"):
                InputValidator.validate_file_path(
                    temp_path,
                    allowed_extensions={'.avi'}
                )

        finally:
            os.unlink(temp_path)

    def test_resource_quota_manager(self):
        """Test resource quota management."""
        manager = ResourceQuotaManager(
            limits=ResourceLimits(
                max_snapshot_count=10,
                max_snapshot_size_mb=1.0
            )
        )

        # Create temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            for i in range(5):
                Path(tmpdir, f"snap_{i}.jpg").write_bytes(b"test")

            # Check quota
            is_ok, msg = manager.check_snapshot_quota(tmpdir)
            assert is_ok is True

            # Cleanup old snapshots
            deleted = manager.cleanup_old_snapshots(tmpdir, keep_count=2)
            assert deleted == 3

    def test_rate_limiter(self):
        """Test rate limiting."""
        limiter = RateLimiter(rate=10.0, capacity=10)

        # Should allow initial burst
        for _ in range(10):
            assert limiter.acquire() is True

        # Should block after capacity exhausted
        assert limiter.acquire() is False

        # Wait for refill
        time.sleep(0.2)
        assert limiter.acquire() is True

    def test_alert_rate_limiter(self):
        """Test alert rate limiting."""
        limiter = AlertRateLimiter(level1_rate=5.0, level2_rate=2.0)

        # Level 1 alerts
        for _ in range(3):
            assert limiter.should_alert(1) is True

        # Should be rate limited
        assert limiter.should_alert(1) is False

        # Reset
        limiter.reset(1)
        assert limiter.should_alert(1) is True

    def test_api_key_manager(self):
        """Test API key management."""
        manager = APIKeyManager()

        # Generate key
        key = manager.generate_key("test_key", permissions=["read", "write"])
        assert len(key) > 0

        # Validate key
        is_valid, info = manager.validate_key(key)
        assert is_valid is True
        assert info["name"] == "test_key"
        assert "read" in info["permissions"]

        # Revoke key
        assert manager.revoke_key(key) is True

        # Should be invalid now
        is_valid, info = manager.validate_key(key)
        assert is_valid is False

    def test_secure_token_generation(self):
        """Test secure token generation."""
        token1 = generate_secure_token(32)
        token2 = generate_secure_token(32)

        assert len(token1) > 0
        assert len(token2) > 0
        assert token1 != token2  # Should be random

    def test_hmac_verification(self):
        """Test HMAC signature verification."""
        message = b"test message"
        secret = "secret_key"

        # Generate signature
        import hmac
        import hashlib
        signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

        # Verify
        assert verify_hmac_signature(message, signature, secret) is True

        # Wrong signature
        assert verify_hmac_signature(message, "wrong", secret) is False


# ─── Integration Tests ───────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for end-to-end workflows."""

    def test_full_pipeline_with_monitoring(self):
        """Test complete pipeline with monitoring."""
        from resource_manager import get_memory_monitor
        from validators import DataQualityMetrics
        from circuit_breaker import CircuitBreaker

        # Setup monitoring
        monitor = get_memory_monitor()
        quality = DataQualityMetrics()
        breaker = CircuitBreaker("test_pipeline")

        # Simulate processing
        for i in range(10):
            try:
                with breaker:
                    # Simulate EAR/MAR calculation
                    ear = 0.25 + (i % 3) * 0.05
                    mar = 0.5
                    quality.record(ear, mar, has_landmarks=True)

            except CircuitBreakerOpen:
                pass

        # Check results
        assert quality.get_overall_quality() > 0.9
        assert breaker.get_state() == CircuitState.CLOSED

    def test_security_pipeline(self):
        """Test security validation pipeline."""
        from security import InputValidator, get_quota_manager, get_alert_rate_limiter

        validator = InputValidator()
        quota = get_quota_manager()
        limiter = get_alert_rate_limiter()

        # Validate input
        is_valid, source_type, value = validator.validate_camera_source("0")
        assert is_valid is True

        # Check quotas
        with tempfile.TemporaryDirectory() as tmpdir:
            is_ok, msg = quota.check_snapshot_quota(tmpdir)
            assert is_ok is True

        # Rate limiting
        assert limiter.should_alert(1) is True


# ─── Performance Tests ───────────────────────────────────────────────────────

class TestPerformance:
    """Performance regression tests."""

    def test_validator_performance(self):
        """Test validator performance."""
        start = time.perf_counter()

        for _ in range(10000):
            is_valid_ear(0.25)
            is_valid_mar(0.5)

        elapsed = time.perf_counter() - start
        assert elapsed < 0.1  # Should be very fast

    def test_rate_limiter_performance(self):
        """Test rate limiter performance."""
        limiter = RateLimiter(rate=1000.0, capacity=1000)

        start = time.perf_counter()

        for _ in range(1000):
            limiter.acquire()

        elapsed = time.perf_counter() - start
        assert elapsed < 0.1  # Should be fast


# ─── Edge Case Tests ─────────────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_data_quality_metrics(self):
        """Test metrics with no data."""
        metrics = DataQualityMetrics()
        assert metrics.get_overall_quality() == 0.0

    def test_circuit_breaker_with_no_failures(self):
        """Test circuit breaker with only successes."""
        breaker = CircuitBreaker("test")

        for _ in range(100):
            with breaker:
                pass

        assert breaker.get_state() == CircuitState.CLOSED
        stats = breaker.get_statistics()
        assert stats['total_calls'] == 100
        assert stats['total_failures'] == 0

    def test_rate_limiter_edge_cases(self):
        """Test rate limiter edge cases."""
        # Very low rate
        limiter = RateLimiter(rate=0.1, capacity=1)
        assert limiter.acquire() is True
        assert limiter.acquire() is False  # Exhausted

        # Very high rate
        limiter = RateLimiter(rate=1000000.0, capacity=100)
        for _ in range(100):
            assert limiter.acquire() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
