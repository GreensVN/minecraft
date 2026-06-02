"""
validators.py — Data validation utilities (v21 NEW).

Provides validation functions for:
- EAR/MAR values (NaN-safe)
- Head pose angles
- Probability vectors
- Input sanitization
- Data quality metrics
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

import numpy as np


# ─── Sentinel Values ─────────────────────────────────────────────────────────

# Use sentinel values instead of NaN for better type safety and performance
INVALID_EAR = -1.0
INVALID_MAR = -1.0
INVALID_ANGLE = -999.0


# ─── EAR/MAR Validation ──────────────────────────────────────────────────────

def is_valid_ear(ear: float) -> bool:
    """
    Check if EAR value is valid.

    Args:
        ear: Eye Aspect Ratio value

    Returns:
        True if valid (finite and in reasonable range)
    """
    if not isinstance(ear, (int, float)):
        return False
    if not math.isfinite(ear):
        return False
    # EAR typically ranges from 0.0 (closed) to 0.4 (wide open)
    # Allow slightly wider range for edge cases
    return 0.0 <= ear <= 1.0


def is_valid_mar(mar: float) -> bool:
    """
    Check if MAR value is valid.

    Args:
        mar: Mouth Aspect Ratio value

    Returns:
        True if valid (finite and in reasonable range)
    """
    if not isinstance(mar, (int, float)):
        return False
    if not math.isfinite(mar):
        return False
    # MAR typically ranges from 0.0 (closed) to 0.8 (wide open/yawn)
    # Allow up to 2.0 for extreme cases
    return 0.0 <= mar <= 2.0


def validate_ear(ear: float, default: float = INVALID_EAR) -> float:
    """
    Validate and sanitize EAR value.

    Args:
        ear: Eye Aspect Ratio value
        default: Default value if invalid

    Returns:
        Validated EAR or default if invalid
    """
    return ear if is_valid_ear(ear) else default


def validate_mar(mar: float, default: float = INVALID_MAR) -> float:
    """
    Validate and sanitize MAR value.

    Args:
        mar: Mouth Aspect Ratio value
        default: Default value if invalid

    Returns:
        Validated MAR or default if invalid
    """
    return mar if is_valid_mar(mar) else default


# ─── Head Pose Validation ────────────────────────────────────────────────────

def is_valid_angle(angle: float) -> bool:
    """
    Check if angle is valid.

    Args:
        angle: Angle in degrees

    Returns:
        True if valid (finite and in reasonable range)
    """
    if not isinstance(angle, (int, float)):
        return False
    if not math.isfinite(angle):
        return False
    # Angles should be in [-180, 180] range
    return -180.0 <= angle <= 180.0


def validate_head_pose(
    pitch: float, yaw: float, roll: float
) -> Tuple[float, float, float]:
    """
    Validate and sanitize head pose angles.

    Args:
        pitch: Pitch angle (degrees)
        yaw: Yaw angle (degrees)
        roll: Roll angle (degrees)

    Returns:
        Tuple of (validated_pitch, validated_yaw, validated_roll)
    """
    return (
        pitch if is_valid_angle(pitch) else INVALID_ANGLE,
        yaw if is_valid_angle(yaw) else INVALID_ANGLE,
        roll if is_valid_angle(roll) else INVALID_ANGLE,
    )


# ─── Probability Validation ──────────────────────────────────────────────────

def is_valid_probability(prob: float) -> bool:
    """
    Check if probability value is valid.

    Args:
        prob: Probability value

    Returns:
        True if valid (finite and in [0, 1])
    """
    if not isinstance(prob, (int, float)):
        return False
    if not math.isfinite(prob):
        return False
    return 0.0 <= prob <= 1.0


def validate_probability_vector(probs: np.ndarray, normalize: bool = True) -> np.ndarray:
    """
    Validate and sanitize probability vector.

    Args:
        probs: Probability vector
        normalize: Whether to normalize if sum != 1.0

    Returns:
        Validated probability vector

    Raises:
        ValueError: If vector is invalid and cannot be fixed
    """
    if not isinstance(probs, np.ndarray):
        raise ValueError(f"Expected numpy array, got {type(probs)}")

    if probs.ndim != 1:
        raise ValueError(f"Expected 1D array, got shape {probs.shape}")

    if len(probs) == 0:
        raise ValueError("Empty probability vector")

    # Check for NaN/inf
    if not np.all(np.isfinite(probs)):
        raise ValueError("Probability vector contains NaN or inf")

    # Check for negative values
    if np.any(probs < 0):
        raise ValueError("Probability vector contains negative values")

    # Normalize if requested and sum != 1.0
    prob_sum = np.sum(probs)
    if normalize and not np.isclose(prob_sum, 1.0, atol=1e-5):
        if prob_sum > 0:
            probs = probs / prob_sum
        else:
            # All zeros → uniform distribution
            probs = np.ones_like(probs) / len(probs)

    return probs.astype(np.float32)


# ─── NaN-Aware Statistics ────────────────────────────────────────────────────

def nanmean_safe(values: list, default: float = 0.0) -> float:
    """
    Compute mean, skipping NaN and invalid values.

    Args:
        values: List of values
        default: Default if all values are invalid

    Returns:
        Mean of valid values or default
    """
    valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return float(np.mean(valid)) if valid else default


def nanmedian_safe(values: list, default: float = 0.0) -> float:
    """
    Compute median, skipping NaN and invalid values.

    Args:
        values: List of values
        default: Default if all values are invalid

    Returns:
        Median of valid values or default
    """
    valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return float(np.median(valid)) if valid else default


def nanpercentile_safe(values: list, percentile: float, default: float = 0.0) -> float:
    """
    Compute percentile, skipping NaN and invalid values.

    Args:
        values: List of values
        percentile: Percentile to compute (0-100)
        default: Default if all values are invalid

    Returns:
        Percentile of valid values or default
    """
    valid = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return float(np.percentile(valid, percentile)) if valid else default


def count_valid(values: list) -> int:
    """
    Count valid (finite) values.

    Args:
        values: List of values

    Returns:
        Number of valid values
    """
    return sum(1 for v in values if isinstance(v, (int, float)) and math.isfinite(v))


def valid_ratio(values: list) -> float:
    """
    Compute ratio of valid values.

    Args:
        values: List of values

    Returns:
        Ratio of valid values (0.0 to 1.0)
    """
    if not values:
        return 0.0
    return count_valid(values) / len(values)


# ─── Data Quality Metrics ────────────────────────────────────────────────────

class DataQualityMetrics:
    """
    [v21 NEW] Track data quality metrics.

    Monitors:
    - Invalid value rate
    - Missing landmark rate
    - Outlier rate
    - Data freshness
    """

    def __init__(self, window_size: int = 100):
        """
        Initialize data quality tracker.

        Args:
            window_size: Number of recent samples to track
        """
        from collections import deque
        self.window_size = window_size
        self.ear_values = deque(maxlen=window_size)
        self.mar_values = deque(maxlen=window_size)
        self.landmark_present = deque(maxlen=window_size)

    def record(self, ear: float, mar: float, has_landmarks: bool) -> None:
        """
        Record a sample.

        Args:
            ear: EAR value
            mar: MAR value
            has_landmarks: Whether landmarks were detected
        """
        self.ear_values.append(ear)
        self.mar_values.append(mar)
        self.landmark_present.append(has_landmarks)

    def get_ear_quality(self) -> float:
        """Get EAR data quality (0.0 = bad, 1.0 = good)."""
        if not self.ear_values:
            return 0.0
        return valid_ratio(list(self.ear_values))

    def get_mar_quality(self) -> float:
        """Get MAR data quality (0.0 = bad, 1.0 = good)."""
        if not self.mar_values:
            return 0.0
        return valid_ratio(list(self.mar_values))

    def get_landmark_detection_rate(self) -> float:
        """Get landmark detection rate (0.0 to 1.0)."""
        if not self.landmark_present:
            return 0.0
        return sum(self.landmark_present) / len(self.landmark_present)

    def get_overall_quality(self) -> float:
        """Get overall data quality score (0.0 to 1.0)."""
        ear_q = self.get_ear_quality()
        mar_q = self.get_mar_quality()
        landmark_q = self.get_landmark_detection_rate()
        return (ear_q + mar_q + landmark_q) / 3.0

    def is_quality_acceptable(self, threshold: float = 0.7) -> bool:
        """
        Check if data quality is acceptable.

        Args:
            threshold: Minimum acceptable quality (0.0 to 1.0)

        Returns:
            True if quality >= threshold
        """
        return self.get_overall_quality() >= threshold

    def get_summary(self) -> dict:
        """Get quality metrics summary."""
        return {
            'ear_quality': self.get_ear_quality(),
            'mar_quality': self.get_mar_quality(),
            'landmark_detection_rate': self.get_landmark_detection_rate(),
            'overall_quality': self.get_overall_quality(),
            'samples': len(self.ear_values),
        }


# ─── Input Sanitization ──────────────────────────────────────────────────────

def sanitize_camera_index(index: Union[int, str]) -> int:
    """
    Sanitize camera index input.

    Args:
        index: Camera index (int or string)

    Returns:
        Validated camera index

    Raises:
        ValueError: If index is invalid
    """
    if isinstance(index, str):
        if not index.isdigit():
            raise ValueError(f"Invalid camera index: {index}")
        index = int(index)

    if not isinstance(index, int):
        raise ValueError(f"Camera index must be int, got {type(index)}")

    if index < 0 or index > 10:  # Reasonable limit
        raise ValueError(f"Camera index out of range: {index}")

    return index


def sanitize_file_path(path: str, allowed_extensions: Optional[list] = None) -> str:
    """
    Sanitize file path input.

    Args:
        path: File path
        allowed_extensions: List of allowed extensions (e.g., ['.mp4', '.avi'])

    Returns:
        Validated file path

    Raises:
        ValueError: If path is invalid
    """
    import os

    if not isinstance(path, str):
        raise ValueError(f"Path must be string, got {type(path)}")

    if not path.strip():
        raise ValueError("Empty path")

    # Check for path traversal attempts
    if '..' in path or path.startswith('/'):
        raise ValueError(f"Suspicious path: {path}")

    # Check extension if specified
    if allowed_extensions:
        ext = os.path.splitext(path)[1].lower()
        if ext not in allowed_extensions:
            raise ValueError(f"Invalid extension {ext}, allowed: {allowed_extensions}")

    return path


def sanitize_numeric_param(
    value: Union[int, float, str],
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
    param_name: str = "parameter"
) -> float:
    """
    Sanitize numeric parameter.

    Args:
        value: Parameter value
        min_val: Minimum allowed value
        max_val: Maximum allowed value
        param_name: Parameter name for error messages

    Returns:
        Validated numeric value

    Raises:
        ValueError: If value is invalid
    """
    try:
        num_val = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid {param_name}: {value}")

    if not math.isfinite(num_val):
        raise ValueError(f"{param_name} must be finite, got {num_val}")

    if min_val is not None and num_val < min_val:
        raise ValueError(f"{param_name} must be >= {min_val}, got {num_val}")

    if max_val is not None and num_val > max_val:
        raise ValueError(f"{param_name} must be <= {max_val}, got {num_val}")

    return num_val
