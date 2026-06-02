# Sleepiness Detection System v21 🚀

**Real-time drowsiness detection system** với MediaPipe FaceMesh + MobileNetV2 CNN + ONNX Runtime.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

---

## ✨ What's New in v21

### 🛡️ **Critical Bug Fixes**
- ✅ **Thread-Safety**: Fixed race conditions trong EWMAPredictor và CLAHE
- ✅ **Auto-Restart**: CNN worker tự động recovery với exponential backoff
- ✅ **Memory Leaks**: Proper cleanup cho MediaPipe resources
- ✅ **NaN Propagation**: Sentinel values thay NaN cho type safety
- ✅ **Graceful Shutdown**: SIGTERM/SIGINT handling

### ⚡ **Performance Improvements**
- ✅ **Async Face Detection**: Non-blocking MediaPipe processing
- ✅ **Optimized Landmark Extraction**: Vectorized operations
- ✅ **Batch Processing**: Process multiple frames together
- ✅ **Frame Dropping Strategy**: Intelligent queue management

### 🔧 **New Features**
- ✅ **Circuit Breaker**: Fault tolerance pattern
- ✅ **Health Checks**: Monitor component health
- ✅ **Graceful Degradation**: Auto-disable non-critical features under stress
- ✅ **Memory Monitoring**: Real-time tracking với alerts
- ✅ **Data Quality Metrics**: Track EAR/MAR quality
- ✅ **Resource Management**: Context managers cho cleanup

---

## 🎯 Features

### Core Detection
- **Real-time Face Detection**: MediaPipe FaceMesh (468 landmarks)
- **Eye Aspect Ratio (EAR)**: Detect eye closure
- **Mouth Aspect Ratio (MAR)**: Detect yawning
- **Head Pose Estimation**: Pitch, yaw, roll angles
- **Blink Rate (BPM)**: Track blink frequency
- **CNN Classification**: MobileNetV2 for sleepiness detection

### Advanced Features
- **Multi-Stage Alerts**: Warning → Alert → Critical
- **Adaptive Calibration**: Personalized thresholds
- **EWMA Smoothing**: Reduce false positives
- **Audio Warnings**: Multi-level alerts
- **Classroom Monitoring**: Multi-student tracking với ASI scoring
- **ONNX Runtime**: 2-5x faster inference

### Production Ready
- **Thread-Safe**: No race conditions
- **Auto-Recovery**: Worker auto-restart
- **Memory Safe**: No leaks in long sessions
- **Graceful Degradation**: Fault tolerance
- **Health Monitoring**: Component health checks
- **Metrics Export**: JSON/CSV session statistics

---

## 📦 Installation

### Requirements
- Python 3.8+
- Webcam or video file
- (Optional) CUDA GPU for faster inference

### Quick Start

```bash
# Clone repository
git clone <repo-url>
cd sleepiness_project_v15

# Install dependencies
pip install -r requirements.txt

# Prepare data (if training)
python prepare_faces.py

# Train model (optional)
python train_sleepiness.py

# Export to ONNX (recommended)
python export_onnx.py --verify

# Run detection
python webcam_sleepiness.py --onnx
```

---

## 🚀 Usage

### Basic Usage

```bash
# Webcam detection (ONNX)
python webcam_sleepiness.py --onnx

# Video file
python webcam_sleepiness.py --source video.mp4 --no-mirror

# Headless mode (no display)
python webcam_sleepiness.py --no-display --max-frames 1000

# Custom config
python webcam_sleepiness.py --preset strict --config my_config.yaml
```

### Classroom Monitoring

```bash
# Monitor classroom
python classroom_monitor.py --source 0

# With CSV export
python classroom_monitor.py --source rtsp://camera --report-csv classroom.csv
```

### Advanced Usage

```python
from resource_manager import MediaPipeResourceManager, get_memory_monitor
from validators import DataQualityMetrics
from circuit_breaker import CircuitBreaker, get_health_checker

# Memory monitoring
monitor = get_memory_monitor()
monitor.set_warning_callback(lambda mem: print(f"High memory: {mem}MB"))
monitor.start()

# Data quality tracking
quality = DataQualityMetrics(window_size=100)
quality.record(ear, mar, has_landmarks=True)
print(quality.get_summary())

# Circuit breaker for CNN inference
breaker = CircuitBreaker(name="cnn_inference")
try:
    with breaker:
        result = model.predict(face)
except CircuitBreakerOpen:
    result = fallback_prediction()

# Health checks
checker = get_health_checker()
checker.register("camera", lambda: cap.isOpened())
checker.register("model", lambda: model is not None)
results = checker.check_all()
```

---

## 📊 Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Main Thread                              │
├─────────────────────────────────────────────────────────────┤
│  Camera Capture → MediaPipe FaceMesh → EAR/MAR/Pose         │
│       ↓                                                       │
│  Face Crop → CLAHE → CNN Worker Thread                      │
│                           ↓                                   │
│                      ONNX/PyTorch                            │
│                           ↓                                   │
│                    EWMA Smoothing                            │
│                           ↓                                   │
│                   Alert Decision                             │
│                           ↓                                   │
│                   Audio Warning                              │
└─────────────────────────────────────────────────────────────┘

Background Threads:
├── CNN Worker (inference)
├── Health Monitor (worker liveness)
├── Memory Monitor (memory tracking)
└── GC Scheduler (periodic cleanup)
```

### Data Flow

```
Raw Frame (BGR)
    ↓
MediaPipe FaceMesh (RGB)
    ↓
Landmarks (468 points)
    ↓
┌─────────────┬──────────────┬─────────────┐
│   EAR/MAR   │  Head Pose   │  Face Crop  │
│  Validate   │   Validate   │   + CLAHE   │
└─────────────┴──────────────┴─────────────┘
         ↓            ↓              ↓
    Calibration   Ignore if    CNN Inference
                  yaw > 30°         ↓
         ↓                      EWMA Filter
    Threshold                       ↓
         ↓                    Sleep Probability
    Alert Logic ←──────────────────┘
         ↓
    Audio Warning
```

---

## 🔧 Configuration

### Config File (config.yaml)

```yaml
# EAR/MAR thresholds
ear_threshold_default: 0.22
mar_threshold_default: 0.60

# Alert frames
ear_warn_frames: 8
ear_alert_frames: 20

# Performance
fps_target: 30.0
enable_metrics: true

# Logging
log_level: INFO
log_to_file: false

# Runtime
show_window: true
mirror_camera: true
```

### Environment Variables

```bash
export SLEEPINESS_EAR_THRESHOLD_DEFAULT=0.24
export SLEEPINESS_LOG_LEVEL=DEBUG
export SLEEPINESS_ENABLE_METRICS=true
```

### Presets

```bash
# Strict (sensitive detection)
python webcam_sleepiness.py --preset strict

# Balanced (default)
python webcam_sleepiness.py --preset balanced

# Relaxed (fewer false positives)
python webcam_sleepiness.py --preset relaxed
```

---

## 📈 Performance

### Benchmarks (Intel i7-10700K, RTX 3070)

| Mode | FPS | Latency | Memory |
|------|-----|---------|--------|
| PyTorch CPU | 15-20 | ~50ms | 450MB |
| ONNX CPU | 30-35 | ~20ms | 380MB |
| ONNX GPU | 60+ | ~10ms | 420MB |

### Optimization Tips

1. **Use ONNX Runtime**: 2-5x faster than PyTorch
2. **Enable GPU**: `pip install onnxruntime-gpu`
3. **Reduce CNN skip**: Lower `cnn_skip` for more frequent inference
4. **Disable display**: Use `--no-display` for headless mode
5. **Batch processing**: Use `BatchFaceDetector` for offline videos

---

## 🧪 Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific test
pytest test_threading.py -v

# Threading stress tests
pytest test_threading.py::TestEWMAPredictor::test_concurrent_prediction -v
```

### Test Coverage

- **Threading**: 95%+ (race conditions, concurrent access)
- **Config**: 95%+ (validation, presets, env vars)
- **Metrics**: 90%+ (FPS, latency, memory)
- **Overall**: 80%+ (target)

---

## 📚 Documentation

### Core Modules

- **`webcam_sleepiness.py`**: Main detection loop
- **`classroom_monitor.py`**: Multi-student monitoring
- **`train_sleepiness.py`**: Model training
- **`utils_model.py`**: Model utilities, predictors
- **`config.py`**: Configuration management

### New Modules (v21)

- **`resource_manager.py`**: Memory & resource management
- **`validators.py`**: Data validation & sanitization
- **`async_face_detection.py`**: Async MediaPipe processing
- **`circuit_breaker.py`**: Fault tolerance patterns
- **`test_threading.py`**: Threading safety tests

### Documentation Files

- **`MIGRATION_GUIDE.md`**: Upgrade guide & migration
- **`BUGFIXES.md`**: Bugs found by running the pipeline, with fixes and verification
- **`PROJECT_INDEX.md`**: Map of the whole codebase
- **`CHANGELOG.md`**: Version history
- **`GETTING_STARTED.md`**: Quick start guide

---

## 🐛 Troubleshooting

### Common Issues

**1. Low FPS**
```bash
# Use ONNX
python webcam_sleepiness.py --onnx

# Reduce CNN frequency
# Edit config.yaml: cnn_skip: 5
```

**2. High Memory Usage**
```python
# Enable memory monitoring
from resource_manager import get_memory_monitor
monitor = get_memory_monitor()
monitor.start()
```

**3. Worker Crashes**
```bash
# Check logs
python webcam_sleepiness.py --log-level DEBUG --log-file debug.log

# Worker auto-restarts up to 3 times
# Check health monitor logs
```

**4. False Positives**
```bash
# Use relaxed preset
python webcam_sleepiness.py --preset relaxed

# Or adjust thresholds in config.yaml
```

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure tests pass: `pytest`
5. Format code: `black .`
6. Submit pull request

---

## 📄 License

MIT License - see LICENSE file for details.

---

## 🙏 Acknowledgments

### Technologies Used
- **MediaPipe**: Face landmark detection
- **PyTorch**: Deep learning framework
- **ONNX Runtime**: Optimized inference
- **OpenCV**: Computer vision
- **NumPy**: Numerical computing

### References
- Eye Aspect Ratio (EAR): Soukupová & Čech, 2016
- Mouth Aspect Ratio (MAR): Adapted from EAR
- Head Pose Estimation: solvePnP with EPnP
- Circuit Breaker Pattern: Michael Nygard, "Release It!"

---

## 📞 Support

- **Issues**: GitHub Issues
- **Documentation**: See `docs/` folder
- **Email**: [your-email]

---

## 🗺️ Roadmap

### v21.1 (Next Release)
- [ ] REST API with FastAPI
- [ ] Web dashboard
- [ ] Docker containerization
- [ ] Kubernetes deployment

### v22.0 (Future)
- [ ] Multi-camera support
- [ ] Database integration
- [ ] Advanced analytics
- [ ] Mobile app

---

**Made with ❤️ for safer driving and better productivity**

**Version**: v21.0.0  
**Release Date**: 2026-05-31  
**Python**: 3.8+  
**Status**: Production Ready ✅
