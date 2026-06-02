"""
config.py — Centralized configuration with validation (v20).

CHANGELOG v20:
    [NEW]  Runtime/UX fields: snapshot_dir, mirror_camera, show_window,
           metrics_window, log_use_json, metrics_export_dir.
    [NEW]  Validation for the new fields + log_level membership check.
    [FIX]  preset_*() now build on top of cls() defaults so YAML/env still layer
           correctly through load_full().

CHANGELOG v18:
    [NEW]  Validation methods for all config values
    [NEW]  Environment variable override support
    [NEW]  Config export/import to JSON
    [NEW]  Preset configurations (strict, balanced, relaxed)
    [NEW]  Runtime config hot-reload support
    [FIX]  Type hints for all fields
    [FIX]  Better error messages for invalid configs

CHANGELOG v17:
    [NEW]  AppConfig dataclass with YAML override support
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Valid logging levels (used by AppConfig.validate()).
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


@dataclass
class AppConfig:
    """Application configuration with validation and presets."""

    # ─── EAR / MAR ───────────────────────────────────────────────────────
    ear_threshold_default: float = 0.22
    mar_threshold_default: float = 0.60
    ear_calib_alpha: float       = 0.65
    mar_calib_beta: float        = 1.50
    ear_baseline_min: float      = 0.20
    ear_baseline_max: float      = 0.35

    # ─── Frame counter cảnh báo ──────────────────────────────────────────
    ear_warn_frames: int  = 8
    ear_alert_frames: int = 20

    # ─── Calibration ─────────────────────────────────────────────────────
    calib_duration_sec: float = 5.0
    calib_min_samples: int    = 30

    # ─── BPM ─────────────────────────────────────────────────────────────
    bpm_window_sec: float       = 60.0
    bpm_low_thresh: float       = 8.0
    bpm_high_thresh: float      = 25.0
    bpm_blink_timeout_sec: float = 3.0

    # ─── Head pose ───────────────────────────────────────────────────────
    pose_yaw_ignore_deg: float = 30.0

    # ─── EWMA ────────────────────────────────────────────────────────────
    ewma_alpha: float = 0.5
    vote_ratio: float = 0.60

    # ─── CLAHE ───────────────────────────────────────────────────────────
    clahe_clip_limit: float          = 2.0
    clahe_tile_grid: Tuple[int, int] = (8, 8)

    # ─── Face crop ───────────────────────────────────────────────────────
    face_padding: float = 0.25

    # ─── Pipeline ────────────────────────────────────────────────────────
    cnn_skip: int               = 3
    no_face_reset_frames: int   = 30
    camera_index: int           = 0
    img_size: int               = 224

    # ─── Classroom ───────────────────────────────────────────────────────
    classroom_ear_history_len: int = 300
    classroom_mar_history_len: int = 300
    perclos_window: int            = 90
    asi_w_perclos: float           = 60.0
    asi_w_yawn: float              = 25.0
    asi_w_head_drop: float         = 15.0
    asi_momentum: float            = 0.92
    asi_warn_threshold: float      = 55.0
    asi_alert_threshold: float     = 75.0
    asi_min_session_sec: float     = 60.0
    session_expire_sec: float      = 30.0
    head_drop_pitch_deg: float     = 25.0
    mar_yawn_threshold: float      = 0.55

    # ─── [v18] Performance ───────────────────────────────────────────────
    enable_profiling: bool = False
    enable_metrics: bool   = True
    fps_target: float      = 30.0

    # ─── [v18] Logging ───────────────────────────────────────────────────
    log_level: str = "INFO"
    log_to_file: bool = False
    log_file_path: str = "sleepiness.log"
    log_use_json: bool = False          # [v20] structured JSON logs

    # ─── [v20] Runtime / UX ──────────────────────────────────────────────
    show_window: bool   = True          # False → headless (no cv2.imshow)
    mirror_camera: bool = True          # selfie-view flip for live webcam
    snapshot_dir: str   = "snapshots"
    metrics_window: int = 100           # MetricsCollector moving-average window
    metrics_export_dir: str = "metrics" # where session JSON/CSV are written

    def validate(self) -> List[str]:
        """
        Validate all configuration values.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # EAR/MAR validation
        if not (0.0 < self.ear_threshold_default < 1.0):
            errors.append(f"ear_threshold_default must be in (0, 1), got {self.ear_threshold_default}")
        if not (0.0 < self.mar_threshold_default < 2.0):
            errors.append(f"mar_threshold_default must be in (0, 2), got {self.mar_threshold_default}")
        if not (0.0 < self.ear_calib_alpha < 1.0):
            errors.append(f"ear_calib_alpha must be in (0, 1), got {self.ear_calib_alpha}")
        if not (0.0 < self.mar_calib_beta < 3.0):
            errors.append(f"mar_calib_beta must be in (0, 3), got {self.mar_calib_beta}")
        if self.ear_baseline_min >= self.ear_baseline_max:
            errors.append(f"ear_baseline_min ({self.ear_baseline_min}) must be < ear_baseline_max ({self.ear_baseline_max})")

        # Frame counters
        if self.ear_warn_frames <= 0:
            errors.append(f"ear_warn_frames must be > 0, got {self.ear_warn_frames}")
        if self.ear_alert_frames <= self.ear_warn_frames:
            errors.append(f"ear_alert_frames ({self.ear_alert_frames}) must be > ear_warn_frames ({self.ear_warn_frames})")

        # Calibration
        if self.calib_duration_sec <= 0:
            errors.append(f"calib_duration_sec must be > 0, got {self.calib_duration_sec}")
        if self.calib_min_samples <= 0:
            errors.append(f"calib_min_samples must be > 0, got {self.calib_min_samples}")

        # BPM
        if self.bpm_window_sec <= 0:
            errors.append(f"bpm_window_sec must be > 0, got {self.bpm_window_sec}")
        if self.bpm_low_thresh < 0:
            errors.append(f"bpm_low_thresh must be >= 0, got {self.bpm_low_thresh}")
        if self.bpm_high_thresh <= self.bpm_low_thresh:
            errors.append(f"bpm_high_thresh ({self.bpm_high_thresh}) must be > bpm_low_thresh ({self.bpm_low_thresh})")

        # EWMA
        if not (0.0 < self.ewma_alpha <= 1.0):
            errors.append(f"ewma_alpha must be in (0, 1], got {self.ewma_alpha}")
        if not (0.0 < self.vote_ratio <= 1.0):
            errors.append(f"vote_ratio must be in (0, 1], got {self.vote_ratio}")

        # CLAHE
        if self.clahe_clip_limit <= 0:
            errors.append(f"clahe_clip_limit must be > 0, got {self.clahe_clip_limit}")
        if len(self.clahe_tile_grid) != 2 or any(x <= 0 for x in self.clahe_tile_grid):
            errors.append(f"clahe_tile_grid must be (int>0, int>0), got {self.clahe_tile_grid}")

        # Pipeline
        if self.cnn_skip <= 0:
            errors.append(f"cnn_skip must be > 0, got {self.cnn_skip}")
        if self.img_size <= 0:
            errors.append(f"img_size must be > 0, got {self.img_size}")
        if self.camera_index < 0:
            errors.append(f"camera_index must be >= 0, got {self.camera_index}")

        # ASI
        if not (0.0 <= self.asi_momentum < 1.0):
            errors.append(f"asi_momentum must be in [0, 1), got {self.asi_momentum}")
        if self.asi_warn_threshold >= self.asi_alert_threshold:
            errors.append(f"asi_warn_threshold ({self.asi_warn_threshold}) must be < asi_alert_threshold ({self.asi_alert_threshold})")

        # FPS
        if self.fps_target <= 0:
            errors.append(f"fps_target must be > 0, got {self.fps_target}")

        # [v20] Logging
        if self.log_level.upper() not in _VALID_LOG_LEVELS:
            errors.append(
                f"log_level must be one of {sorted(_VALID_LOG_LEVELS)}, got {self.log_level!r}"
            )

        # [v20] Runtime / UX
        if self.metrics_window <= 0:
            errors.append(f"metrics_window must be > 0, got {self.metrics_window}")
        if not str(self.snapshot_dir).strip():
            errors.append("snapshot_dir must be a non-empty path")
        if not str(self.metrics_export_dir).strip():
            errors.append("metrics_export_dir must be a non-empty path")

        return errors

    @classmethod
    def load(cls, path: str = "config.yaml", validate: bool = True) -> "AppConfig":
        """
        Load config from YAML file with optional validation.

        Args:
            path: Path to YAML config file
            validate: Whether to validate after loading

        Returns:
            AppConfig instance

        Raises:
            ValueError: If validation fails
        """
        cfg = cls()
        if not os.path.exists(path):
            logger.info(f"[CONFIG] File '{path}' not found, using defaults")
            return cfg

        try:
            import yaml
        except ImportError:
            logger.warning("[CONFIG] pyyaml not installed → skipping %s", path)
            return cfg

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("[CONFIG] Error reading %s: %s → using defaults", path, e)
            return cfg

        valid_keys = {f.name for f in fields(cls)}
        applied = []

        for k, v in data.items():
            if k in valid_keys:
                if k == "clahe_tile_grid" and isinstance(v, list):
                    v = tuple(v)
                setattr(cfg, k, v)
                applied.append(k)
            else:
                logger.warning("[CONFIG] Unknown key: %s", k)

        logger.info("[CONFIG] Loaded %d fields from %s", len(applied), path)

        if validate:
            errors = cfg.validate()
            if errors:
                error_msg = "\n".join(f"  - {e}" for e in errors)
                raise ValueError(f"[CONFIG] Validation failed:\n{error_msg}")

        return cfg

    @classmethod
    def from_env(cls, prefix: str = "SLEEPINESS_") -> "AppConfig":
        """
        Load config from environment variables.

        Args:
            prefix: Prefix for environment variables (e.g., SLEEPINESS_EAR_THRESHOLD_DEFAULT)

        Returns:
            AppConfig instance with values from environment
        """
        cfg = cls()

        for f in fields(cls):
            env_key = f"{prefix}{f.name.upper()}"
            env_val = os.environ.get(env_key)

            if env_val is None:
                continue

            # NOTE: `from __future__ import annotations` makes f.type a *string*
            # (e.g. "int", "float", "bool"), not the type object. We therefore
            # infer the target type from the dataclass default rather than f.type.
            current = getattr(cfg, f.name)
            try:
                if isinstance(current, bool):
                    setattr(cfg, f.name, env_val.strip().lower() in ("true", "1", "yes", "on"))
                elif isinstance(current, int):
                    setattr(cfg, f.name, int(env_val))
                elif isinstance(current, float):
                    setattr(cfg, f.name, float(env_val))
                elif isinstance(current, str):
                    setattr(cfg, f.name, env_val)
                elif isinstance(current, tuple):
                    # e.g. clahe_tile_grid="8,8"
                    parts = tuple(int(p) for p in env_val.replace("(", "").replace(")", "").split(","))
                    setattr(cfg, f.name, parts)
                else:
                    logger.warning("[CONFIG] Cannot parse env var %s for type %s", env_key, type(current))
            except (ValueError, TypeError) as e:
                logger.warning("[CONFIG] Error parsing %s=%s: %s", env_key, env_val, e)

        return cfg

    @classmethod
    def preset_strict(cls) -> "AppConfig":
        """Strict preset: sensitive detection, low false negatives."""
        cfg = cls()
        cfg.ear_threshold_default = 0.24
        cfg.ear_warn_frames = 6
        cfg.ear_alert_frames = 15
        cfg.vote_ratio = 0.55
        cfg.asi_warn_threshold = 50.0
        cfg.asi_alert_threshold = 70.0
        return cfg

    @classmethod
    def preset_balanced(cls) -> "AppConfig":
        """Balanced preset: default settings."""
        return cls()

    @classmethod
    def preset_relaxed(cls) -> "AppConfig":
        """Relaxed preset: less sensitive, fewer false positives."""
        cfg = cls()
        cfg.ear_threshold_default = 0.20
        cfg.ear_warn_frames = 10
        cfg.ear_alert_frames = 25
        cfg.vote_ratio = 0.65
        cfg.asi_warn_threshold = 60.0
        cfg.asi_alert_threshold = 80.0
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)

    def to_json(self, path: str) -> None:
        """Export config to JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"[CONFIG] Exported to {path}")

    @classmethod
    def from_json(cls, path: str, validate: bool = False) -> "AppConfig":
        """Load config from JSON file.

        Args:
            path:     Path to JSON config file.
            validate: If True, raise ValueError when the loaded config is invalid.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cfg = cls()
        valid_keys = {fld.name for fld in fields(cls)}
        for k, v in data.items():
            if k not in valid_keys:
                logger.warning("[CONFIG] Unknown key in %s: %s", path, k)
                continue
            if k == "clahe_tile_grid" and isinstance(v, list):
                v = tuple(v)
            setattr(cfg, k, v)

        if validate:
            errors = cfg.validate()
            if errors:
                error_msg = "\n".join(f"  - {e}" for e in errors)
                raise ValueError(f"[CONFIG] Validation failed:\n{error_msg}")

        return cfg

    @classmethod
    def load_full(
        cls,
        path: str = "config.yaml",
        preset: Optional[str] = None,
        use_env: bool = True,
        validate: bool = True,
    ) -> "AppConfig":
        """[v19] Build a config by layering preset → YAML file → environment.

        Precedence (low → high): preset defaults, then any keys present in the
        YAML file, then any matching ``SLEEPINESS_*`` environment variables.

        Args:
            path:     YAML file to overlay (ignored if missing).
            preset:   One of {"strict", "balanced", "relaxed"} or None.
            use_env:  Apply ``SLEEPINESS_*`` environment overrides last.
            validate: Validate the merged result and raise on error.
        """
        presets = {
            "strict": cls.preset_strict,
            "balanced": cls.preset_balanced,
            "relaxed": cls.preset_relaxed,
        }
        if preset is not None and preset not in presets:
            raise ValueError(
                f"Unknown preset {preset!r}; choose from {sorted(presets)}"
            )
        cfg = presets[preset]() if preset else cls()

        # Overlay YAML keys (without validating the intermediate state).
        if os.path.exists(path):
            file_cfg = cls.load(path, validate=False)
            yaml_keys = cls._keys_present_in_file(path)
            for name in yaml_keys:
                setattr(cfg, name, getattr(file_cfg, name))

        # Overlay environment variables last.
        if use_env:
            env_cfg = cls.from_env()
            for fld in fields(cls):
                env_key = f"SLEEPINESS_{fld.name.upper()}"
                if env_key in os.environ:
                    setattr(cfg, fld.name, getattr(env_cfg, fld.name))

        if validate:
            errors = cfg.validate()
            if errors:
                error_msg = "\n".join(f"  - {e}" for e in errors)
                raise ValueError(f"[CONFIG] Validation failed:\n{error_msg}")
        return cfg

    @staticmethod
    def _keys_present_in_file(path: str) -> List[str]:
        """Return the set of recognised config keys explicitly set in a YAML file."""
        try:
            import yaml
        except ImportError:
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            return []
        valid = {fld.name for fld in fields(AppConfig)}
        return [k for k in data if k in valid]

    def __repr__(self) -> str:
        """Pretty print config."""
        lines = ["AppConfig("]
        for f in fields(self):
            val = getattr(self, f.name)
            lines.append(f"  {f.name}={val!r},")
        lines.append(")")
        return "\n".join(lines)


# ─── Global config instance ──────────────────────────────────────────────────

_global_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """
    Get global config instance (singleton pattern).

    Returns:
        Global AppConfig instance
    """
    global _global_config
    if _global_config is None:
        _global_config = AppConfig.load()
    return _global_config


def set_config(config: AppConfig) -> None:
    """
    Set global config instance.

    Args:
        config: AppConfig instance to set as global
    """
    global _global_config
    _global_config = config


def reload_config(path: str = "config.yaml") -> AppConfig:
    """
    Reload config from file and update global instance.

    Args:
        path: Path to config file

    Returns:
        Reloaded AppConfig instance
    """
    global _global_config
    _global_config = AppConfig.load(path)
    logger.info("[CONFIG] Reloaded from %s", path)
    return _global_config
