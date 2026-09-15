
import subprocess
import os
import math

RECEPTOR = "/app/data/receptor.pdb"
LIGAND = "/app/data/ligand.pdb"
DOCKING_OUT = "/app/data/docking.out"
REC_CHAIN = "B"
LIG_CHAIN = "C"


def read_pdb_atoms(path):
    """Read ATOM lines from a PDB file."""
    lines = []
    with open(path) as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                lines.append(line)
    return lines


def create_complex(rec_path, lig_lines, output_path):
    """Create a PDB file combining receptor and (possibly modified) ligand lines."""
    rec_lines = read_pdb_atoms(rec_path)
    with open(output_path, "w") as f:
        for line in rec_lines:
            f.write(line)
        f.write("TER\n")
        for line in lig_lines:
            f.write(line)
        f.write("END\n")


def translate_ligand(lig_path, dx, dy, dz):
    """Read ligand PDB and translate all ATOM coordinates by (dx, dy, dz)."""
    result = []
    with open(lig_path) as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                x = float(line[30:38]) + dx
                y = float(line[38:46]) + dy
                z = float(line[46:54]) + dz
                new_line = line[:30] + f"{x:8.3f}{y:8.3f}{z:8.3f}" + line[54:]
                result.append(new_line)
    return result


def run_dockq(native_path, model_path, rec_chain=REC_CHAIN, lig_chain=LIG_CHAIN):
    """Run the dockq tool and parse its output."""
    cmd = ["/app/dockq", native_path, model_path,
           "--rec-chain", rec_chain, "--lig-chain", lig_chain]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"dockq failed: {result.stderr}"
    output = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split()
        if len(parts) >= 2:
            key = parts[0].lower()
            val = parts[1]
            if key in ("fnat", "lrms", "irms", "dockq"):
                output[key] = float(val)
            elif key == "capri":
                output["capri"] = val
    return output


def make_native():
    """Create native complex PDB from receptor + ligand."""
    native_path = "/tmp/test_native.pdb"
    lig_lines = read_pdb_atoms(LIGAND)
    create_complex(RECEPTOR, lig_lines, native_path)
    return native_path


class TestBinaryType:
    """Verify compiled C binaries are native ELF executables."""

    def test_decoygen_is_elf(self):
        result = subprocess.run(["file", "/app/decoygen"],
                                capture_output=True, text=True)
        assert "ELF" in result.stdout, (
            f"decoygen must be a native ELF binary, got: {result.stdout.strip()}"
        )

    def test_calcrg_is_elf(self):
        result = subprocess.run(["file", "/app/calcrg"],
                                capture_output=True, text=True)
        assert "ELF" in result.stdout, (
            f"calcrg must be a native ELF binary, got: {result.stdout.strip()}"
        )


class TestSelfComparison:
    """Native vs native should give perfect scores."""

    def test_fnat_is_one(self):
        native = make_native()
        out = run_dockq(native, native)
        assert abs(out["fnat"] - 1.0) < 1e-6, f"fnat={out['fnat']}, expected 1.0"

    def test_lrms_is_zero(self):
        native = make_native()
        out = run_dockq(native, native)
        assert out["lrms"] < 0.01, f"lrms={out['lrms']}, expected ~0.0"

    def test_irms_is_zero(self):
        native = make_native()
        out = run_dockq(native, native)
        assert out["irms"] < 0.01, f"irms={out['irms']}, expected ~0.0"

    def test_dockq_is_one(self):
        native = make_native()
        out = run_dockq(native, native)
        assert abs(out["dockq"] - 1.0) < 1e-4, f"dockq={out['dockq']}, expected 1.0"

    def test_capri_is_high(self):
        native = make_native()
        out = run_dockq(native, native)
        assert out["capri"] == "High", f"capri={out['capri']}, expected High"


class TestFarTranslation:
    """Ligand translated 100A away should be Incorrect."""

    def test_fnat_is_zero(self):
        native = make_native()
        model_path = "/tmp/test_far_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 100, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert abs(out["fnat"]) < 1e-6, f"fnat={out['fnat']}, expected 0.0"

    def test_capri_is_incorrect(self):
        native = make_native()
        model_path = "/tmp/test_far_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 100, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert out["capri"] == "Incorrect", f"capri={out['capri']}, expected Incorrect"

    def test_lrms_large(self):
        native = make_native()
        model_path = "/tmp/test_far_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 100, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert out["lrms"] > 90.0, f"lrms={out['lrms']}, expected >90"


class TestModerateShift:
    """Ligand translated by (0, 0, 2) should preserve most contacts."""

    def test_fnat_high(self):
        native = make_native()
        model_path = "/tmp/test_moderate_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 0, 2)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert out["fnat"] > 0.7, f"fnat={out['fnat']}, expected > 0.7"
        assert out["fnat"] < 1.0, f"fnat={out['fnat']}, expected < 1.0"

    def test_lrms_matches_shift(self):
        native = make_native()
        model_path = "/tmp/test_moderate_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 0, 2)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert abs(out["lrms"] - 2.0) < 0.05, f"lrms={out['lrms']}, expected ~2.0"

    def test_capri_is_high(self):
        native = make_native()
        model_path = "/tmp/test_moderate_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 0, 2)
        create_complex(RECEPTOR, lig_lines, model_path)
        out = run_dockq(native, model_path)
        assert out["capri"] == "High", f"capri={out['capri']}, expected High"


class TestDockQFormula:
    """Verify the DockQ score is correctly computed from fnat, lrms, irms."""

    def _check_formula(self, model_path):
        native = make_native()
        out = run_dockq(native, model_path)
        fnat = out["fnat"]
        lrms = out["lrms"]
        irms = out["irms"]
        expected = (fnat + 1.0 / (1.0 + (lrms / 8.5) ** 2) +
                    1.0 / (1.0 + (irms / 1.5) ** 2)) / 3.0
        assert abs(out["dockq"] - expected) < 0.005, (
            f"dockq={out['dockq']}, expected {expected:.6f} "
            f"from fnat={fnat}, lrms={lrms}, irms={irms}"
        )

    def test_formula_self(self):
        self._check_formula(make_native())

    def test_formula_translated(self):
        model_path = "/tmp/test_formula_model.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 0, 2)
        create_complex(RECEPTOR, lig_lines, model_path)
        self._check_formula(model_path)

    def test_formula_shifted_x(self):
        model_path = "/tmp/test_formula_model_x.pdb"
        lig_lines = translate_ligand(LIGAND, 2, 0, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        self._check_formula(model_path)


class TestCAPRIConsistency:
    """Verify CAPRI classification is consistent with the output metrics."""

    def _classify(self, fnat, lrms, irms):
        if fnat >= 0.5 and (lrms <= 1.0 or irms <= 1.0):
            return "High"
        if (fnat >= 0.3 and fnat < 0.5) and (lrms <= 5.0 or irms <= 2.0):
            return "Medium"
        if fnat >= 0.5 and lrms > 1.0 and irms > 1.0:
            return "Medium"
        if (fnat >= 0.1 and fnat < 0.3) and (lrms <= 10.0 or irms <= 4.0):
            return "Acceptable"
        if fnat >= 0.3 and lrms > 5.0 and irms > 2.0:
            return "Acceptable"
        return "Incorrect"

    def _check_consistency(self, model_path):
        native = make_native()
        out = run_dockq(native, model_path)
        expected = self._classify(out["fnat"], out["lrms"], out["irms"])
        assert out["capri"] == expected, (
            f"CAPRI inconsistency: got {out['capri']}, expected {expected} "
            f"for fnat={out['fnat']}, lrms={out['lrms']}, irms={out['irms']}"
        )

    def test_consistency_self(self):
        self._check_consistency(make_native())

    def test_consistency_far(self):
        model_path = "/tmp/test_capri_far.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 100, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        self._check_consistency(model_path)

    def test_consistency_small(self):
        model_path = "/tmp/test_capri_small.pdb"
        lig_lines = translate_ligand(LIGAND, 0, 0, 2)
        create_complex(RECEPTOR, lig_lines, model_path)
        self._check_consistency(model_path)

    def test_consistency_medium_shift(self):
        model_path = "/tmp/test_capri_medium.pdb"
        lig_lines = translate_ligand(LIGAND, 2, 0, 0)
        create_complex(RECEPTOR, lig_lines, model_path)
        self._check_consistency(model_path)


class TestDecoygen:
    """Verify decoygen produces correctly transformed coordinates."""

    def _parse_first_atom(self, pdb_path):
        with open(pdb_path) as f:
            for line in f:
                if line.startswith("ATOM"):
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                    return x, y, z
        return None

    def test_identity_rotation(self):
        """Pose 1 has identity rotation. Verify first atom coordinates."""
        output_path = "/tmp/test_decoy_1.pdb"
        cmd = ["/app/decoygen", DOCKING_OUT, LIGAND, "1", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"decoygen failed: {result.stderr}"
        assert os.path.exists(output_path), "Output PDB not created"

        coords = self._parse_first_atom(output_path)
        assert coords is not None, "No ATOM records in output"

        expected = (12.899, 19.267, 30.963)
        for i, axis in enumerate(["x", "y", "z"]):
            assert abs(coords[i] - expected[i]) < 0.05, (
                f"Pose 1 {axis}: got {coords[i]:.3f}, expected {expected[i]:.3f}"
            )

    def test_small_rotation(self):
        """Pose 2 has a small rotation. Verify first atom coordinates."""
        output_path = "/tmp/test_decoy_2.pdb"
        cmd = ["/app/decoygen", DOCKING_OUT, LIGAND, "2", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"decoygen failed: {result.stderr}"

        coords = self._parse_first_atom(output_path)
        assert coords is not None, "No ATOM records in output"

        expected = (13.995, 21.617, 30.651)
        for i, axis in enumerate(["x", "y", "z"]):
            assert abs(coords[i] - expected[i]) < 0.1, (
                f"Pose 2 {axis}: got {coords[i]:.3f}, expected {expected[i]:.3f}"
            )

    def test_output_is_valid_pdb(self):
        """Output should have ATOM records with correct format."""
        output_path = "/tmp/test_decoy_valid.pdb"
        cmd = ["/app/decoygen", DOCKING_OUT, LIGAND, "1", output_path]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        atom_count = 0
        with open(output_path) as f:
            for line in f:
                if line.startswith("ATOM"):
                    atom_count += 1
                    assert len(line) >= 54, "ATOM line too short"
        assert atom_count > 500, f"Expected >500 atoms, got {atom_count}"


class TestCalcrg:
    """Verify calcrg produces correct center-of-geometry coordinates."""

    def _run_calcrg(self):
        result = subprocess.run(["/app/calcrg", DOCKING_OUT, "0"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"calcrg failed: {result.stderr}"
        return result.stdout

    def _parse_csv_line(self, line):
        return [float(v.strip()) for v in line.split(",")]

    def test_calcrg_runs(self):
        self._run_calcrg()

    def test_calcrg_ten_lines(self):
        output = self._run_calcrg()
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) == 10, f"Expected 10 center lines, got {len(lines)}"

    def test_calcrg_pose1_identity(self):
        """Pose 1: identity rotation, t=(6,-13,-1), spacing=1.2.
        rg = (r1 - t1*spacing, r2 - t2*spacing, r3 - t3*spacing)
           = (9.283-7.2, 10.928+15.6, 35.584+1.2) = (2.083, 26.528, 36.784)"""
        output = self._run_calcrg()
        lines = output.strip().split("\n")
        vals = self._parse_csv_line(lines[0])
        assert abs(vals[0] - 2.083) < 0.05, f"Pose 1 rg_x: {vals[0]}"
        assert abs(vals[1] - 26.528) < 0.05, f"Pose 1 rg_y: {vals[1]}"
        assert abs(vals[2] - 36.784) < 0.05, f"Pose 1 rg_z: {vals[2]}"

    def test_calcrg_pose10_wrapping(self):
        """Pose 10: t=(64,64,64) wraps to (-64,-64,-64) with N=128.
        rg = (9.283+76.8, 10.928+76.8, 35.584+76.8) = (86.083, 87.728, 112.384)"""
        output = self._run_calcrg()
        lines = output.strip().split("\n")
        vals = self._parse_csv_line(lines[9])
        assert abs(vals[0] - 86.083) < 0.05, f"Pose 10 rg_x: {vals[0]}"
        assert abs(vals[1] - 87.728) < 0.05, f"Pose 10 rg_y: {vals[1]}"
        assert abs(vals[2] - 112.384) < 0.05, f"Pose 10 rg_z: {vals[2]}"

    def test_calcrg_pose5_negative_translation(self):
        """Pose 5: t=(3,-16,2), spacing=1.2.
        rg = (9.283-3.6, 10.928+19.2, 35.584-2.4) = (5.683, 30.128, 33.184)"""
        output = self._run_calcrg()
        lines = output.strip().split("\n")
        vals = self._parse_csv_line(lines[4])
        assert abs(vals[0] - 5.683) < 0.05, f"Pose 5 rg_x: {vals[0]}"
        assert abs(vals[1] - 30.128) < 0.05, f"Pose 5 rg_y: {vals[1]}"
        assert abs(vals[2] - 33.184) < 0.05, f"Pose 5 rg_z: {vals[2]}"


class TestPipeline:
    """Verify score_all.sh produces correct output format."""

    def test_pipeline_runs(self):
        cmd = ["/app/score_all.sh", RECEPTOR, LIGAND, DOCKING_OUT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, f"Pipeline failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        assert len(lines) >= 2, f"Expected header + data lines, got {len(lines)} lines"

    def test_pipeline_header(self):
        cmd = ["/app/score_all.sh", RECEPTOR, LIGAND, DOCKING_OUT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = result.stdout.strip().split("\n")
        header = lines[0].lower().split()
        assert "pose" in header, f"Header missing 'pose': {lines[0]}"
        assert "dockq" in header, f"Header missing 'dockq': {lines[0]}"
        assert "capri" in header, f"Header missing 'capri': {lines[0]}"
        assert "rg_x" in header, f"Header missing 'rg_x': {lines[0]}"
        assert "rg_y" in header, f"Header missing 'rg_y': {lines[0]}"
        assert "rg_z" in header, f"Header missing 'rg_z': {lines[0]}"

    def test_pipeline_sorted_by_dockq(self):
        cmd = ["/app/score_all.sh", RECEPTOR, LIGAND, DOCKING_OUT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = result.stdout.strip().split("\n")

        header = lines[0].lower().split()
        dockq_idx = header.index("dockq")

        dockq_values = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) > dockq_idx:
                dockq_values.append(float(parts[dockq_idx]))

        assert len(dockq_values) >= 5, f"Expected >= 5 data rows, got {len(dockq_values)}"

        for i in range(len(dockq_values) - 1):
            assert dockq_values[i] >= dockq_values[i + 1] - 1e-6, (
                f"Not sorted: dockq[{i}]={dockq_values[i]} < dockq[{i+1}]={dockq_values[i+1]}"
            )

    def test_pipeline_ten_poses(self):
        cmd = ["/app/score_all.sh", RECEPTOR, LIGAND, DOCKING_OUT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = result.stdout.strip().split("\n")
        data_lines = [l for l in lines[1:] if l.strip()]
        assert len(data_lines) == 10, f"Expected 10 poses, got {len(data_lines)}"

    def test_pipeline_rg_values_numeric(self):
        """Verify rg columns contain valid finite numeric values."""
        cmd = ["/app/score_all.sh", RECEPTOR, LIGAND, DOCKING_OUT]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = result.stdout.strip().split("\n")
        header = lines[0].lower().split()
        rg_x_idx = header.index("rg_x")
        rg_y_idx = header.index("rg_y")
        rg_z_idx = header.index("rg_z")

        for line in lines[1:]:
            parts = line.split()
            if not parts:
                continue
            rg_x = float(parts[rg_x_idx])
            rg_y = float(parts[rg_y_idx])
            rg_z = float(parts[rg_z_idx])
            assert math.isfinite(rg_x), f"rg_x not finite: {rg_x}"
            assert math.isfinite(rg_y), f"rg_y not finite: {rg_y}"
            assert math.isfinite(rg_z), f"rg_z not finite: {rg_z}"


class TestMakefile:
    """Verify Makefile can clean and rebuild the C binaries."""

    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_rebuild(self):
        """Clean and rebuild both C binaries."""
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr}"

        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make all failed: {result.stderr}"
        assert os.path.exists("/app/decoygen"), "decoygen not rebuilt"
        assert os.path.exists("/app/calcrg"), "calcrg not rebuilt"

    def test_rebuilt_decoygen_works(self):
        """Rebuilt decoygen should produce valid output."""
        subprocess.run(["make", "-C", "/app", "clean"],
                        capture_output=True, text=True, timeout=30)
        subprocess.run(["make", "-C", "/app", "all"],
                        capture_output=True, text=True, timeout=60)

        output_path = "/tmp/test_rebuild_decoy.pdb"
        cmd = ["/app/decoygen", DOCKING_OUT, LIGAND, "1", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Rebuilt decoygen failed: {result.stderr}"
        assert os.path.exists(output_path), "Output PDB not created"

        with open(output_path) as f:
            for line in f:
                if line.startswith("ATOM"):
                    x = float(line[30:38])
                    assert abs(x - 12.899) < 0.05, f"Rebuilt pose 1 x: {x}"
                    break
