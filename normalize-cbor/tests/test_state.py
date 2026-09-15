"""
Tests for CBOR Deterministic Encoding Conformance Audit.

Verifies that:
1. /app/conformance_report.json correctly identifies violations per encoder
2. Encoder behaviors are consistent with reported verdicts
3. /app/reference_normalizer.py satisfies all RFC 8949 Section 4.2.1 requirements
"""


import subprocess
import json
import os
import pytest


def run_encoder(path, hex_in):
    """Run an encoder script and return its hex output."""
    r = subprocess.run(
        ["python3", path],
        input=hex_in + "\n",
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout.strip()


def run_ref(hex_in):
    """Run the reference normalizer and return hex output."""
    r = subprocess.run(
        ["python3", "/app/reference_normalizer.py"],
        input=hex_in + "\n",
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"Normalizer failed on {hex_in}: {r.stderr}"
    return r.stdout.strip()


ENCODERS = {
    "alpha": "/app/encoders/alpha.py",
    "beta": "/app/encoders/beta.py",
    "gamma": "/app/encoders/gamma.py",
}

REQUIREMENTS = sorted([
    "preferred_int_args",
    "preferred_float_nan",
    "preferred_float_neg_zero",
    "preferred_float_shortest",
    "no_indefinite_length",
    "map_key_ordering",
])


# =========================================================================
# 1. Conformance Report — Structure
# =========================================================================

class TestReportStructure:

    def test_report_exists(self):
        assert os.path.exists("/app/conformance_report.json"), \
            "/app/conformance_report.json not found"

    def test_valid_json(self):
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        assert isinstance(report, dict)

    def test_all_encoders_present(self):
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        for name in ["alpha", "beta", "gamma"]:
            assert name in report, f"Encoder '{name}' missing from report"

    def test_all_requirements_present(self):
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        for enc in ["alpha", "beta", "gamma"]:
            for req in REQUIREMENTS:
                assert req in report[enc], \
                    f"Requirement '{req}' missing for encoder '{enc}'"

    def test_valid_verdicts(self):
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        for enc in ["alpha", "beta", "gamma"]:
            for req in REQUIREMENTS:
                v = report[enc][req]
                assert v in ("pass", "fail"), \
                    f"Invalid verdict '{v}' for {enc}/{req}"


# =========================================================================
# 2. Conformance Report — Verdicts
# =========================================================================

class TestAlphaVerdicts:

    @pytest.fixture
    def verdicts(self):
        with open("/app/conformance_report.json") as f:
            return json.load(f)["alpha"]

    def test_map_key_ordering_fail(self, verdicts):
        assert verdicts["map_key_ordering"] == "fail"

    def test_preferred_float_nan_fail(self, verdicts):
        assert verdicts["preferred_float_nan"] == "fail"

    def test_preferred_int_args_pass(self, verdicts):
        assert verdicts["preferred_int_args"] == "pass"

    def test_preferred_float_neg_zero_pass(self, verdicts):
        assert verdicts["preferred_float_neg_zero"] == "pass"

    def test_preferred_float_shortest_pass(self, verdicts):
        assert verdicts["preferred_float_shortest"] == "pass"

    def test_no_indefinite_length_pass(self, verdicts):
        assert verdicts["no_indefinite_length"] == "pass"


class TestBetaVerdicts:

    @pytest.fixture
    def verdicts(self):
        with open("/app/conformance_report.json") as f:
            return json.load(f)["beta"]

    def test_preferred_int_args_fail(self, verdicts):
        assert verdicts["preferred_int_args"] == "fail"

    def test_preferred_float_neg_zero_fail(self, verdicts):
        assert verdicts["preferred_float_neg_zero"] == "fail"

    def test_map_key_ordering_pass(self, verdicts):
        assert verdicts["map_key_ordering"] == "pass"

    def test_preferred_float_nan_pass(self, verdicts):
        assert verdicts["preferred_float_nan"] == "pass"

    def test_preferred_float_shortest_pass(self, verdicts):
        assert verdicts["preferred_float_shortest"] == "pass"

    def test_no_indefinite_length_pass(self, verdicts):
        assert verdicts["no_indefinite_length"] == "pass"


class TestGammaVerdicts:

    @pytest.fixture
    def verdicts(self):
        with open("/app/conformance_report.json") as f:
            return json.load(f)["gamma"]

    def test_no_indefinite_length_fail(self, verdicts):
        assert verdicts["no_indefinite_length"] == "fail"

    def test_preferred_float_shortest_fail(self, verdicts):
        assert verdicts["preferred_float_shortest"] == "fail"

    def test_preferred_int_args_pass(self, verdicts):
        assert verdicts["preferred_int_args"] == "pass"

    def test_preferred_float_nan_pass(self, verdicts):
        assert verdicts["preferred_float_nan"] == "pass"

    def test_preferred_float_neg_zero_pass(self, verdicts):
        assert verdicts["preferred_float_neg_zero"] == "pass"

    def test_map_key_ordering_pass(self, verdicts):
        assert verdicts["map_key_ordering"] == "pass"


# =========================================================================
# 3. Encoder Behavior Cross-checks
# =========================================================================

class TestEncoderBehavior:
    """Verify encoders actually exhibit the bugs the report should identify."""

    # --- Alpha bugs ---
    def test_alpha_nan_is_wrong(self):
        out = run_encoder(ENCODERS["alpha"], "fb7ff8000000000000")
        assert out != "f97e00", "Alpha should NOT canonicalize NaN"

    def test_alpha_nan_f32_is_wrong(self):
        out = run_encoder(ENCODERS["alpha"], "fa7fc00000")
        assert out != "f97e00", "Alpha should NOT canonicalize f32 NaN"

    def test_alpha_map_ordering_is_wrong(self):
        # {1000:1, "z":2} — bytewise keeps this order, length-first swaps
        out = run_encoder(ENCODERS["alpha"], "a21903e801617a02")
        assert out != "a21903e801617a02", "Alpha should use wrong map ordering"

    # --- Alpha correct behaviors ---
    def test_alpha_int255_correct(self):
        assert run_encoder(ENCODERS["alpha"], "18ff") == "18ff"

    def test_alpha_int255_from_u16_correct(self):
        assert run_encoder(ENCODERS["alpha"], "1900ff") == "18ff"

    def test_alpha_negzero_correct(self):
        assert run_encoder(ENCODERS["alpha"], "fa80000000") == "f98000"

    def test_alpha_indef_array_correct(self):
        assert run_encoder(ENCODERS["alpha"], "9f010203ff") == "83010203"

    def test_alpha_float_shortest_correct(self):
        assert run_encoder(ENCODERS["alpha"], "fb40f86a0000000000") == "fa47c35000"

    # --- Beta bugs ---
    def test_beta_int255_is_wrong(self):
        out = run_encoder(ENCODERS["beta"], "18ff")
        assert out != "18ff", "Beta should widen 255 to u16"

    def test_beta_negzero_is_wrong(self):
        out = run_encoder(ENCODERS["beta"], "fa80000000")
        assert out != "f98000", "Beta should lose negative zero sign"

    # --- Beta correct behaviors ---
    def test_beta_nan_correct(self):
        assert run_encoder(ENCODERS["beta"], "fb7ff8000000000000") == "f97e00"

    def test_beta_map_correct(self):
        assert run_encoder(ENCODERS["beta"], "a21903e801617a02") == "a21903e801617a02"

    def test_beta_indef_array_correct(self):
        assert run_encoder(ENCODERS["beta"], "9f010203ff") == "83010203"

    def test_beta_float_shortest_correct(self):
        assert run_encoder(ENCODERS["beta"], "fb40f86a0000000000") == "fa47c35000"

    # --- Gamma bugs ---
    def test_gamma_indef_array_is_wrong(self):
        out = run_encoder(ENCODERS["gamma"], "9f010203ff")
        assert out != "83010203", "Gamma should preserve indefinite arrays"

    def test_gamma_indef_map_is_wrong(self):
        out = run_encoder(ENCODERS["gamma"], "bf616101616202ff")
        assert out != "a2616101616202", "Gamma should preserve indefinite maps"

    def test_gamma_float_shortest_is_wrong(self):
        out = run_encoder(ENCODERS["gamma"], "fb40f86a0000000000")
        assert out != "fa47c35000", "Gamma should skip f32 precision"

    # --- Gamma correct behaviors ---
    def test_gamma_nan_correct(self):
        assert run_encoder(ENCODERS["gamma"], "fb7ff8000000000000") == "f97e00"

    def test_gamma_negzero_correct(self):
        assert run_encoder(ENCODERS["gamma"], "fa80000000") == "f98000"

    def test_gamma_int255_correct(self):
        assert run_encoder(ENCODERS["gamma"], "18ff") == "18ff"

    def test_gamma_map_ordering_correct(self):
        assert run_encoder(ENCODERS["gamma"], "a21903e801617a02") == "a21903e801617a02"


# =========================================================================
# 4. Reference Normalizer — Correctness
# =========================================================================

class TestReferenceNormalizer:
    """Verify the reference normalizer satisfies all §4.2.1 requirements."""

    def test_exists(self):
        assert os.path.exists("/app/reference_normalizer.py")

    # --- Preferred integer serialization ---
    def test_int_zero_passthrough(self):
        assert run_ref("00") == "00"

    def test_int_u8_zero_normalize(self):
        assert run_ref("1800") == "00"

    def test_int_u16_zero_normalize(self):
        assert run_ref("190000") == "00"

    def test_int_u32_zero_normalize(self):
        assert run_ref("1a00000000") == "00"

    def test_int_u64_zero_normalize(self):
        assert run_ref("1b0000000000000000") == "00"

    def test_int_23_passthrough(self):
        assert run_ref("17") == "17"

    def test_int_23_from_u8(self):
        assert run_ref("1817") == "17"

    def test_int_24_passthrough(self):
        assert run_ref("1818") == "1818"

    def test_int_255_passthrough(self):
        assert run_ref("18ff") == "18ff"

    def test_int_255_from_u16(self):
        assert run_ref("1900ff") == "18ff"

    def test_int_256_passthrough(self):
        assert run_ref("190100") == "190100"

    def test_neg_1_normalize(self):
        assert run_ref("3800") == "20"

    def test_neg_256_passthrough(self):
        assert run_ref("38ff") == "38ff"

    def test_neg_256_from_s16(self):
        assert run_ref("3900ff") == "38ff"

    def test_int_65535_from_u32(self):
        assert run_ref("1a0000ffff") == "19ffff"

    # --- NaN canonicalization ---
    def test_nan_f64(self):
        assert run_ref("fb7ff8000000000000") == "f97e00"

    def test_nan_f32(self):
        assert run_ref("fa7fc00000") == "f97e00"

    def test_nan_f16_passthrough(self):
        assert run_ref("f97e00") == "f97e00"

    # --- Negative zero sign preservation ---
    def test_negzero_f32(self):
        assert run_ref("fa80000000") == "f98000"

    def test_negzero_f64(self):
        assert run_ref("fb8000000000000000") == "f98000"

    def test_negzero_f16_passthrough(self):
        assert run_ref("f98000") == "f98000"

    def test_poszero_f16_passthrough(self):
        assert run_ref("f90000") == "f90000"

    def test_poszero_f32(self):
        assert run_ref("fa00000000") == "f90000"

    # --- Float shortest precision ---
    def test_f64_one_to_f16(self):
        assert run_ref("fb3ff0000000000000") == "f93c00"

    def test_f32_one_to_f16(self):
        assert run_ref("fa3f800000") == "f93c00"

    def test_f64_1_5_to_f16(self):
        assert run_ref("fb3ff8000000000000") == "f93e00"

    def test_f64_100000_to_f32(self):
        assert run_ref("fb40f86a0000000000") == "fa47c35000"

    def test_f32_100000_passthrough(self):
        assert run_ref("fa47c35000") == "fa47c35000"

    def test_f64_1_1_stays_f64(self):
        assert run_ref("fb3ff199999999999a") == "fb3ff199999999999a"

    def test_inf_f32_to_f16(self):
        assert run_ref("fa7f800000") == "f97c00"

    def test_inf_f64_to_f16(self):
        assert run_ref("fb7ff0000000000000") == "f97c00"

    def test_neg_inf_f32_to_f16(self):
        assert run_ref("faff800000") == "f9fc00"

    def test_neg_inf_f64_to_f16(self):
        assert run_ref("fbfff0000000000000") == "f9fc00"

    # --- Map key ordering (bytewise lexicographic) ---
    def test_map_sort_text_keys(self):
        assert run_ref("a2616202616101") == "a2616101616202"

    def test_map_bytewise_lex_preserves(self):
        assert run_ref("a21903e801617a02") == "a21903e801617a02"

    def test_map_bytewise_lex_reorders(self):
        assert run_ref("a2617a021903e801") == "a21903e801617a02"

    def test_rfc_8key_map(self):
        inp = "a8f4008120018118640262616103617a0420051864060a07"
        exp = "a80a071864062005617a046261610381186402812001f400"
        assert run_ref(inp) == exp

    # --- No indefinite-length items ---
    def test_indef_array(self):
        assert run_ref("9f010203ff") == "83010203"

    def test_indef_empty_array(self):
        assert run_ref("9fff") == "80"

    def test_indef_bstr(self):
        assert run_ref("5f42010243030405ff") == "450102030405"

    def test_indef_tstr(self):
        assert run_ref("7f657374726561646d696e67ff") == "6973747265616d696e67"

    def test_indef_map(self):
        assert run_ref("bf616101616202ff") == "a2616101616202"

    # --- Tag argument normalization ---
    def test_tag_u64_normalize(self):
        assert run_ref("db000000000000000100") == "c100"

    def test_tag_content_normalize(self):
        assert run_ref("c11a000003e8") == "c11903e8"

    # --- Passthrough ---
    def test_passthrough_int_0(self):
        assert run_ref("00") == "00"

    def test_passthrough_int_1(self):
        assert run_ref("01") == "01"

    def test_passthrough_array(self):
        assert run_ref("83010203") == "83010203"

    def test_passthrough_false(self):
        assert run_ref("f4") == "f4"

    def test_passthrough_true(self):
        assert run_ref("f5") == "f5"

    def test_passthrough_null(self):
        assert run_ref("f6") == "f6"

    def test_passthrough_text(self):
        assert run_ref("6449455446") == "6449455446"

    def test_passthrough_empty_map(self):
        assert run_ref("a0") == "a0"

    def test_passthrough_empty_array(self):
        assert run_ref("80") == "80"

    def test_passthrough_bignum(self):
        assert run_ref("c249010000000000000000") == "c249010000000000000000"

    def test_passthrough_sorted_map(self):
        assert run_ref("a201020304") == "a201020304"

    # --- Combined / integration ---
    def test_nested_normalization(self):
        assert run_ref("8181190000") == "818100"

    def test_map_with_nan_and_boundary(self):
        inp = "a218fffb7ff8000000000000190100fa80000000"
        exp = "a218fff97e00190100f98000"
        assert run_ref(inp) == exp

    def test_indef_map_with_reordering(self):
        assert run_ref("bf1903e801617a02ff") == "a21903e801617a02"
