"""Tests for GRIB conformance forensics task.

Verifies that all five GRIB files have been correctly diagnosed and repaired,
data integrity is preserved, and required reports are well-formed.

"""
import json
import os

import eccodes
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CORRECTED_DIR = '/app/output/corrected'
DATA_DIR = '/app/data'

INPUT_FILES = [
    'forecast_humidity.grib',
    'forecast_surface.grib',
    'forecast_temperature.grib',
    'forecast_upper_air.grib',
    'forecast_wind.grib',
]


def read_all_meta(filepath, keys):
    """Read metadata dicts for every message in a GRIB file."""
    metas = []
    with open(filepath, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            meta = {}
            for k in keys:
                try:
                    meta[k] = eccodes.codes_get(mid, k)
                except Exception:
                    meta[k] = None
            metas.append(meta)
            eccodes.codes_release(mid)
    return metas


def read_all_values(filepath):
    """Read data-value arrays for every message in a GRIB file."""
    values = []
    with open(filepath, 'rb') as f:
        while True:
            mid = eccodes.codes_grib_new_from_file(f)
            if mid is None:
                break
            values.append(eccodes.codes_get_values(mid))
            eccodes.codes_release(mid)
    return values


# ===================================================================
# 1. Corrected files exist and are readable
# ===================================================================

class TestCorrectedFilesExist:
    @pytest.mark.parametrize("fname", INPUT_FILES)
    def test_file_exists(self, fname):
        path = os.path.join(CORRECTED_DIR, fname)
        assert os.path.exists(path), "Missing corrected file: {}".format(fname)

    @pytest.mark.parametrize("fname", INPUT_FILES)
    def test_file_readable(self, fname):
        """Each corrected file must contain at least one valid GRIB message."""
        path = os.path.join(CORRECTED_DIR, fname)
        if not os.path.exists(path):
            pytest.skip("file missing")
        metas = read_all_meta(path, ['edition'])
        assert len(metas) >= 1, "No valid GRIB messages in {}".format(fname)


# ===================================================================
# 2. Temperature — packing precision fix
# ===================================================================

class TestTemperatureFix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(CORRECTED_DIR, 'forecast_temperature.grib')
        if not os.path.exists(path):
            pytest.skip("corrected file missing")
        self.metas = read_all_meta(path, [
            'shortName', 'level', 'typeOfLevel', 'bitsPerValue'])
        self.values = read_all_values(path)

    def test_message_count(self):
        assert len(self.metas) == 3

    def test_bits_per_value_adequate(self):
        for i, m in enumerate(self.metas):
            assert m['bitsPerValue'] >= 12, \
                "Message {} bitsPerValue={}, expected >= 12".format(
                    i + 1, m['bitsPerValue'])

    def test_levels(self):
        levels = sorted(m['level'] for m in self.metas)
        assert levels == [500, 700, 850]

    def test_short_name_preserved(self):
        for m in self.metas:
            assert m['shortName'] == 't'

    def test_data_range_physical(self):
        """Temperature values must be in a physically plausible range."""
        for i, v in enumerate(self.values):
            assert np.min(v) > 200.0, \
                "Msg {} min={:.1f} — too low for temperature".format(i + 1, np.min(v))
            assert np.max(v) < 320.0, \
                "Msg {} max={:.1f} — too high for temperature".format(i + 1, np.max(v))


# ===================================================================
# 3. Upper air — parameter identity fix
# ===================================================================

class TestUpperAirFix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(CORRECTED_DIR, 'forecast_upper_air.grib')
        if not os.path.exists(path):
            pytest.skip("corrected file missing")
        self.metas = read_all_meta(path, [
            'shortName', 'paramId', 'level', 'typeOfLevel'])
        self.values = read_all_values(path)

    def test_message_count(self):
        assert len(self.metas) == 1

    def test_parameter_is_geopotential(self):
        """shortName must be 'z' (geopotential), not 't' (temperature)."""
        assert self.metas[0]['shortName'] == 'z', \
            "Expected shortName='z', got '{}'".format(self.metas[0]['shortName'])

    def test_param_id(self):
        assert self.metas[0]['paramId'] == 129, \
            "Expected paramId=129, got {}".format(self.metas[0]['paramId'])

    def test_data_range_geopotential(self):
        """Geopotential at 500 hPa should be ~54000 m^2/s^2."""
        v = self.values[0]
        assert np.min(v) > 40000.0, "Min too low for geopotential"
        assert np.max(v) < 65000.0, "Max too high for geopotential"

    def test_level_preserved(self):
        assert self.metas[0]['level'] == 500


# ===================================================================
# 4. Wind — scanning direction fix
# ===================================================================

class TestWindFix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(CORRECTED_DIR, 'forecast_wind.grib')
        if not os.path.exists(path):
            pytest.skip("corrected file missing")
        self.metas = read_all_meta(path, [
            'shortName', 'level', 'jScansPositively'])
        self.values = read_all_values(path)

    def test_message_count(self):
        assert len(self.metas) == 4

    def test_all_j_scans_positively_zero(self):
        """All messages must have jScansPositively=0 for N-to-S grid."""
        for i, m in enumerate(self.metas):
            assert m['jScansPositively'] == 0, \
                "Message {} has jScansPositively={}".format(i + 1, m['jScansPositively'])

    def test_parameters_present(self):
        short_names = {m['shortName'] for m in self.metas}
        assert 'u' in short_names
        assert 'v' in short_names

    def test_levels_present(self):
        levels = {m['level'] for m in self.metas}
        assert 500 in levels
        assert 850 in levels

    def test_data_range_wind(self):
        """Wind values must be in a reasonable range for tropospheric winds."""
        for i, v in enumerate(self.values):
            assert np.min(v) > -50.0
            assert np.max(v) < 50.0


# ===================================================================
# 5. Surface — data units fix
# ===================================================================

class TestSurfaceFix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(CORRECTED_DIR, 'forecast_surface.grib')
        if not os.path.exists(path):
            pytest.skip("corrected file missing")
        self.metas = read_all_meta(path, ['shortName', 'typeOfLevel', 'level'])
        self.values = read_all_values(path)

    def test_message_count(self):
        assert len(self.metas) == 1

    def test_short_name_preserved(self):
        assert self.metas[0]['shortName'] == 'msl'

    def test_data_in_pascals(self):
        """MSLP must be in Pascals (~101325 Pa), not hectopascals (~1013 hPa)."""
        v = self.values[0]
        assert np.min(v) > 98000.0, \
            "Min={:.1f} — values appear to still be in hPa".format(np.min(v))
        assert np.max(v) < 105000.0, \
            "Max={:.1f} — values out of expected Pa range".format(np.max(v))

    def test_data_mean_in_pascal_range(self):
        """Mean MSLP should be ~101325 Pa."""
        v = self.values[0]
        mean_val = float(np.mean(v))
        assert 99000.0 < mean_val < 103000.0, \
            "Mean={:.1f} — not in expected MSLP range (Pa)".format(mean_val)


# ===================================================================
# 6. Humidity — vertical level uniqueness fix
# ===================================================================

class TestHumidityFix:
    @pytest.fixture(autouse=True)
    def load(self):
        path = os.path.join(CORRECTED_DIR, 'forecast_humidity.grib')
        if not os.path.exists(path):
            pytest.skip("corrected file missing")
        self.metas = read_all_meta(path, ['shortName', 'level', 'typeOfLevel'])
        self.values = read_all_values(path)

    def test_message_count(self):
        assert len(self.metas) == 2

    def test_unique_levels(self):
        levels = sorted(m['level'] for m in self.metas)
        assert levels == [700, 850], \
            "Expected levels [700, 850], got {}".format(levels)

    def test_short_name_preserved(self):
        for m in self.metas:
            assert m['shortName'] == 'r'

    def test_level_data_consistency(self):
        """The message at 850 hPa should have higher mean humidity than 700 hPa."""
        means = {}
        for m, v in zip(self.metas, self.values):
            means[m['level']] = float(np.mean(v))
        assert means[850] > means[700], \
            "850 hPa mean ({:.1f}) should exceed 700 hPa mean ({:.1f})".format(
                means[850], means[700])

    def test_data_range_humidity(self):
        for i, v in enumerate(self.values):
            assert np.min(v) >= 0.0
            assert np.max(v) <= 100.0


# ===================================================================
# 7. Data preservation — independent cross-check
# ===================================================================

class TestDataPreservation:
    """Verify data integrity: metadata-only fixes must not alter data values."""

    def test_wind_data_unchanged(self):
        """Wind fix changes scanning flag only, not data values."""
        orig = read_all_values(os.path.join(DATA_DIR, 'forecast_wind.grib'))
        corr = read_all_values(os.path.join(CORRECTED_DIR, 'forecast_wind.grib'))
        assert len(orig) == len(corr)
        for i, (o, c) in enumerate(zip(orig, corr)):
            diff = float(np.max(np.abs(np.array(o) - np.array(c))))
            assert diff < 0.01, \
                "Wind msg {}: data changed (max_diff={:.6f})".format(i + 1, diff)

    def test_upper_air_data_unchanged(self):
        """Upper air fix changes parameter ID only, not data values."""
        orig = read_all_values(os.path.join(DATA_DIR, 'forecast_upper_air.grib'))
        corr = read_all_values(os.path.join(CORRECTED_DIR, 'forecast_upper_air.grib'))
        assert len(orig) == len(corr)
        for i, (o, c) in enumerate(zip(orig, corr)):
            diff = float(np.max(np.abs(np.array(o) - np.array(c))))
            assert diff < 0.01, \
                "Upper air msg {}: data changed (max_diff={:.6f})".format(i + 1, diff)

    def test_humidity_data_unchanged(self):
        """Humidity fix changes level metadata only, not data values."""
        orig = read_all_values(os.path.join(DATA_DIR, 'forecast_humidity.grib'))
        corr = read_all_values(os.path.join(CORRECTED_DIR, 'forecast_humidity.grib'))
        assert len(orig) == len(corr)
        for i, (o, c) in enumerate(zip(orig, corr)):
            diff = float(np.max(np.abs(np.array(o) - np.array(c))))
            assert diff < 0.01, \
                "Humidity msg {}: data changed (max_diff={:.6f})".format(i + 1, diff)

    def test_temperature_data_close(self):
        """Repacking from 4-bit to higher precision should not significantly alter values."""
        orig = read_all_values(os.path.join(DATA_DIR, 'forecast_temperature.grib'))
        corr = read_all_values(os.path.join(CORRECTED_DIR, 'forecast_temperature.grib'))
        assert len(orig) == len(corr)
        for i, (o, c) in enumerate(zip(orig, corr)):
            diff = float(np.max(np.abs(np.array(o) - np.array(c))))
            assert diff < 1.0, \
                "Temperature msg {}: repacking diff too large ({:.4f})".format(i + 1, diff)

    def test_surface_data_converted(self):
        """Surface data should be scaled by ~100 (hPa to Pa conversion)."""
        orig = read_all_values(os.path.join(DATA_DIR, 'forecast_surface.grib'))
        corr = read_all_values(os.path.join(CORRECTED_DIR, 'forecast_surface.grib'))
        assert len(orig) == len(corr)
        orig_mean = float(np.mean(orig[0]))
        corr_mean = float(np.mean(corr[0]))
        ratio = corr_mean / orig_mean
        assert 99.0 < ratio < 101.0, \
            "Expected ~100x scaling, got {:.1f}x (orig_mean={:.1f}, corr_mean={:.1f})".format(
                ratio, orig_mean, corr_mean)


# ===================================================================
# 8. Audit report structure
# ===================================================================

class TestAuditReport:
    @pytest.fixture(autouse=True)
    def load(self):
        path = '/app/output/audit.json'
        assert os.path.exists(path), "audit.json not found"
        with open(path) as f:
            self.audit = json.load(f)

    def test_is_list(self):
        assert isinstance(self.audit, list)

    def test_entry_count(self):
        assert len(self.audit) == 5

    def test_required_keys(self):
        for entry in self.audit:
            assert 'filename' in entry, "Missing 'filename' key"
            assert 'root_cause' in entry, "Missing 'root_cause' key"
            assert 'correction' in entry, "Missing 'correction' key"

    def test_all_filenames_present(self):
        reported = {e['filename'] for e in self.audit}
        for fname in INPUT_FILES:
            assert fname in reported, "Missing audit entry for {}".format(fname)

    def test_non_empty_diagnosis(self):
        for entry in self.audit:
            assert len(entry['root_cause']) > 5, \
                "root_cause too short for {}".format(entry['filename'])
            assert len(entry['correction']) > 5, \
                "correction too short for {}".format(entry['filename'])


# ===================================================================
# 9. Integrity report structure
# ===================================================================

class TestIntegrityReport:
    @pytest.fixture(autouse=True)
    def load(self):
        path = '/app/output/integrity.json'
        assert os.path.exists(path), "integrity.json not found"
        with open(path) as f:
            self.integrity = json.load(f)

    def test_is_dict(self):
        assert isinstance(self.integrity, dict)

    def test_all_filenames_present(self):
        for fname in INPUT_FILES:
            assert fname in self.integrity, \
                "Missing integrity entry for {}".format(fname)

    def test_required_keys(self):
        for fname, entry in self.integrity.items():
            assert 'message_count' in entry, \
                "{}: missing 'message_count'".format(fname)
            assert 'max_abs_diff' in entry, \
                "{}: missing 'max_abs_diff'".format(fname)

    def test_message_counts(self):
        expected = {
            'forecast_temperature.grib': 3,
            'forecast_upper_air.grib': 1,
            'forecast_wind.grib': 4,
            'forecast_surface.grib': 1,
            'forecast_humidity.grib': 2,
        }
        for fname, exp_count in expected.items():
            if fname in self.integrity:
                assert self.integrity[fname]['message_count'] == exp_count, \
                    "{}: expected {} messages, reported {}".format(
                        fname, exp_count, self.integrity[fname]['message_count'])

    def test_max_abs_diff_types(self):
        for fname, entry in self.integrity.items():
            assert isinstance(entry['max_abs_diff'], (int, float)), \
                "{}: max_abs_diff must be numeric".format(fname)
            assert entry['max_abs_diff'] >= 0.0, \
                "{}: max_abs_diff must be non-negative".format(fname)
