"""
Tests for the ROS2 sensor data pipeline output and anomaly_filter implementation.

"""
import csv
import os
import math
import pytest

RESULTS_FILE = '/app/output/results.csv'
CALIBRATION_OFFSET = 1.5
CALIBRATION_SCALE = 1.02
NUM_READINGS = 10
TOLERANCE = 0.01


def expected_readings():
    """Generate expected calibrated readings matching the sensor_publisher output."""
    readings = []
    for i in range(NUM_READINGS):
        raw_temp = 20.0 + 5.0 * math.sin(i * 0.1)
        raw_humidity = 45.0 + 10.0 * math.cos(i * 0.1)
        raw_pressure = 1013.25 + 2.0 * math.sin(i * 0.05)

        cal_temp = raw_temp * CALIBRATION_SCALE + CALIBRATION_OFFSET
        cal_humidity = raw_humidity * CALIBRATION_SCALE + CALIBRATION_OFFSET
        cal_pressure = raw_pressure * CALIBRATION_SCALE + CALIBRATION_OFFSET

        is_valid = (
            -40.0 <= cal_temp <= 85.0
            and 0.0 <= cal_humidity <= 100.0
            and 300.0 <= cal_pressure <= 1100.0
        )

        readings.append({
            'sensor_id': 1,
            'temperature': cal_temp,
            'humidity': cal_humidity,
            'pressure': cal_pressure,
            'is_valid': is_valid
        })
    return readings


class TestPipelineOutput:

    def test_results_file_exists(self):
        """The pipeline must produce a results CSV file."""
        assert os.path.exists(RESULTS_FILE), \
            f"Results file {RESULTS_FILE} does not exist - pipeline did not produce output"

    def test_correct_number_of_readings(self):
        """The CSV must contain exactly NUM_READINGS data rows."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == NUM_READINGS, \
            f"Expected {NUM_READINGS} readings, got {len(rows)}"

    def test_correct_headers(self):
        """The CSV must have the expected column headers."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
        expected = ['sensor_id', 'temperature', 'humidity',
                    'pressure', 'is_valid']
        assert headers == expected, \
            f"Expected headers {expected}, got {headers}"

    def test_sensor_id_correct(self):
        """All readings must come from sensor_id 1."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        for i, row in enumerate(rows):
            assert int(row['sensor_id']) == 1, \
                f"Reading {i}: expected sensor_id 1, got {row['sensor_id']}"

    def test_calibration_applied_correctly(self):
        """Calibrated values must match: raw * scale + offset."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        expected = expected_readings()

        for i, (row, exp) in enumerate(zip(rows, expected)):
            actual_temp = float(row['temperature'])
            assert abs(actual_temp - exp['temperature']) < TOLERANCE, \
                (f"Reading {i}: temperature {actual_temp:.4f} != "
                 f"expected {exp['temperature']:.4f}")

            actual_humidity = float(row['humidity'])
            assert abs(actual_humidity - exp['humidity']) < TOLERANCE, \
                (f"Reading {i}: humidity {actual_humidity:.4f} != "
                 f"expected {exp['humidity']:.4f}")

            actual_pressure = float(row['pressure'])
            assert abs(actual_pressure - exp['pressure']) < TOLERANCE, \
                (f"Reading {i}: pressure {actual_pressure:.4f} != "
                 f"expected {exp['pressure']:.4f}")

    def test_validity_flags_correct(self):
        """Validity flags must match expected range checks."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        expected = expected_readings()

        for i, (row, exp) in enumerate(zip(rows, expected)):
            actual_valid = row['is_valid'] == 'True'
            assert actual_valid == exp['is_valid'], \
                (f"Reading {i}: is_valid={row['is_valid']} != "
                 f"expected {exp['is_valid']}")

    def test_values_are_not_uncalibrated(self):
        """Verify calibration was actually applied (not identity transform)."""
        with open(RESULTS_FILE, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        first_temp = float(rows[0]['temperature'])
        assert abs(first_temp - 20.0) > 0.5, \
            (f"First temperature {first_temp} is suspiciously close to raw value 20.0 "
             f"- calibration parameters may not be loaded correctly")


class TestAnomalyFilterImplementation:

    def test_anomaly_filter_is_lifecycle_node(self):
        """The anomaly_filter must be a proper lifecycle-managed node."""
        filter_path = '/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py'
        assert os.path.exists(filter_path), \
            f"anomaly_filter.py not found at {filter_path}"
        with open(filter_path) as f:
            content = f.read()
        assert 'LifecycleNode' in content, \
            "anomaly_filter must inherit from LifecycleNode"

    def test_anomaly_filter_has_lifecycle_callbacks(self):
        """The anomaly_filter must implement lifecycle callbacks."""
        with open('/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py') as f:
            content = f.read()
        assert 'on_configure' in content, \
            "anomaly_filter must implement on_configure callback"
        assert 'on_activate' in content, \
            "anomaly_filter must implement on_activate callback"

    def test_anomaly_filter_has_pub_sub(self):
        """The anomaly_filter must create subscription and publisher."""
        with open('/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py') as f:
            content = f.read()
        assert 'create_subscription' in content, \
            "anomaly_filter must create a subscription to receive processed data"
        assert 'create_publisher' in content, \
            "anomaly_filter must create a publisher to forward filtered data"

    def test_anomaly_filter_has_statistics(self):
        """The anomaly_filter must implement statistical outlier detection."""
        with open('/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py') as f:
            content = f.read()
        content_lower = content.lower()
        stat_indicators = [
            'mean', 'std', 'variance', 'deviation', 'z_score', 'zscore',
            'statistics', 'average', 'median', 'percentile', 'quartile',
            'sigma', 'stdev'
        ]
        has_stats = any(ind in content_lower for ind in stat_indicators)
        assert has_stats, \
            "anomaly_filter must implement statistical analysis (mean, std deviation, z-score, etc.)"

    def test_anomaly_filter_is_substantial(self):
        """The anomaly_filter must be a real implementation, not a trivial stub."""
        with open('/app/ros2_ws/src/data_pipeline/data_pipeline/anomaly_filter.py') as f:
            lines = [l for l in f.readlines()
                     if l.strip() and not l.strip().startswith('#')]
        assert len(lines) >= 40, \
            (f"anomaly_filter.py has only {len(lines)} non-empty, non-comment "
             f"lines - implementation is too trivial for a lifecycle node with "
             f"statistical filtering")

    def test_result_writer_subscribes_to_filtered(self):
        """Result writer must receive data from /sensor/filtered topic."""
        with open('/app/ros2_ws/src/data_pipeline/data_pipeline/result_writer.py') as f:
            content = f.read()
        assert '/sensor/filtered' in content, \
            "result_writer must subscribe to /sensor/filtered topic"
