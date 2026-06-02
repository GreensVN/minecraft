"""
test_face_crop.py — Unit tests for face_crop.crop_face_with_padding (v19 NEW).
"""

import numpy as np
import pytest

from face_crop import crop_face_with_padding


def _img(h=200, w=200):
    # Distinct per-pixel values so we can assert on crop content if needed.
    return np.full((h, w, 3), 127, dtype=np.uint8)


class TestCropFaceWithPadding:
    def test_returns_square(self):
        out = crop_face_with_padding(_img(), (50, 50, 60, 80), padding=0.25)
        assert out is not None
        assert out.shape[0] == out.shape[1], "crop must be square"

    def test_none_image(self):
        assert crop_face_with_padding(None, (0, 0, 10, 10)) is None

    def test_empty_image(self):
        assert crop_face_with_padding(np.empty((0, 0, 3), dtype=np.uint8), (0, 0, 10, 10)) is None

    def test_zero_width_bbox(self):
        assert crop_face_with_padding(_img(), (10, 10, 0, 30)) is None

    def test_negative_dim_bbox(self):
        assert crop_face_with_padding(_img(), (10, 10, -5, 30)) is None

    def test_bbox_fully_outside_returns_none(self):
        # Far off the right/bottom edge → no valid intersection.
        assert crop_face_with_padding(_img(100, 100), (500, 500, 20, 20)) is None

    def test_edge_bbox_is_padded_to_square(self):
        # Face flush against the top-left corner still yields a square via border pad.
        out = crop_face_with_padding(_img(120, 120), (0, 0, 40, 60), padding=0.5)
        assert out is not None
        assert out.shape[0] == out.shape[1]
        assert out.shape[2] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
