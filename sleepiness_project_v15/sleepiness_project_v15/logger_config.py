"""
logger_config.py — Centralized logging configuration (v18 NEW).

Provides structured logging with:
- Multiple handlers (console, file, rotating file)
- Colored console output
- JSON structured logging option
- Performance metrics logging
- Context managers for timed operations
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, Any
import json
from datetime import datetime, timezone


class ColoredFormatter(logging.Formatter):
    """Colored console formatter for better readability."""

    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add custom fields
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


class PerformanceLogger:
    """Logger for performance metrics."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.metrics: Dict[str, list] = {}

    def log_metric(self, name: str, value: float, unit: str = "") -> None:
        """Log a performance metric."""
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)

        self.logger.debug(f"[METRIC] {name}: {value:.3f} {unit}")

    def get_stats(self, name: str) -> Optional[Dict[str, float]]:
        """Get statistics for a metric."""
        if name not in self.metrics or not self.metrics[name]:
            return None

        import numpy as np
        values = self.metrics[name]
        return {
            'count': len(values),
            'mean': float(np.mean(values)),
            'std': float(np.std(values)),
            'min': float(np.min(values)),
            'max': float(np.max(values)),
            'median': float(np.median(values)),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        self.metrics.clear()

    def summary(self) -> str:
        """Get summary of all metrics."""
        lines = ["Performance Metrics Summary:"]
        for name in sorted(self.metrics.keys()):
            stats = self.get_stats(name)
            if stats:
                lines.append(
                    f"  {name}: mean={stats['mean']:.3f} "
                    f"std={stats['std']:.3f} "
                    f"min={stats['min']:.3f} "
                    f"max={stats['max']:.3f} "
                    f"(n={stats['count']})"
                )
        return "\n".join(lines)


def setup_logging(
    level: str = "INFO",
    log_to_file: bool = False,
    log_file_path: str = "sleepiness.log",
    use_colors: bool = True,
    use_json: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Setup centralized logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to file
        log_file_path: Path to log file
        use_colors: Use colored console output
        use_json: Use JSON structured logging
        max_bytes: Max size of log file before rotation
        backup_count: Number of backup files to keep

    Returns:
        Configured root logger
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    if use_json:
        console_formatter = JSONFormatter()
    elif use_colors and sys.stdout.isatty():
        console_formatter = ColoredFormatter(
            '%(levelname)s  %(name)s:%(funcName)s:%(lineno)d  %(message)s'
        )
    else:
        console_formatter = logging.Formatter(
            '%(levelname)s  %(name)s:%(funcName)s:%(lineno)d  %(message)s'
        )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler with rotation
    if log_to_file:
        from logging.handlers import RotatingFileHandler

        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
        file_handler.setLevel(logging.DEBUG)

        if use_json:
            file_formatter = JSONFormatter()
        else:
            file_formatter = logging.Formatter(
                '%(asctime)s  %(levelname)s  %(name)s:%(funcName)s:%(lineno)d  %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    return root_logger


@contextmanager
def timed_operation(logger: logging.Logger, operation_name: str, level: int = logging.INFO):
    """
    Context manager for timing operations.

    Usage:
        with timed_operation(logger, "model_inference"):
            result = model.predict(image)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.log(level, f"[TIMING] {operation_name}: {elapsed*1000:.2f}ms")


@contextmanager
def log_exceptions(logger: logging.Logger, operation: str = "operation", reraise: bool = True):
    """
    Context manager for logging exceptions.

    Usage:
        with log_exceptions(logger, "face_detection"):
            faces = detector.detect(image)
    """
    try:
        yield
    except Exception as e:
        logger.exception(f"[ERROR] Exception in {operation}: {e}")
        if reraise:
            raise


# Global performance logger instance
_perf_logger: Optional[PerformanceLogger] = None


def get_performance_logger() -> PerformanceLogger:
    """Get global performance logger instance."""
    global _perf_logger
    if _perf_logger is None:
        _perf_logger = PerformanceLogger(logging.getLogger("performance"))
    return _perf_logger
