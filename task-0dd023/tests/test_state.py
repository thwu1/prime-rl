
import json
import os
import math
import pytest

# Reference value is embedded ONLY here — not in any environment file,
# Docker image layer, or instruction visible to the solver agent.
_REF_SIGMA_Y_MPA = -5.38


def load_results():
    with open("/app/results.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Independent parsers for cross-validation (anti-cheat)
# These re-derive values from the actual computational artifacts so that
# a fabricated results.json without real solver output will fail.
# ---------------------------------------------------------------------------

def _parse_inp_node_count(filepath):
    """Count explicit *NODE entries in a CalculiX .inp file."""
    count = 0
    in_node = False
    with open(filepath) as f:
        for line in f:
            s = line.strip()
            if s.upper().startswith("*NODE"):
                in_node = True
                continue
            if in_node and s.startswith("*"):
                in_node = False
            if in_node and s and not s.startswith("**"):
                parts = s.split(",")
                if len(parts) >= 3:
                    try:
                        int(parts[0].strip())
                        float(parts[1].strip())
                        count += 1
                    except (ValueError, IndexError):
                        pass
    return count


def _parse_inp_element_count(filepath):
    """Count elements by collecting all integer tokens inside *ELEMENT blocks
    and dividing by (1 + nodes_per_element)."""
    in_elem = False
    nnodes = 20
    total_ints = 0
    type_map = {"C3D20": 20, "C3D20R": 20, "C3D10": 10, "C3D8": 8, "C3D4": 4}
    with open(filepath) as f:
        for line in f:
            s = line.strip()
            if s.upper().startswith("*ELEMENT"):
                in_elem = True
                for p in s.split(","):
                    p = p.strip().upper()
                    if p.startswith("TYPE="):
                        nnodes = type_map.get(p[5:], 20)
                continue
            if in_elem and s.startswith("*"):
                in_elem = False
            if in_elem and s and not s.startswith("**"):
                for tok in s.rstrip(",").split(","):
                    try:
                        int(tok.strip())
                        total_ints += 1
                    except ValueError:
                        pass
    return total_ints // (1 + nnodes) if nnodes > 0 else 0


def _parse_frd_nodes(filepath):
    """Parse node coordinates from the 2C block of a CalculiX .frd file."""
    nodes = {}
    in_coords = False
    with open(filepath) as f:
        for line in f:
            if line.startswith("    2C"):
                in_coords = True
                continue
            if in_coords and line.startswith(" -3"):
                in_coords = False
                continue
            if in_coords and line.startswith(" -1"):
                try:
                    nid = int(line[3:13])
                    x = float(line[13:25])
                    y = float(line[25:37])
                    z = float(line[37:49])
                    nodes[nid] = (x, y, z)
                except (ValueError, IndexError):
                    continue
    return nodes


def _parse_frd_stress_syy(filepath, target_nid):
    """Extract SYY at target_nid from the STRESS block of a .frd file."""
    in_stress = False
    with open(filepath) as f:
        for line in f:
            if " -4  STRESS" in line:
                in_stress = True
                continue
            if in_stress and line.startswith(" -3"):
                in_stress = False
                continue
            if in_stress and line.startswith(" -1"):
                try:
                    nid = int(line[3:13])
                    if nid == target_nid:
                        return float(line[25:37])  # SYY is the second stress component
                except (ValueError, IndexError):
                    continue
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_results_schema(self):
        results = load_results()
        for key in ("num_nodes", "num_elements", "point_D_node_id",
                     "point_D_coords_m", "sigma_y_Pa", "sigma_y_MPa",
                     "relative_error_pct"):
            assert key in results, f"Missing required key: {key}"


class TestOutputFiles:
    def test_frd_file_exists(self):
        assert os.path.isfile("/app/le10_ccx.frd"), "le10_ccx.frd not found"

    def test_inp_file_exists(self):
        assert os.path.isfile("/app/le10_ccx.inp"), "le10_ccx.inp not found"

    def test_inp_no_ncopy(self):
        with open("/app/le10_ccx.inp") as f:
            content = f.read().upper()
        assert "*NCOPY" not in content, "Expanded .inp still contains *NCOPY"

    def test_inp_no_elgen(self):
        with open("/app/le10_ccx.inp") as f:
            content = f.read().upper()
        assert "*ELGEN" not in content, "Expanded .inp still contains *ELGEN"

    def test_frd_has_coordinate_block(self):
        """Verify the .frd contains a proper CalculiX coordinate block."""
        found = False
        with open("/app/le10_ccx.frd") as f:
            for line in f:
                if line.startswith("    2C"):
                    found = True
                    break
        assert found, ".frd missing coordinate block (2C marker)"

    def test_frd_has_stress_block(self):
        """Verify the .frd contains a STRESS results block."""
        found = False
        with open("/app/le10_ccx.frd") as f:
            for line in f:
                if " -4  STRESS" in line:
                    found = True
                    break
        assert found, ".frd missing STRESS results block"


class TestCrossValidateInp:
    """Cross-validate results.json counts against the actual .inp file."""

    def test_node_count_matches_inp(self):
        results = load_results()
        actual = _parse_inp_node_count("/app/le10_ccx.inp")
        assert actual > 0, "Could not parse any nodes from le10_ccx.inp"
        assert actual == results["num_nodes"], (
            f"results.json claims {results['num_nodes']} nodes "
            f"but le10_ccx.inp contains {actual}"
        )

    def test_element_count_matches_inp(self):
        results = load_results()
        actual = _parse_inp_element_count("/app/le10_ccx.inp")
        assert actual > 0, "Could not parse any elements from le10_ccx.inp"
        assert actual == results["num_elements"], (
            f"results.json claims {results['num_elements']} elements "
            f"but le10_ccx.inp contains {actual}"
        )

    def test_node_count_plausible(self):
        """Mesh expansion must produce a non-trivial 3-D mesh."""
        actual = _parse_inp_node_count("/app/le10_ccx.inp")
        assert actual > 100, f"Only {actual} nodes — mesh expansion likely failed"

    def test_element_count_plausible(self):
        actual = _parse_inp_element_count("/app/le10_ccx.inp")
        assert actual > 10, f"Only {actual} elements — mesh expansion likely failed"


class TestCrossValidateFrd:
    """Cross-validate results.json stress against the actual .frd file."""

    def test_point_d_node_in_frd(self):
        """point_D_node_id must exist in .frd and lie near point D."""
        results = load_results()
        frd_nodes = _parse_frd_nodes("/app/le10_ccx.frd")
        nid = results["point_D_node_id"]
        assert nid in frd_nodes, (
            f"point_D_node_id {nid} not found in .frd coordinate block"
        )
        x, y, z = frd_nodes[nid]
        dist = math.sqrt((x - 2.0) ** 2 + y ** 2 + (z - 0.6) ** 2)
        assert dist < 0.001, (
            f"Node {nid} in .frd at ({x},{y},{z}), "
            f"{dist:.6f} m from expected point D"
        )

    def test_stress_matches_frd(self):
        """sigma_y_Pa must match SYY extracted directly from the .frd."""
        results = load_results()
        nid = results["point_D_node_id"]
        frd_syy = _parse_frd_stress_syy("/app/le10_ccx.frd", nid)
        assert frd_syy is not None, (
            f"No stress data in .frd for node {nid}"
        )
        reported = results["sigma_y_Pa"]
        if abs(frd_syy) > 1.0:
            rel = abs(frd_syy - reported) / abs(frd_syy) * 100
            assert rel < 0.1, (
                f"sigma_y_Pa ({reported}) != SYY in .frd ({frd_syy}), "
                f"diff {rel:.4f}%"
            )
        else:
            assert abs(reported - frd_syy) < 1.0


class TestPointD:
    def test_point_d_coords_length(self):
        results = load_results()
        coords = results["point_D_coords_m"]
        assert len(coords) == 3, f"point_D_coords_m must have 3 components"

    def test_point_d_node_id_positive(self):
        results = load_results()
        assert isinstance(results["point_D_node_id"], int)
        assert results["point_D_node_id"] > 0


class TestStressResult:
    def test_sigma_y_within_tolerance(self):
        results = load_results()
        sigma_y = results["sigma_y_MPa"]
        rel_error = abs(sigma_y - _REF_SIGMA_Y_MPA) / abs(_REF_SIGMA_Y_MPA) * 100
        assert rel_error < 15, (
            f"sigma_y = {sigma_y:.4f} MPa, error = {rel_error:.2f}% (limit 15%)"
        )

    def test_sigma_y_is_negative(self):
        results = load_results()
        assert results["sigma_y_MPa"] < 0, (
            f"sigma_y should be compressive (negative), got {results['sigma_y_MPa']}"
        )

    def test_sigma_y_units_consistency(self):
        results = load_results()
        if results["sigma_y_MPa"] == 0:
            pytest.skip("sigma_y_MPa is zero")
        ratio = results["sigma_y_Pa"] / results["sigma_y_MPa"]
        assert abs(ratio - 1e6) / 1e6 < 0.01, (
            f"Pa/MPa ratio = {ratio}, expected ~1e6"
        )

    def test_relative_error_computation(self):
        results = load_results()
        expected = abs(results["sigma_y_MPa"] - _REF_SIGMA_Y_MPA) / abs(_REF_SIGMA_Y_MPA) * 100
        actual = results["relative_error_pct"]
        assert abs(actual - expected) < 0.5, (
            f"relative_error_pct = {actual:.4f}, expected {expected:.4f}"
        )
