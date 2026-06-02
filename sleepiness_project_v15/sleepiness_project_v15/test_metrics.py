"""
test_metrics.py — Unit tests for metrics module (v18 NEW).
"""

import pytest
import time
from metrics import MetricsCollector, LatencyTracker, SessionStatistics


class TestMetricsCollector:
    """Test MetricsCollector class."""

    def test_initialization(self):
        """Test metrics collector initialization."""
        collector = MetricsCollector(window_size=50)
        assert collector.window_size == 50
        assert collector.total_frames == 0
        assert collector.total_faces == 0

    def test_record_frame(self):
        """Test recording frame metrics."""
        collector = MetricsCollector()
        collector.record_frame(
            detection_time_ms=10.5,
            inference_time_ms=15.2,
            num_faces=1,
            alert_level=0
        )

        assert collector.total_frames == 1
        assert collector.total_faces == 1
        assert collector.alert_counts[0] == 1

    def test_fps_calculation(self):
        """Test FPS calculation."""
        collector = MetricsCollector()

        # Simulate frames at ~30 FPS
        for _ in range(10):
            collector.record_frame()
            time.sleep(1/30)

        fps = collector.get_current_fps()
        assert 25 < fps < 35  # Allow some variance

    def test_alert_counting(self):
        """Test alert level counting."""
        collector = MetricsCollector()

        collector.record_frame(alert_level=0)
        collector.record_frame(alert_level=1)
        collector.record_frame(alert_level=1)
        collector.record_frame(alert_level=2)

        assert collector.alert_counts[0] == 1
        assert collector.alert_counts[1] == 2
        assert collector.alert_counts[2] == 1

    def test_timing_averages(self):
        """Test timing averages."""
        collector = MetricsCollector()

        collector.record_frame(detection_time_ms=10.0, inference_time_ms=20.0)
        collector.record_frame(detection_time_ms=12.0, inference_time_ms=18.0)
        collector.record_frame(detection_time_ms=11.0, inference_time_ms=19.0)

        avg_detection = collector.get_avg_detection_time()
        avg_inference = collector.get_avg_inference_time()

        assert abs(avg_detection - 11.0) < 0.1
        assert abs(avg_inference - 19.0) < 0.1

    def test_session_statistics(self):
        """Test session statistics generation."""
        collector = MetricsCollector()

        for i in range(5):
            collector.record_frame(
                detection_time_ms=10.0,
                inference_time_ms=15.0,
                num_faces=1,
                alert_level=i % 3
            )

        stats = collector.get_session_statistics()

        assert stats.total_frames == 5
        assert stats.total_faces_detected == 5
        assert stats.total_alerts_level1 >= 0
        assert stats.total_alerts_level2 >= 0

    def test_reset(self):
        """Test metrics reset."""
        collector = MetricsCollector()

        collector.record_frame(num_faces=1, alert_level=1)
        collector.record_frame(num_faces=2, alert_level=2)

        assert collector.total_frames == 2

        collector.reset()

        assert collector.total_frames == 0
        assert collector.total_faces == 0
        assert all(count == 0 for count in collector.alert_counts.values())

    def test_summary_generation(self):
        """Test summary string generation."""
        collector = MetricsCollector()

        for _ in range(3):
            collector.record_frame(detection_time_ms=10.0, inference_time_ms=15.0)

        summary = collector.get_summary()

        assert "SESSION METRICS SUMMARY" in summary
        assert "Total Frames" in summary
        assert "Avg FPS" in summary


class TestLatencyTracker:
    """Test LatencyTracker class."""

    def test_initialization(self):
        """Test latency tracker initialization."""
        tracker = LatencyTracker("test_op", window_size=50)
        assert tracker.name == "test_op"
        assert len(tracker.latencies) == 0

    def test_timing(self):
        """Test timing measurement."""
        tracker = LatencyTracker("test_op")

        tracker.start()
        time.sleep(0.01)  # 10ms
        latency = tracker.stop()

        assert 8 < latency < 15  # Allow some variance

    def test_average_latency(self):
        """Test average latency calculation."""
        tracker = LatencyTracker("test_op")

        tracker.start()
        time.sleep(0.01)
        tracker.stop()

        tracker.start()
        time.sleep(0.01)
        tracker.stop()

        avg = tracker.get_avg()
        assert 8 < avg < 15

    def test_percentile(self):
        """Test percentile calculation."""
        tracker = LatencyTracker("test_op")

        # Add some latencies
        for i in range(100):
            tracker.latencies.append(float(i))

        p95 = tracker.get_p95()
        assert 90 <= p95 <= 95

    def test_max_latency(self):
        """Test max latency."""
        tracker = LatencyTracker("test_op")

        tracker.latencies.extend([10.0, 20.0, 30.0, 15.0])
        max_lat = tracker.get_max()

        assert max_lat == 30.0


class TestSessionStatistics:
    """Test SessionStatistics class."""

    def test_duration_calculation(self):
        """Test session duration calculation."""
        start = time.time()
        stats = SessionStatistics(
            session_id="test",
            start_time=start,
            end_time=start + 60.0
        )

        duration = stats.duration_sec()
        assert abs(duration - 60.0) < 0.1

    def test_duration_without_end_time(self):
        """Test duration calculation without end time."""
        start = time.time()
        stats = SessionStatistics(
            session_id="test",
            start_time=start
        )

        time.sleep(0.1)
        duration = stats.duration_sec()
        assert duration >= 0.1

    def test_to_dict(self):
        """Test conversion to dictionary."""
        stats = SessionStatistics(
            session_id="test",
            start_time=time.time(),
            total_frames=100
        )

        d = stats.to_dict()
        assert isinstance(d, dict)
        assert d["session_id"] == "test"
        assert d["total_frames"] == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
