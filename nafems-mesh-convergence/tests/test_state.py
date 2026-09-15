
import json
import os
import pytest

# Reference kept ONLY in test (not in any environment file or instruction)
_R = 46.35 * 2  # assembled indirectly to resist trivial grep


def _ref():
    return _R


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


class TestNafemsLE1Results:
    """Verify the NAFEMS LE1 mesh convergence study results."""

    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), "/app/results.json not found"

    def test_valid_json_structure(self):
        data = load_results()
        assert isinstance(data, dict), "Root must be a JSON object"
        assert data.get("benchmark") == "NAFEMS_LE1", "benchmark must be NAFEMS_LE1"
        assert "convergence_study" in data, "Missing convergence_study key"
        assert isinstance(data["convergence_study"], list), "convergence_study must be a list"

    def test_minimum_mesh_levels(self):
        data = load_results()
        n = len(data["convergence_study"])
        assert n >= 4, f"Need >= 4 mesh levels, got {n}"

    def test_entry_fields_and_types(self):
        data = load_results()
        required = ["num_elements", "num_nodes", "sigma_yy_MPa", "sigma_xx_MPa",
                     "max_displacement_mm"]
        for i, entry in enumerate(data["convergence_study"]):
            for key in required:
                assert key in entry, f"Entry {i}: missing {key}"
            ne = entry["num_elements"]
            nn = entry["num_nodes"]
            syy = entry["sigma_yy_MPa"]
            sxx = entry["sigma_xx_MPa"]
            disp = entry["max_displacement_mm"]
            assert isinstance(ne, (int, float)) and ne > 0, \
                f"Entry {i}: num_elements must be positive number"
            assert isinstance(nn, (int, float)) and nn > 0, \
                f"Entry {i}: num_nodes must be positive number"
            assert isinstance(syy, (int, float)), f"Entry {i}: sigma_yy_MPa not numeric"
            assert isinstance(sxx, (int, float)), f"Entry {i}: sigma_xx_MPa not numeric"
            assert isinstance(disp, (int, float)) and disp > 0, \
                f"Entry {i}: max_displacement_mm must be positive"
            assert 10 < syy < 200, (
                f"Entry {i}: sigma_yy_MPa={syy} outside physically plausible range"
            )

    def test_distinct_increasing_mesh_sizes(self):
        data = load_results()
        entries = sorted(data["convergence_study"], key=lambda x: x["level"])
        counts = [int(e["num_elements"]) for e in entries]
        for i in range(1, len(counts)):
            assert counts[i] > counts[i - 1], (
                f"Element counts must strictly increase across levels: {counts}"
            )

    def test_mesh_files_exist(self):
        """Every reported level must have a corresponding mesh file."""
        data = load_results()
        for entry in data["convergence_study"]:
            level = entry["level"]
            mesh_path = f"/app/meshes/level_{level}.msh"
            assert os.path.isfile(mesh_path), f"Mesh file {mesh_path} not found"
            fsize = os.path.getsize(mesh_path)
            assert fsize > 512, (
                f"Mesh file {mesh_path} suspiciously small ({fsize} bytes)"
            )

    def test_mesh_files_loadable_and_consistent(self):
        """Load each mesh with gmsh API — verifies files are real meshes, not fabricated."""
        import gmsh
        data = load_results()
        prev_ne = 0

        for entry in sorted(data["convergence_study"], key=lambda x: x["level"]):
            level = entry["level"]
            mesh_path = f"/app/meshes/level_{level}.msh"

            gmsh.initialize()
            gmsh.option.setNumber("General.Terminal", 0)
            try:
                gmsh.open(mesh_path)

                ntags, _, _ = gmsh.model.mesh.getNodes()
                nn_file = len(ntags)

                _, elem_tags_list, _ = gmsh.model.mesh.getElements(dim=2)
                ne_file = sum(len(et) for et in elem_tags_list)

                # Must contain non-trivial mesh data
                assert nn_file >= 20, (
                    f"Level {level}: mesh has only {nn_file} nodes"
                )
                assert ne_file >= 5, (
                    f"Level {level}: mesh has only {ne_file} 2D elements"
                )

                # Reported counts must be consistent with actual mesh file
                nn_rep = entry["num_nodes"]
                ne_rep = entry["num_elements"]
                assert nn_file > nn_rep * 0.3, (
                    f"Level {level}: mesh file has {nn_file} nodes but "
                    f"reported {nn_rep} — inconsistent"
                )
                assert ne_file > ne_rep * 0.3, (
                    f"Level {level}: mesh file has {ne_file} elements but "
                    f"reported {ne_rep} — inconsistent"
                )
                assert nn_file < nn_rep * 3.0, (
                    f"Level {level}: mesh file has {nn_file} nodes but "
                    f"reported {nn_rep} — inconsistent"
                )
                assert ne_file < ne_rep * 3.0, (
                    f"Level {level}: mesh file has {ne_file} elements but "
                    f"reported {ne_rep} — inconsistent"
                )

                # Element counts in files must also increase
                assert ne_file > prev_ne, (
                    f"Level {level}: mesh element count {ne_file} not greater "
                    f"than previous level ({prev_ne})"
                )
                prev_ne = ne_file
            finally:
                gmsh.finalize()

    def test_finest_mesh_accuracy(self):
        data = load_results()
        entries = sorted(data["convergence_study"], key=lambda x: x["num_elements"])
        finest = entries[-1]
        syy = finest["sigma_yy_MPa"]
        ref = _ref()
        error_pct = abs(syy - ref) / ref * 100
        assert error_pct < 5.0, (
            f"Finest mesh (n={finest['num_elements']}): "
            f"sigma_yy={syy:.2f} MPa, error={error_pct:.2f}% (must be < 5%)"
        )

    def test_convergence_trend(self):
        data = load_results()
        entries = sorted(data["convergence_study"], key=lambda x: x["num_elements"])
        ref = _ref()
        errors = [abs(e["sigma_yy_MPa"] - ref) / ref * 100 for e in entries]
        assert errors[-1] < errors[0], (
            f"No convergence: coarsest error={errors[0]:.2f}%, "
            f"finest error={errors[-1]:.2f}%"
        )

    def test_sigma_xx_physically_consistent(self):
        """sigma_xx at D should be compressive for this loading configuration."""
        data = load_results()
        entries = sorted(data["convergence_study"], key=lambda x: x["num_elements"])
        finest_sxx = entries[-1]["sigma_xx_MPa"]
        # sigma_xx at D is approximately -23.6 MPa — check broad plausible range
        assert -80 < finest_sxx < 20, (
            f"sigma_xx at finest mesh = {finest_sxx:.2f}, outside plausible range"
        )
        # Values must not all be identical (anti-fabrication check)
        sxx_vals = [e["sigma_xx_MPa"] for e in entries]
        assert len(set(round(v, 1) for v in sxx_vals)) > 1, (
            "All sigma_xx values are identical across mesh levels — likely fabricated"
        )

    def test_displacement_physically_consistent(self):
        """Max displacement should be in mm range for this E/p combination."""
        data = load_results()
        entries = sorted(data["convergence_study"], key=lambda x: x["num_elements"])
        for entry in entries:
            d = entry["max_displacement_mm"]
            # With E=210 GPa, p=10 MPa, domain ~3m: displacement order ~1 mm
            assert 0.005 < d < 50.0, (
                f"max_displacement_mm={d} outside plausible range for this problem"
            )
        # Values must not all be identical
        disp_vals = [e["max_displacement_mm"] for e in entries]
        assert len(set(round(d, 4) for d in disp_vals)) > 1, (
            "All displacement values identical across mesh levels — likely fabricated"
        )
