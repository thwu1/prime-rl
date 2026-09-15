
"""
Verification tests for I2C bus capture analyzer output.
Tests independently compute expected values using known capture constants
and the Bosch BME280 reference compensation algorithms.
"""

import json
import os
import pytest


# ============================================================
# Known constants from the capture (deterministic generation)
# ============================================================

# BME280 calibration values embedded in the capture
CAL = {
    'dig_T1': 27504, 'dig_T2': 26435, 'dig_T3': -1000,
    'dig_P1': 36477, 'dig_P2': -10685, 'dig_P3': 3024,
    'dig_P4': 2855, 'dig_P5': 140, 'dig_P6': -7,
    'dig_P7': 15500, 'dig_P8': -14600, 'dig_P9': 6000,
    'dig_H1': 75, 'dig_H2': 370, 'dig_H3': 0,
    'dig_H4': 313, 'dig_H5': 50, 'dig_H6': 30,
}

# Raw ADC values from the capture
ADC_T = 520192   # (0x7F << 12) | (0x00 << 4) | (0x00 >> 4)
ADC_P = 415744   # (0x65 << 12) | (0x80 << 4) | (0x00 >> 4)
ADC_H = 28000    # (0x6D << 8) | 0x60

# MPU6050 raw sensor data from the capture
MPU_RAW = {
    'accel_x': 819, 'accel_y': -328, 'accel_z': 16548,
    'gyro_x': 197, 'gyro_y': -105, 'gyro_z': 39,
}

# MPU6050 sensitivity for AFS_SEL=0 (+-2g) and FS_SEL=0 (+-250dps)
ACCEL_SENSITIVITY = 16384.0  # LSB/g
GYRO_SENSITIVITY = 131.0     # LSB/(deg/s)


# ============================================================
# Reference BME280 Bosch compensation algorithms
# ============================================================

def _ref_bme280_temperature(adc_T):
    var1 = (adc_T / 16384.0 - CAL['dig_T1'] / 1024.0) * CAL['dig_T2']
    var2 = ((adc_T / 131072.0 - CAL['dig_T1'] / 8192.0) ** 2) * CAL['dig_T3']
    t_fine = var1 + var2
    return t_fine / 5120.0, t_fine


def _ref_bme280_pressure(adc_P, t_fine):
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * CAL['dig_P6'] / 32768.0
    var2 = var2 + var1 * CAL['dig_P5'] * 2.0
    var2 = var2 / 4.0 + CAL['dig_P4'] * 65536.0
    var1 = (CAL['dig_P3'] * var1 * var1 / 524288.0 + CAL['dig_P2'] * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * CAL['dig_P1']
    if var1 == 0:
        return 0
    pressure = 1048576.0 - adc_P
    pressure = ((pressure - var2 / 4096.0) * 6250.0) / var1
    var1 = CAL['dig_P9'] * pressure * pressure / 2147483648.0
    var2 = pressure * CAL['dig_P8'] / 32768.0
    pressure = pressure + (var1 + var2 + CAL['dig_P7']) / 16.0
    return pressure / 100.0


def _ref_bme280_humidity(adc_H, t_fine):
    h = t_fine - 76800.0
    if h == 0:
        return 0
    h = (adc_H - (CAL['dig_H4'] * 64.0 + (CAL['dig_H5'] / 16384.0) * h)) * \
        (CAL['dig_H2'] / 65536.0 * (1.0 + CAL['dig_H6'] / 67108864.0 * h *
        (1.0 + CAL['dig_H3'] / 67108864.0 * h)))
    h = h * (1.0 - CAL['dig_H1'] * h / 524288.0)
    return max(0.0, min(100.0, h))


# Pre-compute reference values
REF_TEMP, REF_TFINE = _ref_bme280_temperature(ADC_T)
REF_PRESS = _ref_bme280_pressure(ADC_P, REF_TFINE)
REF_HUMID = _ref_bme280_humidity(ADC_H, REF_TFINE)


# ============================================================
# Helpers
# ============================================================

def load_output():
    path = '/app/output.json'
    assert os.path.exists(path), f"output.json not found at {path}"
    with open(path) as f:
        return json.load(f)


def parse_hex_addr(s):
    """Parse address to integer, accepting '0x76', '0X76', '76', or int."""
    if isinstance(s, int):
        return s
    s = str(s).strip().lower()
    if s.startswith('0x'):
        return int(s, 16)
    try:
        return int(s, 16)
    except ValueError:
        return int(s)


# ============================================================
# Tests: Output Structure
# ============================================================

class TestOutputStructure:
    def test_output_exists(self):
        assert os.path.exists('/app/output.json'), "output.json not found"

    def test_valid_json(self):
        data = load_output()
        assert isinstance(data, dict)

    def test_required_top_level_keys(self):
        data = load_output()
        for key in ['devices_found', 'failed_addresses', 'bme280',
                     'mpu6050', 'anomalies', 'summary']:
            assert key in data, f"Missing top-level key: {key}"


# ============================================================
# Tests: Device Discovery
# ============================================================

class TestDeviceDiscovery:
    def test_bme280_found(self):
        data = load_output()
        addrs = {parse_hex_addr(d['address']) for d in data['devices_found']}
        assert 0x76 in addrs, "BME280 (0x76) not in devices_found"

    def test_mpu6050_found(self):
        data = load_output()
        addrs = {parse_hex_addr(d['address']) for d in data['devices_found']}
        assert 0x69 in addrs, "MPU6050 (0x69) not in devices_found"

    def test_exactly_two_responding(self):
        data = load_output()
        assert len(data['devices_found']) == 2

    def test_failed_address_0x50(self):
        data = load_output()
        failed = {parse_hex_addr(a) for a in data['failed_addresses']}
        assert 0x50 in failed, "0x50 not in failed_addresses"


# ============================================================
# Tests: BME280 Calibration Extraction
# ============================================================

class TestBME280Calibration:
    def test_temperature_coefficients(self):
        cal = load_output()['bme280']['calibration']
        assert cal['dig_T1'] == CAL['dig_T1'], f"dig_T1: got {cal['dig_T1']}"
        assert cal['dig_T2'] == CAL['dig_T2'], f"dig_T2: got {cal['dig_T2']}"
        assert cal['dig_T3'] == CAL['dig_T3'], f"dig_T3: got {cal['dig_T3']}"

    def test_pressure_coefficients(self):
        cal = load_output()['bme280']['calibration']
        for key in ['dig_P1', 'dig_P2', 'dig_P3', 'dig_P4', 'dig_P5',
                     'dig_P6', 'dig_P7', 'dig_P8', 'dig_P9']:
            assert cal[key] == CAL[key], \
                f"{key}: expected {CAL[key]}, got {cal[key]}"

    def test_humidity_h1_h2_h3(self):
        cal = load_output()['bme280']['calibration']
        assert cal['dig_H1'] == CAL['dig_H1'], f"dig_H1: got {cal['dig_H1']}"
        assert cal['dig_H2'] == CAL['dig_H2'], f"dig_H2: got {cal['dig_H2']}"
        assert cal['dig_H3'] == CAL['dig_H3'], f"dig_H3: got {cal['dig_H3']}"

    def test_humidity_h4_composite(self):
        """dig_H4 is a 12-bit composite from regs 0xE4 and 0xE5[3:0]."""
        cal = load_output()['bme280']['calibration']
        assert cal['dig_H4'] == CAL['dig_H4'], \
            f"dig_H4: expected {CAL['dig_H4']}, got {cal['dig_H4']}"

    def test_humidity_h5_composite(self):
        """dig_H5 is a 12-bit composite from regs 0xE5[7:4] and 0xE6."""
        cal = load_output()['bme280']['calibration']
        assert cal['dig_H5'] == CAL['dig_H5'], \
            f"dig_H5: expected {CAL['dig_H5']}, got {cal['dig_H5']}"

    def test_humidity_h6(self):
        cal = load_output()['bme280']['calibration']
        assert cal['dig_H6'] == CAL['dig_H6'], f"dig_H6: got {cal['dig_H6']}"


# ============================================================
# Tests: BME280 Measurements
# ============================================================

class TestBME280Measurements:
    def test_chip_id(self):
        chip_id = parse_hex_addr(load_output()['bme280']['chip_id'])
        assert chip_id == 0x60, f"chip_id: expected 0x60, got 0x{chip_id:02x}"

    def test_raw_adc_temperature(self):
        raw = load_output()['bme280']['raw_adc']
        assert raw['temperature'] == ADC_T, \
            f"raw temperature: expected {ADC_T}, got {raw['temperature']}"

    def test_raw_adc_pressure(self):
        raw = load_output()['bme280']['raw_adc']
        assert raw['pressure'] == ADC_P, \
            f"raw pressure: expected {ADC_P}, got {raw['pressure']}"

    def test_raw_adc_humidity(self):
        raw = load_output()['bme280']['raw_adc']
        assert raw['humidity'] == ADC_H, \
            f"raw humidity: expected {ADC_H}, got {raw['humidity']}"

    def test_compensated_temperature(self):
        comp = load_output()['bme280']['compensated']
        assert abs(comp['temperature_c'] - REF_TEMP) < 0.05, \
            f"temperature: expected {REF_TEMP:.4f}, got {comp['temperature_c']}"

    def test_compensated_pressure(self):
        comp = load_output()['bme280']['compensated']
        assert abs(comp['pressure_hpa'] - REF_PRESS) < 0.1, \
            f"pressure: expected {REF_PRESS:.4f}, got {comp['pressure_hpa']}"

    def test_compensated_humidity(self):
        comp = load_output()['bme280']['compensated']
        assert abs(comp['humidity_pct'] - REF_HUMID) < 0.5, \
            f"humidity: expected {REF_HUMID:.4f}, got {comp['humidity_pct']}"


# ============================================================
# Tests: MPU6050
# ============================================================

class TestMPU6050:
    def test_who_am_i(self):
        who = parse_hex_addr(load_output()['mpu6050']['who_am_i'])
        assert who == 0x68, f"WHO_AM_I: expected 0x68, got 0x{who:02x}"

    def test_accel_range_config(self):
        r = load_output()['mpu6050']['config']['accel_range'].lower().replace(' ', '')
        assert '2g' in r, f"accel_range should indicate +-2g, got: {r}"

    def test_gyro_range_config(self):
        r = load_output()['mpu6050']['config']['gyro_range'].lower().replace(' ', '')
        assert '250' in r, f"gyro_range should indicate +-250dps, got: {r}"

    def test_raw_accel_values(self):
        raw = load_output()['mpu6050']['raw']
        assert raw['accel_x'] == MPU_RAW['accel_x'], f"accel_x: {raw['accel_x']}"
        assert raw['accel_y'] == MPU_RAW['accel_y'], f"accel_y: {raw['accel_y']}"
        assert raw['accel_z'] == MPU_RAW['accel_z'], f"accel_z: {raw['accel_z']}"

    def test_raw_gyro_values(self):
        raw = load_output()['mpu6050']['raw']
        assert raw['gyro_x'] == MPU_RAW['gyro_x'], f"gyro_x: {raw['gyro_x']}"
        assert raw['gyro_y'] == MPU_RAW['gyro_y'], f"gyro_y: {raw['gyro_y']}"
        assert raw['gyro_z'] == MPU_RAW['gyro_z'], f"gyro_z: {raw['gyro_z']}"

    def test_calibrated_accel(self):
        accel = load_output()['mpu6050']['calibrated']['accel_g']
        assert abs(accel['x'] - MPU_RAW['accel_x'] / ACCEL_SENSITIVITY) < 0.001
        assert abs(accel['y'] - MPU_RAW['accel_y'] / ACCEL_SENSITIVITY) < 0.001
        assert abs(accel['z'] - MPU_RAW['accel_z'] / ACCEL_SENSITIVITY) < 0.001

    def test_calibrated_gyro(self):
        gyro = load_output()['mpu6050']['calibrated']['gyro_dps']
        assert abs(gyro['x'] - MPU_RAW['gyro_x'] / GYRO_SENSITIVITY) < 0.01
        assert abs(gyro['y'] - MPU_RAW['gyro_y'] / GYRO_SENSITIVITY) < 0.01
        assert abs(gyro['z'] - MPU_RAW['gyro_z'] / GYRO_SENSITIVITY) < 0.01


# ============================================================
# Tests: Anomaly Detection
# ============================================================

class TestAnomalies:
    def test_exactly_two_anomalies(self):
        data = load_output()
        assert len(data['anomalies']) == 2, \
            f"Expected 2 anomalies, got {len(data['anomalies'])}"

    def test_address_nack_for_0x50(self):
        """Device 0x50 sent address NACK (not present on bus)."""
        data = load_output()
        addr_nacks = [
            a for a in data['anomalies']
            if 'nack' in a.get('type', '').lower()
            and parse_hex_addr(a.get('address', '0')) == 0x50
        ]
        assert len(addr_nacks) >= 1, \
            "Missing address NACK anomaly for device 0x50"

    def test_data_nack_for_mpu6050(self):
        """MPU6050 NACKed a write to read-only register 0x75."""
        data = load_output()
        data_nacks = [
            a for a in data['anomalies']
            if 'nack' in a.get('type', '').lower()
            and parse_hex_addr(a.get('address', '0')) == 0x69
        ]
        assert len(data_nacks) >= 1, \
            "Missing data NACK anomaly for MPU6050 (0x69)"


# ============================================================
# Tests: Summary Counts
# ============================================================

class TestSummary:
    def test_total_transactions(self):
        s = load_output()['summary']
        assert s['total_transactions'] == 13, \
            f"total_transactions: expected 13, got {s['total_transactions']}"

    def test_successful_transactions(self):
        s = load_output()['summary']
        assert s['successful_transactions'] == 11, \
            f"successful: expected 11, got {s['successful_transactions']}"

    def test_failed_transactions(self):
        s = load_output()['summary']
        assert s['failed_transactions'] == 2, \
            f"failed: expected 2, got {s['failed_transactions']}"

    def test_total_anomalies_consistent(self):
        data = load_output()
        assert data['summary']['total_anomalies'] == len(data['anomalies'])

    def test_devices_responding(self):
        s = load_output()['summary']
        assert s['devices_responding'] == 2, \
            f"devices_responding: expected 2, got {s['devices_responding']}"
