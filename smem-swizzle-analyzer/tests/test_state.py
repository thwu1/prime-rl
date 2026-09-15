
import csv
import glob
import json
import os
import sys

import pytest

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Tests for C library build & ctypes integration
# ---------------------------------------------------------------------------

class TestCLibraryIntegration:
    """Verify the C library is built as a shared library and loadable via ctypes."""

    def test_shared_library_file_exists(self):
        """At least one .so file for libsmembank must exist."""
        so_files = (
            glob.glob("/app/lib/libsmembank.so*") +
            glob.glob("/app/build/libsmembank.so*")
        )
        assert len(so_files) > 0, (
            "No libsmembank.so found. The C library must be compiled as SHARED."
        )

    def test_ctypes_binding_callable(self):
        """banking.count_bank_conflicts must work through ctypes FFI."""
        from smem_optimizer.banking import count_bank_conflicts
        result = count_bank_conflicts([0, 4, 8, 12])
        assert result == 1, f"Expected 1 (no conflict), got {result}"

    def test_c_compute_bank_id(self):
        """C compute_bank_id must map byte addresses to correct bank indices."""
        from smem_optimizer.banking import compute_bank_id
        assert compute_bank_id(0) == 0
        assert compute_bank_id(4) == 1
        assert compute_bank_id(124) == 31
        assert compute_bank_id(128) == 0   # wraps: (128/4)%32 = 0


# ---------------------------------------------------------------------------
# Tests for banking.py -- count_bank_conflicts (via C library)
# ---------------------------------------------------------------------------

class TestBankConflicts:
    def test_all_same_bank(self):
        """32 threads all access bank 0 -> 32-way conflict."""
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [0] * 32
        assert count_bank_conflicts(addrs) == 32

    def test_all_different_banks(self):
        """Each thread hits a unique bank -> conflict-free (1)."""
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [i * 4 for i in range(32)]
        assert count_bank_conflicts(addrs) == 1

    def test_16_way(self):
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [0, 4] * 16
        assert count_bank_conflicts(addrs) == 16

    def test_8_way(self):
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [(i % 4) * 4 for i in range(32)]
        assert count_bank_conflicts(addrs) == 8

    def test_4_way(self):
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [(i % 8) * 4 for i in range(32)]
        assert count_bank_conflicts(addrs) == 4

    def test_2_way(self):
        from smem_optimizer.banking import count_bank_conflicts
        addrs = [(i % 16) * 4 for i in range(32)]
        assert count_bank_conflicts(addrs) == 2

    def test_empty(self):
        from smem_optimizer.banking import count_bank_conflicts
        assert count_bank_conflicts([]) == 0


# ---------------------------------------------------------------------------
# Tests for swizzle.py -- apply_swizzle with various sizeof_TC
# ---------------------------------------------------------------------------

class TestSwizzle:
    """Test XOR swizzle with different chunk granularities."""

    # --- sizeof_TC == sizeof_T == 4 (float32, scalar) ---
    def test_identity_row_zero(self):
        from smem_optimizer.swizzle import apply_swizzle
        for x in range(32):
            assert apply_swizzle(0, x, 32, 4, 4) == x

    def test_xor_basic_tc4(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(3, 5, 32, 4, 4) == 6  # 3^5=6

    def test_xor_small_NX_tc4(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(5, 3, 8, 4, 4) == 6  # (5^3)%8=6

    def test_xor_wrap_tc4(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(31, 31, 32, 4, 4) == 0  # 31^31=0

    # --- sizeof_TC == 16, sizeof_T == 4 (float32, vec4) ---
    def test_tc16_fp32_basic(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(1, 0, 32, 4, 16) == 4

    def test_tc16_fp32_nonzero_col(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(3, 4, 32, 4, 16) == 8

    def test_tc16_fp32_with_remainder(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(7, 5, 32, 4, 16) == 25

    # --- sizeof_TC == 16, sizeof_T == 2 (float16, vec8) ---
    def test_tc16_fp16(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(1, 0, 128, 2, 16) == 8

    # --- sizeof_TC == 8, sizeof_T == 8 (float64, scalar) ---
    def test_tc8_fp64(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(3, 5, 16, 8, 8) == 6

    def test_tc8_fp64_wrap(self):
        from smem_optimizer.swizzle import apply_swizzle
        assert apply_swizzle(7, 10, 16, 8, 8) == 13

    # --- Range checks ---
    def test_range_within_NX(self):
        from smem_optimizer.swizzle import apply_swizzle
        for NX, sT, sTC in [(32, 4, 4), (32, 4, 16), (128, 2, 16), (16, 8, 8)]:
            for y in range(64):
                for x in range(NX):
                    xs = apply_swizzle(y, x, NX, sT, sTC)
                    assert 0 <= xs < NX, f"NX={NX},sT={sT},sTC={sTC},y={y},x={x}: got {xs}"

    # --- Bijectivity ---
    def test_bijective_fp32_tc4(self):
        from smem_optimizer.swizzle import verify_bijective
        assert verify_bijective(32, 32, 4, 4) is True

    def test_bijective_fp32_tc16(self):
        from smem_optimizer.swizzle import verify_bijective
        assert verify_bijective(32, 32, 4, 16) is True

    def test_bijective_fp16_tc16(self):
        from smem_optimizer.swizzle import verify_bijective
        assert verify_bijective(128, 16, 2, 16) is True

    def test_bijective_fp64_tc8(self):
        from smem_optimizer.swizzle import verify_bijective
        assert verify_bijective(16, 32, 8, 8) is True

    def test_bijective_small_nx(self):
        from smem_optimizer.swizzle import verify_bijective
        assert verify_bijective(8, 32, 4, 4) is True


# ---------------------------------------------------------------------------
# Tests for padding.py -- find_optimal_padding
# ---------------------------------------------------------------------------

class TestPadding:
    def test_square_fp32_scalar(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(32, 32, 4, 1, "column")
        assert pad == 1
        assert conflict == 1
        assert overhead == 128

    def test_tiny_fp32_scalar(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(8, 32, 4, 1, "column")
        assert pad == 1
        assert conflict == 1
        assert overhead == 128

    def test_wide_fp32_vec4(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(128, 16, 4, 4, "column")
        assert pad == 4
        assert conflict == 4
        assert overhead == 256

    def test_narrow_fp32_scalar(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(16, 32, 4, 1, "column")
        assert pad == 1
        assert conflict == 1
        assert overhead == 128

    def test_row_access_no_change(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(32, 32, 4, 1, "row")
        assert pad == 0
        assert conflict == 1
        assert overhead == 0

    def test_wide_fp16_vec8(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(128, 16, 2, 8, "column")
        assert pad == 8
        assert conflict == 4
        assert overhead == 256

    def test_narrow_fp64_scalar(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(16, 32, 8, 1, "column")
        assert pad == 1
        assert conflict == 2
        assert overhead == 256

    def test_small_fp32_vec4(self):
        from smem_optimizer.padding import find_optimal_padding
        pad, conflict, overhead = find_optimal_padding(32, 16, 4, 4, "column")
        assert pad == 4
        assert conflict == 4
        assert overhead == 256


# ---------------------------------------------------------------------------
# Tests for optimal_layouts.json
# ---------------------------------------------------------------------------

class TestOutputJSON:
    EXPECTED = {
        "square_fp32_scalar": {
            "baseline_conflicts": 32,
            "swizzle_conflicts": 1,
            "swizzle_sizeof_tc": 4,
            "padding_conflicts": 1,
            "padding_amount": 1,
            "padding_overhead_bytes": 128,
            "optimal_strategy": "swizzle",
            "optimal_conflicts": 1,
        },
        "tiny_fp32_scalar": {
            "baseline_conflicts": 8,
            "swizzle_conflicts": 4,
            "swizzle_sizeof_tc": 4,
            "padding_conflicts": 1,
            "padding_amount": 1,
            "padding_overhead_bytes": 128,
            "optimal_strategy": "padding",
            "optimal_conflicts": 1,
        },
        "wide_fp32_vec4": {
            "baseline_conflicts": 32,
            "swizzle_conflicts": 4,
            "swizzle_sizeof_tc": 16,
            "padding_conflicts": 4,
            "padding_amount": 4,
            "padding_overhead_bytes": 256,
            "optimal_strategy": "swizzle",
            "optimal_conflicts": 4,
        },
        "narrow_fp32_scalar": {
            "baseline_conflicts": 16,
            "swizzle_conflicts": 2,
            "swizzle_sizeof_tc": 4,
            "padding_conflicts": 1,
            "padding_amount": 1,
            "padding_overhead_bytes": 128,
            "optimal_strategy": "padding",
            "optimal_conflicts": 1,
        },
        "square_fp32_row": {
            "baseline_conflicts": 1,
            "swizzle_conflicts": 1,
            "swizzle_sizeof_tc": 4,
            "padding_conflicts": 1,
            "padding_amount": 0,
            "padding_overhead_bytes": 0,
            "optimal_strategy": "none",
            "optimal_conflicts": 1,
        },
        "wide_fp16_vec8": {
            "baseline_conflicts": 32,
            "swizzle_conflicts": 4,
            "swizzle_sizeof_tc": 16,
            "padding_conflicts": 4,
            "padding_amount": 8,
            "padding_overhead_bytes": 256,
            "optimal_strategy": "swizzle",
            "optimal_conflicts": 4,
        },
        "narrow_fp64_scalar": {
            "baseline_conflicts": 32,
            "swizzle_conflicts": 2,
            "swizzle_sizeof_tc": 8,
            "padding_conflicts": 2,
            "padding_amount": 1,
            "padding_overhead_bytes": 256,
            "optimal_strategy": "swizzle",
            "optimal_conflicts": 2,
        },
        "small_fp32_vec4": {
            "baseline_conflicts": 32,
            "swizzle_conflicts": 4,
            "swizzle_sizeof_tc": 16,
            "padding_conflicts": 4,
            "padding_amount": 4,
            "padding_overhead_bytes": 256,
            "optimal_strategy": "swizzle",
            "optimal_conflicts": 4,
        },
    }

    def test_file_exists(self):
        assert os.path.isfile("/app/optimal_layouts.json"), (
            "/app/optimal_layouts.json not found -- run the optimizer pipeline"
        )

    def test_valid_json_array(self):
        with open("/app/optimal_layouts.json") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 8, f"Expected 8 entries, got {len(data)}"

    def test_required_keys(self):
        with open("/app/optimal_layouts.json") as f:
            data = json.load(f)
        required = {
            "name", "baseline_conflicts", "swizzle_conflicts",
            "swizzle_sizeof_tc", "padding_conflicts", "padding_amount",
            "padding_overhead_bytes", "optimal_strategy", "optimal_conflicts",
        }
        for entry in data:
            missing = required - set(entry.keys())
            assert not missing, f"Entry '{entry.get('name','?')}' missing: {missing}"

    @pytest.mark.parametrize("config_name", [
        "square_fp32_scalar", "tiny_fp32_scalar", "wide_fp32_vec4",
        "narrow_fp32_scalar", "square_fp32_row", "wide_fp16_vec8",
        "narrow_fp64_scalar", "small_fp32_vec4",
    ])
    def test_values(self, config_name):
        with open("/app/optimal_layouts.json") as f:
            data = json.load(f)

        entry = None
        for r in data:
            if r["name"] == config_name:
                entry = r
                break
        assert entry is not None, f"No entry for '{config_name}'"

        exp = self.EXPECTED[config_name]
        for key, val in exp.items():
            assert entry[key] == val, (
                f"{config_name}.{key}: expected {val}, got {entry.get(key)}"
            )


# ---------------------------------------------------------------------------
# Tests for analysis_report.csv
# ---------------------------------------------------------------------------

class TestOutputCSV:
    EXPECTED_HEADERS = [
        "name", "baseline_conflicts", "swizzle_sizeof_tc", "swizzle_conflicts",
        "padding_amount", "padding_conflicts", "padding_overhead_bytes",
        "optimal_strategy", "optimal_conflicts",
    ]

    def test_file_exists(self):
        assert os.path.isfile("/app/analysis_report.csv"), (
            "/app/analysis_report.csv not found"
        )

    def test_headers(self):
        with open("/app/analysis_report.csv", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader)
        assert headers == self.EXPECTED_HEADERS, (
            f"CSV headers mismatch: {headers}"
        )

    def test_row_count(self):
        with open("/app/analysis_report.csv", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == 8, f"Expected 8 data rows, got {len(rows)}"

    def test_spot_check_padding_winner(self):
        """Verify narrow_fp32_scalar in CSV (a case where padding wins)."""
        with open("/app/analysis_report.csv", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["name"] == "narrow_fp32_scalar":
                    assert row["optimal_strategy"] == "padding"
                    assert int(row["optimal_conflicts"]) == 1
                    assert int(row["padding_amount"]) == 1
                    return
        pytest.fail("narrow_fp32_scalar not found in CSV")

    def test_spot_check_swizzle_winner(self):
        """Verify wide_fp32_vec4 in CSV (sizeof_tc=16 for vec4 alignment)."""
        with open("/app/analysis_report.csv", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["name"] == "wide_fp32_vec4":
                    assert row["optimal_strategy"] == "swizzle"
                    assert int(row["swizzle_sizeof_tc"]) == 16
                    assert int(row["swizzle_conflicts"]) == 4
                    return
        pytest.fail("wide_fp32_vec4 not found in CSV")

    def test_spot_check_none(self):
        """Verify square_fp32_row selects 'none' (already conflict-free)."""
        with open("/app/analysis_report.csv", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["name"] == "square_fp32_row":
                    assert row["optimal_strategy"] == "none"
                    assert int(row["baseline_conflicts"]) == 1
                    return
        pytest.fail("square_fp32_row not found in CSV")
