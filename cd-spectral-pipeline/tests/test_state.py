"""Tests for the cdspec CD spectroscopy analysis pipeline."""

import json
import math
import os
import shutil
import subprocess

import pytest


def run_cdspec(*args):
    """Run the cdspec tool and return the subprocess result."""
    result = subprocess.run(
        ["/app/cdspec"] + list(args),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result


def read_csv_data(path):
    """Read a two-column CSV, skipping # comments and non-numeric headers."""
    col1 = []
    col2 = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    col1.append(float(parts[0]))
                    col2.append(float(parts[1]))
                except ValueError:
                    continue
    return col1, col2


class TestExecutable:
    """Verify the cdspec executable exists and is runnable."""

    def test_executable_exists(self):
        assert os.path.isfile("/app/cdspec"), "/app/cdspec does not exist"

    def test_executable_runs(self):
        r = subprocess.run(
            ["/app/cdspec", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert r.returncode >= 0


class TestConvert:
    """Test the unit conversion subcommand."""

    def test_mdeg_to_de(self):
        """Convert raw millidegrees spectrum to delta epsilon."""
        r = run_cdspec(
            "convert",
            "--input", "/app/data/raw_spectrum.csv",
            "--from-unit", "mdeg",
            "--to-unit", "de",
            "--conc", "1.0",
            "--mw", "40000",
            "--nres", "370",
            "--path", "0.1",
        )
        assert r.returncode == 0, f"cdspec convert failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert "wavelengths" in data
        assert "values" in data
        assert len(data["wavelengths"]) == 71
        assert len(data["values"]) == 71

        # Independently compute expected values
        wls_raw, mdeg_raw = read_csv_data("/app/data/raw_spectrum.csv")
        mrw = 40000.0 / 370.0
        for i in range(len(wls_raw)):
            expected_de = mdeg_raw[i] * mrw / (32980.0 * 1.0 * 0.1)
            assert abs(data["values"][i] - round(expected_de, 4)) < 0.01, (
                f"Mismatch at wavelength {wls_raw[i]}: "
                f"got {data['values'][i]}, expected {round(expected_de, 4)}"
            )

    def test_de_to_mre(self):
        """Convert delta epsilon to mean residue ellipticity."""
        r = run_cdspec(
            "convert",
            "--input", "/app/data/protein_A.csv",
            "--from-unit", "de",
            "--to-unit", "mre",
            "--conc", "1.0",
            "--mw", "40000",
            "--nres", "370",
            "--path", "0.1",
        )
        assert r.returncode == 0, f"cdspec convert failed: {r.stderr}"
        data = json.loads(r.stdout)

        wls_de, vals_de = read_csv_data("/app/data/protein_A.csv")
        for i in range(len(wls_de)):
            expected_mre = vals_de[i] * 3298.0
            assert abs(data["values"][i] - round(expected_mre, 4)) < 1.0, (
                f"MRE mismatch at {wls_de[i]}nm: "
                f"got {data['values'][i]}, expected ~{round(expected_mre, 4)}"
            )

    def test_mre_to_mdeg_roundtrip(self):
        """Round-trip conversion de -> mre -> mdeg -> de preserves values."""
        # de -> mre
        r1 = run_cdspec(
            "convert",
            "--input", "/app/data/protein_A.csv",
            "--from-unit", "de",
            "--to-unit", "mre",
            "--conc", "1.0",
            "--mw", "40000",
            "--nres", "370",
            "--path", "0.1",
        )
        assert r1.returncode == 0
        mre_data = json.loads(r1.stdout)

        # Write MRE to temp file
        tmp_path = "/app/data/_tmp_mre.csv"
        with open(tmp_path, "w") as f:
            f.write("wavelength,mre\n")
            for w, v in zip(mre_data["wavelengths"], mre_data["values"]):
                f.write(f"{w},{v}\n")

        # mre -> mdeg
        r2 = run_cdspec(
            "convert",
            "--input", tmp_path,
            "--from-unit", "mre",
            "--to-unit", "mdeg",
            "--conc", "1.0",
            "--mw", "40000",
            "--nres", "370",
            "--path", "0.1",
        )
        assert r2.returncode == 0, f"mre->mdeg failed: {r2.stderr}"
        mdeg_data = json.loads(r2.stdout)

        # Write mdeg to temp file
        tmp_path2 = "/app/data/_tmp_mdeg.csv"
        with open(tmp_path2, "w") as f:
            f.write("wavelength,mdeg\n")
            for w, v in zip(mdeg_data["wavelengths"], mdeg_data["values"]):
                f.write(f"{w},{v}\n")

        # mdeg -> de
        r3 = run_cdspec(
            "convert",
            "--input", tmp_path2,
            "--from-unit", "mdeg",
            "--to-unit", "de",
            "--conc", "1.0",
            "--mw", "40000",
            "--nres", "370",
            "--path", "0.1",
        )
        assert r3.returncode == 0
        roundtrip_data = json.loads(r3.stdout)

        # Compare with original de values
        wls_orig, vals_orig = read_csv_data("/app/data/protein_A.csv")
        for i in range(len(wls_orig)):
            assert abs(roundtrip_data["values"][i] - vals_orig[i]) < 0.05, (
                f"Round-trip error at {wls_orig[i]}nm: "
                f"got {roundtrip_data['values'][i]}, original {vals_orig[i]}"
            )

        for p in [tmp_path, tmp_path2]:
            if os.path.exists(p):
                os.remove(p)


class TestDeconvolve:
    """Test the secondary structure deconvolution subcommand."""

    def test_protein_A_fractions(self):
        """Recover known composition of protein A (aldolase-like)."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_A.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0, f"deconvolve failed: {r.stderr}"
        data = json.loads(r.stdout)
        fracs = data["fractions"]

        # Ground truth: helix=0.425, strand=0.138, turn=0.103, coil=0.334
        assert abs(fracs["helix"] - 0.425) < 0.05, f"helix {fracs['helix']} far from 0.425"
        assert abs(fracs["strand"] - 0.138) < 0.05, f"strand {fracs['strand']} far from 0.138"
        assert abs(fracs["turn"] - 0.103) < 0.05, f"turn {fracs['turn']} far from 0.103"
        assert abs(fracs["coil"] - 0.334) < 0.05, f"coil {fracs['coil']} far from 0.334"

    def test_protein_B_fractions(self):
        """Recover known composition of protein B (beta-rich)."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_B.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0, f"deconvolve failed: {r.stderr}"
        data = json.loads(r.stdout)
        fracs = data["fractions"]

        # Ground truth: helix=0.10, strand=0.50, turn=0.15, coil=0.25
        assert abs(fracs["helix"] - 0.10) < 0.05
        assert abs(fracs["strand"] - 0.50) < 0.05
        assert abs(fracs["turn"] - 0.15) < 0.05
        assert abs(fracs["coil"] - 0.25) < 0.05

    def test_protein_C_fractions(self):
        """Recover near-boundary composition (near-zero helix fraction)."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_C.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0, f"deconvolve failed: {r.stderr}"
        data = json.loads(r.stdout)
        fracs = data["fractions"]

        # Ground truth: helix=0.02, strand=0.15, turn=0.30, coil=0.53
        assert abs(fracs["helix"] - 0.02) < 0.07, f"helix {fracs['helix']} far from 0.02"
        assert abs(fracs["strand"] - 0.15) < 0.07, f"strand {fracs['strand']} far from 0.15"
        assert abs(fracs["turn"] - 0.30) < 0.07, f"turn {fracs['turn']} far from 0.30"
        assert abs(fracs["coil"] - 0.53) < 0.07, f"coil {fracs['coil']} far from 0.53"

    def test_fractions_sum_to_one(self):
        """Fractions must sum to 1.0."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_A.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        total = sum(data["fractions"].values())
        assert abs(total - 1.0) < 0.005, f"Fractions sum to {total}, expected 1.0"

    def test_nonnegative_fractions(self):
        """All fractions must be non-negative across all test proteins."""
        for spec_file in ["/app/data/protein_A.csv", "/app/data/protein_B.csv",
                          "/app/data/protein_C.csv"]:
            r = run_cdspec(
                "deconvolve",
                "--spectrum", spec_file,
                "--basis", "/app/data/basis_spectra.csv",
            )
            assert r.returncode == 0
            data = json.loads(r.stdout)
            for name, val in data["fractions"].items():
                assert val >= -0.001, (
                    f"Fraction '{name}' is negative ({val}) for {spec_file}"
                )

    def test_nrmsd_quality(self):
        """NRMSD should be low for well-matched spectra."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_A.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["nrmsd"] < 0.1, f"NRMSD {data['nrmsd']} too high"

    def test_reconstructed_spectrum_length(self):
        """Reconstructed spectrum should have correct length."""
        r = run_cdspec(
            "deconvolve",
            "--spectrum", "/app/data/protein_A.csv",
            "--basis", "/app/data/basis_spectra.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert len(data["reconstructed"]) == 71


class TestThermomelt:
    """Test the thermal melt fitting subcommand."""

    def test_tm_extraction(self):
        """Extract melting temperature within tolerance."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_single.csv",
        )
        assert r.returncode == 0, f"thermomelt failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert abs(data["tm_K"] - 340.0) < 1.5, (
            f"Tm = {data['tm_K']}K, expected ~340.0K"
        )

    def test_dh_extraction(self):
        """Extract van't Hoff enthalpy within tolerance."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_single.csv",
        )
        assert r.returncode == 0, f"thermomelt failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert abs(data["dh_kj_mol"] - 250.0) < 25.0, (
            f"dH = {data['dh_kj_mol']} kJ/mol, expected ~250.0"
        )

    def test_fraction_folded_boundaries(self):
        """Fraction folded should be ~1.0 at low T and ~0.0 at high T."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_single.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        ff = data["fraction_folded"]
        assert len(ff) > 0, "fraction_folded array is empty"
        assert ff[0] > 0.9, f"f_folded at low T = {ff[0]}, expected > 0.9"
        assert ff[-1] < 0.1, f"f_folded at high T = {ff[-1]}, expected < 0.1"

    def test_fraction_folded_monotonic(self):
        """Fraction folded should be monotonically decreasing."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_single.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        ff = data["fraction_folded"]
        for i in range(1, len(ff)):
            assert ff[i] <= ff[i - 1] + 0.01, (
                f"fraction_folded not monotonic at index {i}: {ff[i]} > {ff[i-1]}"
            )

    def test_steep_melt_tm(self):
        """Extract Tm from a steeper cooperative transition."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_steep.csv",
        )
        assert r.returncode == 0, f"thermomelt failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert abs(data["tm_K"] - 320.0) < 1.5, (
            f"Tm = {data['tm_K']}K, expected ~320.0K"
        )

    def test_steep_melt_dh(self):
        """Extract enthalpy from steeper transition."""
        r = run_cdspec(
            "thermomelt",
            "--input", "/app/data/melt_steep.csv",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert abs(data["dh_kj_mol"] - 350.0) < 30.0, (
            f"dH = {data['dh_kj_mol']} kJ/mol, expected ~350.0"
        )


class TestMatch:
    """Test the spectral similarity matching subcommand."""

    def test_ranking_count(self):
        """Should rank all 8 library spectra."""
        r = run_cdspec(
            "match",
            "--query", "/app/data/protein_A.csv",
            "--library", "/app/data/library",
        )
        assert r.returncode == 0, f"match failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert len(data["rankings"]) == 8

    def test_ranking_sorted(self):
        """Rankings should be sorted ascending by NRMSD."""
        r = run_cdspec(
            "match",
            "--query", "/app/data/protein_A.csv",
            "--library", "/app/data/library",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        nrmsds = [entry["nrmsd"] for entry in data["rankings"]]
        for i in range(len(nrmsds) - 1):
            assert nrmsds[i] <= nrmsds[i + 1] + 1e-6, (
                f"Not sorted: {nrmsds[i]} > {nrmsds[i+1]}"
            )

    def test_nrmsd_nonnegative(self):
        """All NRMSD values should be non-negative."""
        r = run_cdspec(
            "match",
            "--query", "/app/data/protein_A.csv",
            "--library", "/app/data/library",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        for entry in data["rankings"]:
            assert entry["nrmsd"] >= 0, f"Negative NRMSD: {entry}"

    def test_dissimilar_spectra_ranked_last(self):
        """Very different compositions should have high NRMSD (ranked last)."""
        r = run_cdspec(
            "match",
            "--query", "/app/data/protein_A.csv",
            "--library", "/app/data/library",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        bottom_3 = {entry["file"] for entry in data["rankings"][-3:]}
        dissimilar = {"ref_mostly_strand.csv", "ref_mostly_coil.csv", "ref_mostly_turn.csv"}
        overlap = bottom_3 & dissimilar
        assert len(overlap) >= 2, (
            f"Expected at least 2 of {dissimilar} in bottom 3, "
            f"but bottom 3 are {bottom_3}"
        )

    def test_self_match_zero_nrmsd(self):
        """A spectrum matched against a copy of itself should have NRMSD ~ 0."""
        src = "/app/data/protein_A.csv"
        dst = "/app/data/library/_self_copy.csv"
        shutil.copy(src, dst)
        try:
            r = run_cdspec(
                "match",
                "--query", src,
                "--library", "/app/data/library",
            )
            assert r.returncode == 0, f"match failed: {r.stderr}"
            data = json.loads(r.stdout)
            self_entry = None
            for entry in data["rankings"]:
                if entry["file"] == "_self_copy.csv":
                    self_entry = entry
                    break
            assert self_entry is not None, "_self_copy.csv not found in rankings"
            assert self_entry["nrmsd"] < 0.001, (
                f"Self-match NRMSD = {self_entry['nrmsd']}, expected ~0"
            )
            assert data["rankings"][0]["file"] == "_self_copy.csv", (
                f"Self-copy not ranked first, top is {data['rankings'][0]}"
            )
        finally:
            if os.path.exists(dst):
                os.remove(dst)

    def test_ranking_has_filenames(self):
        """Each ranking entry should have a 'file' and 'nrmsd' field."""
        r = run_cdspec(
            "match",
            "--query", "/app/data/protein_A.csv",
            "--library", "/app/data/library",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        for entry in data["rankings"]:
            assert "file" in entry, f"Missing 'file' key in {entry}"
            assert "nrmsd" in entry, f"Missing 'nrmsd' key in {entry}"
            assert isinstance(entry["file"], str)
            assert isinstance(entry["nrmsd"], (int, float))


class TestValidate:
    """Test the CD data quality validation subcommand."""

    def test_good_data_passes_all(self):
        """Good quality data should pass all checks."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_good.json",
        )
        assert r.returncode == 0, f"validate failed: {r.stderr}"
        data = json.loads(r.stdout)
        assert data["passed"] is True, f"Expected overall pass but got: {data}"
        assert data["checks"]["ht_voltage"]["passed"] is True
        assert data["checks"]["wavelength_range"]["passed"] is True
        assert data["checks"]["baseline_flatness"]["passed"] is True
        assert data["checks"]["csa_calibration"]["passed"] is True

    def test_bad_ht_voltage_fails(self):
        """HT voltage exceeding benchtop threshold should fail."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_bad.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["passed"] is False
        assert data["checks"]["ht_voltage"]["passed"] is False
        assert data["checks"]["ht_voltage"]["value"] == 650.0
        assert data["checks"]["ht_voltage"]["threshold"] == 600.0

    def test_short_wavelength_range_fails(self):
        """Spectrum not extending to 200nm should fail wavelength check."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_short.csv",
            "--metadata", "/app/data/validation/meta_short.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["passed"] is False
        assert data["checks"]["wavelength_range"]["passed"] is False
        assert data["checks"]["wavelength_range"]["value"] == 205.0

    def test_bad_baseline_fails(self):
        """Non-zero baseline at long wavelengths should fail."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_bad_baseline.csv",
            "--metadata", "/app/data/validation/meta_baseline.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["passed"] is False
        assert data["checks"]["baseline_flatness"]["passed"] is False
        assert data["checks"]["baseline_flatness"]["value"] > 2.0

    def test_missing_csa_passes_by_default(self):
        """Missing CSA ratio in metadata should pass csa_calibration check."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_short.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["checks"]["csa_calibration"]["passed"] is True

    def test_synchrotron_higher_threshold(self):
        """Synchrotron instruments allow HT up to 700V."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_synchrotron.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["checks"]["ht_voltage"]["passed"] is True
        assert data["checks"]["ht_voltage"]["threshold"] == 700.0

    def test_bad_csa_ratio_fails(self):
        """CSA ratio outside [1.95, 2.05] should fail."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_bad.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["checks"]["csa_calibration"]["passed"] is False

    def test_all_check_names_present(self):
        """Output should include exactly four validation checks."""
        r = run_cdspec(
            "validate",
            "--input", "/app/data/validation/spectrum_good.csv",
            "--metadata", "/app/data/validation/meta_good.json",
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)
        expected_checks = {"ht_voltage", "wavelength_range", "baseline_flatness", "csa_calibration"}
        assert set(data["checks"].keys()) == expected_checks, (
            f"Expected checks {expected_checks}, got {set(data['checks'].keys())}"
        )
