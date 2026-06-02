# Sleepiness Detection System v18 - Comprehensive Upgrade

## 🎉 What's New in v18

This is a **MAJOR UPGRADE** that transforms the sleepiness detection system from v17 to a production-ready, enterprise-grade application with:

### ✨ Key Improvements

1. **Configuration Management** - Centralized, validated configuration with presets
2. **Logging Infrastructure** - Structured, colored logging with rotation
3. **Metrics & Monitoring** - Real-time performance tracking and statistics
4. **Testing Framework** - Comprehensive unit tests with pytest
5. **Error Handling** - Robust validation and graceful degradation
6. **Performance** - Optimizations and profiling support
7. **Code Quality** - Type hints, docstrings, and quality tools

### 📦 New Files

- `logger_config.py` - Centralized logging configuration
- `metrics.py` - Performance metrics and monitoring
- `test_config.py` - Unit tests for configuration
- `test_metrics.py` - Unit tests for metrics
- `CHANGELOG.md` - Detailed changelog
- `requirements.txt` - Runtime dependencies
- `requirements-dev.txt` - Development & tooling dependencies
- `pyproject.toml` - Project metadata + pytest/black/mypy config
- `.flake8` - Linting configuration

### 🔧 Enhanced Files

- `config.py` - Added validation, presets, env vars, JSON export
- `requirements.txt` - Updated with new dependencies

## 🚀 Quick Start

### Installation

```bash
# Runtime only
pip install -r requirements.txt

# With dev tools (tests, linting, optional features)
pip install -r requirements-dev.txt
```

### Basic Usage

```python
from config import get_config
from logger_config import setup_logging
from metrics import get_metrics_collector

# Setup
logger = setup_logging(level="INFO", use_colors=True)
config = get_config()
metrics = get_metrics_collector()

# Use in your code
logger.info(f"Starting with camera {config.camera_index}")
# ... your detection code ...
metrics.record_frame(detection_time_ms=10.5, num_faces=1)
```

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html

# View coverage
open htmlcov/index.html
```

### Configuration

Create `config.yaml` to override defaults:

```yaml
# Detection thresholds
ear_threshold_default: 0.24
mar_threshold_default: 0.58

# Camera
camera_index: 0
img_size: 224

# Performance
fps_target: 30.0
enable_metrics: true

# Logging
log_level: INFO
log_to_file: true
log_file_path: sleepiness.log
```

Or use environment variables:

```bash
export SLEEPINESS_EAR_THRESHOLD_DEFAULT=0.24
export SLEEPINESS_CAMERA_INDEX=1
export SLEEPINESS_LOG_LEVEL=DEBUG
```

Or use presets:

```python
from config import AppConfig

# Strict: sensitive detection
config = AppConfig.preset_strict()

# Balanced: default settings
config = AppConfig.preset_balanced()

# Relaxed: fewer false positives
config = AppConfig.preset_relaxed()
```

## 📊 Metrics & Monitoring

### Real-time Metrics

```python
from metrics import get_metrics_collector

metrics = get_metrics_collector()

# In your main loop
metrics.record_frame(
    detection_time_ms=10.5,
    inference_time_ms=15.2,
    num_faces=1,
    alert_level=0
)

# Get current stats
print(f"FPS: {metrics.get_current_fps():.1f}")
print(f"Avg detection: {metrics.get_avg_detection_time():.2f}ms")
print(f"Memory: {metrics.get_memory_usage_mb():.1f}MB")
```

### Session Summary

```python
# At end of session
print(metrics.get_summary())

# Export to files
metrics.export_to_json("session_stats.json")
metrics.export_frame_metrics_to_csv("frame_metrics.csv")
```

## 🧪 Testing

### Test Structure

```
test_config.py      - Configuration tests
test_metrics.py     - Metrics tests
test_*.py           - Additional test files
```

### Writing Tests

```python
import pytest
from config import AppConfig

def test_my_feature():
    cfg = AppConfig()
    assert cfg.ear_threshold_default == 0.22
```

### Run Specific Tests

```bash
# Run one file
pytest test_config.py -v

# Run one test
pytest test_config.py::TestAppConfig::test_validation_valid -v

# Run with markers
pytest -m unit
pytest -m "not slow"
```

## 🎨 Code Quality

### Format Code

```bash
# Auto-format with black
black .

# Sort imports
isort .
```

### Check Quality

```bash
# Linting
flake8 .

# Type checking
mypy .
```

## 📈 Performance

### Profiling

Enable profiling in config:

```python
config = get_config()
config.enable_profiling = True
```

Or in `config.yaml`:

```yaml
enable_profiling: true
```

### Benchmarking

```python
from logger_config import timed_operation
import logging

logger = logging.getLogger(__name__)

with timed_operation(logger, "face_detection"):
    faces = detector.detect(image)
# Logs: [TIMING] face_detection: 10.52ms
```

## 🔍 Debugging

### Enable Debug Logging

```python
from logger_config import setup_logging

logger = setup_logging(level="DEBUG", use_colors=True)
```

Or via environment:

```bash
export SLEEPINESS_LOG_LEVEL=DEBUG
python webcam_sleepiness.py
```

### View Logs

```bash
# Console output (colored)
python webcam_sleepiness.py

# File output
tail -f sleepiness.log

# JSON logs for analysis
jq . sleepiness.log
```

## 🐛 Troubleshooting

### Config Validation Errors

```python
from config import AppConfig

cfg = AppConfig()
errors = cfg.validate()
if errors:
    for error in errors:
        print(f"❌ {error}")
```

### Import Errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### Test Failures

```bash
# Run with verbose output
pytest -vv

# Run with print statements
pytest -s

# Run with debugging
pytest --pdb
```

## 📚 Documentation

- `CHANGELOG.md` - Detailed changelog
- `README.md` - This file
- Module docstrings - In-code documentation
- Type hints - Function signatures

## 🤝 Contributing

### Code Style

- Use `black` for formatting
- Use `isort` for import sorting
- Follow PEP 8 guidelines
- Add type hints to all functions
- Write docstrings for public APIs
- Add tests for new features

### Pull Request Process

1. Create feature branch
2. Write code with tests
3. Run quality checks
4. Submit PR with description

## 📄 License

MIT License - See LICENSE file

## 🙏 Credits

Built with ❤️ using:
- PyTorch & torchvision
- OpenCV & MediaPipe
- ONNX Runtime
- pytest
- And many other amazing open-source libraries

---

**Version**: 18.0.0  
**Python**: 3.8+  
**Status**: Production Ready ✅
