"""
Filament PBR BRDF Evaluation - Verification Tests

"""

import json
import os
import pytest

OUTPUT_PATH = "/app/output.json"

# Reference values computed from the correct PBR formulations
REFERENCE = {
    "dfg_01": {"dfg1": 0.41547, "dfg2": 0.57868},
    "dfg_02": {"dfg1": 0.76067, "dfg2": 0.13995},
    "dfg_03": {"dfg1": 0.76023, "dfg2": 0.03203},
    "dfg_04": {"dfg1": 0.81153, "dfg2": 0.13581},
    "dfg_05": {"dfg1": 0.96859, "dfg2": 0.03143},
    "dfg_06": {"dfg1": 0.83319, "dfg2": 0.02233},
    "dfg_07": {"dfg1": 0.53070, "dfg2": 0.00454},
    "dfg_08": {"dfg1": 0.99897, "dfg2": 0.00048},
    "dfg_09": {"dfg1": 0.68984, "dfg2": 0.00122},
    "dfg_10": {"dfg1": 0.91160, "dfg2": 0.00013},
    "dfg_11": {"dfg1": 0.91627, "dfg2": 0.00003},
    "dfg_12": {"dfg1": 0.88754, "dfg2": 0.06427},
    "brdf_01": {
        "specular": [0.00189, 0.00189, 0.00189],
        "diffuse": [0.25465, 0.06366, 0.03183],
        "total": [0.18140, 0.04636, 0.02385]
    },
    "brdf_02": {
        "specular": [0.00582, 0.00413, 0.00169],
        "diffuse": [0.0, 0.0, 0.0],
        "total": [0.00504, 0.00358, 0.00146]
    },
    "brdf_03": {
        "specular": [0.04936, 0.04936, 0.04936],
        "diffuse": [0.07958, 0.07958, 0.07958],
        "total": [0.12698, 0.12698, 0.12698]
    },
    "brdf_04": {
        "specular": [0.00034, 0.00034, 0.00034],
        "diffuse": [0.28648, 0.28648, 0.28648],
        "total": [0.26952, 0.26952, 0.26952]
    },
    "brdf_05": {
        "specular": [0.10393, 0.10393, 0.10393],
        "diffuse": [0.19099, 0.09549, 0.03183],
        "total": [0.20854, 0.14101, 0.09600]
    },
    "brdf_06": {
        "specular": [1.79039, 1.20616, 1.01769],
        "diffuse": [0.0, 0.0, 0.0],
        "total": [1.78357, 1.20157, 1.01382]
    },
    "cc_01": {
        "specular": [0.00189, 0.00189, 0.00189],
        "diffuse": [0.25465, 0.03183, 0.03183],
        "clearcoat_specular": 2.357e-06,
        "total": [0.17410, 0.02284, 0.02284]
    },
    "cc_02": {
        "specular": [0.00062, 0.00062, 0.00492],
        "diffuse": [0.0, 0.0, 0.0],
        "clearcoat_specular": 6.707e-05,
        "total": [0.00056, 0.00056, 0.00405]
    },
    "ec_01": {
        "E": 0.85553,
        "compensation": [1.00675, 1.00675, 1.00675]
    },
    "ec_02": {
        "E": 0.82479,
        "compensation": [1.21243, 1.15082, 1.06160]
    },
    "ec_03": {
        "E": 0.99941,
        "compensation": [1.00033, 1.00034, 1.00034]
    },
    "ec_04": {
        "E": 0.62706,
        "compensation": [1.56500, 1.38063, 1.32116]
    },
}


def approx_equal(actual, expected, atol=0.005, rtol=0.05):
    """Check approximate equality using max(atol, rtol * |expected|)."""
    tol = max(atol, rtol * abs(expected))
    return abs(actual - expected) <= tol


@pytest.fixture(scope="session")
def output():
    """Load the output.json produced by the evaluation pipeline."""
    assert os.path.exists(OUTPUT_PATH), (
        f"Output file not found at {OUTPUT_PATH}. "
        "Build the project and run the driver first."
    )
    with open(OUTPUT_PATH, "r") as f:
        data = json.load(f)
    return data


class TestOutputStructure:
    """Verify that the output contains all required evaluation IDs."""

    def test_all_keys_present(self, output):
        for key in REFERENCE:
            assert key in output, f"Missing evaluation result: {key}"


class TestDFGComputation:
    """Verify DFG LUT values (split-sum BRDF integration)."""

    @pytest.mark.parametrize("eval_id", [
        "dfg_01", "dfg_02", "dfg_03", "dfg_04", "dfg_05", "dfg_06",
        "dfg_07", "dfg_08", "dfg_09", "dfg_10", "dfg_11", "dfg_12",
    ])
    def test_dfg_values(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]

        assert "dfg1" in result, f"{eval_id}: missing dfg1"
        assert "dfg2" in result, f"{eval_id}: missing dfg2"

        assert approx_equal(result["dfg1"], ref["dfg1"]), (
            f"{eval_id} dfg1: got {result['dfg1']:.6f}, expected {ref['dfg1']:.5f}"
        )
        assert approx_equal(result["dfg2"], ref["dfg2"]), (
            f"{eval_id} dfg2: got {result['dfg2']:.6f}, expected {ref['dfg2']:.5f}"
        )

    def test_dfg_physical_constraints(self, output):
        """DFG values must satisfy physical constraints."""
        for eval_id in [k for k in REFERENCE if k.startswith("dfg_")]:
            result = output[eval_id]
            assert result["dfg1"] >= -0.001, f"{eval_id}: dfg1 must be >= 0"
            assert result["dfg2"] >= -0.001, f"{eval_id}: dfg2 must be >= 0"
            E = result["dfg1"] + result["dfg2"]
            assert E <= 1.05, f"{eval_id}: E = dfg1 + dfg2 = {E:.4f} exceeds 1.0"

    def test_dfg_roughness_trend(self, output):
        """At fixed NoV=0.5, dfg2 should decrease as roughness increases."""
        dfg2_r01 = output["dfg_05"]["dfg2"]
        dfg2_r05 = output["dfg_06"]["dfg2"]
        dfg2_r09 = output["dfg_07"]["dfg2"]
        assert dfg2_r01 > dfg2_r05 > dfg2_r09, (
            f"dfg2 should decrease with roughness at fixed NoV: "
            f"{dfg2_r01:.6f} > {dfg2_r05:.6f} > {dfg2_r09:.6f}"
        )


class TestStandardBRDF:
    """Verify standard model BRDF evaluation."""

    @pytest.mark.parametrize("eval_id", [
        "brdf_01", "brdf_02", "brdf_03", "brdf_04", "brdf_05", "brdf_06",
    ])
    def test_brdf_total(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "total" in result, f"{eval_id}: missing 'total'"

        for i, channel in enumerate(["R", "G", "B"]):
            assert approx_equal(result["total"][i], ref["total"][i]), (
                f"{eval_id} total[{channel}]: got {result['total'][i]:.6f}, "
                f"expected {ref['total'][i]:.5f}"
            )

    @pytest.mark.parametrize("eval_id", [
        "brdf_01", "brdf_02", "brdf_03", "brdf_04", "brdf_05", "brdf_06",
    ])
    def test_brdf_specular(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "specular" in result, f"{eval_id}: missing 'specular'"

        for i, channel in enumerate(["R", "G", "B"]):
            assert approx_equal(result["specular"][i], ref["specular"][i]), (
                f"{eval_id} specular[{channel}]: got {result['specular'][i]:.6f}, "
                f"expected {ref['specular'][i]:.5f}"
            )

    @pytest.mark.parametrize("eval_id", [
        "brdf_01", "brdf_02", "brdf_03", "brdf_04", "brdf_05", "brdf_06",
    ])
    def test_brdf_diffuse(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "diffuse" in result, f"{eval_id}: missing 'diffuse'"

        for i, channel in enumerate(["R", "G", "B"]):
            assert approx_equal(result["diffuse"][i], ref["diffuse"][i]), (
                f"{eval_id} diffuse[{channel}]: got {result['diffuse'][i]:.6f}, "
                f"expected {ref['diffuse'][i]:.5f}"
            )

    def test_metallic_no_diffuse(self, output):
        """Fully metallic materials should have zero diffuse."""
        for eval_id in ["brdf_02", "brdf_06"]:
            result = output[eval_id]
            for i in range(3):
                assert abs(result["diffuse"][i]) < 0.001, (
                    f"{eval_id}: metallic=1.0 should have zero diffuse, "
                    f"got {result['diffuse']}"
                )

    def test_dielectric_equal_specular_channels(self, output):
        """Dielectric materials with reflectance-only f0 have equal specular channels."""
        for eval_id in ["brdf_01", "brdf_04"]:
            result = output[eval_id]
            assert approx_equal(result["specular"][0], result["specular"][1],
                                atol=0.001), (
                f"{eval_id}: dielectric specular R != G"
            )
            assert approx_equal(result["specular"][1], result["specular"][2],
                                atol=0.001), (
                f"{eval_id}: dielectric specular G != B"
            )


class TestClearCoatBRDF:
    """Verify clear coat model BRDF evaluation."""

    @pytest.mark.parametrize("eval_id", ["cc_01", "cc_02"])
    def test_clearcoat_total(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "total" in result, f"{eval_id}: missing 'total'"

        for i, channel in enumerate(["R", "G", "B"]):
            assert approx_equal(result["total"][i], ref["total"][i]), (
                f"{eval_id} total[{channel}]: got {result['total'][i]:.6f}, "
                f"expected {ref['total'][i]:.5f}"
            )

    @pytest.mark.parametrize("eval_id", ["cc_01", "cc_02"])
    def test_clearcoat_specular_exists(self, output, eval_id):
        result = output[eval_id]
        assert "clearcoat_specular" in result, (
            f"{eval_id}: missing 'clearcoat_specular'"
        )
        ref = REFERENCE[eval_id]
        assert approx_equal(
            result["clearcoat_specular"], ref["clearcoat_specular"],
            atol=1e-4, rtol=0.1
        ), (
            f"{eval_id} clearcoat_specular: got {result['clearcoat_specular']:.6e}, "
            f"expected {ref['clearcoat_specular']:.3e}"
        )

    def test_clearcoat_attenuates_base(self, output):
        """Clear coat should attenuate the base layer's contribution."""
        cc = output["cc_01"]
        assert cc["total"][0] > 0, "cc_01 total R should be positive"
        assert cc["total"][0] < 0.3, "cc_01 total R should be attenuated"


class TestEnergyCompensation:
    """Verify multi-scatter energy compensation."""

    @pytest.mark.parametrize("eval_id", ["ec_01", "ec_02", "ec_03", "ec_04"])
    def test_compensation_values(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "compensation" in result, f"{eval_id}: missing 'compensation'"

        for i, channel in enumerate(["R", "G", "B"]):
            assert approx_equal(
                result["compensation"][i], ref["compensation"][i],
                atol=0.01, rtol=0.05
            ), (
                f"{eval_id} compensation[{channel}]: "
                f"got {result['compensation'][i]:.6f}, "
                f"expected {ref['compensation'][i]:.5f}"
            )

    @pytest.mark.parametrize("eval_id", ["ec_01", "ec_02", "ec_03", "ec_04"])
    def test_energy_value(self, output, eval_id):
        ref = REFERENCE[eval_id]
        result = output[eval_id]
        assert "E" in result, f"{eval_id}: missing 'E'"

        assert approx_equal(result["E"], ref["E"], atol=0.01, rtol=0.05), (
            f"{eval_id} E: got {result['E']:.6f}, expected {ref['E']:.5f}"
        )

    def test_compensation_always_ge_one(self, output):
        """Energy compensation should always be >= 1.0."""
        for eval_id in ["ec_01", "ec_02", "ec_03", "ec_04"]:
            result = output[eval_id]
            for i, c in enumerate(result["compensation"]):
                assert c >= 0.999, (
                    f"{eval_id} compensation[{i}] = {c:.6f} < 1.0"
                )

    def test_compensation_increases_with_roughness(self, output):
        """Higher roughness should need more energy compensation."""
        comp_01 = output["ec_01"]["compensation"][0]
        comp_04 = output["ec_04"]["compensation"][0]
        assert comp_04 > comp_01, (
            f"Higher roughness should need more compensation: "
            f"r=0.9 ({comp_04:.4f}) vs r=0.5 ({comp_01:.4f})"
        )
