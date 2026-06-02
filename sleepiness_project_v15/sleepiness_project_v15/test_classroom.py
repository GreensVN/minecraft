"""
test_classroom.py — Unit tests for classroom_monitor pure logic (v19 NEW).

Focus: the calibration / tracker code paths that don't need YOLO, MediaPipe or a
camera. Includes a regression test for the NaN-poisoned-baseline bug fixed in v19.
"""

import math

import numpy as np
import pytest

from classroom_monitor import (
    EAR_BASELINE_MAX,
    EAR_BASELINE_MIN,
    StudentState,
    _CentroidTracker,
    _calibrate_from_samples,
    _compute_asi,
)


class TestCalibration:
    def test_trimmed_mean_within_clamp(self):
        samples = [0.28] * 100
        out = _calibrate_from_samples(samples)
        assert math.isclose(out, 0.28, rel_tol=1e-6)

    def test_clamps_low_baseline(self):
        # Sleepy-at-calibration → raw mean below physical floor → clamp up.
        out = _calibrate_from_samples([0.05] * 100)
        assert out == pytest.approx(EAR_BASELINE_MIN)

    def test_clamps_high_baseline(self):
        out = _calibrate_from_samples([0.9] * 100)
        assert out == pytest.approx(EAR_BASELINE_MAX)

    def test_empty_returns_safe_default(self):
        assert _calibrate_from_samples([]) == pytest.approx(0.28)

    def test_nan_samples_filtered(self):
        # REGRESSION (v19): NaN/inf must not poison the baseline → NaN.
        samples = [float("nan"), float("inf"), 0.30, 0.30, 0.30, 0.30]
        out = _calibrate_from_samples(samples)
        assert math.isfinite(out)
        assert EAR_BASELINE_MIN <= out <= EAR_BASELINE_MAX

    def test_all_nan_returns_default(self):
        out = _calibrate_from_samples([float("nan"), float("nan")])
        assert out == pytest.approx(0.28)


class TestComputeASI:
    def test_open_eyes_low_asi(self):
        st = StudentState(student_id=1)
        st.ear_baseline = 0.30
        st.is_calibrated = True
        score = 0.0
        for _ in range(120):
            score = _compute_asi(st, raw_ear=0.30, raw_mar=0.1, pitch=0.0)
        assert score < 5.0

    def test_closed_eyes_drive_asi_up(self):
        st = StudentState(student_id=2)
        st.ear_baseline = 0.30
        st.is_calibrated = True
        score = 0.0
        for _ in range(120):
            # EAR well below 0.75*baseline → PERCLOS saturates.
            score = _compute_asi(st, raw_ear=0.05, raw_mar=0.1, pitch=0.0)
        assert score > 30.0

    def test_nan_frames_do_not_crash(self):
        st = StudentState(student_id=3)
        st.ear_baseline = 0.30
        st.is_calibrated = True
        score = _compute_asi(st, raw_ear=float("nan"), raw_mar=float("nan"), pitch=0.0)
        assert math.isfinite(score)


class TestCentroidTracker:
    def test_registers_new_objects(self):
        t = _CentroidTracker()
        pairs = t.update(np.array([[0, 0, 10, 10], [100, 100, 110, 110]], dtype=np.float32))
        assert len(pairs) == 2
        ids = {tid for tid, _ in pairs}
        assert len(ids) == 2, "each detection gets a unique id"

    def test_keeps_identity_across_frames(self):
        t = _CentroidTracker()
        first = dict((tuple(np.round(b)), tid)
                     for tid, b in t.update(np.array([[0, 0, 10, 10]], dtype=np.float32)))
        # Slight movement of the same face.
        pairs2 = t.update(np.array([[2, 2, 12, 12]], dtype=np.float32))
        assert len(pairs2) == 1
        tid2 = pairs2[0][0]
        assert tid2 == next(iter(first.values())), "id must persist for the same face"

    def test_distinct_faces_get_distinct_ids(self):
        t = _CentroidTracker()
        t.update(np.array([[0, 0, 10, 10]], dtype=np.float32))
        pairs = t.update(np.array([[0, 0, 10, 10], [300, 300, 320, 320]], dtype=np.float32))
        ids = {tid for tid, _ in pairs}
        assert len(ids) == 2

    def test_max_distance_forces_new_track(self):
        t = _CentroidTracker(max_distance=5.0)
        p1 = t.update(np.array([[0, 0, 10, 10]], dtype=np.float32))
        # Jump far beyond max_distance → should NOT reuse the id.
        p2 = t.update(np.array([[200, 200, 210, 210]], dtype=np.float32))
        assert p1[0][0] != p2[0][0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
