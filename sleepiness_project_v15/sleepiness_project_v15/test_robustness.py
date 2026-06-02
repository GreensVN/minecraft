"""
test_robustness.py — Regression tests for bugs found by running the pipeline.

Each test pins a specific defect fixed in the robustness pass so it can't
silently come back. See BUGFIXES.md for the narrative.
"""

import math

import numpy as np
import pytest


class _LM:
    """Minimal MediaPipe-landmark stand-in with .x / .y."""
    def __init__(self, x, y):
        self.x = x
        self.y = y


# ─── head_pose degenerate-input guards ───────────────────────────────────────

class TestHeadPoseGuards:
    def test_all_points_coincident_returns_zero(self):
        from face_geometry import head_pose
        lm = [_LM(0.5, 0.5) for _ in range(478)]
        assert head_pose(lm, 640, 480) == (0.0, 0.0, 0.0)

    def test_missing_landmarks_no_crash(self):
        from face_geometry import head_pose
        # Fewer landmarks than POSE_LM_IDS references → must not raise.
        assert head_pose([_LM(0.5, 0.5) for _ in range(5)], 640, 480) == (0.0, 0.0, 0.0)

    def test_zero_frame_size(self):
        from face_geometry import head_pose
        assert head_pose([_LM(0.5, 0.5) for _ in range(478)], 0, 0) == (0.0, 0.0, 0.0)

    def test_nan_landmarks(self):
        from face_geometry import head_pose
        lm = [_LM(float("nan"), 0.5) for _ in range(478)]
        assert head_pose(lm, 640, 480) == (0.0, 0.0, 0.0)

    def test_valid_spread_returns_finite(self):
        from face_geometry import head_pose, POSE_LM_IDS
        # Construct a well-spread, non-degenerate set of pose points.
        lm = [_LM(0.5, 0.5) for _ in range(478)]
        spread = [(0.5, 0.3), (0.5, 0.8), (0.3, 0.5),
                  (0.7, 0.5), (0.4, 0.7), (0.6, 0.7)]
        for idx, (x, y) in zip(POSE_LM_IDS, spread):
            lm[idx] = _LM(x, y)
        p, y, r = head_pose(lm, 640, 480)
        assert all(math.isfinite(v) for v in (p, y, r))


# ─── Calibration empty-slice / NaN guard ─────────────────────────────────────

class TestCalibrationTrimmedMean:
    def test_nanmean_safe_on_empty(self):
        from validators import nanmean_safe
        assert nanmean_safe([], default=0.4) == 0.4

    def test_nanmean_safe_filters_nan(self):
        from validators import nanmean_safe
        vals = [0.2, float("nan"), 0.4, float("inf")]
        assert abs(nanmean_safe(vals, default=0.0) - 0.3) < 1e-9

    def test_single_sample_trim_does_not_nan(self):
        # Mirrors the webcam calibration trim logic on a 1-element list.
        from validators import nanmean_safe
        mar_sorted = sorted(s for s in [0.5] if math.isfinite(s))
        cutoff = int(len(mar_sorted) * 0.75)  # 0
        valid = mar_sorted[:cutoff] or mar_sorted
        result = nanmean_safe(valid, default=0.4)
        assert math.isfinite(result)
        assert result == 0.5


# ─── Mesh-to-track one-to-one matching ───────────────────────────────────────

class _MeshSet:
    def __init__(self, cx, cy):
        self.landmark = [_LM(cx, cy) for _ in range(478)]


class _Results:
    def __init__(self, sets):
        self.multi_face_landmarks = sets


def _make_monitor():
    from classroom_monitor import ClassroomMonitor
    return ClassroomMonitor.__new__(ClassroomMonitor)  # bypass __init__


class TestMeshMatching:
    def test_two_tracks_two_meshes_distinct(self):
        m = _make_monitor()
        w, h = 640, 480
        tracks = [(0, np.array([50, 50, 150, 150])),
                  (1, np.array([450, 350, 550, 450]))]
        meshes = _Results([_MeshSet(100 / w, 100 / h), _MeshSet(500 / w, 400 / h)])
        res = m._match_mesh_to_tracks(tracks, meshes, w, h)
        assert len(res) == 2
        assert set(res.keys()) == {0, 1}

    def test_far_mesh_rejected(self):
        m = _make_monitor()
        w, h = 640, 480
        tracks = [(5, np.array([0, 0, 40, 40]))]
        meshes = _Results([_MeshSet(0.5, 0.5)])  # centre, far from corner bbox
        res = m._match_mesh_to_tracks(tracks, meshes, w, h)
        assert res == {}

    def test_one_mesh_one_track_no_double_assign(self):
        m = _make_monitor()
        w, h = 640, 480
        tracks = [(7, np.array([100, 100, 200, 200])),
                  (8, np.array([110, 110, 210, 210]))]
        meshes = _Results([_MeshSet(150 / w, 150 / h)])
        res = m._match_mesh_to_tracks(tracks, meshes, w, h)
        assert len(res) == 1  # only the closer track gets it

    def test_empty_mesh_results(self):
        m = _make_monitor()
        assert m._match_mesh_to_tracks([(0, np.array([0, 0, 10, 10]))], None, 640, 480) == {}


# ─── ONNX export produces a complete, consistent model ───────────────────────

class TestOnnxExport:
    def test_export_is_full_and_consistent(self, tmp_path):
        """Regression for the torch-2.x dynamo export that silently wrote a
        ~0.2 MB truncated graph. A real MobileNetV2 export is multi-MB and must
        agree with PyTorch logits."""
        torch = pytest.importorskip("torch")
        pytest.importorskip("onnx")
        ort = pytest.importorskip("onnxruntime")
        import numpy as np
        from utils_model import build_model, export_to_onnx, _preprocess_face

        model = build_model(2, training=False, init_pretrained=False)
        model.eval()
        out = tmp_path / "m.onnx"
        export_to_onnx(model, str(out), img_size=224, opset_version=17)

        # A truncated/broken export was ~0.2 MB; the real graph is several MB.
        size_mb = out.stat().st_size / (1024 * 1024)
        assert size_mb > 1.0, f"ONNX file suspiciously small: {size_mb:.2f} MB"

        # PyTorch vs ONNX logits must match closely.
        face = np.random.randint(0, 256, (224, 224, 3), dtype=np.uint8)
        x = _preprocess_face(face, 224)
        sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
        onnx_logits = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]

        import cv2
        from PIL import Image
        from utils_model import get_transform
        tfm = get_transform(224)
        xt = tfm(Image.fromarray(cv2.cvtColor(face, cv2.COLOR_BGR2RGB))).unsqueeze(0)
        with torch.inference_mode():
            pt_logits = model(xt)[0].numpy()

        assert float(np.abs(pt_logits - onnx_logits).max()) < 1e-3


# ─── Modules import without a working MediaPipe ──────────────────────────────

class TestImportResilience:
    """These modules built mp.solutions at import with an ImportError-only guard,
    so an mp.solutions AttributeError crashed the whole import. They must import
    regardless and fall back to Haar."""

    def test_predict_sleepiness_imports(self):
        import importlib
        mod = importlib.import_module("predict_sleepiness")
        # At least one detector path must be available (Haar is built-in to cv2).
        assert mod._HAAR_AVAILABLE or mod._MP_AVAILABLE

    def test_prepare_faces_imports(self):
        import importlib
        mod = importlib.import_module("prepare_faces")
        # Haar cascade must always be wired up as a fallback.
        assert mod._face_cascade is not None or mod._MP_AVAILABLE


# ─── Quantization API compatibility ──────────────────────────────────────────

class TestQuantizationApi:
    """quantize_static/dynamic dropped optimize_model and per_channel can crash
    the final Gemm bias quant. The wrappers must not pass dead kwargs and must
    fall back cleanly."""

    def test_no_dead_kwargs_in_source(self):
        src = open("quantize_onnx.py", encoding="utf-8").read()
        # The removed kwarg must not be *passed* (it may still be named in a
        # comment explaining why it was dropped).
        assert "optimize_model=" not in src

    def test_dynamic_quantize_runs(self, tmp_path):
        pytest.importorskip("onnxruntime")
        import json
        import torch
        from utils_model import build_model, export_to_onnx
        import quantize_onnx

        fp32 = tmp_path / "m.onnx"
        model = build_model(2, training=False, init_pretrained=False).eval()
        export_to_onnx(model, str(fp32))

        out = tmp_path / "m_int8.onnx"
        quantize_onnx.quantize_dynamic(str(fp32), str(out))
        assert out.exists() and out.stat().st_size > 0


# ─── REST API error semantics ────────────────────────────────────────────────

def _api_client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import api_server
    from fastapi.testclient import TestClient
    key = api_server.api_key_manager.generate_key("test", ["read", "write", "admin"])
    return api_server, TestClient(api_server.app), key


def _jpeg_b64():
    import base64
    import cv2
    import numpy as np
    img = np.full((224, 224, 3), 120, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    return base64.b64encode(buf).decode()


class TestApiErrorSemantics:
    def test_detect_not_throttled_by_audio_limiter(self):
        """20 quick calls must all succeed — the API must not reuse the
        audio-alert limiter (capacity 3)."""
        api_server, client, key = _api_client()
        b64 = _jpeg_b64()
        with client:
            h = {"Authorization": f"Bearer {key}"}
            codes = [client.post("/detect", json={"image_base64": b64}, headers=h).status_code
                     for _ in range(20)]
        assert codes.count(200) == 20, codes

    def test_bad_base64_is_400_not_500(self):
        api_server, client, key = _api_client()
        with client:
            h = {"Authorization": f"Bearer {key}"}
            r = client.post("/detect", json={"image_base64": "bad!!!"}, headers=h)
        assert r.status_code == 400

    def test_non_image_bytes_is_400(self):
        import base64
        api_server, client, key = _api_client()
        with client:
            h = {"Authorization": f"Bearer {key}"}
            payload = base64.b64encode(b"hello world").decode()
            r = client.post("/detect", json={"image_base64": payload}, headers=h)
        assert r.status_code == 400

    def test_batch_with_bad_entry_is_400(self):
        api_server, client, key = _api_client()
        b64 = _jpeg_b64()
        with client:
            h = {"Authorization": f"Bearer {key}"}
            r = client.post("/detect/batch",
                            json={"images_base64": [b64, "bad!!!"]}, headers=h)
        assert r.status_code == 400

    def test_unauthenticated_detect_is_401(self):
        api_server, client, key = _api_client()
        with client:
            r = client.post("/detect", json={"image_base64": "x"})
        assert r.status_code in (401, 403)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
