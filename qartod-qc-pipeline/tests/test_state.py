"""Tests for QARTOD QC pipeline output verification."""
import json
import os

import pytest


OUTPUT_PATH = "/app/output/flags.json"
DATA_LENGTH = 20


@pytest.fixture(scope="module")
def flags():
    assert os.path.exists(OUTPUT_PATH), f"Output not found at {OUTPUT_PATH}"
    with open(OUTPUT_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict), "Output must be a JSON object"
    return data


class TestOutputStructure:
    def test_streams_present(self, flags):
        for s in ["water_temperature", "salinity", "density"]:
            assert s in flags, f"Missing stream: {s}"

    def test_water_temp_keys(self, flags):
        keys = set(flags["water_temperature"].keys())
        expected = {
            "gross_range_test",
            "spike_test",
            "rate_of_change_test",
            "flat_line_test",
            "climatology_test",
            "aggregate",
        }
        assert keys == expected, f"water_temperature keys: {keys}"

    def test_salinity_keys(self, flags):
        keys = set(flags["salinity"].keys())
        expected = {
            "gross_range_test",
            "spike_test",
            "attenuated_signal_test",
            "aggregate",
        }
        assert keys == expected, f"salinity keys: {keys}"

    def test_density_keys(self, flags):
        keys = set(flags["density"].keys())
        expected = {
            "gross_range_test",
            "density_inversion_test",
            "aggregate",
        }
        assert keys == expected, f"density keys: {keys}"

    def test_array_lengths(self, flags):
        for stream in flags:
            for test_name, arr in flags[stream].items():
                assert len(arr) == DATA_LENGTH, (
                    f"{stream}.{test_name} length {len(arr)}, expected {DATA_LENGTH}"
                )

    def test_valid_flag_values(self, flags):
        valid = {1, 2, 3, 4, 9}
        for stream in flags:
            for test_name, arr in flags[stream].items():
                for i, v in enumerate(arr):
                    assert v in valid, (
                        f"{stream}.{test_name}[{i}]={v} not a valid QARTOD flag"
                    )


class TestWaterTemperature:
    def test_gross_range(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 1, 9, 1, 3, 1, 4, 1, 1]
        assert flags["water_temperature"]["gross_range_test"] == expected

    def test_spike(self, flags):
        expected = [2, 1, 1, 1, 1, 1, 1, 1, 4, 4, 1, 4, 2, 9, 2, 4, 4, 4, 4, 2]
        assert flags["water_temperature"]["spike_test"] == expected

    def test_rate_of_change(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 3, 3, 3, 9, 1, 3, 3, 3, 3, 1]
        assert flags["water_temperature"]["rate_of_change_test"] == expected

    def test_flat_line(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 3, 3, 1, 1, 1, 1, 9, 1, 1, 1, 1, 1, 1]
        assert flags["water_temperature"]["flat_line_test"] == expected

    def test_climatology(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 1, 9, 1, 3, 1, 3, 1, 1]
        assert flags["water_temperature"]["climatology_test"] == expected

    def test_aggregate(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 3, 4, 4, 3, 4, 3, 9, 1, 4, 4, 4, 4, 1]
        assert flags["water_temperature"]["aggregate"] == expected


class TestSalinity:
    def test_gross_range(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 1, 3, 1, 4, 1, 1]
        assert flags["salinity"]["gross_range_test"] == expected

    def test_spike(self, flags):
        expected = [2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 9, 2, 4, 1, 4, 1, 2]
        assert flags["salinity"]["spike_test"] == expected

    def test_attenuated_signal(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 1, 1, 1, 1, 1, 1]
        assert flags["salinity"]["attenuated_signal_test"] == expected

    def test_aggregate(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 1, 4, 1, 4, 1, 1]
        assert flags["salinity"]["aggregate"] == expected


class TestDensity:
    def test_gross_range(self, flags):
        expected = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 9, 1, 1, 1, 1, 1, 1]
        assert flags["density"]["gross_range_test"] == expected

    def test_density_inversion(self, flags):
        expected = [1, 4, 4, 1, 1, 1, 4, 4, 1, 1, 1, 1, 9, 9, 9, 4, 4, 1, 1, 1]
        assert flags["density"]["density_inversion_test"] == expected

    def test_aggregate(self, flags):
        expected = [1, 4, 4, 1, 1, 1, 4, 4, 1, 1, 1, 1, 9, 9, 1, 4, 4, 1, 1, 1]
        assert flags["density"]["aggregate"] == expected


class TestEdgeCases:
    """Verify specific edge case behaviors."""

    def test_missing_data_flagged(self, flags):
        """NaN values at index 13 must be MISSING in all per-test arrays."""
        for stream in ["water_temperature", "salinity"]:
            for test_name, arr in flags[stream].items():
                if test_name == "aggregate":
                    continue
                assert arr[13] == 9, (
                    f"{stream}.{test_name}[13] should be MISSING(9), got {arr[13]}"
                )

    def test_spike_first_last_unknown(self, flags):
        """First and last values in spike test must be UNKNOWN."""
        for stream in ["water_temperature", "salinity"]:
            arr = flags[stream]["spike_test"]
            assert arr[0] == 2, f"{stream} spike[0] should be UNKNOWN(2)"
            assert arr[-1] == 2, f"{stream} spike[-1] should be UNKNOWN(2)"

    def test_aggregate_good_over_missing(self, flags):
        """At idx 14 density: gross_range=GOOD(1) but inversion=MISSING(9).
        Aggregate must be GOOD because GOOD has higher priority than MISSING."""
        assert flags["density"]["aggregate"][14] == 1

    def test_density_missing_forward_propagation(self, flags):
        """density_inversion: missing density at idx 12-13 must propagate
        MISSING flag to idx 14 (following point rule)."""
        inv = flags["density"]["density_inversion_test"]
        assert inv[12] == 9
        assert inv[13] == 9
        assert inv[14] == 9

    def test_spike_nan_neighbor_makes_unknown(self, flags):
        """When spike ref is undefined due to adjacent NaN, flag UNKNOWN(2)."""
        sp = flags["water_temperature"]["spike_test"]
        assert sp[12] == 2, "Spike at idx 12 should be UNKNOWN (ref involves NaN at idx 13)"
        assert sp[14] == 2, "Spike at idx 14 should be UNKNOWN (ref involves NaN at idx 13)"

    def test_flat_line_pre_window_passes(self, flags):
        """Points before end of first suspect window must not be flagged."""
        fl = flags["water_temperature"]["flat_line_test"]
        for i in range(7):
            assert fl[i] in (1, 9), (
                f"flat_line[{i}] should be GOOD or MISSING before window end"
            )

    def test_climatology_boundary_value(self, flags):
        """Water temp 25.0 at idx 9 is on vspan boundary [5,25] and should be GOOD."""
        assert flags["water_temperature"]["climatology_test"][9] == 1

    def test_density_inversion_direction(self, flags):
        """Density decrease with increasing depth (idx 6-7: 1024.7->1024.6)
        should trigger FAIL for both adjacent points."""
        inv = flags["density"]["density_inversion_test"]
        assert inv[6] == 4
        assert inv[7] == 4

    def test_differential_spike_direction_check(self, flags):
        """Differential spike at idx 16: slopes don't oppose (both positive
        from recovery), so spike stat is zeroed and flag is GOOD."""
        assert flags["salinity"]["spike_test"][16] == 1
