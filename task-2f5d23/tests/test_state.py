
import json
import os
import ctypes
import pytest

RESULTS_PATH = "/app/results.json"
LIB_DIR = "/app/lib"
TESTDATA_DIR = "/app/testdata"

POLYNOMIALS = ["0xe7", "0xa6", "0x97", "0xea", "0x9c"]

# Expected HD profiles from Koopman CRC Zoo data
EXPECTED_PROFILES = {
    "0xe7": [247, 19, 1, 1, 1],
    "0xa6": [247, 15, 6],
    "0x97": [119, 119, 3, 3],
    "0xea": [85, 85, 2, 2],
    "0x9c": [9, 9, 9],
}

EXPECTED_X_PLUS_1 = {
    "0xe7": False,
    "0xa6": False,
    "0x97": True,
    "0xea": True,
    "0x9c": False,
}

EXPECTED_HW = [
    {"polynomial": "0xe7", "dataword_length": 247, "error_weight": 2, "hw_value": 0},
    {"polynomial": "0xe7", "dataword_length": 248, "error_weight": 2, "hw_value": 1},
    {"polynomial": "0xea", "dataword_length": 85, "error_weight": 2, "hw_value": 0},
    {"polynomial": "0xea", "dataword_length": 86, "error_weight": 2, "hw_value": 1},
    {"polynomial": "0x97", "dataword_length": 119, "error_weight": 3, "hw_value": 0},
    {"polynomial": "0x97", "dataword_length": 120, "error_weight": 2, "hw_value": 1},
    {"polynomial": "0x9c", "dataword_length": 9, "error_weight": 2, "hw_value": 0},
    {"polynomial": "0x9c", "dataword_length": 10, "error_weight": 2, "hw_value": 1},
]

# Hardcoded expected CRC-8 values (init=0, no reflect, xor_out=0)
# Keys: (filename, koopman_hex) -> expected CRC value
EXPECTED_CHECKSUMS = {
    ("msg_01.bin", "0xe7"): 0xd9,
    ("msg_01.bin", "0xa6"): 0x01,
    ("msg_01.bin", "0x97"): 0x1d,
    ("msg_01.bin", "0xea"): 0x8e,
    ("msg_01.bin", "0x9c"): 0xfc,
    ("msg_02.bin", "0xe7"): 0x23,
    ("msg_02.bin", "0xa6"): 0xda,
    ("msg_02.bin", "0x97"): 0x3e,
    ("msg_02.bin", "0xea"): 0x76,
    ("msg_02.bin", "0x9c"): 0x1e,
    ("msg_03.bin", "0xe7"): 0x98,
    ("msg_03.bin", "0xa6"): 0x13,
    ("msg_03.bin", "0x97"): 0xe7,
    ("msg_03.bin", "0xea"): 0xed,
    ("msg_03.bin", "0x9c"): 0xf0,
    ("msg_04.bin", "0xe7"): 0xc2,
    ("msg_04.bin", "0xa6"): 0x86,
    ("msg_04.bin", "0x97"): 0x7e,
    ("msg_04.bin", "0xea"): 0x21,
    ("msg_04.bin", "0x9c"): 0xc0,
}


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


class TestSharedLibraries:
    """Verify that compiled C shared libraries exist and are functional."""

    @pytest.mark.parametrize("poly", POLYNOMIALS)
    def test_so_file_exists(self, poly):
        so_path = os.path.join(LIB_DIR, f"crc_{poly}.so")
        assert os.path.isfile(so_path), (
            f"Shared library not found at {so_path}. "
            f"Must compile C source with gcc -shared -fPIC."
        )

    @pytest.mark.parametrize("poly", POLYNOMIALS)
    def test_so_exports_crc8_compute(self, poly):
        so_path = os.path.join(LIB_DIR, f"crc_{poly}.so")
        if not os.path.isfile(so_path):
            pytest.skip(f"Library {so_path} not found")
        lib = ctypes.CDLL(so_path)
        assert hasattr(lib, "crc8_compute"), (
            f"Library {so_path} does not export crc8_compute function"
        )

    @pytest.mark.parametrize("poly", POLYNOMIALS)
    def test_so_produces_correct_crc(self, poly):
        """Load each .so via ctypes and verify it produces correct CRC values."""
        so_path = os.path.join(LIB_DIR, f"crc_{poly}.so")
        if not os.path.isfile(so_path):
            pytest.skip(f"Library {so_path} not found")

        lib = ctypes.CDLL(so_path)
        lib.crc8_compute.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint]
        lib.crc8_compute.restype = ctypes.c_ubyte

        # Test with msg_01.bin = b"Hello"
        data = b"Hello"
        buf = (ctypes.c_ubyte * len(data))(*data)
        result = lib.crc8_compute(buf, len(data))
        expected = EXPECTED_CHECKSUMS[("msg_01.bin", poly)]
        assert result == expected, (
            f"C library CRC mismatch for {poly} on 'Hello': "
            f"got 0x{result:02x}, expected 0x{expected:02x}"
        )

    def test_all_so_files_are_elf(self):
        """Verify .so files are actual ELF shared objects, not scripts."""
        for poly in POLYNOMIALS:
            so_path = os.path.join(LIB_DIR, f"crc_{poly}.so")
            if not os.path.isfile(so_path):
                continue
            with open(so_path, "rb") as f:
                magic = f.read(4)
            assert magic == b"\x7fELF", (
                f"{so_path} is not a valid ELF binary (magic: {magic!r})"
            )


class TestResultsStructure:
    def test_top_level_keys(self, results):
        for key in ["profiles", "checksums", "cross_validation_passed", "hamming_weights"]:
            assert key in results, f"Missing '{key}' key in results"

    def test_profiles_is_dict(self, results):
        assert isinstance(results["profiles"], dict)

    def test_checksums_is_dict(self, results):
        assert isinstance(results["checksums"], dict)

    def test_hamming_weights_is_list(self, results):
        assert isinstance(results["hamming_weights"], list)

    def test_cross_validation_is_bool(self, results):
        assert isinstance(results["cross_validation_passed"], bool)

    def test_all_polynomials_present(self, results):
        for poly in POLYNOMIALS:
            assert poly in results["profiles"], f"Missing polynomial {poly} in profiles"


class TestCRCChecksums:
    """Verify CRC checksum values in results.json against hardcoded expectations."""

    def test_all_test_files_present(self, results):
        checksums = results["checksums"]
        for fname in ["msg_01.bin", "msg_02.bin", "msg_03.bin", "msg_04.bin"]:
            assert fname in checksums, f"Missing {fname} in checksums"

    @pytest.mark.parametrize("fname,poly", [
        (f, p) for f in ["msg_01.bin", "msg_02.bin", "msg_03.bin", "msg_04.bin"]
        for p in POLYNOMIALS
    ])
    def test_checksum_value(self, results, fname, poly):
        actual = results["checksums"][fname][poly]
        expected = EXPECTED_CHECKSUMS[(fname, poly)]
        assert actual == expected, (
            f"CRC checksum mismatch for {fname}/{poly}: "
            f"got 0x{actual:02x}, expected 0x{expected:02x}"
        )

    def test_cross_validation_passed(self, results):
        assert results["cross_validation_passed"] is True, (
            "Cross-validation between C library and Python GF(2) CRC must pass"
        )


class TestHDProfiles:
    @pytest.mark.parametrize("poly,expected", list(EXPECTED_PROFILES.items()))
    def test_hd_profile(self, results, poly, expected):
        actual = results["profiles"][poly]["hd_profile"]
        assert actual == expected, (
            f"HD profile mismatch for {poly}: expected {expected}, got {actual}"
        )

    def test_profiles_are_monotonically_decreasing(self, results):
        for poly, profile_data in results["profiles"].items():
            profile = profile_data["hd_profile"]
            for i in range(1, len(profile)):
                assert profile[i] <= profile[i - 1], (
                    f"Profile for {poly} not monotonically non-increasing: "
                    f"P{i+3}={profile[i]} > P{i+2}={profile[i-1]}"
                )

    def test_primitive_polys_have_maximal_hd3(self, results):
        for poly in ["0xe7", "0xa6"]:
            profile = results["profiles"][poly]["hd_profile"]
            assert profile[0] == 247, (
                f"Primitive poly {poly} should have P3=247, got {profile[0]}"
            )


class TestXPlus1Factor:
    @pytest.mark.parametrize("poly,expected", list(EXPECTED_X_PLUS_1.items()))
    def test_has_x_plus_1_factor(self, results, poly, expected):
        actual = results["profiles"][poly]["has_x_plus_1_factor"]
        assert actual == expected, (
            f"has_x_plus_1_factor mismatch for {poly}: expected {expected}, got {actual}"
        )

    def test_odd_detecting_polys_have_paired_profiles(self, results):
        for poly in ["0x97", "0xea"]:
            profile = results["profiles"][poly]["hd_profile"]
            assert len(profile) >= 2, f"{poly} profile too short"
            assert profile[0] == profile[1], (
                f"{poly} has (x+1) factor: P3={profile[0]} should equal P4={profile[1]}"
            )


class TestHammingWeights:
    def test_hamming_weight_count(self, results):
        assert len(results["hamming_weights"]) == len(EXPECTED_HW), (
            f"Expected {len(EXPECTED_HW)} HW queries, got {len(results['hamming_weights'])}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_HW)))
    def test_hamming_weight_value(self, results, idx):
        expected = EXPECTED_HW[idx]
        actual = results["hamming_weights"][idx]
        assert actual["polynomial"] == expected["polynomial"]
        assert actual["dataword_length"] == expected["dataword_length"]
        assert actual["error_weight"] == expected["error_weight"]
        assert actual["hw_value"] == expected["hw_value"], (
            f"HW query {idx} ({expected['polynomial']}, L={expected['dataword_length']}, "
            f"w={expected['error_weight']}): expected hw={expected['hw_value']}, "
            f"got hw={actual['hw_value']}"
        )

    def test_boundary_hw_pairs(self, results):
        hw_list = results["hamming_weights"]
        boundary_pairs = [(0, 1), (2, 3), (6, 7)]
        for at_boundary, past_boundary in boundary_pairs:
            assert hw_list[at_boundary]["hw_value"] == 0
            assert hw_list[past_boundary]["hw_value"] > 0
