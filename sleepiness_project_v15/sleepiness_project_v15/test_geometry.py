"""
test_geometry.py — Unit tests for face_geometry EAR/MAR/head-pose helpers (v19 NEW).

These cover the pure-math primitives that the whole detection pipeline relies on
but that previously had no automated coverage.
"""

import math

import cv2
import numpy as np
import pytest

from face_geometry import (
    FACE_3D_POINTS,
    POSE_LM_IDS,
    ear,
    head_pose,
    mar,
)


class _Pt:
    """Minimal stand-in for a MediaPipe NormalizedLandmark (.x / .y in [0, 1])."""

    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x = float(x)
        self.y = float(y)


class TestEAR:
    def test_open_eye_ratio(self):
        # Horizontal span 0.6, vertical spans 0.2 each (w = h = 100).
        lm = [
            _Pt(0.0, 0.5),  # p0 outer corner
            _Pt(0.2, 0.4),  # p1 top
            _Pt(0.4, 0.4),  # p2 top
            _Pt(0.6, 0.5),  # p3 inner corner
            _Pt(0.4, 0.6),  # p4 bottom
            _Pt(0.2, 0.6),  # p5 bottom
        ]
        val = ear(lm, [0, 1, 2, 3, 4, 5], 100, 100)
        assert math.isclose(val, 40.0 / 120.0, rel_tol=1e-6)

    def test_closed_eye_is_low(self):
        # Vertical pairs collapse → EAR ≈ 0.
        lm = [
            _Pt(0.0, 0.5),
            _Pt(0.2, 0.5),
            _Pt(0.4, 0.5),
            _Pt(0.6, 0.5),
            _Pt(0.4, 0.5),
            _Pt(0.2, 0.5),
        ]
        assert ear(lm, [0, 1, 2, 3, 4, 5], 100, 100) == pytest.approx(0.0)

    def test_degenerate_horizontal_returns_one(self):
        # p0 == p3 → horizontal distance 0 → safe "wide open" sentinel.
        lm = [_Pt(0.5, 0.5)] * 6
        assert ear(lm, [0, 1, 2, 3, 4, 5], 100, 100) == 1.0


class TestMAR:
    def test_mouth_ratio(self):
        lm = [
            _Pt(0.0, 0.5),   # p0 left corner
            _Pt(0.5, 0.5),   # p1 right corner -> horiz 50
            _Pt(0.25, 0.4),  # p2
            _Pt(0.25, 0.6),  # p3 -> vert 20
            _Pt(0.30, 0.4),  # p4
            _Pt(0.30, 0.6),  # p5 -> vert 20
        ]
        # vert = 40, horiz = 50 -> 40 / (2*50) = 0.4
        assert mar(lm, [0, 1, 2, 3, 4, 5], 100, 100) == pytest.approx(0.4)

    def test_degenerate_horizontal_returns_zero(self):
        lm = [_Pt(0.5, 0.5)] * 6
        assert mar(lm, [0, 1, 2, 3, 4, 5], 100, 100) == 0.0


class TestHeadPose:
    def test_frontal_face_returns_finite_small_angles(self):
        w, h = 640, 480
        focal = float(w)
        cam = np.array(
            [[focal, 0, w / 2.0], [0, focal, h / 2.0], [0, 0, 1]],
            dtype=np.float64,
        )
        rvec = np.zeros((3, 1))
        tvec = np.array([[0.0], [0.0], [1000.0]])
        pts2d, _ = cv2.projectPoints(FACE_3D_POINTS, rvec, tvec, cam, np.zeros((4, 1)))
        pts2d = pts2d.reshape(-1, 2)

        lm = {idx: _Pt(u / w, v / h) for idx, (u, v) in zip(POSE_LM_IDS, pts2d)}
        pitch, yaw, roll = head_pose(lm, w, h)

        assert all(math.isfinite(a) for a in (pitch, yaw, roll))
        # Perfectly frontal projection → yaw/pitch close to zero.
        assert abs(yaw) < 20.0
        assert abs(pitch) < 20.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
