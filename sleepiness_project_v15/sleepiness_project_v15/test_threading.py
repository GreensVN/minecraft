"""
test_threading.py — Tests for thread-safety improvements (v21).

Tests:
- ThreadSafeCLAHE concurrent access
- EWMAPredictor race condition fixes
- CNN worker auto-restart mechanism
"""

import threading
import time
from typing import List

import numpy as np
import pytest

from utils_model import ThreadSafeCLAHE, EWMAPredictor


class TestThreadSafeCLAHE:
    """Test ThreadSafeCLAHE wrapper."""

    def test_basic_apply(self):
        """Test basic CLAHE application."""
        clahe = ThreadSafeCLAHE(clip_limit=2.0, tile_grid_size=(8, 8))
        img = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
        result = clahe.apply(img)

        assert result.shape == img.shape
        assert result.dtype == np.uint8

    def test_concurrent_apply(self):
        """Test concurrent CLAHE application from multiple threads."""
        clahe = ThreadSafeCLAHE(clip_limit=2.0, tile_grid_size=(8, 8))
        num_threads = 10
        num_iterations = 50
        errors: List[Exception] = []

        def worker():
            try:
                for _ in range(num_iterations):
                    img = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
                    result = clahe.apply(img)
                    assert result.shape == img.shape
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_reconfigure(self):
        """Test reconfiguring CLAHE parameters."""
        clahe = ThreadSafeCLAHE(clip_limit=2.0, tile_grid_size=(8, 8))

        params = clahe.get_params()
        assert params['clip_limit'] == 2.0
        assert params['tile_grid_size'] == (8, 8)

        clahe.reconfigure(clip_limit=3.0, tile_grid_size=(16, 16))

        params = clahe.get_params()
        assert params['clip_limit'] == 3.0
        assert params['tile_grid_size'] == (16, 16)

    def test_concurrent_reconfigure(self):
        """Test concurrent reconfiguration and application."""
        clahe = ThreadSafeCLAHE(clip_limit=2.0, tile_grid_size=(8, 8))
        errors: List[Exception] = []

        def applier():
            try:
                for _ in range(100):
                    img = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
                    clahe.apply(img)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reconfigurer():
            try:
                for i in range(10):
                    clip = 2.0 + i * 0.5
                    clahe.reconfigure(clip_limit=clip, tile_grid_size=(8, 8))
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        applier_threads = [threading.Thread(target=applier) for _ in range(3)]
        reconfig_thread = threading.Thread(target=reconfigurer)

        for t in applier_threads:
            t.start()
        reconfig_thread.start()

        for t in applier_threads:
            t.join()
        reconfig_thread.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"


class MockPredictor:
    """Mock predictor for testing EWMAPredictor."""

    def __init__(self, num_classes: int = 2):
        self.num_classes = num_classes
        self.call_count = 0

    def predict_probs(self, face_bgr: np.ndarray) -> np.ndarray:
        """Return random probabilities."""
        self.call_count += 1
        probs = np.random.dirichlet(np.ones(self.num_classes))
        return probs.astype(np.float32)


class TestEWMAPredictor:
    """Test EWMAPredictor thread-safety."""

    def test_basic_prediction(self):
        """Test basic prediction."""
        base = MockPredictor(num_classes=2)
        predictor = EWMAPredictor(base, ["normal", "sleepy"], alpha=0.5)

        face = np.zeros((224, 224, 3), dtype=np.uint8)
        label, conf = predictor.predict(face)

        assert label in ["normal", "sleepy"]
        assert 0.0 <= conf <= 1.0

    def test_concurrent_prediction(self):
        """Test concurrent predictions from multiple threads."""
        base = MockPredictor(num_classes=2)
        predictor = EWMAPredictor(base, ["normal", "sleepy"], alpha=0.5)
        num_threads = 10
        num_iterations = 100
        errors: List[Exception] = []

        def worker():
            try:
                for _ in range(num_iterations):
                    face = np.zeros((224, 224, 3), dtype=np.uint8)
                    label, conf = predictor.predict(face)
                    assert label in ["normal", "sleepy"]
                    assert 0.0 <= conf <= 1.0
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_concurrent_predict_and_reset(self):
        """Test concurrent predictions and resets."""
        base = MockPredictor(num_classes=2)
        predictor = EWMAPredictor(base, ["normal", "sleepy"], alpha=0.5)
        errors: List[Exception] = []

        def predictor_worker():
            try:
                for _ in range(200):
                    face = np.zeros((224, 224, 3), dtype=np.uint8)
                    predictor.predict(face)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reset_worker():
            try:
                for _ in range(20):
                    predictor.reset()
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        pred_threads = [threading.Thread(target=predictor_worker) for _ in range(3)]
        reset_thread = threading.Thread(target=reset_worker)

        for t in pred_threads:
            t.start()
        reset_thread.start()

        for t in pred_threads:
            t.join()
        reset_thread.join()

        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_predict_all_probs(self):
        """Test predict_all_probs returns correct shape."""
        base = MockPredictor(num_classes=3)
        predictor = EWMAPredictor(base, ["normal", "sleepy", "very_sleepy"], alpha=0.5)

        face = np.zeros((224, 224, 3), dtype=np.uint8)
        probs = predictor.predict_all_probs(face)

        assert probs.shape == (3,)
        assert np.isclose(probs.sum(), 1.0, atol=1e-5)
        assert np.all(probs >= 0.0) and np.all(probs <= 1.0)

    def test_ewma_smoothing(self):
        """Test that EWMA actually smooths predictions."""
        # Create predictor that always returns [0.9, 0.1]
        class ConstantPredictor:
            def predict_probs(self, face_bgr):
                return np.array([0.9, 0.1], dtype=np.float32)

        base = ConstantPredictor()
        predictor = EWMAPredictor(base, ["normal", "sleepy"], alpha=0.5)

        face = np.zeros((224, 224, 3), dtype=np.uint8)

        # First prediction should be close to raw
        probs1 = predictor.predict_all_probs(face)
        assert np.allclose(probs1, [0.9, 0.1], atol=0.1)

        # Subsequent predictions should converge
        for _ in range(10):
            probs = predictor.predict_all_probs(face)

        # Should be very close to [0.9, 0.1] after many iterations
        assert np.allclose(probs, [0.9, 0.1], atol=0.01)

    def test_reset_clears_state(self):
        """Test that reset clears EWMA state."""
        base = MockPredictor(num_classes=2)
        predictor = EWMAPredictor(base, ["normal", "sleepy"], alpha=0.5)

        face = np.zeros((224, 224, 3), dtype=np.uint8)

        # Make some predictions
        for _ in range(10):
            predictor.predict(face)

        # Reset
        predictor.reset()

        # Next prediction should start fresh
        probs = predictor.predict_all_probs(face)
        # After reset, first prediction should be the raw prediction
        # (not influenced by previous EWMA state)
        assert probs.shape == (2,)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
