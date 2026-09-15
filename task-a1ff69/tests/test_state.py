
import re
import os
import json
import math
import pytest


def parse_lulesh_output(filepath):
    """Parse LULESH output to extract key metrics."""
    with open(filepath, "r") as f:
        text = f.read()

    result = {}

    m = re.search(r"Final Origin Energy\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)", text)
    if m:
        result["final_energy"] = float(m.group(1))

    m = re.search(r"MaxAbsDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)", text)
    if m:
        result["max_abs_diff"] = float(m.group(1))

    m = re.search(r"TotalAbsDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)", text)
    if m:
        result["total_abs_diff"] = float(m.group(1))

    m = re.search(r"MaxRelDiff\s*=\s*([+-]?\d+\.?\d*[eE][+-]?\d+)", text)
    if m:
        result["max_rel_diff"] = float(m.group(1))

    m = re.search(r"Iteration count\s*=\s*(\d+)", text)
    if m:
        result["iterations"] = int(m.group(1))

    m = re.search(r"Problem size\s*=\s*(\d+)", text)
    if m:
        result["problem_size"] = int(m.group(1))

    return result


def relative_error(a, b):
    """Compute relative error between two values."""
    if abs(b) < 1e-300:
        return abs(a - b)
    return abs(a - b) / abs(b)


def values_close(agent_val, ref_val, rel_tol=0.25, abs_tol=0.01):
    """Check if two numeric values are close, handling inf/nan/zero."""
    if not isinstance(agent_val, (int, float)):
        return False
    if not isinstance(ref_val, (int, float)):
        return False
    if math.isnan(agent_val) or math.isnan(ref_val):
        return False
    if math.isinf(agent_val) and math.isinf(ref_val):
        return (agent_val > 0) == (ref_val > 0)
    if math.isinf(agent_val) or math.isinf(ref_val):
        return False
    if abs(ref_val) < 1e-30:
        return abs(agent_val - ref_val) < abs_tol
    rel = abs(agent_val - ref_val) / abs(ref_val)
    return rel < rel_tol or abs(agent_val - ref_val) < abs_tol


class TestLuleshPrimaryCorrectness:
    """Verify the agent's LULESH fixes produce correct numerical results."""

    def test_build_succeeds(self):
        """The LULESH code must compile without errors."""
        assert os.path.exists("/app/lulesh2.0"), \
            "lulesh2.0 binary not found — build may have failed"

    def test_run_s10_completes(self):
        """LULESH must run successfully with -s 10 -i 100."""
        output_path = "/tmp/agent_output_s10_i100.txt"
        assert os.path.exists(output_path), \
            "Output file for -s 10 -i 100 not found"
        metrics = parse_lulesh_output(output_path)
        assert "final_energy" in metrics, \
            "Could not parse Final Origin Energy from output"
        assert metrics.get("problem_size") == 10, \
            "Problem size mismatch"
        assert metrics.get("iterations") == 100, \
            "Iteration count mismatch — expected 100"

    def test_run_s15_completes(self):
        """LULESH must run successfully with -s 15 -i 50."""
        output_path = "/tmp/agent_output_s15_i50.txt"
        assert os.path.exists(output_path), \
            "Output file for -s 15 -i 50 not found"
        metrics = parse_lulesh_output(output_path)
        assert "final_energy" in metrics, \
            "Could not parse Final Origin Energy from output"
        assert metrics.get("problem_size") == 15, \
            "Problem size mismatch"
        assert metrics.get("iterations") == 50, \
            "Iteration count mismatch — expected 50"

    def test_energy_matches_reference_s10(self):
        """Final Origin Energy for -s 10 -i 100 must match reference."""
        ref_path = "/reference/output_s10_i100.txt"
        agent_path = "/tmp/agent_output_s10_i100.txt"

        assert os.path.exists(ref_path), \
            "Reference output not found at " + ref_path
        assert os.path.exists(agent_path), \
            "Agent output not found — did the run complete?"

        ref = parse_lulesh_output(ref_path)
        agent = parse_lulesh_output(agent_path)

        assert "final_energy" in ref, \
            "Could not parse reference Final Origin Energy"
        assert "final_energy" in agent, \
            "Could not parse agent Final Origin Energy"

        rel_err = relative_error(agent["final_energy"], ref["final_energy"])
        assert rel_err < 1e-10, \
            (f"Final Origin Energy mismatch for -s 10 -i 100: "
             f"agent={agent['final_energy']:.6e}, "
             f"reference={ref['final_energy']:.6e}, "
             f"relative_error={rel_err:.2e}")

    def test_energy_matches_reference_s15(self):
        """Final Origin Energy for -s 15 -i 50 must match reference."""
        ref_path = "/reference/output_s15_i50.txt"
        agent_path = "/tmp/agent_output_s15_i50.txt"

        assert os.path.exists(ref_path), \
            "Reference output not found at " + ref_path
        assert os.path.exists(agent_path), \
            "Agent output not found — did the run complete?"

        ref = parse_lulesh_output(ref_path)
        agent = parse_lulesh_output(agent_path)

        assert "final_energy" in ref, \
            "Could not parse reference Final Origin Energy"
        assert "final_energy" in agent, \
            "Could not parse agent Final Origin Energy"

        rel_err = relative_error(agent["final_energy"], ref["final_energy"])
        assert rel_err < 1e-10, \
            (f"Final Origin Energy mismatch for -s 15 -i 50: "
             f"agent={agent['final_energy']:.6e}, "
             f"reference={ref['final_energy']:.6e}, "
             f"relative_error={rel_err:.2e}")

    def test_symmetry_check_s10(self):
        """Energy symmetry must be preserved (MaxAbsDiff matches reference)."""
        agent_path = "/tmp/agent_output_s10_i100.txt"
        ref_path = "/reference/output_s10_i100.txt"

        agent = parse_lulesh_output(agent_path)
        ref = parse_lulesh_output(ref_path)

        if "max_abs_diff" in ref and "max_abs_diff" in agent:
            assert relative_error(
                agent["max_abs_diff"], ref["max_abs_diff"]
            ) < 1e-6, \
                (f"MaxAbsDiff mismatch: agent={agent['max_abs_diff']:.6e}, "
                 f"reference={ref['max_abs_diff']:.6e}")

    def test_symmetry_check_s15(self):
        """Energy symmetry for s15 must match reference."""
        agent_path = "/tmp/agent_output_s15_i50.txt"
        ref_path = "/reference/output_s15_i50.txt"

        agent = parse_lulesh_output(agent_path)
        ref = parse_lulesh_output(ref_path)

        if "max_abs_diff" in ref and "max_abs_diff" in agent:
            assert relative_error(
                agent["max_abs_diff"], ref["max_abs_diff"]
            ) < 1e-6, \
                (f"MaxAbsDiff mismatch: agent={agent['max_abs_diff']:.6e}, "
                 f"reference={ref['max_abs_diff']:.6e}")

    def test_iteration_count_matches_s10(self):
        """Iteration count must match reference (confirms same timestep evolution)."""
        ref_path = "/reference/output_s10_i100.txt"
        agent_path = "/tmp/agent_output_s10_i100.txt"

        ref = parse_lulesh_output(ref_path)
        agent = parse_lulesh_output(agent_path)

        assert ref.get("iterations") == agent.get("iterations"), \
            (f"Iteration count mismatch for -s 10: "
             f"agent={agent.get('iterations')}, "
             f"reference={ref.get('iterations')}")


class TestConvergenceCorrectness:
    """Verify convergence simulation results match reference at all mesh sizes."""

    @pytest.mark.parametrize("size", [8, 12, 16, 20])
    def test_convergence_energy(self, size):
        """Final Origin Energy at convergence mesh size must match reference."""
        ref_path = f"/reference/convergence/output_s{size}_i50.txt"
        agent_path = f"/tmp/agent_conv_s{size}.txt"

        assert os.path.exists(ref_path), \
            f"Reference convergence output not found for size {size}"
        assert os.path.exists(agent_path), \
            f"Agent convergence output not found for size {size}"

        ref = parse_lulesh_output(ref_path)
        agent = parse_lulesh_output(agent_path)

        assert "final_energy" in ref, \
            f"Could not parse reference energy for size {size}"
        assert "final_energy" in agent, \
            f"Could not parse agent energy for size {size}"

        rel_err = relative_error(agent["final_energy"], ref["final_energy"])
        assert rel_err < 1e-10, \
            (f"Energy mismatch at size {size}: "
             f"agent={agent['final_energy']:.6e}, "
             f"reference={ref['final_energy']:.6e}, "
             f"relative_error={rel_err:.2e}")

    @pytest.mark.parametrize("size", [8, 12, 16, 20])
    def test_convergence_symmetry(self, size):
        """Symmetry metrics at each convergence mesh size must match reference."""
        ref_path = f"/reference/convergence/output_s{size}_i50.txt"
        agent_path = f"/tmp/agent_conv_s{size}.txt"

        if not os.path.exists(ref_path) or not os.path.exists(agent_path):
            pytest.skip(f"Output not found for size {size}")

        ref = parse_lulesh_output(ref_path)
        agent = parse_lulesh_output(agent_path)

        if "max_rel_diff" in ref and "max_rel_diff" in agent:
            assert relative_error(
                agent["max_rel_diff"], ref["max_rel_diff"]
            ) < 1e-4, \
                (f"MaxRelDiff mismatch at size {size}: "
                 f"agent={agent['max_rel_diff']:.6e}, "
                 f"reference={ref['max_rel_diff']:.6e}")


class TestGCIFramework:
    """Verify the GCI verification framework design and output."""

    def _load_report(self):
        report_path = "/app/gci_report.json"
        assert os.path.exists(report_path), \
            "gci_report.json not found at /app/gci_report.json"
        with open(report_path, "r") as f:
            return json.load(f)

    def _load_reference_gci(self):
        ref_path = "/reference/gci_reference.json"
        if not os.path.exists(ref_path):
            return None
        with open(ref_path, "r") as f:
            return json.load(f)

    def test_gci_script_exists(self):
        """gci_analysis.py must exist at /app/."""
        assert os.path.exists("/app/gci_analysis.py"), \
            "gci_analysis.py not found at /app/gci_analysis.py"

    def test_gci_report_valid_json(self):
        """gci_report.json must exist and be valid JSON."""
        report_path = "/app/gci_report.json"
        assert os.path.exists(report_path), \
            "gci_report.json not found"
        with open(report_path, "r") as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report must be a JSON object"

    def test_report_has_required_fields(self):
        """The GCI report must contain all required fields."""
        report = self._load_report()
        required = [
            "mesh_sizes", "energies", "convergence_order",
            "gci_fine", "gci_coarse", "asymptotic_ratio",
            "richardson_estimate", "assessment"
        ]
        for field in required:
            assert field in report, \
                f"Required field '{field}' missing from GCI report"

    def test_mesh_sizes_correct(self):
        """Report must list mesh sizes 8, 12, 16, 20."""
        report = self._load_report()
        sizes = sorted(report["mesh_sizes"])
        assert sizes == [8, 12, 16, 20], \
            f"Expected mesh sizes [8,12,16,20], got {sizes}"

    def test_energies_present_for_all_sizes(self):
        """Report must contain energy values for all mesh sizes."""
        report = self._load_report()
        energies = report["energies"]
        for size in [8, 12, 16, 20]:
            key = str(size)
            assert key in energies, \
                f"Energy missing for mesh size {size}"
            assert isinstance(energies[key], (int, float)), \
                f"Energy for size {size} is not numeric"

    def test_report_energies_match_reference(self):
        """Energies in the GCI report must match simulation reference values."""
        report = self._load_report()
        energies = report["energies"]
        for size in [8, 12, 16, 20]:
            ref_path = f"/reference/convergence/output_s{size}_i50.txt"
            if not os.path.exists(ref_path):
                continue
            ref = parse_lulesh_output(ref_path)
            if "final_energy" not in ref:
                continue
            key = str(size)
            assert key in energies, \
                f"Energy for size {size} missing from report"
            rel_err = relative_error(energies[key], ref["final_energy"])
            assert rel_err < 1e-8, \
                (f"GCI report energy for size {size} does not match reference: "
                 f"report={energies[key]:.6e}, "
                 f"reference={ref['final_energy']:.6e}, "
                 f"relative_error={rel_err:.2e}")

    def test_convergence_order_matches_reference(self):
        """Computed convergence order must match reference GCI computation."""
        report = self._load_report()
        ref_gci = self._load_reference_gci()
        p = report["convergence_order"]
        assert isinstance(p, (int, float)), \
            "convergence_order is not numeric"
        assert math.isfinite(p), \
            f"convergence_order is not finite: {p}"
        if ref_gci is not None:
            ref_p = ref_gci["convergence_order"]
            assert values_close(p, ref_p, rel_tol=0.25, abs_tol=0.5), \
                (f"convergence_order {p:.4f} does not match "
                 f"reference {ref_p:.4f}")
        else:
            assert p > 0, \
                f"convergence_order must be positive, got {p}"

    def test_gci_fine_matches_reference(self):
        """GCI for finest grid pair must match reference."""
        report = self._load_report()
        ref_gci = self._load_reference_gci()
        gci = report["gci_fine"]
        assert isinstance(gci, (int, float)), "gci_fine is not numeric"
        if ref_gci is not None:
            ref_gci_fine = ref_gci["gci_fine"]
            assert values_close(gci, ref_gci_fine, rel_tol=0.30, abs_tol=0.01), \
                (f"gci_fine {gci:.6e} does not match "
                 f"reference {ref_gci_fine:.6e}")
        else:
            assert math.isfinite(gci), f"gci_fine is not finite: {gci}"
            assert gci > 0, f"gci_fine must be positive, got {gci}"

    def test_gci_coarse_matches_reference(self):
        """GCI for coarser grid pair must match reference."""
        report = self._load_report()
        ref_gci = self._load_reference_gci()
        gci = report["gci_coarse"]
        assert isinstance(gci, (int, float)), "gci_coarse is not numeric"
        if ref_gci is not None:
            ref_gci_coarse = ref_gci["gci_coarse"]
            assert values_close(gci, ref_gci_coarse, rel_tol=0.30, abs_tol=0.01), \
                (f"gci_coarse {gci:.6e} does not match "
                 f"reference {ref_gci_coarse:.6e}")
        else:
            assert math.isfinite(gci), f"gci_coarse is not finite: {gci}"
            assert gci > 0, f"gci_coarse must be positive, got {gci}"

    def test_asymptotic_ratio_matches_reference(self):
        """Asymptotic ratio must match reference."""
        report = self._load_report()
        ref_gci = self._load_reference_gci()
        ar = report["asymptotic_ratio"]
        assert isinstance(ar, (int, float)), "asymptotic_ratio is not numeric"
        if ref_gci is not None:
            ref_ar = ref_gci["asymptotic_ratio"]
            assert values_close(ar, ref_ar, rel_tol=0.15, abs_tol=0.1), \
                (f"asymptotic_ratio {ar:.6f} does not match "
                 f"reference {ref_ar:.6f}")
        else:
            assert math.isfinite(ar), \
                f"asymptotic_ratio is not finite: {ar}"

    def test_richardson_estimate_reasonable(self):
        """Richardson extrapolation should be close to the finest-mesh energy."""
        report = self._load_report()
        rich = report["richardson_estimate"]
        assert isinstance(rich, (int, float)), "richardson_estimate is not numeric"
        assert math.isfinite(rich), f"richardson_estimate is not finite: {rich}"
        # The extrapolation should be within 50% of the finest mesh energy
        finest_key = str(max(report["mesh_sizes"]))
        if finest_key in report["energies"]:
            finest_energy = report["energies"][finest_key]
            if abs(finest_energy) > 1e-30:
                rel_diff = abs(rich - finest_energy) / abs(finest_energy)
                assert rel_diff < 0.50, \
                    (f"Richardson estimate {rich:.6e} differs from finest "
                     f"energy {finest_energy:.6e} by {rel_diff:.1%}")

    def test_assessment_field_valid(self):
        """Assessment must be 'verified' or 'not_verified'."""
        report = self._load_report()
        assert report["assessment"] in ("verified", "not_verified"), \
            f"assessment must be 'verified' or 'not_verified', got '{report['assessment']}'"

    def test_assessment_consistent_with_criteria(self):
        """Assessment must be consistent with convergence_order and asymptotic_ratio."""
        report = self._load_report()
        p = report["convergence_order"]
        ar = report["asymptotic_ratio"]
        expected = "verified" if (p >= 0.8 and 0.9 <= ar <= 1.1) else "not_verified"
        assert report["assessment"] == expected, \
            (f"Assessment '{report['assessment']}' is inconsistent: "
             f"convergence_order={p:.4f}, asymptotic_ratio={ar:.6f} "
             f"→ expected '{expected}'")
