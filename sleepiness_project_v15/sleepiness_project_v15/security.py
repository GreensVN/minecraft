"""
security.py — Security hardening utilities (v21 NEW).

Provides security features for production deployment:
- Input validation and sanitization
- Path traversal prevention
- Resource limits and quotas
- Rate limiting
- Authentication helpers
- Audit logging
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ─── Input Validation ────────────────────────────────────────────────────────

class InputValidator:
    """
    [v21 NEW] Comprehensive input validation.

    Validates and sanitizes all user inputs to prevent security vulnerabilities.
    """

    # Allowed video extensions
    ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv'}

    # Allowed image extensions
    ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}

    # Maximum path length
    MAX_PATH_LENGTH = 4096

    # Camera index range
    MIN_CAMERA_INDEX = 0
    MAX_CAMERA_INDEX = 10

    @staticmethod
    def validate_camera_source(source: str) -> Tuple[bool, str, Optional[int]]:
        """
        Validate camera source (index or file path).

        Args:
            source: Camera index or file path

        Returns:
            (is_valid, source_type, validated_value)
            source_type: "camera" or "file"
            validated_value: int for camera, str for file
        """
        # Check if it's a camera index
        if source.isdigit():
            index = int(source)
            if InputValidator.MIN_CAMERA_INDEX <= index <= InputValidator.MAX_CAMERA_INDEX:
                return True, "camera", index
            else:
                logger.error(f"Camera index out of range: {index}")
                return False, "camera", None

        # Check if it's a file path
        try:
            validated_path = InputValidator.validate_file_path(
                source,
                allowed_extensions=InputValidator.ALLOWED_VIDEO_EXTENSIONS,
                must_exist=True
            )
            return True, "file", validated_path
        except ValueError as e:
            logger.error(f"Invalid source: {e}")
            return False, "file", None

    @staticmethod
    def validate_file_path(
        path: str,
        allowed_extensions: Optional[Set[str]] = None,
        must_exist: bool = False,
        allow_absolute_only: bool = False,
    ) -> str:
        """
        Validate and sanitize file path.

        Args:
            path: File path to validate
            allowed_extensions: Set of allowed extensions (e.g., {'.mp4', '.avi'})
            must_exist: Whether file must exist
            allow_absolute_only: Only allow absolute paths

        Returns:
            Validated absolute path

        Raises:
            ValueError: If path is invalid
        """
        if not isinstance(path, str):
            raise ValueError(f"Path must be string, got {type(path)}")

        if not path.strip():
            raise ValueError("Empty path")

        # Check length
        if len(path) > InputValidator.MAX_PATH_LENGTH:
            raise ValueError(f"Path too long: {len(path)} > {InputValidator.MAX_PATH_LENGTH}")

        # Convert to Path object
        try:
            path_obj = Path(path)
        except Exception as e:
            raise ValueError(f"Invalid path: {e}")

        # Check for path traversal attempts
        if '..' in path_obj.parts:
            raise ValueError("Path traversal detected (..)")

        # Resolve to absolute path
        try:
            abs_path = path_obj.resolve()
        except Exception as e:
            raise ValueError(f"Cannot resolve path: {e}")

        # Check if absolute path required
        if allow_absolute_only and not path_obj.is_absolute():
            raise ValueError("Only absolute paths allowed")

        # Check extension
        if allowed_extensions:
            ext = abs_path.suffix.lower()
            if ext not in allowed_extensions:
                raise ValueError(
                    f"Invalid extension {ext}, allowed: {allowed_extensions}"
                )

        # Check existence
        if must_exist and not abs_path.exists():
            raise ValueError(f"Path does not exist: {abs_path}")

        return str(abs_path)

    @staticmethod
    def validate_output_path(
        path: str,
        allowed_extensions: Optional[Set[str]] = None,
        create_parent: bool = True,
    ) -> str:
        """
        Validate output file path.

        Args:
            path: Output file path
            allowed_extensions: Allowed extensions
            create_parent: Create parent directory if not exists

        Returns:
            Validated absolute path

        Raises:
            ValueError: If path is invalid
        """
        validated = InputValidator.validate_file_path(
            path,
            allowed_extensions=allowed_extensions,
            must_exist=False,
            allow_absolute_only=False,
        )

        path_obj = Path(validated)

        # Create parent directory
        if create_parent:
            try:
                path_obj.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise ValueError(f"Cannot create parent directory: {e}")

        return validated

    @staticmethod
    def sanitize_filename(filename: str, max_length: int = 255) -> str:
        """
        Sanitize filename to prevent security issues.

        Args:
            filename: Original filename
            max_length: Maximum filename length

        Returns:
            Sanitized filename
        """
        # Remove path separators
        filename = os.path.basename(filename)

        # Remove dangerous characters
        filename = re.sub(r'[^\w\s\-\.]', '_', filename)

        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')

        # Limit length
        if len(filename) > max_length:
            name, ext = os.path.splitext(filename)
            name = name[:max_length - len(ext) - 1]
            filename = name + ext

        # Ensure not empty
        if not filename:
            filename = 'unnamed'

        return filename


# ─── Resource Limits ─────────────────────────────────────────────────────────

@dataclass
class ResourceLimits:
    """Resource limits configuration."""
    max_snapshot_size_mb: float = 100.0      # Max total snapshot directory size
    max_snapshot_count: int = 1000           # Max number of snapshots
    max_metrics_size_mb: float = 50.0        # Max metrics directory size
    max_log_size_mb: float = 100.0           # Max log file size
    max_memory_mb: float = 1000.0            # Max memory usage
    max_cpu_percent: float = 80.0            # Max CPU usage


class ResourceQuotaManager:
    """
    [v21 NEW] Manage resource quotas to prevent abuse.

    Monitors and enforces limits on:
    - Disk usage (snapshots, metrics, logs)
    - Memory usage
    - CPU usage
    """

    def __init__(self, limits: Optional[ResourceLimits] = None):
        """
        Initialize quota manager.

        Args:
            limits: Resource limits configuration
        """
        self.limits = limits or ResourceLimits()

    def check_snapshot_quota(self, snapshot_dir: str) -> Tuple[bool, str]:
        """
        Check if snapshot quota is exceeded.

        Args:
            snapshot_dir: Snapshot directory path

        Returns:
            (is_ok, message)
        """
        if not os.path.exists(snapshot_dir):
            return True, "OK"

        try:
            # Count files
            files = [f for f in os.listdir(snapshot_dir) if os.path.isfile(os.path.join(snapshot_dir, f))]
            file_count = len(files)

            if file_count >= self.limits.max_snapshot_count:
                return False, f"Snapshot count limit exceeded: {file_count} >= {self.limits.max_snapshot_count}"

            # Calculate total size
            total_size = sum(
                os.path.getsize(os.path.join(snapshot_dir, f))
                for f in files
            )
            total_size_mb = total_size / (1024 * 1024)

            if total_size_mb >= self.limits.max_snapshot_size_mb:
                return False, f"Snapshot size limit exceeded: {total_size_mb:.1f}MB >= {self.limits.max_snapshot_size_mb}MB"

            return True, f"OK ({file_count} files, {total_size_mb:.1f}MB)"

        except Exception as e:
            logger.error(f"Error checking snapshot quota: {e}")
            return False, f"Error: {e}"

    def cleanup_old_snapshots(self, snapshot_dir: str, keep_count: int = 100) -> int:
        """
        Clean up old snapshots to free space.

        Args:
            snapshot_dir: Snapshot directory
            keep_count: Number of recent snapshots to keep

        Returns:
            Number of files deleted
        """
        if not os.path.exists(snapshot_dir):
            return 0

        try:
            # Get all files with timestamps
            files = []
            for f in os.listdir(snapshot_dir):
                path = os.path.join(snapshot_dir, f)
                if os.path.isfile(path):
                    mtime = os.path.getmtime(path)
                    files.append((mtime, path))

            # Sort by modification time (newest first)
            files.sort(reverse=True)

            # Delete old files
            deleted = 0
            for _, path in files[keep_count:]:
                try:
                    os.remove(path)
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Cannot delete {path}: {e}")

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old snapshots")

            return deleted

        except Exception as e:
            logger.error(f"Error cleaning snapshots: {e}")
            return 0

    def check_memory_quota(self) -> Tuple[bool, str]:
        """
        Check if memory quota is exceeded.

        Returns:
            (is_ok, message)
        """
        try:
            import psutil
            process = psutil.Process(os.getpid())
            memory_mb = process.memory_info().rss / (1024 * 1024)

            if memory_mb >= self.limits.max_memory_mb:
                return False, f"Memory limit exceeded: {memory_mb:.1f}MB >= {self.limits.max_memory_mb}MB"

            return True, f"OK ({memory_mb:.1f}MB)"

        except ImportError:
            return True, "psutil not available"
        except Exception as e:
            logger.error(f"Error checking memory: {e}")
            return False, f"Error: {e}"


# ─── Rate Limiting ───────────────────────────────────────────────────────────

class RateLimiter:
    """
    [v21 NEW] Token bucket rate limiter.

    Prevents abuse by limiting request rate.
    """

    def __init__(self, rate: float, capacity: int):
        """
        Initialize rate limiter.

        Args:
            rate: Tokens per second
            capacity: Maximum tokens (burst capacity)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()
        self._lock = __import__('threading').Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if acquired, False if rate limited
        """
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update

            # Add tokens based on elapsed time
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            # Try to acquire
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            else:
                return False

    def reset(self) -> None:
        """Reset rate limiter."""
        with self._lock:
            self.tokens = self.capacity
            self.last_update = time.time()


class AlertRateLimiter:
    """
    [v21 NEW] Rate limiter specifically for alerts.

    Prevents alert spam by limiting alert frequency per level.
    """

    def __init__(
        self,
        level1_rate: float = 1.0,  # 1 per second
        level2_rate: float = 0.5,  # 1 per 2 seconds
    ):
        """
        Initialize alert rate limiter.

        Args:
            level1_rate: Level 1 alerts per second
            level2_rate: Level 2 alerts per second
        """
        self.limiters = {
            1: RateLimiter(rate=level1_rate, capacity=3),
            2: RateLimiter(rate=level2_rate, capacity=2),
        }

    def should_alert(self, level: int) -> bool:
        """
        Check if alert should be sent.

        Args:
            level: Alert level (1 or 2)

        Returns:
            True if alert should be sent
        """
        if level not in self.limiters:
            return True

        return self.limiters[level].acquire()

    def reset(self, level: Optional[int] = None) -> None:
        """
        Reset rate limiter.

        Args:
            level: Alert level to reset (None = all)
        """
        if level is None:
            for limiter in self.limiters.values():
                limiter.reset()
        elif level in self.limiters:
            self.limiters[level].reset()


# ─── Authentication Helpers ──────────────────────────────────────────────────

class APIKeyManager:
    """
    [v21 NEW] Simple API key management.

    For future REST API authentication.
    """

    def __init__(self):
        """Initialize API key manager."""
        self._keys: Dict[str, Dict] = {}  # key -> {name, created, permissions}

    def generate_key(self, name: str, permissions: Optional[List[str]] = None) -> str:
        """
        Generate new API key.

        Args:
            name: Key name/description
            permissions: List of permissions

        Returns:
            Generated API key
        """
        # Generate secure random key
        key = secrets.token_urlsafe(32)

        self._keys[key] = {
            'name': name,
            'created': time.time(),
            'permissions': permissions or [],
        }

        logger.info(f"Generated API key: {name}")
        return key

    def validate_key(self, key: str) -> Tuple[bool, Optional[Dict]]:
        """
        Validate API key.

        Args:
            key: API key to validate

        Returns:
            (is_valid, key_info)
        """
        if key in self._keys:
            return True, self._keys[key]
        else:
            return False, None

    def revoke_key(self, key: str) -> bool:
        """
        Revoke API key.

        Args:
            key: API key to revoke

        Returns:
            True if revoked
        """
        if key in self._keys:
            name = self._keys[key]['name']
            del self._keys[key]
            logger.info(f"Revoked API key: {name}")
            return True
        return False


def generate_secure_token(length: int = 32) -> str:
    """
    Generate cryptographically secure random token.

    Args:
        length: Token length in bytes

    Returns:
        URL-safe token string
    """
    return secrets.token_urlsafe(length)


def verify_hmac_signature(
    message: bytes,
    signature: str,
    secret: str,
    algorithm: str = 'sha256'
) -> bool:
    """
    Verify HMAC signature.

    Args:
        message: Message bytes
        signature: Signature to verify (hex string)
        secret: Secret key
        algorithm: Hash algorithm

    Returns:
        True if signature is valid
    """
    try:
        expected = hmac.new(
            secret.encode(),
            message,
            getattr(hashlib, algorithm)
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"HMAC verification error: {e}")
        return False


# ─── Audit Logging ───────────────────────────────────────────────────────────

class AuditLogger:
    """
    [v21 NEW] Audit logging for security events.

    Logs security-relevant events for compliance and forensics.
    """

    def __init__(self, log_file: Optional[str] = None):
        """
        Initialize audit logger.

        Args:
            log_file: Optional audit log file path
        """
        self.logger = logging.getLogger('audit')
        self.log_file = log_file

        if log_file:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s - AUDIT - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_access(self, user: str, resource: str, action: str, result: str) -> None:
        """
        Log access attempt.

        Args:
            user: User identifier
            resource: Resource accessed
            action: Action performed
            result: Result (success/failure)
        """
        self.logger.info(f"ACCESS | user={user} | resource={resource} | action={action} | result={result}")

    def log_auth(self, user: str, method: str, result: str, ip: Optional[str] = None) -> None:
        """
        Log authentication attempt.

        Args:
            user: User identifier
            method: Auth method
            result: Result (success/failure)
            ip: IP address
        """
        ip_str = f" | ip={ip}" if ip else ""
        self.logger.info(f"AUTH | user={user} | method={method} | result={result}{ip_str}")

    def log_config_change(self, user: str, parameter: str, old_value: str, new_value: str) -> None:
        """
        Log configuration change.

        Args:
            user: User who made change
            parameter: Parameter changed
            old_value: Old value
            new_value: New value
        """
        self.logger.info(
            f"CONFIG | user={user} | param={parameter} | "
            f"old={old_value} | new={new_value}"
        )

    def log_security_event(self, event_type: str, details: str, severity: str = "INFO") -> None:
        """
        Log security event.

        Args:
            event_type: Type of event
            details: Event details
            severity: Severity level
        """
        self.logger.log(
            getattr(logging, severity),
            f"SECURITY | type={event_type} | details={details}"
        )


# ─── Global Instances ────────────────────────────────────────────────────────

_quota_manager: Optional[ResourceQuotaManager] = None
_alert_rate_limiter: Optional[AlertRateLimiter] = None
_audit_logger: Optional[AuditLogger] = None


def get_quota_manager() -> ResourceQuotaManager:
    """Get global quota manager instance."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = ResourceQuotaManager()
    return _quota_manager


def get_alert_rate_limiter() -> AlertRateLimiter:
    """Get global alert rate limiter instance."""
    global _alert_rate_limiter
    if _alert_rate_limiter is None:
        _alert_rate_limiter = AlertRateLimiter()
    return _alert_rate_limiter


def get_audit_logger() -> AuditLogger:
    """Get global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
