
import json
import os

import flopy
import numpy as np
import pytest

# Reference bottom-layer concentrations for the correctly configured
# density-dependent saltwater intrusion problem with parameters from
# parameters.json (10-layer x 20-column confined aquifer).
REFERENCE_CONC = np.array([
    6.62568993e-05, 2.62136709e-04, 1.03376866e-03, 4.03149437e-03,
    1.54745356e-02, 5.80960685e-02, 2.11109069e-01, 7.29225328e-01,
    2.32090039e+00, 6.46492264e+00, 1.28547693e+01, 1.86965727e+01,
    2.36023472e+01, 2.74207659e+01, 3.02383176e+01, 3.22172463e+01,
    3.35101828e+01, 3.42835666e+01, 3.46963233e+01, 3.48890176e+01,
])

SEAWATER_CONC = 35.0
NCOL = 20
DELR = 2.0 / NCOL  # 0.1 m

REFERENCE_TOE = 1.1295
REFERENCE_MZW = 0.6353


@pytest.fixture
def results():
    """Load the results JSON file."""
    results_path = "/app/results.json"
    assert os.path.isfile(results_path), (
        f"results.json not found at {results_path}"
    )
    with open(results_path) as f:
        data = json.load(f)
    return data


class TestResultsStructure:
    """Verify results.json has the correct structure."""

    def test_has_bottom_concentrations(self, results):
        assert "bottom_concentrations" in results

    def test_has_toe_position(self, results):
        assert "toe_position" in results

    def test_has_mixing_zone_width(self, results):
        assert "mixing_zone_width" in results

    def test_bottom_concentrations_length(self, results):
        conc = results["bottom_concentrations"]
        assert isinstance(conc, list)
        assert len(conc) == NCOL, (
            f"Expected {NCOL} values, got {len(conc)}"
        )

    def test_bottom_concentrations_are_numeric(self, results):
        for i, c in enumerate(results["bottom_concentrations"]):
            assert isinstance(c, (int, float)), (
                f"bottom_concentrations[{i}] = {c!r} is not numeric"
            )

    def test_toe_position_is_numeric(self, results):
        assert isinstance(results["toe_position"], (int, float))

    def test_mixing_zone_width_is_numeric(self, results):
        assert isinstance(results["mixing_zone_width"], (int, float))


class TestPhysicalConsistency:
    """Verify that results are physically consistent."""

    def test_concentrations_in_range(self, results):
        conc = np.array(results["bottom_concentrations"])
        assert np.all(conc >= -0.5), f"Min = {conc.min()}"
        assert np.all(conc <= SEAWATER_CONC + 0.5), f"Max = {conc.max()}"

    def test_concentrations_monotonically_increasing(self, results):
        conc = np.array(results["bottom_concentrations"])
        diffs = np.diff(conc)
        assert np.all(diffs >= -0.01), (
            f"Non-monotonic: largest decrease = {diffs.min():.6f}"
        )

    def test_toe_position_in_domain(self, results):
        tp = results["toe_position"]
        assert 0.0 < tp < 2.0, f"toe_position = {tp} outside [0, 2]"

    def test_mixing_zone_width_positive(self, results):
        assert results["mixing_zone_width"] > 0.0

    def test_mixing_zone_width_less_than_domain(self, results):
        assert results["mixing_zone_width"] < 2.0

    def test_left_concentration_near_zero(self, results):
        assert results["bottom_concentrations"][0] < 1.0, (
            f"Leftmost = {results['bottom_concentrations'][0]}"
        )

    def test_right_concentration_near_seawater(self, results):
        assert results["bottom_concentrations"][-1] > 30.0, (
            f"Rightmost = {results['bottom_concentrations'][-1]}"
        )


class TestNumericalAccuracy:
    """Verify numerical accuracy against reference solution."""

    def test_bottom_concentrations_match_reference(self, results):
        conc = np.array(results["bottom_concentrations"])
        max_diff = np.max(np.abs(conc - REFERENCE_CONC))
        assert np.allclose(conc, REFERENCE_CONC, atol=1.0), (
            f"Max absolute difference: {max_diff:.4f} (tolerance: 1.0)"
        )

    def test_toe_position_matches_reference(self, results):
        diff = abs(results["toe_position"] - REFERENCE_TOE)
        assert diff < 0.2, (
            f"Toe position diff = {diff:.4f} (tolerance: 0.2)"
        )

    def test_mixing_zone_width_matches_reference(self, results):
        diff = abs(results["mixing_zone_width"] - REFERENCE_MZW)
        assert diff < 0.25, (
            f"Mixing zone width diff = {diff:.4f} (tolerance: 0.25)"
        )


class TestModelWorkspace:
    """Verify model workspace contains expected files."""

    def test_model_directory_exists(self):
        assert os.path.isdir("/app/model")

    def test_mfsim_nam_exists(self):
        assert os.path.isfile("/app/model/mfsim.nam")

    def test_mfsim_nam_valid(self):
        with open("/app/model/mfsim.nam") as f:
            content = f.read()
        assert "BEGIN" in content.upper(), "mfsim.nam appears invalid"
        assert len(content) > 50, "mfsim.nam too small to be valid"

    def test_model_has_head_output(self):
        files = os.listdir("/app/model")
        assert any(f.endswith(".hds") for f in files), "No .hds file found"

    def test_model_has_concentration_output(self):
        files = os.listdir("/app/model")
        assert any(f.endswith(".ucn") for f in files), "No .ucn file found"

    def test_listing_shows_normal_termination(self):
        lst_files = [
            f for f in os.listdir("/app/model") if f.endswith(".lst")
        ]
        assert lst_files, "No listing file (.lst) found"
        found_termination = False
        for lst in lst_files:
            with open(os.path.join("/app/model", lst)) as f:
                content = f.read()
            if "NORMAL TERMINATION" in content.upper():
                found_termination = True
                break
        assert found_termination, (
            "No listing file contains NORMAL TERMINATION"
        )


class TestModelOutputConsistency:
    """Cross-validate results.json against actual model output files."""

    def test_ucn_matches_results(self, results):
        """Verify concentrations in results.json match the .ucn binary."""
        ucn_files = [
            f for f in os.listdir("/app/model") if f.endswith(".ucn")
        ]
        assert ucn_files, "No .ucn file in /app/model/"
        ucn_path = os.path.join("/app/model", ucn_files[0])
        cobj = flopy.utils.HeadFile(
            ucn_path, precision="double", text="CONCENTRATION"
        )
        data = cobj.get_data()
        nlay = data.shape[0]
        bottom_from_file = data[nlay - 1, 0, :].tolist()
        reported = results["bottom_concentrations"]
        assert len(bottom_from_file) == len(reported), (
            f"UCN has {len(bottom_from_file)} cols, "
            f"results.json has {len(reported)}"
        )
        assert np.allclose(bottom_from_file, reported, atol=0.01), (
            "results.json concentrations do not match .ucn file content"
        )

    def test_hds_file_readable(self):
        """Verify .hds binary is a valid MODFLOW 6 head file."""
        hds_files = [
            f for f in os.listdir("/app/model") if f.endswith(".hds")
        ]
        assert hds_files, "No .hds file"
        hds_path = os.path.join("/app/model", hds_files[0])
        hobj = flopy.utils.HeadFile(hds_path, precision="double")
        heads = hobj.get_data()
        assert heads.size > 0, "Head array is empty"
        assert np.all(np.isfinite(heads[heads != 1e30])), (
            "Head array contains non-finite values"
        )
