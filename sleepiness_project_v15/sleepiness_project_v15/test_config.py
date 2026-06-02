"""
test_config.py — Unit tests for config module (v18 NEW).
"""

import pytest
import tempfile
import os
from pathlib import Path

from config import AppConfig, get_config, set_config, reload_config


class TestAppConfig:
    """Test AppConfig class."""

    def test_default_config(self):
        """Test default configuration values."""
        cfg = AppConfig()
        assert cfg.ear_threshold_default == 0.22
        assert cfg.mar_threshold_default == 0.60
        assert cfg.img_size == 224
        assert cfg.camera_index == 0

    def test_validation_valid(self):
        """Test validation with valid config."""
        cfg = AppConfig()
        errors = cfg.validate()
        assert len(errors) == 0

    def test_validation_invalid_ear_threshold(self):
        """Test validation catches invalid EAR threshold."""
        cfg = AppConfig()
        cfg.ear_threshold_default = 1.5  # Invalid: > 1.0
        errors = cfg.validate()
        assert len(errors) > 0
        assert any("ear_threshold_default" in e for e in errors)

    def test_validation_invalid_frame_counters(self):
        """Test validation catches invalid frame counters."""
        cfg = AppConfig()
        cfg.ear_alert_frames = 5
        cfg.ear_warn_frames = 10  # Invalid: alert < warn
        errors = cfg.validate()
        assert len(errors) > 0

    def test_validation_invalid_asi_thresholds(self):
        """Test validation catches invalid ASI thresholds."""
        cfg = AppConfig()
        cfg.asi_warn_threshold = 80.0
        cfg.asi_alert_threshold = 70.0  # Invalid: warn > alert
        errors = cfg.validate()
        assert len(errors) > 0

    def test_preset_strict(self):
        """Test strict preset."""
        cfg = AppConfig.preset_strict()
        assert cfg.ear_threshold_default == 0.24
        assert cfg.ear_warn_frames == 6
        assert cfg.asi_warn_threshold == 50.0

    def test_preset_relaxed(self):
        """Test relaxed preset."""
        cfg = AppConfig.preset_relaxed()
        assert cfg.ear_threshold_default == 0.20
        assert cfg.ear_warn_frames == 10
        assert cfg.asi_warn_threshold == 60.0

    def test_to_dict(self):
        """Test conversion to dictionary."""
        cfg = AppConfig()
        d = cfg.to_dict()
        assert isinstance(d, dict)
        assert "ear_threshold_default" in d
        assert d["ear_threshold_default"] == 0.22

    def test_json_export_import(self):
        """Test JSON export and import."""
        cfg = AppConfig()
        cfg.ear_threshold_default = 0.25
        cfg.camera_index = 1

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            cfg.to_json(temp_path)
            cfg_loaded = AppConfig.from_json(temp_path)
            assert cfg_loaded.ear_threshold_default == 0.25
            assert cfg_loaded.camera_index == 1
        finally:
            os.unlink(temp_path)

    def test_yaml_load_missing_file(self):
        """Test loading from non-existent YAML file."""
        cfg = AppConfig.load("nonexistent.yaml")
        assert cfg.ear_threshold_default == 0.22  # Should use defaults

    def test_yaml_load_with_data(self):
        """Test loading from YAML file with data."""
        yaml_content = """
ear_threshold_default: 0.25
camera_index: 2
img_size: 256
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            cfg = AppConfig.load(temp_path)
            assert cfg.ear_threshold_default == 0.25
            assert cfg.camera_index == 2
            assert cfg.img_size == 256
        finally:
            os.unlink(temp_path)

    def test_from_env(self):
        """Test loading from environment variables."""
        os.environ["SLEEPINESS_EAR_THRESHOLD_DEFAULT"] = "0.26"
        os.environ["SLEEPINESS_CAMERA_INDEX"] = "3"
        os.environ["SLEEPINESS_ENABLE_PROFILING"] = "true"

        try:
            cfg = AppConfig.from_env()
            assert cfg.ear_threshold_default == 0.26
            assert cfg.camera_index == 3
            assert cfg.enable_profiling is True
        finally:
            del os.environ["SLEEPINESS_EAR_THRESHOLD_DEFAULT"]
            del os.environ["SLEEPINESS_CAMERA_INDEX"]
            del os.environ["SLEEPINESS_ENABLE_PROFILING"]

    def test_global_config_singleton(self):
        """Test global config singleton pattern."""
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_set_global_config(self):
        """Test setting global config."""
        cfg = AppConfig()
        cfg.camera_index = 5
        set_config(cfg)

        cfg_retrieved = get_config()
        assert cfg_retrieved.camera_index == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
