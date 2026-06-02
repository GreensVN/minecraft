#!/usr/bin/env python3
"""
verify_setup.py — Environment & installation verification.

Run this after installing dependencies to confirm the project is ready:
1. Checking Python version
2. Installing dependencies
3. Validating configuration
4. Running the test suite
5. Generating a sample config.yaml
"""

import sys
import subprocess
import os
from pathlib import Path


def print_header(text: str) -> None:
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_step(step: int, total: int, text: str) -> None:
    """Print step progress."""
    print(f"\n[{step}/{total}] {text}...")


def run_command(cmd: list, description: str) -> bool:
    """Run command and return success status."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ {description}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"❌ {description} failed: Command not found")
        return False


def check_python_version() -> bool:
    """Check Python version >= 3.8."""
    version = sys.version_info
    if (version.major, version.minor) >= (3, 8):
        print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"❌ Python {version.major}.{version.minor} (need >= 3.8)")
        return False


def install_dependencies() -> bool:
    """Install runtime dependencies."""
    return run_command(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        "Installing dependencies"
    )


def run_tests() -> bool:
    """Run test suite."""
    return run_command(
        [sys.executable, "-m", "pytest", "-v"],
        "Running tests"
    )


def validate_config() -> bool:
    """Validate configuration."""
    try:
        from config import AppConfig
        cfg = AppConfig.load()
        errors = cfg.validate()
        if errors:
            print("❌ Configuration validation failed:")
            for error in errors:
                print(f"   - {error}")
            return False
        else:
            print("✅ Configuration valid")
            return True
    except Exception as e:
        print(f"❌ Configuration validation error: {e}")
        return False


def generate_sample_config() -> bool:
    """Generate sample config.yaml."""
    try:
        sample_config = """# Sleepiness Detection Configuration
# Override default values here

# Detection thresholds
ear_threshold_default: 0.22
mar_threshold_default: 0.60

# Frame counters
ear_warn_frames: 8
ear_alert_frames: 20

# Calibration
calib_duration_sec: 5.0
calib_min_samples: 30

# Camera
camera_index: 0
img_size: 224

# Performance
fps_target: 30.0
enable_metrics: true
enable_profiling: false

# Logging
log_level: INFO
log_to_file: false
log_file_path: sleepiness.log

# EWMA smoothing
ewma_alpha: 0.5
vote_ratio: 0.60

# Classroom monitoring
asi_warn_threshold: 55.0
asi_alert_threshold: 75.0
"""

        config_path = Path("config.yaml.sample")
        if not config_path.exists():
            with open(config_path, "w") as f:
                f.write(sample_config)
            print(f"✅ Sample config created: {config_path}")
        else:
            print(f"ℹ️  Sample config already exists: {config_path}")

        return True
    except Exception as e:
        print(f"❌ Sample config generation failed: {e}")
        return False


def print_summary(results: dict) -> None:
    """Print verification summary."""
    print_header("VERIFICATION SUMMARY")

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for step, success in results.items():
        status = "✅" if success else "❌"
        print(f"{status} {step}")

    print(f"\nTotal: {passed}/{total} steps completed successfully")

    if passed == total:
        print("\n🎉 Setup verified successfully!")
        print("\nNext steps:")
        print("1. Review config.yaml.sample and create your config.yaml")
        print("2. Run: python webcam_sleepiness.py")
        print("3. Check metrics: metrics.get_summary()")
        print("4. Read GETTING_STARTED.md for full documentation")
    else:
        print("\n⚠️  Verification incomplete. Please fix the errors above and re-run.")


def main():
    """Run all verification steps."""
    print_header("SLEEPINESS DETECTION — SETUP VERIFICATION")
    print("This script checks your environment, dependencies, configuration,")
    print("and test suite to confirm the project is ready to run.")

    # Confirm
    response = input("\nProceed? [y/N]: ")
    if response.lower() not in ('y', 'yes'):
        print("Cancelled.")
        return

    results = {}

    # Step 1: Check Python version
    print_step(1, 5, "Checking Python version")
    results["Python version"] = check_python_version()

    # Step 2: Install dependencies
    print_step(2, 5, "Installing dependencies")
    results["Dependencies"] = install_dependencies()

    # Step 3: Validate configuration
    print_step(3, 5, "Validating configuration")
    results["Configuration"] = validate_config()

    # Step 4: Run tests
    print_step(4, 5, "Running tests")
    results["Tests"] = run_tests()

    # Step 5: Generate sample config
    print_step(5, 5, "Generating sample configuration")
    results["Sample config"] = generate_sample_config()

    print_summary(results)


if __name__ == "__main__":
    main()
