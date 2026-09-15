
import pytest
import json
import subprocess
import os
import math
import tempfile

TOOL = "/app/xrd_tool.py"
DATA_DIR = "/app/data"
WAVELENGTH = 1.5406  # Cu K-alpha in angstroms
TWO_THETA_MAX = 90.0

ALL_CIF_FILES = ["nacl.cif", "calcite.cif", "batio3.cif", "rutile.cif", "cuo.cif"]


def run_simulate(cif_file, wavelength=WAVELENGTH, two_theta_max=TWO_THETA_MAX):
    """Run the simulate subcommand and return parsed JSON output."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_path = f.name
    try:
        result = subprocess.run(
            ["python3", TOOL, "simulate", cif_file,
             "--wavelength", str(wavelength),
             "--two-theta-max", str(two_theta_max),
             "--output", output_path],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, (
            f"simulate failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        with open(output_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


def run_identify(observed_json_path, cif_dir, wavelength=WAVELENGTH):
    """Run the identify subcommand and return parsed JSON output."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        output_path = f.name
    try:
        result = subprocess.run(
            ["python3", TOOL, "identify", observed_json_path, cif_dir,
             "--wavelength", str(wavelength),
             "--output", output_path],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, (
            f"identify failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        with open(output_path) as f:
            return json.load(f)
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)


# ===== Tool Existence =====

class TestToolExists:
    def test_tool_file_exists(self):
        assert os.path.isfile(TOOL), f"{TOOL} does not exist"

    def test_cif_data_exists(self):
        for name in ALL_CIF_FILES:
            path = os.path.join(DATA_DIR, name)
            assert os.path.isfile(path), f"Missing CIF file: {path}"


# ===== NaCl Simulation Tests (cubic, standard CIF tags) =====

class TestSimulateNaCl:
    @pytest.fixture(scope="class")
    def nacl_data(self):
        return run_simulate(os.path.join(DATA_DIR, "nacl.cif"))

    def test_cell_parameters(self, nacl_data):
        cell = nacl_data["cell"]
        assert abs(cell["a"] - 5.6402) < 0.01
        assert abs(cell["b"] - 5.6402) < 0.01
        assert abs(cell["c"] - 5.6402) < 0.01
        assert abs(cell["alpha"] - 90.0) < 0.1
        assert abs(cell["beta"] - 90.0) < 0.1
        assert abs(cell["gamma"] - 90.0) < 0.1

    def test_volume(self, nacl_data):
        assert abs(nacl_data["volume"] - 179.43) < 1.0

    def test_space_group(self, nacl_data):
        sg = nacl_data["space_group"]
        assert "m" in sg.lower() and ("3" in sg or "-3" in sg), (
            f"Space group should be Fm-3m variant, got: {sg}"
        )

    def test_asymmetric_atom_count(self, nacl_data):
        assert nacl_data["num_atoms_asymmetric"] == 2

    def test_unit_cell_atom_count(self, nacl_data):
        assert nacl_data["num_atoms_unit_cell"] == 8

    def test_peak_positions_present(self, nacl_data):
        """Check known NaCl peak 2theta positions are present."""
        peaks = nacl_data["peaks"]
        two_thetas = [p["two_theta"] for p in peaks]
        expected = [27.35, 31.71, 45.45, 53.86, 56.46, 66.22]
        for exp_2th in expected:
            found = any(abs(tt - exp_2th) < 0.5 for tt in two_thetas)
            assert found, (
                f"Expected NaCl peak near 2theta={exp_2th} not found. "
                f"Peaks at: {sorted(two_thetas)[:10]}"
            )

    def test_strongest_peak_is_200(self, nacl_data):
        peaks = nacl_data["peaks"]
        strongest = max(peaks, key=lambda p: p["intensity"])
        assert abs(strongest["two_theta"] - 31.71) < 0.5, (
            f"Strongest peak at 2theta={strongest['two_theta']}, expected ~31.7"
        )
        assert strongest["intensity"] == 100.0

    def test_systematic_absences(self, nacl_data):
        """F-centered: only h,k,l all odd or all even should appear."""
        peaks = nacl_data["peaks"]
        two_thetas = [p["two_theta"] for p in peaks]
        forbidden_positions = [15.7, 22.3, 35.6]
        for fb_pos in forbidden_positions:
            found_nearby = any(abs(tt - fb_pos) < 0.3 for tt in two_thetas)
            assert not found_nearby, (
                f"Found peak near forbidden position 2theta={fb_pos}"
            )

    def test_multiplicities(self, nacl_data):
        peaks = nacl_data["peaks"]
        peak_111 = next((p for p in peaks if abs(p["two_theta"] - 27.35) < 0.5), None)
        peak_200 = next((p for p in peaks if abs(p["two_theta"] - 31.71) < 0.5), None)
        peak_220 = next((p for p in peaks if abs(p["two_theta"] - 45.45) < 0.5), None)

        assert peak_111 is not None, "Missing (111) peak"
        assert peak_200 is not None, "Missing (200) peak"
        assert peak_220 is not None, "Missing (220) peak"
        assert peak_111["multiplicity"] == 8, f"(111) mult={peak_111['multiplicity']}, expected 8"
        assert peak_200["multiplicity"] == 6, f"(200) mult={peak_200['multiplicity']}, expected 6"
        assert peak_220["multiplicity"] == 12, f"(220) mult={peak_220['multiplicity']}, expected 12"

    def test_d_spacings(self, nacl_data):
        peaks = nacl_data["peaks"]
        peak_200 = next((p for p in peaks if abs(p["two_theta"] - 31.71) < 0.5), None)
        assert peak_200 is not None
        assert abs(peak_200["d_spacing"] - 2.8201) < 0.01

        peak_220 = next((p for p in peaks if abs(p["two_theta"] - 45.45) < 0.5), None)
        assert peak_220 is not None
        assert abs(peak_220["d_spacing"] - 1.9945) < 0.01


# ===== Calcite Tests (trigonal, modern _space_group_symop_operation_xyz tag) =====

class TestSimulateCalcite:
    @pytest.fixture(scope="class")
    def calcite_data(self):
        return run_simulate(os.path.join(DATA_DIR, "calcite.cif"))

    def test_cell_parameters(self, calcite_data):
        cell = calcite_data["cell"]
        assert abs(cell["a"] - 4.9896) < 0.01
        assert abs(cell["c"] - 17.0610) < 0.01
        assert abs(cell["gamma"] - 120.0) < 0.1

    def test_volume(self, calcite_data):
        assert abs(calcite_data["volume"] - 367.78) < 2.0

    def test_asymmetric_atom_count(self, calcite_data):
        assert calcite_data["num_atoms_asymmetric"] == 3

    def test_unit_cell_atom_count(self, calcite_data):
        # R-3c with Ca(6b)+C(6a)+O(18e) = 30
        assert calcite_data["num_atoms_unit_cell"] == 30

    def test_has_peaks(self, calcite_data):
        peaks = calcite_data["peaks"]
        assert len(peaks) > 5, f"Expected >5 peaks for calcite, got {len(peaks)}"

    def test_peaks_normalized(self, calcite_data):
        peaks = calcite_data["peaks"]
        max_intensity = max(p["intensity"] for p in peaks)
        assert abs(max_intensity - 100.0) < 0.01


# ===== BaTiO3 Tests (tetragonal, B_iso displacement parameters) =====

class TestSimulateBaTiO3:
    @pytest.fixture(scope="class")
    def batio3_data(self):
        return run_simulate(os.path.join(DATA_DIR, "batio3.cif"))

    def test_cell_parameters(self, batio3_data):
        cell = batio3_data["cell"]
        assert abs(cell["a"] - 3.9945) < 0.01
        assert abs(cell["c"] - 4.0335) < 0.01
        assert abs(cell["a"] - cell["b"]) < 0.001
        assert abs(cell["a"] - cell["c"]) > 0.01

    def test_volume(self, batio3_data):
        assert abs(batio3_data["volume"] - 64.38) < 0.5

    def test_asymmetric_atom_count(self, batio3_data):
        assert batio3_data["num_atoms_asymmetric"] == 4

    def test_unit_cell_atom_count(self, batio3_data):
        # P4mm: Ba(1a)+Ti(1b)+O1(1b)+O2(2c) = 5
        assert batio3_data["num_atoms_unit_cell"] == 5

    def test_has_peaks(self, batio3_data):
        peaks = batio3_data["peaks"]
        assert len(peaks) > 5


# ===== Rutile Tests (tetragonal, modern tags, numbered ops, uncertainties) =====

class TestSimulateRutile:
    @pytest.fixture(scope="class")
    def rutile_data(self):
        return run_simulate(os.path.join(DATA_DIR, "rutile.cif"))

    def test_cell_parameters(self, rutile_data):
        cell = rutile_data["cell"]
        assert abs(cell["a"] - 4.5937) < 0.01
        assert abs(cell["b"] - 4.5937) < 0.01
        assert abs(cell["c"] - 2.9587) < 0.01
        assert abs(cell["alpha"] - 90.0) < 0.1

    def test_volume(self, rutile_data):
        # V = a^2 * c = 4.5937^2 * 2.9587 = 62.43
        assert abs(rutile_data["volume"] - 62.43) < 0.5

    def test_space_group(self, rutile_data):
        sg = rutile_data["space_group"]
        assert "42" in sg or "4_2" in sg or "4₂" in sg or "mnm" in sg.lower() or "m n m" in sg, (
            f"Space group should be P42/mnm variant, got: {sg}"
        )

    def test_asymmetric_atom_count(self, rutile_data):
        assert rutile_data["num_atoms_asymmetric"] == 2

    def test_unit_cell_atom_count(self, rutile_data):
        # P42/mnm: Ti(2a) + O(4f) = 6
        assert rutile_data["num_atoms_unit_cell"] == 6

    def test_peak_110(self, rutile_data):
        """The (110) reflection at ~27.4° should be present and strongest."""
        peaks = rutile_data["peaks"]
        two_thetas = [p["two_theta"] for p in peaks]
        found = any(abs(tt - 27.44) < 0.5 for tt in two_thetas)
        assert found, f"Expected rutile (110) peak near 2theta=27.44. Peaks: {sorted(two_thetas)[:10]}"

    def test_peak_101(self, rutile_data):
        """The (101) reflection at ~36.1° should be present."""
        peaks = rutile_data["peaks"]
        two_thetas = [p["two_theta"] for p in peaks]
        found = any(abs(tt - 36.09) < 0.5 for tt in two_thetas)
        assert found, f"Expected rutile (101) peak near 2theta=36.09. Peaks: {sorted(two_thetas)[:10]}"

    def test_has_sufficient_peaks(self, rutile_data):
        peaks = rutile_data["peaks"]
        assert len(peaks) > 5, f"Expected >5 peaks for rutile, got {len(peaks)}"


# ===== CuO Tests (monoclinic, C-centered, beta != 90) =====

class TestSimulateCuO:
    @pytest.fixture(scope="class")
    def cuo_data(self):
        return run_simulate(os.path.join(DATA_DIR, "cuo.cif"))

    def test_cell_parameters(self, cuo_data):
        cell = cuo_data["cell"]
        assert abs(cell["a"] - 4.6837) < 0.01
        assert abs(cell["b"] - 3.4226) < 0.01
        assert abs(cell["c"] - 5.1288) < 0.01
        assert abs(cell["alpha"] - 90.0) < 0.1
        assert abs(cell["gamma"] - 90.0) < 0.1

    def test_monoclinic_beta(self, cuo_data):
        """Beta angle must be non-orthogonal (monoclinic)."""
        cell = cuo_data["cell"]
        assert abs(cell["beta"] - 99.54) < 0.1, (
            f"Expected beta=99.54, got {cell['beta']}"
        )

    def test_volume(self, cuo_data):
        # V = abc*sin(beta) ~ 81.08
        assert abs(cuo_data["volume"] - 81.08) < 1.0

    def test_asymmetric_atom_count(self, cuo_data):
        assert cuo_data["num_atoms_asymmetric"] == 2

    def test_unit_cell_atom_count(self, cuo_data):
        # C 2/c: Cu(4e) + O(4e) = 8, or Cu(4a/4b) + O(4e) = 8
        assert cuo_data["num_atoms_unit_cell"] == 8

    def test_has_peaks(self, cuo_data):
        peaks = cuo_data["peaks"]
        assert len(peaks) > 5, f"Expected >5 peaks for CuO, got {len(peaks)}"

    def test_peaks_normalized(self, cuo_data):
        peaks = cuo_data["peaks"]
        max_intensity = max(p["intensity"] for p in peaks)
        assert abs(max_intensity - 100.0) < 0.01


# ===== Output Format Tests =====

class TestOutputFormat:
    @pytest.fixture(scope="class")
    def nacl_data(self):
        return run_simulate(os.path.join(DATA_DIR, "nacl.cif"))

    def test_json_schema(self, nacl_data):
        required_keys = ["cell", "volume", "space_group",
                         "num_atoms_asymmetric", "num_atoms_unit_cell", "peaks"]
        for key in required_keys:
            assert key in nacl_data, f"Missing key: {key}"

        cell = nacl_data["cell"]
        for param in ["a", "b", "c", "alpha", "beta", "gamma"]:
            assert param in cell, f"Missing cell parameter: {param}"

    def test_peak_schema(self, nacl_data):
        peaks = nacl_data["peaks"]
        assert len(peaks) > 0
        for p in peaks:
            for key in ["hkl", "d_spacing", "two_theta", "intensity", "multiplicity"]:
                assert key in p, f"Peak missing key: {key}"
            assert isinstance(p["hkl"], list) and len(p["hkl"]) == 3
            assert isinstance(p["multiplicity"], int) and p["multiplicity"] > 0
            assert p["d_spacing"] > 0
            assert 0 < p["two_theta"] <= TWO_THETA_MAX

    def test_peaks_sorted_by_two_theta(self, nacl_data):
        peaks = nacl_data["peaks"]
        for i in range(1, len(peaks)):
            assert peaks[i]["two_theta"] >= peaks[i-1]["two_theta"], (
                f"Peaks not sorted: {peaks[i-1]['two_theta']} > {peaks[i]['two_theta']}"
            )

    def test_intensities_normalized(self, nacl_data):
        peaks = nacl_data["peaks"]
        max_int = max(p["intensity"] for p in peaks)
        assert abs(max_int - 100.0) < 0.01
        for p in peaks:
            assert p["intensity"] >= 0.1, (
                f"Peak with intensity {p['intensity']} < 0.1 should be filtered"
            )

    def test_types_correct(self, nacl_data):
        assert isinstance(nacl_data["volume"], (int, float))
        assert isinstance(nacl_data["space_group"], str)
        assert isinstance(nacl_data["num_atoms_asymmetric"], int)
        assert isinstance(nacl_data["num_atoms_unit_cell"], int)


# ===== Phase Identification Tests =====

class TestIdentify:
    def _create_observed_peaks(self, peaks_list, path):
        data = {"peaks": [{"two_theta": tt, "intensity": intens}
                          for tt, intens in peaks_list]}
        with open(path, "w") as f:
            json.dump(data, f)

    def test_identify_nacl(self):
        nacl_observed = [
            (27.4, 8.0),
            (31.7, 100.0),
            (45.5, 55.0),
            (53.9, 15.0),
            (56.5, 11.0),
            (66.2, 6.0),
        ]
        obs_path = "/tmp/test_observed_nacl.json"
        self._create_observed_peaks(nacl_observed, obs_path)
        try:
            result = run_identify(obs_path, DATA_DIR)
            assert "best_match" in result
            assert result["best_match"] == "nacl.cif", (
                f"Expected nacl.cif, got {result['best_match']}"
            )
            assert "rankings" in result
            assert len(result["rankings"]) == len(ALL_CIF_FILES)
        finally:
            os.unlink(obs_path)

    def test_identify_batio3(self):
        batio3_observed = [
            (22.1, 30.0),
            (31.5, 100.0),
            (38.8, 50.0),
            (45.2, 40.0),
            (50.8, 15.0),
            (56.0, 60.0),
        ]
        obs_path = "/tmp/test_observed_batio3.json"
        self._create_observed_peaks(batio3_observed, obs_path)
        try:
            result = run_identify(obs_path, DATA_DIR)
            assert result["best_match"] == "batio3.cif", (
                f"Expected batio3.cif, got {result['best_match']}"
            )
        finally:
            os.unlink(obs_path)

    def test_identify_scores_valid(self):
        nacl_observed = [
            (31.7, 100.0),
            (45.5, 55.0),
        ]
        obs_path = "/tmp/test_observed_scores.json"
        self._create_observed_peaks(nacl_observed, obs_path)
        try:
            result = run_identify(obs_path, DATA_DIR)
            rankings = result["rankings"]
            for r in rankings:
                assert 0.0 <= r["score"] <= 1.0, (
                    f"Score {r['score']} out of [0,1] range"
                )
                assert "file" in r
            for i in range(1, len(rankings)):
                assert rankings[i]["score"] <= rankings[i-1]["score"], (
                    "Rankings not sorted by score descending"
                )
        finally:
            os.unlink(obs_path)


# ===== Fetch Tests (COD REST API) =====

class TestFetch:
    def test_fetch_known_entry(self):
        """Fetch a known COD entry and verify output is CIF."""
        import urllib.request
        import urllib.error

        # Use COD search to find a valid NaCl entry
        search_url = "https://www.crystallography.net/cod/result?formula=Na%20Cl&format=lst"
        try:
            response = urllib.request.urlopen(search_url, timeout=30)
            entries = response.read().decode().strip().split('\n')
            cod_id = entries[0].strip()
            if not cod_id.isdigit():
                pytest.skip("COD search returned no valid entries")
        except Exception as e:
            pytest.skip(f"COD API unreachable: {e}")

        fetch_path = "/tmp/test_cod_fetch.cif"
        try:
            result = subprocess.run(
                ["python3", TOOL, "fetch", cod_id, "--output", fetch_path],
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0, (
                f"Fetch failed for COD {cod_id}: {result.stderr}"
            )
            assert os.path.isfile(fetch_path), "Fetched file not created"

            with open(fetch_path) as f:
                content = f.read()
            assert len(content) > 50, "Downloaded file too small"
            assert "data_" in content, "Downloaded file is not valid CIF"
        finally:
            if os.path.exists(fetch_path):
                os.unlink(fetch_path)


# ===== Cross-System Consistency =====

class TestCrossSystem:
    def test_all_cifs_simulate_successfully(self):
        """All bundled CIF files should simulate without error."""
        for name in ALL_CIF_FILES:
            path = os.path.join(DATA_DIR, name)
            data = run_simulate(path)
            assert len(data["peaks"]) > 0, f"No peaks produced for {name}"
            assert data["volume"] > 0, f"Invalid volume for {name}"
            assert data["num_atoms_unit_cell"] > 0, f"No atoms for {name}"

    def test_distinct_patterns(self):
        """Different compounds should produce distinct peak patterns."""
        patterns = {}
        for name in ALL_CIF_FILES:
            path = os.path.join(DATA_DIR, name)
            data = run_simulate(path)
            strongest = max(data["peaks"], key=lambda p: p["intensity"])
            patterns[name] = round(strongest["two_theta"], 1)
        # At least 3 different strongest-peak positions among 5 compounds
        unique_positions = len(set(patterns.values()))
        assert unique_positions >= 3, (
            f"Expected >= 3 distinct strongest-peak positions, got {unique_positions}: {patterns}"
        )
