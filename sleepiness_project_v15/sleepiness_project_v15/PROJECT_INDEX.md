# Project Index — Sleepiness Detection System

A real-time drowsiness detection system: MediaPipe FaceMesh (with Haar fallback)
+ MobileNetV2/ResNet/EfficientNet CNN + ONNX Runtime, plus a multi-student
classroom monitor.

## Documentation

| File | Purpose |
|------|---------|
| `README.md` | Project overview (original) |
| `USER_GUIDE.md` | Feature documentation and usage |
| `GETTING_STARTED.md` | Quick setup walkthrough |
| `MIGRATION_GUIDE.md` | Upgrade notes |
| `BUGFIXES.md` | Log of bugs found by running the pipeline, with fixes and how each was verified |
| `CHANGELOG.md` | Version history |
| `PROJECT_INDEX.md` | This file — map of the codebase |

## Source modules

### Detection / inference
| File | Responsibility |
|------|----------------|
| `webcam_sleepiness.py` | Single-face real-time loop: capture → detect → EAR/MAR/pose → CNN → EWMA → multi-stage alert. Headless + video-file + metrics support. |
| `classroom_monitor.py` | Multi-student loop: detect → track → per-student ASI scoring. |
| `face_geometry.py` | Landmark constants + `ear()`, `mar()`, `head_pose()` (degenerate-input safe). |
| `face_crop.py` | `crop_face_with_padding()` shared crop helper. |
| `utils_model.py` | `build_model`, `load_model`, `OnnxPredictor`, `TorchPredictor`, `EWMAPredictor`, `ThreadSafeCLAHE`, `export_to_onnx`. |
| `predict_sleepiness.py` | Single-image prediction (cached model). |
| `audio_warning.py` | Lazy-initialised multi-level audio alerts. |

### Training / export
| File | Responsibility |
|------|----------------|
| `train_sleepiness.py` | Training: FocalLoss + targeted-eye CutMix, resume support. |
| `prepare_faces.py` | Crop faces from `raw_data/` into `data/` (resumable). |
| `export_onnx.py` | PyTorch → ONNX with `--verify` consistency check. |
| `quantize_onnx.py` | FP32 → INT8 with real-image calibration. |

### Infrastructure (support modules)
| File | Responsibility |
|------|----------------|
| `config.py` | `AppConfig` dataclass: validation, presets, YAML/env layering. |
| `logger_config.py` | Centralised logging (colored / JSON / rotating). |
| `metrics.py` | `MetricsCollector`, `LatencyTracker` (FPS / latency / memory / alerts). |
| `validators.py` | NaN-safe stats, EAR/MAR/angle validation, input sanitisation, `DataQualityMetrics`. |
| `resource_manager.py` | MediaPipe cleanup, `MemoryMonitor`, GC scheduler, leak detector. |
| `security.py` | `InputValidator`, resource quotas, rate limiting, API keys, audit log. |
| `circuit_breaker.py` | Circuit breaker, retry-with-backoff, health checks, graceful degradation. |
| `async_face_detection.py` | Non-blocking MediaPipe + batch/optimised landmark extraction. |
| `batch_inference.py` | Dynamic batching, batch ONNX/Torch predictors, GPU pooling. |
| `api_server.py` | FastAPI REST + WebSocket service (needs `fastapi`, `uvicorn`). |

### Tests
| File | Covers |
|------|--------|
| `test_config.py` | Config validation / presets / env. |
| `test_metrics.py` | Metrics + latency percentiles. |
| `test_geometry.py` | EAR / MAR / head pose. |
| `test_face_crop.py` | Crop-with-padding. |
| `test_classroom.py` | Classroom monitor + tracker. |
| `test_threading.py` | EWMA + CLAHE thread safety. |
| `test_comprehensive.py` | validators / security / circuit_breaker / resource_manager. |
| `test_robustness.py` | Regression pins for bugs in `BUGFIXES.md` (head_pose, calibration NaN, mesh matching, ONNX export). |

### Deployment
| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage, non-root, health-checked image. |
| `docker-compose.yml` | API + monitoring stack. |
| `k8s-deployment.yaml` | Deployment, service, HPA, ingress, network policy. |
| `requirements.txt` / `requirements-dev.txt` | Runtime / dev dependencies. |

## Data layout
```
data/{train,val}/{binh_thuong,thieu_ngu}/   # processed training crops
raw_data/{train,val}/...                      # unprocessed source images
```

## Run

```bash
pip install -r requirements.txt

python prepare_faces.py                       # build dataset
python train_sleepiness.py                    # train
python export_onnx.py --verify                # export + check
python webcam_sleepiness.py --onnx            # run (ONNX)
python webcam_sleepiness.py --source clip.mp4 --no-mirror --no-display   # offline
python classroom_monitor.py --source 0        # classroom

pytest                                         # tests
```
