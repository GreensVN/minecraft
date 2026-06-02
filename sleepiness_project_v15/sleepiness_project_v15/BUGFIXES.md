# Bug Fixes & Verification Log

Verified by actually running the pipeline end-to-end (synthetic video, both
PyTorch and ONNX paths, headless) — not just by static review. Every fix below
was confirmed against observed behaviour.

## Bugs found by running the code

| # | Severity | File | Symptom (observed) | Fix |
|---|----------|------|--------------------|-----|
| 1 | **Crash** | `webcam_sleepiness.py` | `signal.signal()` raises `ValueError: signal only works in main thread` when `main()` is driven from a worker thread (e.g. the API server). | Install handlers only when `threading.current_thread() is threading.main_thread()`; otherwise log and let the caller own shutdown. |
| 2 | **Crash** | `webcam_sleepiness.py`, `classroom_monitor.py` | `import mediapipe` succeeds but `mp.solutions.face_mesh` raises `AttributeError: module 'mediapipe' has no attribute 'solutions'` on some installs → hard crash at startup despite the `_MP_AVAILABLE` guard. | Wrap FaceMesh / FaceDetection construction in `try/except`; fall back to Haar cascade (webcam) or detect-only (classroom). |
| 3 | **Data loss** | `webcam_sleepiness.py` | On a video file, live calibration consumed the first ~5 s of frames; on clips shorter than the calibration window the main loop processed **0 frames**. | After calibrating a file source, rewind with `CAP_PROP_POS_FRAMES=0` (skipped for cameras / network streams). |
| 4 | **Missing dep** | `requirements.txt`, export path | `torch.onnx.export` fails with `ModuleNotFoundError: No module named 'onnxscript'` on torch ≥ 2.5 (the dynamo exporter). | Add `onnxscript>=0.1.0` and `onnx>=1.14.0` to requirements. |
| 5 | **Wrong pin** | `requirements.txt` | `numpy>=1.21,<2.0` contradicted the installed/working numpy 2.4; torch ≥ 2.3 and opencv ≥ 4.10 wheels build against numpy 2. | Relax to `numpy>=1.24` (no upper cap). |
| 6 | **Logic** | `webcam_sleepiness.py` | `_worker_restart_count` only incremented; after 3 *transient* worker failures inference stayed permanently `CNN OFF`. | Health monitor restores one restart credit after the worker stays healthy for 10 s (`_worker_last_ok` beacon updated on each successful inference). |
| 7 | **Fragility** | `webcam_sleepiness.py` | Health monitor rebound the `worker` closure variable via a mid-body `nonlocal` — works by luck, breaks if the variable is touched earlier. | Hold the worker in an explicit list cell (`_worker_handle`). |

## Integrations (modules that existed but were never wired in)

The v21 helper modules were previously written but unused. They are now actually
called from the webcam main loop:

- **`security.InputValidator`** — the `--source` argument is validated before
  `cv2.VideoCapture`. Confirmed it rejects path traversal (`../../../etc/passwd`),
  out-of-range camera indices (`99`), and non-existent files.
- **`security.get_alert_rate_limiter`** — audible alerts are token-bucket rate
  limited so a sustained drowsy state doesn't replay the buzzer every frame
  (HUD/border still show the true level).
- **`security.get_quota_manager`** — the `S` snapshot hotkey prunes the oldest
  snapshots when the directory exceeds its size/count quota.
- **`resource_manager.get_memory_monitor`** — a background memory monitor runs
  during detection (thresholds raised to 1500/2500 MB to suit a torch process)
  and is stopped in the `finally` block.

## Second robustness pass — bugs found by deeper probing

| # | Severity | File | Symptom (observed) | Fix |
|---|----------|------|--------------------|-----|
| 8 | **Garbage output** | `face_geometry.py` | `head_pose` with coincident/degenerate 2D points returns junk angles (e.g. yaw 90°); `solvePnP` reports `ok=True`. The junk yaw then silently disables EAR via `POSE_YAW_IGNORE_DEG`. Also `IndexError` on too-few landmarks. | Guard frame size, finiteness, and point spread (≥2% of frame); wrap `solvePnP` in try/except; clamp non-finite output to `(0,0,0)`. |
| 9 | **NaN baseline** | `webcam_sleepiness.py` | IQR trimmed-mean in `run_calibration` does `np.mean(slice)`; for small `min_samples` the trim slice can be empty → `np.mean([])` = NaN (+ RuntimeWarning) → EAR threshold NaN → every later comparison silently wrong. | Filter non-finite samples, fall back to the full list when the trim slice is empty, compute with `validators.nanmean_safe`. (Also restored the missing `import math`.) |
| 10 | **Wrong attribution / O(n²)** | `classroom_monitor.py` | `_match_mesh_to_tracks` recomputed each mesh centroid (`np.mean` of 478 pts) once *per track* (O(tracks×faces)), allowed the **same mesh to be assigned to multiple tracks** (swapping EAR/MAR between nearby students), and had no max-distance (a far mesh could be attached to a track with no real face). | Pre-compute each centroid once; greedy one-to-one assignment by ascending distance; reject matches beyond half the bbox diagonal. |

## Third pass — ONNX export (torch 2.x)

| # | Severity | File | Symptom (observed) | Fix |
|---|----------|------|--------------------|-----|
| 11 | **Broken artefact** | `utils_model.py` (`export_to_onnx`) | torch ≥ 2.9 defaults `torch.onnx.export` to the dynamo backend, which then asks onnxscript's `version_converter` to downconvert to opset 17 and crashes (`No initializer or constant input to node found`) — printing a full traceback while still writing a **0.2 MB truncated** ONNX file (a correct MobileNetV2 is ~8.4 MB). Inference "ran" on the broken graph. | Pass `dynamo=False` (guarded by signature check for torch < 2.5 compat) to use the stable TorchScript exporter; silence its DeprecationWarning. Now exports the full 8.4 MB model; `--verify` confirms PyTorch↔ONNX agreement to L∞ = 3e-08. |

## Fourth pass — import-time crashes & quantization API drift

| # | Severity | File | Symptom (observed) | Fix |
|---|----------|------|--------------------|-----|
| 12 | **Import crash** | `predict_sleepiness.py` | Builds `mp.solutions.face_detection` at module import inside an `except ImportError` guard. On installs where `mp.solutions` raises `AttributeError`, `import predict_sleepiness` dies outright — the whole single-image predictor is unusable and the Haar fallback is never reached. | Catch `Exception` (not just `ImportError`); validate the Haar cascade with `.empty()`. Module now imports and predicts via Haar. |
| 13 | **Import crash + no fallback** | `prepare_faces.py` | Same import-time `mp.solutions` crash; additionally the Haar cascade was only built in the `else` branch, so when MediaPipe was nominally available there was no fallback if it failed at runtime. | Broaden the guard; always construct the Haar cascade so detection works regardless. |
| 14 | **TypeError (crash)** | `quantize_onnx.py` | `quantize_dynamic()` **and** `quantize_static()` were called with `optimize_model=True`, which current onnxruntime removed → `TypeError: unexpected keyword argument 'optimize_model'`. Both quantization paths crashed immediately. | Drop the dead kwarg; pass only signature-supported args (guard `per_channel` by signature for older onnxruntime). |
| 15 | **ValueError (crash)** | `quantize_onnx.py` | Static quant with `per_channel=True` crashes in onnxruntime's `quantize_bias_static` for the final Gemm: `operands could not be broadcast (2560,) (2,)`. No INT8 file is produced. | Try `per_channel=True`, catch `ValueError`, rebuild the (consumed) calibration reader and retry with `per_channel=False`. |

## Fifth pass — REST API error semantics

| # | Severity | File | Symptom (observed) | Fix |
|---|----------|------|--------------------|-----|
| 16 | **Spurious 429** | `api_server.py` | `/detect` rate-limited by `get_alert_rate_limiter()` — the *audio buzzer* limiter (capacity 3 @ 1/s) shared with the webcam. After 3 quick requests the API returned 429. Verified: `[200,200,200,429,429,...]`. | Give the API its own `RateLimiter(rate=20, capacity=40)`; decouple from the audio path. Now 20/20 quick calls succeed. |
| 17 | **500 for client error** | `api_server.py` | Malformed base64 / non-image bytes raised `binascii.Error` caught by the broad `except Exception` → **500 Internal Server Error** instead of 400. | Decode via a `_decode_image_b64()` helper that raises `HTTPException(400)`; applied to `/detect` and `/detect/batch`. |
| 18 | **400 masked as 500** | `api_server.py` | The explicit `HTTPException(400, "Invalid image data")` was raised *inside* the `try`, so the handler's `except Exception` re-wrapped it as 500 — the 400 never reached the client. | Add `except HTTPException: raise` before the generic handler in both endpoints so client errors pass through unchanged. |

## Verification

```
# Modules that previously crashed at import now import + predict:
predict_sleepiness: import OK (MP unavailable → Haar), predict_image runs
prepare_faces:      import OK, Haar cascade always wired

# Quantization (both modes) now run end-to-end:
dynamic: 8.4 MB → 2.3 MB (3.7x), verify L∞ PASS
static : per_channel=True → auto-fallback False → 8.4 MB → 2.2 MB (3.9x), verify PASS

# Batch / async numerical correctness (vs single-image reference):
BatchOnnxPredictor / BatchTorchPredictor : max diff 0.0
OptimizedPreprocessor vs _preprocess_face: < 1e-4
OptimizedLandmarkExtractor EAR/MAR        : matches face_geometry to ~1e-8
BatchInferenceEngine (threaded)           : all results valid

# Both inference paths processed all frames of synthetic clips headless:
PyTorch : Total Frames 60/90 | Faces 60/60 | Inference ~12 ms
ONNX    : Total Frames 60    | Faces 60    | Inference ~7 ms  (8.4 MB model)
Face-disappears clip: 90 frames, num_faces correctly 1→0→1, no crash, clean recovery
Classroom: 90 frames processed, graceful fallback when MediaPipe unavailable

# ONNX export (--verify), clean (no dynamo/version_converter traceback):
[ONNX] Xác thực: PASS | 8.4 MB
PyTorch↔ONNX consistency: L∞ = 2.98e-08, L1 = 2.98e-08  (< 1e-4)

# Targeted checks:
- head_pose degenerate/short/NaN/zero-size → (0,0,0); valid spread → finite angles
- EWMA: 4 workers + 1 resetter, 8000+ concurrent predictions → 0 errors
- Centroid tracker: IDs stable across motion, clean disappear/empty handling
- Mesh matching: 2↔2 distinct, far mesh rejected, 1 mesh → 1 track (no double-assign)
- Calibration trim on 1 sample → finite (no NaN)
- Security: rejects ../traversal, camera index 99, non-existent file

# Test suite:
118 passed  (96 baseline + 22 in test_robustness.py)
```

## Notes / known environment limitations

- This dev container's MediaPipe wheel cannot load `mp.solutions`, so EAR/MAR/
  head-pose ran via the Haar fallback during verification. On a host with a
  working MediaPipe native install the landmark path is exercised; the fallback
  is what bug #2 makes safe.
- `ultralytics` and a SORT tracker are optional; classroom monitoring falls back
  to the centroid tracker without them.
