"""Tests for RRUFF mineral identification tool and pipeline."""

import subprocess
import json
import os
import sqlite3
import pytest


TOOL = "/app/mineral_id.py"


def run_tool(*args, timeout=60):
    result = subprocess.run(
        ["python3", TOOL] + list(args),
        capture_output=True, text=True, timeout=timeout
    )
    return result


# ---------------------------------------------------------------------------
# Parse RRUFF files
# ---------------------------------------------------------------------------

class TestParseRRUFF:
    def test_parse_full_headers(self, tmp_path):
        content = (
            "##NAMES=Quartz\n"
            "##RRUFFID=R040031\n"
            "##IDEAL CHEMISTRY=SiO_2_\n"
            "##LOCALITY=Spruce Claim, King County, Washington, USA\n"
            "##OWNER=RRUFF\n"
            "##SOURCE=Bob Downs\n"
            "##DESCRIPTION=Colorless hexagonal prism\n"
            "##STATUS=The identification of this mineral has been confirmed\n"
            "##URL=https://www.rruff.net/odr/rruff_sample/R040031\n"
            "##CELL PARAMETERS=a: 4.9134 b: 4.9134 c: 5.4042 alpha: 90 "
            "beta: 90 gamma: 120 volume: 112.991 crystal system: hexagonal\n"
            "##FILETYPE=Raman Processed\n"
            "##RAMAN WAVELENGTH=532\n"
            "\n"
            "128.0049, 9347.007\n"
            "206.0000, 5000.000\n"
            "265.0000, 3000.000\n"
            "355.0000, 2000.000\n"
            "464.0000, 20000.00\n"
        )
        fp = tmp_path / "quartz_processed.txt"
        fp.write_text(content)
        r = run_tool("parse", str(fp))
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        d = json.loads(r.stdout)
        assert d["names"] == "Quartz"
        assert d["rruff_id"] == "R040031"
        assert d["ideal_chemistry"] == "SiO_2_"
        assert d["locality"] == "Spruce Claim, King County, Washington, USA"
        assert d["filetype"] == "Raman Processed"
        assert d["cell_parameters"] is not None
        assert d["cell_parameters"]["a"] == pytest.approx(4.9134, abs=0.001)
        assert d["cell_parameters"]["b"] == pytest.approx(4.9134, abs=0.001)
        assert d["cell_parameters"]["c"] == pytest.approx(5.4042, abs=0.001)
        assert d["cell_parameters"]["alpha"] == pytest.approx(90.0, abs=0.1)
        assert d["cell_parameters"]["gamma"] == pytest.approx(120.0, abs=0.1)
        assert d["cell_parameters"]["volume"] == pytest.approx(112.991, abs=0.01)
        assert d["cell_parameters"]["crystal_system"] == "hexagonal"
        assert d["wavelength"] == 532
        assert d["data_points"] == 5
        assert d["wavenumber_range"][0] == pytest.approx(128.0049, abs=0.01)
        assert d["wavenumber_range"][1] == pytest.approx(464.0, abs=0.01)

    def test_parse_missing_optional_headers(self, tmp_path):
        content = (
            "##NAMES=UnknownMineral\n"
            "##RRUFFID=R888888\n"
            "##IDEAL CHEMISTRY=FeS_2_\n"
            "##FILETYPE=Raman Processed\n"
            "\n"
            "200.0, 1.0\n"
            "400.0, 0.5\n"
        )
        fp = tmp_path / "unknown.txt"
        fp.write_text(content)
        r = run_tool("parse", str(fp))
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        d = json.loads(r.stdout)
        assert d["names"] == "UnknownMineral"
        assert d["rruff_id"] == "R888888"
        assert d["cell_parameters"] is None
        assert d["wavelength"] is None
        assert d["data_points"] == 2

    def test_parse_scientific_notation(self, tmp_path):
        content = (
            "##NAMES=Actinolite\n"
            "##RRUFFID=R040063\n"
            "##IDEAL CHEMISTRY=Ca_2_(Mg,Fe)_5_Si_8_O_22_(OH)_2_\n"
            "##FILETYPE=Infrared RAW\n"
            "\n"
            "3.991926e+002, 0.000000e+000\n"
            "4.011211e+002, 3.742658e-001\n"
            "4.030496e+002, 3.760734e-001\n"
        )
        fp = tmp_path / "ir_data.txt"
        fp.write_text(content)
        r = run_tool("parse", str(fp))
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        d = json.loads(r.stdout)
        assert d["names"] == "Actinolite"
        assert d["data_points"] == 3
        assert d["wavenumber_range"][0] == pytest.approx(399.1926, abs=0.01)
        assert d["wavenumber_range"][1] == pytest.approx(403.0496, abs=0.01)

    def test_parse_end_marker(self, tmp_path):
        """RRUFF files may end with ##END= marker — data after it is excluded."""
        content = (
            "##NAMES=Pyrite\n"
            "##RRUFFID=R050190\n"
            "##IDEAL CHEMISTRY=FeS_2_\n"
            "##FILETYPE=Raman Processed\n"
            "##RAMAN WAVELENGTH=532\n"
            "\n"
            "100.0, 50.0\n"
            "200.0, 100.0\n"
            "300.0, 75.0\n"
            "##END=\n"
        )
        fp = tmp_path / "pyrite.txt"
        fp.write_text(content)
        r = run_tool("parse", str(fp))
        assert r.returncode == 0, f"parse failed: {r.stderr}"
        d = json.loads(r.stdout)
        assert d["data_points"] == 3
        assert d["wavelength"] == 532


# ---------------------------------------------------------------------------
# Crystal system classification
# ---------------------------------------------------------------------------

class TestCrystalSystem:
    @pytest.mark.parametrize("params,expected", [
        # NaCl: cubic (a=b=c, all 90)
        ((5.6402, 5.6402, 5.6402, 90, 90, 90), "cubic"),
        # Quartz: hexagonal (a=b, gamma=120)
        ((4.9134, 4.9134, 5.4042, 90, 90, 120), "hexagonal"),
        # Rutile TiO2: tetragonal (a=b!=c, all 90)
        ((4.594, 4.594, 2.959, 90, 90, 90), "tetragonal"),
        # Aragonite: orthorhombic (a!=b!=c, all 90)
        ((5.741, 9.951, 4.692, 90, 90, 90), "orthorhombic"),
        # Actinolite: monoclinic (beta!=90)
        ((9.839, 18.074, 5.283, 90, 104.71, 90), "monoclinic"),
        # Albite: triclinic (no 90-degree angles)
        ((8.560, 12.964, 7.209, 93.45, 116.10, 87.68), "triclinic"),
    ])
    def test_classify(self, params, expected):
        args = [str(p) for p in params]
        r = run_tool("classify-crystal", *args)
        assert r.returncode == 0, f"classify-crystal failed: {r.stderr}"
        d = json.loads(r.stdout)
        assert d["crystal_system"] == expected, \
            f"For params {params}: expected {expected}, got {d['crystal_system']}"


class TestCrystalSystemTolerance:
    def test_near_cubic_within_tolerance(self):
        """Very small deviation should still be cubic."""
        r = run_tool("classify-crystal", "5.640", "5.640", "5.645", "90", "90", "90")
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["crystal_system"] == "cubic"

    def test_clearly_not_cubic(self):
        """Large c deviation from a=b, all 90 -> tetragonal."""
        r = run_tool("classify-crystal", "5.640", "5.640", "5.800", "90", "90", "90")
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["crystal_system"] == "tetragonal"

    def test_monoclinic_beta_only(self):
        """Only beta deviates significantly from 90."""
        r = run_tool("classify-crystal", "8.0", "6.0", "10.0", "90", "95.0", "90")
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["crystal_system"] == "monoclinic"

    def test_trigonal_as_hexagonal(self):
        """Trigonal minerals use hexagonal cell setting (a=b, gamma=120)."""
        r = run_tool("classify-crystal", "5.029", "5.029", "13.749", "90", "90", "120")
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["crystal_system"] == "hexagonal"


# ---------------------------------------------------------------------------
# Chemical formula parsing
# ---------------------------------------------------------------------------

class TestFormulaParser:
    @pytest.mark.parametrize("formula,expected_elements,expected_mw", [
        ("SiO_2_", {"Si": 1.0, "O": 2.0}, 60.084),
        ("CaCO_3_", {"Ca": 1.0, "C": 1.0, "O": 3.0}, 100.086),
        ("Fe_2_O_3_", {"Fe": 2.0, "O": 3.0}, 159.687),
        ("NaAlSi_3_O_8_", {"Na": 1.0, "Al": 1.0, "Si": 3.0, "O": 8.0}, 262.222),
        ("Ca(OH)_2_", {"Ca": 1.0, "O": 2.0, "H": 2.0}, 74.092),
        ("Pb_2_SnInBiS_7_",
         {"Pb": 2.0, "Sn": 1.0, "In": 1.0, "Bi": 1.0, "S": 7.0}, 1081.328),
        # Charge notation stripped
        ("Cu^2+^SO_4_", {"Cu": 1.0, "S": 1.0, "O": 4.0}, 159.602),
        # Range subscript: use first value
        ("Mg_1.5-0.5_Fe_0.5-1.5_SiO_4_",
         {"Mg": 1.5, "Fe": 0.5, "Si": 1.0, "O": 4.0}, 156.462),
        # [box] prefix, ranges, nested parentheses
        ("[box]Ca_2_(Mg_4.5-2.5_Fe_0.5-2.5_)Si_8_O_22_(OH)_2_",
         {"Ca": 2.0, "Mg": 4.5, "Fe": 0.5, "Si": 8.0, "O": 24.0, "H": 2.0},
         828.131),
    ])
    def test_formula(self, formula, expected_elements, expected_mw):
        r = run_tool("parse-formula", formula)
        assert r.returncode == 0, f"parse-formula failed for '{formula}': {r.stderr}"
        d = json.loads(r.stdout)
        for elem, count in expected_elements.items():
            assert elem in d["elements"], \
                f"Missing element {elem} in result for '{formula}'"
            assert d["elements"][elem] == pytest.approx(count, abs=0.01), \
                f"{elem}: expected {count}, got {d['elements'][elem]} for '{formula}'"
        assert d["molecular_weight"] == pytest.approx(expected_mw, abs=0.5), \
            f"MW: expected {expected_mw}, got {d['molecular_weight']} for '{formula}'"

    def test_solid_solution_first_element(self):
        """(Mg,Fe) solid solution: use only first element."""
        r = run_tool("parse-formula", "(Mg,Fe)SiO_3_")
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert "Mg" in d["elements"]
        assert d["elements"]["Mg"] == pytest.approx(1.0, abs=0.01)
        assert "Fe" not in d["elements"]


# ---------------------------------------------------------------------------
# Spectral library building and identification (SQLite-backed)
# ---------------------------------------------------------------------------

class TestSpectralMatching:
    @pytest.fixture
    def spectral_data(self, tmp_path):
        """Create synthetic Raman spectra for three distinct minerals."""
        import numpy as np

        wn = np.arange(100.0, 1200.0, 1.0)

        def gauss(x, c, w, h):
            return h * np.exp(-0.5 * ((x - c) / w) ** 2)

        minerals = {
            "QuartzSynth": {
                "id": "R999001",
                "chem": "SiO_2_",
                "peaks": [(128, 8, 0.5), (206, 8, 0.3), (265, 8, 0.2),
                          (464, 8, 1.0)],
            },
            "CalciteSynth": {
                "id": "R999002",
                "chem": "CaCO_3_",
                "peaks": [(155, 8, 0.3), (282, 8, 1.0), (712, 8, 0.5),
                          (1086, 8, 0.8)],
            },
            "FluoriteSynth": {
                "id": "R999003",
                "chem": "CaF_2_",
                "peaks": [(322, 8, 1.0)],
            },
        }

        lib_dir = tmp_path / "library"
        lib_dir.mkdir()

        for name, info in minerals.items():
            y = np.zeros_like(wn)
            for c, w, h in info["peaks"]:
                y += gauss(wn, c, w, h)

            lines = [
                f"##NAMES={name}",
                f"##RRUFFID={info['id']}",
                f"##IDEAL CHEMISTRY={info['chem']}",
                "##CELL PARAMETERS=a: 4.9134 b: 4.9134 c: 5.4042 alpha: 90 "
                "beta: 90 gamma: 120 volume: 112.991 crystal system: hexagonal",
                "##FILETYPE=Raman Processed",
                "##RAMAN WAVELENGTH=532",
                "",
            ]
            for x_val, y_val in zip(wn, y):
                lines.append(f"{x_val:.4f}, {y_val:.8f}")
            (lib_dir / f"{name}_processed.txt").write_text(
                "\n".join(lines) + "\n")

        # Query: QuartzSynth with linear baseline + noise -> RAW
        qy = np.zeros_like(wn)
        for c, w, h in minerals["QuartzSynth"]["peaks"]:
            qy += gauss(wn, c, w, h)
        qy += 0.001 * wn
        rng = np.random.RandomState(42)
        qy += rng.normal(0, 0.02, len(wn))

        q_lines = [
            "##NAMES=Unknown",
            "##RRUFFID=R999999",
            "##FILETYPE=Raman RAW",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x_val, y_val in zip(wn, qy):
            q_lines.append(f"{x_val:.4f}, {y_val:.8f}")
        qf = tmp_path / "query_raw.txt"
        qf.write_text("\n".join(q_lines) + "\n")

        return lib_dir, qf

    def test_build_library_sqlite(self, spectral_data, tmp_path):
        """build-library must produce a valid SQLite database."""
        lib_dir, _ = spectral_data
        lib_file = tmp_path / "library.db"

        r = run_tool("build-library", str(lib_dir), str(lib_file))
        assert r.returncode == 0, f"build-library failed: {r.stderr}"

        # Verify it is a valid SQLite database
        conn = sqlite3.connect(str(lib_file))
        cursor = conn.cursor()

        # Check 'spectra' table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='spectra'")
        assert cursor.fetchone() is not None, "Table 'spectra' not found in database"

        # Check required column names
        cursor.execute("PRAGMA table_info(spectra)")
        col_info = cursor.fetchall()
        col_names = {row[1] for row in col_info}
        for required in ("name", "rruff_id", "wavelength", "wavenumbers", "intensities"):
            assert required in col_names, \
                f"Missing required column '{required}' in spectra table"

        # Check correct number of entries
        cursor.execute("SELECT COUNT(*) FROM spectra")
        count = cursor.fetchone()[0]
        assert count == 3, f"Expected 3 library entries, got {count}"

        # Verify data integrity
        cursor.execute("SELECT name, wavelength, wavenumbers, intensities FROM spectra")
        names = set()
        for row in cursor.fetchall():
            name, wl, wns_json, ints_json = row
            names.add(name)
            wns = json.loads(wns_json)
            ints = json.loads(ints_json)
            assert isinstance(wns, list), "wavenumbers must be a JSON array"
            assert isinstance(ints, list), "intensities must be a JSON array"
            assert len(wns) == len(ints)
            assert len(wns) > 100
            assert max(ints) <= 1.0001, \
                f"Intensities not normalized for {name}"
            assert wl == 532

        assert names == {"QuartzSynth", "CalciteSynth", "FluoriteSynth"}
        conn.close()

    def test_build_library_from_zip(self, spectral_data, tmp_path):
        """build-library must accept a .zip archive as source."""
        import zipfile

        lib_dir, _ = spectral_data
        zip_path = tmp_path / "spectra.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for fp in sorted(lib_dir.glob("*.txt")):
                zf.write(fp, fp.name)

        lib_file = tmp_path / "library_from_zip.db"
        r = run_tool("build-library", str(zip_path), str(lib_file))
        assert r.returncode == 0, f"build-library from zip failed: {r.stderr}"

        conn = sqlite3.connect(str(lib_file))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM spectra")
        count = cursor.fetchone()[0]
        assert count == 3, f"Expected 3 entries from zip, got {count}"

        cursor.execute("SELECT name, intensities FROM spectra")
        for row in cursor.fetchall():
            ints = json.loads(row[1])
            assert max(ints) <= 1.0001
        conn.close()

    def test_sqlite3_cli_queryable(self, spectral_data, tmp_path):
        """The library database must be queryable via the sqlite3 CLI."""
        lib_dir, _ = spectral_data
        lib_file = tmp_path / "library.db"

        r = run_tool("build-library", str(lib_dir), str(lib_file))
        assert r.returncode == 0, f"build-library failed: {r.stderr}"

        # Query using sqlite3 command-line tool
        result = subprocess.run(
            ["sqlite3", str(lib_file),
             "SELECT name, wavelength FROM spectra ORDER BY name;"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, \
            f"sqlite3 CLI query failed: {result.stderr}"

        output = result.stdout.strip()
        lines = output.split('\n')
        assert len(lines) == 3, \
            f"Expected 3 rows from sqlite3 CLI, got {len(lines)}"
        assert "CalciteSynth" in output
        assert "FluoriteSynth" in output
        assert "QuartzSynth" in output

        # Verify a filtered query works
        result2 = subprocess.run(
            ["sqlite3", str(lib_file),
             "SELECT COUNT(*) FROM spectra WHERE wavelength = 532;"],
            capture_output=True, text=True, timeout=10
        )
        assert result2.returncode == 0
        assert result2.stdout.strip() == "3"

    def test_identify_correct_mineral(self, spectral_data, tmp_path):
        lib_dir, query_file = spectral_data
        lib_file = tmp_path / "library.db"

        r1 = run_tool("build-library", str(lib_dir), str(lib_file))
        assert r1.returncode == 0, f"build-library failed: {r1.stderr}"

        r = run_tool("identify", str(query_file),
                      "--library", str(lib_file), "--top", "3")
        assert r.returncode == 0, f"identify failed: {r.stderr}"

        matches = json.loads(r.stdout)
        assert len(matches) == 3, f"Expected 3 matches, got {len(matches)}"

        assert matches[0]["name"] == "QuartzSynth", \
            f"Expected QuartzSynth as top match, got {matches[0]['name']}"
        assert matches[0]["score"] > 0.8, \
            f"Expected score > 0.8, got {matches[0]['score']}"

        scores = [m["score"] for m in matches]
        assert scores == sorted(scores, reverse=True), \
            f"Results not sorted descending: {scores}"

    def test_identify_processed_self_match(self, tmp_path):
        """A Processed query matched against itself should score >= 0.99."""
        import numpy as np

        wn = np.arange(150.0, 900.0, 1.0)

        def gauss(x, c, w, h):
            return h * np.exp(-0.5 * ((x - c) / w) ** 2)

        y = gauss(wn, 400, 10, 1.0) + gauss(wn, 600, 10, 0.6)

        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()

        lines = [
            "##NAMES=TestMineral",
            "##RRUFFID=R777777",
            "##FILETYPE=Raman Processed",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x_val, y_val in zip(wn, y):
            lines.append(f"{x_val:.4f}, {y_val:.8f}")
        content = "\n".join(lines) + "\n"

        (lib_dir / "test_processed.txt").write_text(content)

        qf = tmp_path / "query_processed.txt"
        qf.write_text(content)

        lib_file = tmp_path / "lib.db"
        run_tool("build-library", str(lib_dir), str(lib_file))

        r = run_tool("identify", str(qf),
                      "--library", str(lib_file), "--top", "1")
        assert r.returncode == 0, r.stderr

        matches = json.loads(r.stdout)
        assert len(matches) >= 1
        assert matches[0]["name"] == "TestMineral"
        assert matches[0]["score"] > 0.99, \
            f"Self-match score should be >= 0.99, got {matches[0]['score']}"

    def test_identify_wavelength_filter(self, tmp_path):
        """Library entries with mismatched wavelength must be excluded."""
        import numpy as np

        wn = np.arange(150.0, 800.0, 1.0)

        def gauss(x, c, w, h):
            return h * np.exp(-0.5 * ((x - c) / w) ** 2)

        y = gauss(wn, 400, 10, 1.0)

        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()

        # Library entry at 780nm
        lines780 = [
            "##NAMES=Mineral780",
            "##RRUFFID=R666001",
            "##FILETYPE=Raman Processed",
            "##RAMAN WAVELENGTH=780",
            "",
        ]
        for x_val, y_val in zip(wn, y):
            lines780.append(f"{x_val:.4f}, {y_val:.8f}")
        (lib_dir / "m780.txt").write_text("\n".join(lines780) + "\n")

        # Library entry at 532nm (different peak)
        y2 = gauss(wn, 500, 10, 1.0)
        lines532 = [
            "##NAMES=Mineral532",
            "##RRUFFID=R666002",
            "##FILETYPE=Raman Processed",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x_val, y_val in zip(wn, y2):
            lines532.append(f"{x_val:.4f}, {y_val:.8f}")
        (lib_dir / "m532.txt").write_text("\n".join(lines532) + "\n")

        lib_file = tmp_path / "lib.db"
        run_tool("build-library", str(lib_dir), str(lib_file))

        # Query at 532nm - should only match Mineral532
        qlines = [
            "##NAMES=QueryMin",
            "##RRUFFID=R666099",
            "##FILETYPE=Raman Processed",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x_val, y_val in zip(wn, y2):
            qlines.append(f"{x_val:.4f}, {y_val:.8f}")
        qf = tmp_path / "query532.txt"
        qf.write_text("\n".join(qlines) + "\n")

        r = run_tool("identify", str(qf),
                      "--library", str(lib_file), "--top", "5")
        assert r.returncode == 0, r.stderr
        matches = json.loads(r.stdout)

        # Only 532nm entries should appear
        for m in matches:
            assert m["rruff_id"] != "R666001", \
                "780nm entry should be excluded from 532nm query"


# ---------------------------------------------------------------------------
# Cosmic ray spike detection
# ---------------------------------------------------------------------------

class TestSpikeDetection:
    def test_detect_known_spikes(self, tmp_path):
        """Detect artificial cosmic ray spikes injected into a smooth spectrum."""
        import numpy as np

        wn = np.arange(200.0, 1200.0, 1.0)
        # Smooth spectrum: Gaussian peak plus baseline
        y = (500.0 * np.exp(-0.5 * ((wn - 500) / 20) ** 2)
             + 100.0
             + 0.01 * wn)

        # Inject 3 cosmic ray spikes at known positions
        spike_indices = [150, 400, 750]
        for idx in spike_indices:
            y[idx] = y[idx] + 50000.0

        lines = [
            "##NAMES=TestSpiked",
            "##RRUFFID=R999888",
            "##FILETYPE=Raman RAW",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x, yi in zip(wn, y):
            lines.append(f"{x:.4f}, {yi:.6f}")

        fp = tmp_path / "spiked.txt"
        fp.write_text("\n".join(lines) + "\n")

        r = run_tool("detect-spikes", str(fp))
        assert r.returncode == 0, f"detect-spikes failed: {r.stderr}"
        d = json.loads(r.stdout)

        assert d["spike_count"] == 3, \
            f"Expected 3 spikes, found {d['spike_count']}"

        detected_indices = sorted([s["index"] for s in d["spikes"]])
        assert detected_indices == spike_indices, \
            f"Expected spike indices {spike_indices}, got {detected_indices}"

        for spike in d["spikes"]:
            assert spike["original_intensity"] > 40000, \
                "original_intensity should reflect the spike"
            assert spike["cleaned_intensity"] < spike["original_intensity"] / 10, \
                "cleaned_intensity should be much lower than spike"

    def test_no_spikes_clean_spectrum(self, tmp_path):
        """A clean spectrum should have zero spikes detected."""
        import numpy as np

        wn = np.arange(200.0, 800.0, 1.0)
        y = 300.0 * np.exp(-0.5 * ((wn - 500) / 30) ** 2) + 50.0

        lines = [
            "##NAMES=CleanMineral",
            "##RRUFFID=R999777",
            "##FILETYPE=Raman RAW",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x, yi in zip(wn, y):
            lines.append(f"{x:.4f}, {yi:.6f}")

        fp = tmp_path / "clean.txt"
        fp.write_text("\n".join(lines) + "\n")

        r = run_tool("detect-spikes", str(fp))
        assert r.returncode == 0, f"detect-spikes failed: {r.stderr}"
        d = json.loads(r.stdout)

        assert d["spike_count"] == 0, \
            f"Expected 0 spikes in clean data, found {d['spike_count']}"

    def test_spike_wavenumber_correct(self, tmp_path):
        """The wavenumber reported for each spike matches its position."""
        import numpy as np

        wn = np.arange(300.0, 700.0, 0.5)
        y = np.full_like(wn, 100.0)
        spike_idx = 200  # wavenumber = 300 + 200*0.5 = 400.0
        y[spike_idx] = 80000.0

        lines = [
            "##NAMES=WNTest",
            "##RRUFFID=R999666",
            "##FILETYPE=Raman RAW",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x, yi in zip(wn, y):
            lines.append(f"{x:.4f}, {yi:.6f}")

        fp = tmp_path / "wn_spike.txt"
        fp.write_text("\n".join(lines) + "\n")

        r = run_tool("detect-spikes", str(fp))
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)

        assert d["spike_count"] == 1
        assert d["spikes"][0]["wavenumber"] == pytest.approx(400.0, abs=0.5)
        assert d["spikes"][0]["index"] == spike_idx


# ---------------------------------------------------------------------------
# Pipeline (multi-tool: sqlite3 CLI + jq + mineral_id.py)
# ---------------------------------------------------------------------------

class TestPipeline:
    @pytest.fixture
    def pipeline_data(self, tmp_path):
        """Create synthetic library with multiple wavelengths and a query."""
        import numpy as np

        wn = np.arange(100.0, 1200.0, 1.0)

        def gauss(x, c, w, h):
            return h * np.exp(-0.5 * ((x - c) / w) ** 2)

        minerals = {
            "AlphaSynth": {"id": "R111001", "wl": 532,
                           "peaks": [(400, 10, 1.0), (600, 10, 0.5)]},
            "BetaSynth": {"id": "R111002", "wl": 532,
                          "peaks": [(700, 10, 1.0)]},
            "GammaSynth": {"id": "R111003", "wl": 780,
                           "peaks": [(400, 10, 1.0)]},
        }

        lib_dir = tmp_path / "pipeline_lib"
        lib_dir.mkdir()

        for name, info in minerals.items():
            y = np.zeros_like(wn)
            for c, w, h in info["peaks"]:
                y += gauss(wn, c, w, h)
            lines = [
                f"##NAMES={name}",
                f"##RRUFFID={info['id']}",
                "##FILETYPE=Raman Processed",
                f"##RAMAN WAVELENGTH={info['wl']}",
                "",
            ]
            for x_val, y_val in zip(wn, y):
                lines.append(f"{x_val:.4f}, {y_val:.8f}")
            (lib_dir / f"{name}_processed.txt").write_text(
                "\n".join(lines) + "\n")

        # Query at 532nm matching AlphaSynth
        qy = np.zeros_like(wn)
        for c, w, h in minerals["AlphaSynth"]["peaks"]:
            qy += gauss(wn, c, w, h)
        qlines = [
            "##NAMES=Query",
            "##RRUFFID=R999999",
            "##FILETYPE=Raman Processed",
            "##RAMAN WAVELENGTH=532",
            "",
        ]
        for x_val, y_val in zip(wn, qy):
            qlines.append(f"{x_val:.4f}, {y_val:.8f}")
        qf = tmp_path / "query_pipeline.txt"
        qf.write_text("\n".join(qlines) + "\n")

        return lib_dir, qf

    def test_pipeline_output_structure(self, pipeline_data, tmp_path):
        """pipeline.sh must produce correct JSON with library_stats and identification."""
        lib_dir, query_file = pipeline_data
        output_file = tmp_path / "result.json"

        r = subprocess.run(
            ["bash", "/app/pipeline.sh",
             str(lib_dir), str(query_file), str(output_file)],
            capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, f"pipeline.sh failed: {r.stderr}\n{r.stdout}"
        assert output_file.exists(), "Output file not created"

        d = json.loads(output_file.read_text())

        # Verify top-level structure
        assert "library_stats" in d, "Missing library_stats key"
        assert "identification" in d, "Missing identification key"

        stats = d["library_stats"]
        assert stats["total_spectra"] == 3, \
            f"Expected 3 total spectra, got {stats['total_spectra']}"
        assert sorted(stats["unique_minerals"]) == \
            ["AlphaSynth", "BetaSynth", "GammaSynth"]
        # Must be sorted alphabetically
        assert stats["unique_minerals"] == sorted(stats["unique_minerals"]), \
            "unique_minerals must be sorted alphabetically"

        wl = stats["wavelengths"]
        assert wl["532"] == 2, f"Expected 2 spectra at 532nm, got {wl.get('532')}"
        assert wl["780"] == 1, f"Expected 1 spectrum at 780nm, got {wl.get('780')}"

        matches = d["identification"]
        assert isinstance(matches, list)
        assert len(matches) >= 1
        assert matches[0]["name"] == "AlphaSynth", \
            f"Expected AlphaSynth as top match, got {matches[0]['name']}"
        assert matches[0]["score"] > 0.9

    def test_pipeline_uses_sqlite3_and_jq(self):
        """pipeline.sh must invoke sqlite3 CLI and jq as external commands."""
        assert os.path.exists("/app/pipeline.sh"), \
            "/app/pipeline.sh does not exist"
        script = open("/app/pipeline.sh").read()
        assert "sqlite3" in script, \
            "pipeline.sh must use the sqlite3 CLI tool"
        assert "jq" in script, \
            "pipeline.sh must use jq for JSON processing"

    def test_pipeline_from_zip(self, pipeline_data, tmp_path):
        """pipeline.sh must accept a .zip archive as source."""
        import zipfile

        lib_dir, query_file = pipeline_data
        zip_path = tmp_path / "pipeline_lib.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for fp in sorted(lib_dir.glob("*.txt")):
                zf.write(fp, fp.name)

        output_file = tmp_path / "result_zip.json"
        r = subprocess.run(
            ["bash", "/app/pipeline.sh",
             str(zip_path), str(query_file), str(output_file)],
            capture_output=True, text=True, timeout=120
        )
        assert r.returncode == 0, f"pipeline.sh with zip failed: {r.stderr}"

        d = json.loads(output_file.read_text())
        assert d["library_stats"]["total_spectra"] == 3
        assert len(d["identification"]) >= 1
