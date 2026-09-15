
import pytest
import json
import csv
import os
import sys
import math
import ast
import itertools
import subprocess

sys.path.insert(0, "/app")

import yaml
from cost_model import evaluate_config, compute_composite_area


def _compute_pass_at_k(n, c, k):
    """Independent Pass@K computation for verification."""
    if n < k:
        return 1.0 if c > 0 else 0.0
    if c >= n:
        return 1.0
    if c == 0:
        return 0.0
    log_ratio = 0.0
    for i in range(k):
        if n - c - i <= 0:
            return 1.0
        log_ratio += math.log(n - c - i) - math.log(n - i)
    return 1.0 - math.exp(log_ratio)


def _load_designs():
    """Load all design JSON files."""
    designs = {}
    design_dir = "/app/designs"
    for fname in sorted(os.listdir(design_dir)):
        if fname.endswith(".json"):
            with open(os.path.join(design_dir, fname)) as f:
                d = json.load(f)
                designs[d["name"]] = d
    return designs


def _expand_configs():
    """Expand DSE YAML into all configurations."""
    with open("/app/dse_space.yaml") as f:
        space = yaml.safe_load(f)
    keys = list(space.keys())
    values = [space[k] for k in keys]
    configs = []
    for combo in itertools.product(*values):
        configs.append(dict(zip(keys, combo)))
    return configs


def _hypervolume_2d(points, ref_x, ref_y):
    """Compute 2D hypervolume for minimization."""
    pts = [(x, y) for (x, y) in points if x < ref_x and y < ref_y]
    if not pts:
        return 0.0
    pts.sort(key=lambda p: p[0])
    front = []
    min_y = float('inf')
    for x, y in pts:
        if y < min_y:
            front.append((x, y))
            min_y = y
    area = 0.0
    for i, (x, y) in enumerate(front):
        x_next = front[i + 1][0] if i + 1 < len(front) else ref_x
        area += (x_next - x) * (ref_y - y)
    return area


def _hypervolume_3d(points, ref):
    """Compute exact 3D hypervolume via z-sweep."""
    pts = [(x, y, z) for (x, y, z) in points
           if x < ref[0] and y < ref[1] and z < ref[2]]
    if not pts:
        return 0.0
    pts.sort(key=lambda p: p[2])
    vol = 0.0
    active = []
    for i, (x, y, z) in enumerate(pts):
        active.append((x, y))
        z_next = pts[i + 1][2] if i + 1 < len(pts) else ref[2]
        dz = z_next - z
        if dz > 0:
            vol += dz * _hypervolume_2d(active, ref[0], ref[1])
    return vol


# ---------- Makefile and CLI structure ----------

class TestMakefileStructure:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_has_required_targets(self):
        with open("/app/Makefile") as f:
            content = f.read()
        for target in ["all", "evaluate", "optimize", "statistics", "report"]:
            assert target in content, f"Makefile missing target: {target}"

    def test_references_cli_tool(self):
        with open("/app/Makefile") as f:
            content = f.read()
        assert "dse_tool.py" in content, "Makefile should invoke dse_tool.py"

    def test_has_dependencies(self):
        """Makefile should define dependencies between targets."""
        with open("/app/Makefile") as f:
            content = f.read()
        lines = content.split("\n")
        has_dep = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("."):
                continue
            if ":" in stripped:
                parts = stripped.split(":", 1)
                if len(parts) == 2 and parts[1].strip():
                    has_dep = True
                    break
        assert has_dep, "Makefile should have dependency declarations"

    def test_dry_run_succeeds(self):
        """make -n all should parse and resolve dependencies."""
        result = subprocess.run(
            ["make", "-n", "all"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=10
        )
        assert result.returncode == 0, f"make -n all failed: {result.stderr}"


class TestCLITool:
    def test_tool_exists(self):
        assert os.path.exists("/app/dse_tool.py"), "dse_tool.py not found"

    def test_valid_python(self):
        with open("/app/dse_tool.py") as f:
            source = f.read()
        ast.parse(source)

    def test_has_mode_argument(self):
        with open("/app/dse_tool.py") as f:
            content = f.read()
        assert "--mode" in content, "CLI tool must accept --mode argument"

    def test_has_all_modes(self):
        with open("/app/dse_tool.py") as f:
            content = f.read()
        for mode in ["evaluate", "optimize", "statistics", "report"]:
            assert mode in content, f"CLI tool missing mode: {mode}"


# ---------- Output file existence ----------

class TestOutputFilesExist:
    def test_pareto_fronts_exists(self):
        assert os.path.exists("/app/output/pareto_fronts.json")

    def test_pass_at_k_exists(self):
        assert os.path.exists("/app/output/pass_at_k.json")

    def test_dse_summary_exists(self):
        assert os.path.exists("/app/output/dse_summary.json")

    def test_full_results_csv_exists(self):
        assert os.path.exists("/app/output/full_results.csv")


# ---------- JSON structure ----------

class TestParetoFrontsStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/pareto_fronts.json") as f:
            self.data = json.load(f)

    def test_has_all_designs(self):
        for name in ["counter_8bit", "fir_filter", "aes_cipher",
                      "jpeg_decoder", "optical_flow"]:
            assert name in self.data, f"Missing design: {name}"

    def test_design_count(self):
        assert len(self.data) == 5

    def test_point_count_consistency(self):
        for name in self.data:
            assert self.data[name]["num_pareto_points"] == len(
                self.data[name]["pareto_points"]
            )

    def test_point_fields(self):
        for name in self.data:
            for pp in self.data[name]["pareto_points"]:
                assert "latency_ns" in pp
                assert "composite_area" in pp
                assert "power_mw" in pp
                assert "luts" in pp
                assert "ffs" in pp
                assert "differential_ppa" in pp
                diff = pp["differential_ppa"]
                assert "latency_ns" in diff
                assert "luts" in diff
                assert "ffs" in diff
                assert "power_mw" in diff


class TestPassAtKStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/pass_at_k.json") as f:
            self.data = json.load(f)

    def test_has_all_designs(self):
        assert len(self.data) == 5

    def test_fields_present(self):
        for name in self.data:
            assert "n_total" in self.data[name]
            assert "n_compile" in self.data[name]
            assert "n_sim" in self.data[name]
            assert "n_synth" in self.data[name]
            for k in [1, 5, 10]:
                for stage in ["compile", "sim", "synth"]:
                    key = f"{stage}_pass_at_{k}"
                    assert key in self.data[name], f"Missing {key} for {name}"


class TestDSESummaryStructure:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/dse_summary.json") as f:
            self.data = json.load(f)

    def test_has_all_designs(self):
        assert len(self.data) == 5

    def test_fields_present(self):
        for name in self.data:
            assert "n_total_configs" in self.data[name]
            assert "n_synthesizable" in self.data[name]
            assert "n_pareto_points" in self.data[name]
            assert "hypervolume" in self.data[name]
            assert isinstance(self.data[name]["hypervolume"], (int, float))
            assert "dse_improvement_gt_20pct" in self.data[name]
            assert isinstance(self.data[name]["dse_improvement_gt_20pct"], bool)
            assert "best_improvements_pct" in self.data[name]

    def test_best_improvements_pct_keys(self):
        for name in self.data:
            bip = self.data[name]["best_improvements_pct"]
            assert isinstance(bip, dict)
            for metric in ["latency_ns", "luts", "ffs", "power_mw"]:
                assert metric in bip, (
                    f"{name}: best_improvements_pct missing key {metric}"
                )
                assert isinstance(bip[metric], (int, float))


# ---------- Total configuration count ----------

class TestTotalConfigurations:
    def test_total_is_3456(self):
        with open("/app/output/pass_at_k.json") as f:
            data = json.load(f)
        for name in data:
            assert data[name]["n_total"] == 3456, (
                f"{name}: expected 3456 total configs, got {data[name]['n_total']}"
            )

    def test_expansion_matches(self):
        configs = _expand_configs()
        assert len(configs) == 3456


# ---------- Pass@K formula verification ----------

class TestPassAtKFormula:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/pass_at_k.json") as f:
            self.data = json.load(f)

    def test_formula_consistency(self):
        for name in self.data:
            n = self.data[name]["n_total"]
            for stage in ["compile", "sim", "synth"]:
                c = self.data[name][f"n_{stage}"]
                for k in [1, 5, 10]:
                    expected = _compute_pass_at_k(n, c, k)
                    actual = self.data[name][f"{stage}_pass_at_{k}"]
                    assert abs(actual - expected) < 1e-4, (
                        f"{name} {stage} pass@{k}: got {actual}, "
                        f"expected {expected} (n={n}, c={c})"
                    )

    def test_monotonicity(self):
        for name in self.data:
            for stage in ["compile", "sim", "synth"]:
                p1 = self.data[name][f"{stage}_pass_at_1"]
                p5 = self.data[name][f"{stage}_pass_at_5"]
                p10 = self.data[name][f"{stage}_pass_at_10"]
                assert p1 <= p5 + 1e-9, f"{name} {stage}: pass@1 > pass@5"
                assert p5 <= p10 + 1e-9, f"{name} {stage}: pass@5 > pass@10"


# ---------- Stage count consistency ----------

class TestStageCounts:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/pass_at_k.json") as f:
            self.data = json.load(f)

    def test_stage_ordering(self):
        for name in self.data:
            n_total = self.data[name]["n_total"]
            n_compile = self.data[name]["n_compile"]
            n_sim = self.data[name]["n_sim"]
            n_synth = self.data[name]["n_synth"]
            assert n_compile <= n_total
            assert n_sim <= n_compile
            assert n_synth <= n_sim
            assert n_synth > 0, f"{name}: no synthesizable configs"


# ---------- Pareto front mathematical properties ----------

class TestParetoFrontProperties:
    @pytest.fixture(autouse=True)
    def load_data(self):
        with open("/app/output/pareto_fronts.json") as f:
            self.data = json.load(f)

    def test_non_dominated(self):
        """Every Pareto point must NOT be dominated by any other Pareto point."""
        for name in self.data:
            points = self.data[name]["pareto_points"]
            for i, pi in enumerate(points):
                for j, pj in enumerate(points):
                    if i == j:
                        continue
                    dominated = (
                        pj["latency_ns"] <= pi["latency_ns"]
                        and pj["composite_area"] <= pi["composite_area"]
                        and pj["power_mw"] <= pi["power_mw"]
                        and (pj["latency_ns"] < pi["latency_ns"]
                             or pj["composite_area"] < pi["composite_area"]
                             or pj["power_mw"] < pi["power_mw"])
                    )
                    assert not dominated, (
                        f"{name}: point {i} dominated by point {j}"
                    )

    def test_pareto_count_bounded(self):
        with open("/app/output/pass_at_k.json") as f:
            pk = json.load(f)
        for name in self.data:
            n_pareto = self.data[name]["num_pareto_points"]
            n_synth = pk[name]["n_synth"]
            assert n_pareto <= n_synth
            assert n_pareto > 0


# ---------- Spot-check: counter_8bit default config ----------

class TestCounterDefaultConfig:
    def test_default_matches_reference(self):
        """Default config for counter_8bit should exactly match reference PPA."""
        design = {
            "name": "counter_8bit",
            "base_cycles": 16,
            "base_luts": 45,
            "base_ffs": 32,
            "base_dsps": 0,
            "base_brams": 0,
            "base_power_mw": 12.5,
            "pipeline_depth": 4,
        }
        config = {
            "clock_period_ns": 5.0,
            "enable_pipeline": False,
            "pipeline_ii": 1,
            "enable_dataflow": False,
            "unroll_factor": 1,
            "array_partition_factor": 1,
            "allocation_limit_add": 0,
            "dsp_full_reg": False,
            "vivado_strategy": "Default",
        }
        result = evaluate_config(design, config)
        assert result["compile_pass"]
        assert result["sim_pass"]
        assert result["synth_pass"]
        assert result["latency_ns"] == 80.0
        assert result["luts"] == 45
        assert result["ffs"] == 32
        assert result["power_mw"] == 12.5

    def test_all_compile(self):
        """counter_8bit has 0 brams and base_cycles=16 > max_unroll=8,
        so all configurations should compile."""
        with open("/app/output/pass_at_k.json") as f:
            data = json.load(f)
        assert data["counter_8bit"]["n_compile"] == 3456


# ---------- Synthesis failures for large designs ----------

class TestSynthesisFailures:
    def test_optical_flow_has_failures(self):
        """optical_flow with base_luts=42000 should have synthesis failures
        for high unroll factors that exceed Artix-7 LUT capacity."""
        with open("/app/output/pass_at_k.json") as f:
            data = json.load(f)
        assert data["optical_flow"]["n_synth"] < data["optical_flow"]["n_sim"]

    def test_fir_filter_compile_failures(self):
        """fir_filter has base_brams=2, so array_partition_factor=4 (>3)
        should cause compilation failures."""
        with open("/app/output/pass_at_k.json") as f:
            data = json.load(f)
        assert data["fir_filter"]["n_compile"] < 3456


# ---------- DSE improvement detection ----------

class TestDSEImprovement:
    def test_latency_improvement_exists(self):
        """Pipeline + dataflow + unroll should achieve significant latency
        improvements for all designs."""
        with open("/app/output/pareto_fronts.json") as f:
            pf = json.load(f)
        for name in pf:
            has_improvement = any(
                pp["differential_ppa"]["latency_ns"] < -20.0
                for pp in pf[name]["pareto_points"]
            )
            assert has_improvement, (
                f"{name}: expected >20% latency improvement on Pareto front"
            )

    def test_dse_flags_set(self):
        """All designs should have dse_improvement_gt_20pct=True
        given the large latency improvements possible."""
        with open("/app/output/dse_summary.json") as f:
            summary = json.load(f)
        for name in summary:
            assert summary[name]["dse_improvement_gt_20pct"] is True, (
                f"{name}: expected DSE improvement flag to be True"
            )


# ---------- CSV structure ----------

class TestCSVStructure:
    def test_row_count(self):
        """CSV should have 5 designs x 3456 configs = 17280 data rows."""
        with open("/app/output/full_results.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        assert len(rows) == 17280, f"Expected 17280 rows, got {len(rows)}"

    def test_required_columns(self):
        """CSV must have design, config params, stage flags, and PPA columns."""
        with open("/app/output/full_results.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        header_set = set(h.strip() for h in header)
        assert "design" in header_set
        for param in ["clock_period_ns", "unroll_factor", "enable_pipeline"]:
            assert param in header_set, f"Missing config column: {param}"
        for flag in ["compile_pass", "sim_pass", "synth_pass"]:
            assert flag in header_set, f"Missing stage flag column: {flag}"
        for metric in ["latency_ns", "luts", "composite_area"]:
            assert metric in header_set, f"Missing PPA column: {metric}"

    def test_synth_rows_have_ppa(self):
        """Synthesizable rows should have PPA values populated."""
        with open("/app/output/full_results.csv") as f:
            reader = csv.DictReader(f)
            synth_count = 0
            for row in reader:
                if row.get("synth_pass", "").lower() in ("true", "1"):
                    synth_count += 1
                    assert row.get("latency_ns", "") != "", (
                        "Synth-passing row missing latency_ns"
                    )
        assert synth_count > 0, "No synthesizable rows found in CSV"


# ---------- Full Pareto completeness verification ----------

class TestParetoCompleteness:
    def test_counter_8bit_pareto_complete(self):
        """Independently recompute the Pareto front for counter_8bit
        and verify it matches the output."""
        designs = _load_designs()
        design = designs["counter_8bit"]
        configs = _expand_configs()

        synth_results = []
        for config in configs:
            result = evaluate_config(design, config)
            if result.get("synth_pass"):
                synth_results.append(result)

        n = len(synth_results)
        is_pareto = [True] * n
        for i in range(n):
            if not is_pareto[i]:
                continue
            for j in range(n):
                if i == j or not is_pareto[j]:
                    continue
                ri = synth_results[i]
                rj = synth_results[j]
                if (rj["latency_ns"] <= ri["latency_ns"]
                        and rj["composite_area"] <= ri["composite_area"]
                        and rj["power_mw"] <= ri["power_mw"]
                        and (rj["latency_ns"] < ri["latency_ns"]
                             or rj["composite_area"] < ri["composite_area"]
                             or rj["power_mw"] < ri["power_mw"])):
                    is_pareto[i] = False
                    break

        expected_count = sum(is_pareto)

        with open("/app/output/pareto_fronts.json") as f:
            pf = json.load(f)

        actual_count = pf["counter_8bit"]["num_pareto_points"]
        assert actual_count == expected_count, (
            f"counter_8bit Pareto count: got {actual_count}, "
            f"expected {expected_count}"
        )

        expected_pareto = [synth_results[i] for i in range(n) if is_pareto[i]]
        expected_latencies = sorted(r["latency_ns"] for r in expected_pareto)
        actual_latencies = sorted(
            pp["latency_ns"] for pp in pf["counter_8bit"]["pareto_points"]
        )
        assert len(expected_latencies) == len(actual_latencies)
        for exp, act in zip(expected_latencies, actual_latencies):
            assert abs(exp - act) < 0.01, (
                f"Latency mismatch: expected {exp}, got {act}"
            )

    def test_counter_8bit_stage_counts(self):
        """Independently verify stage counts for counter_8bit."""
        designs = _load_designs()
        design = designs["counter_8bit"]
        configs = _expand_configs()

        n_compile = 0
        n_sim = 0
        n_synth = 0
        for config in configs:
            result = evaluate_config(design, config)
            if result["compile_pass"]:
                n_compile += 1
            if result.get("sim_pass", False):
                n_sim += 1
            if result.get("synth_pass", False):
                n_synth += 1

        with open("/app/output/pass_at_k.json") as f:
            data = json.load(f)

        assert data["counter_8bit"]["n_compile"] == n_compile
        assert data["counter_8bit"]["n_sim"] == n_sim
        assert data["counter_8bit"]["n_synth"] == n_synth


# ---------- Differential PPA correctness ----------

class TestDifferentialPPA:
    def test_differential_signs(self):
        """Pareto points with lower metrics than reference should have
        negative differential PPA values."""
        with open("/app/output/pareto_fronts.json") as f:
            pf = json.load(f)
        designs = _load_designs()

        for name in pf:
            ref = designs[name]["reference_ppa"]
            for pp in pf[name]["pareto_points"]:
                for metric in ["latency_ns", "luts", "ffs", "power_mw"]:
                    if metric in pp and metric in ref and ref[metric] > 0:
                        expected_sign = (pp[metric] - ref[metric])
                        actual_diff = pp["differential_ppa"][metric]
                        if expected_sign < -0.01:
                            assert actual_diff < 0, (
                                f"{name}: {metric} should be negative diff"
                            )
                        elif expected_sign > 0.01:
                            assert actual_diff > 0, (
                                f"{name}: {metric} should be positive diff"
                            )

    def test_differential_magnitude(self):
        """Verify differential PPA calculation: (gen - ref) / ref * 100."""
        with open("/app/output/pareto_fronts.json") as f:
            pf = json.load(f)
        designs = _load_designs()

        for name in pf:
            ref = designs[name]["reference_ppa"]
            for pp in pf[name]["pareto_points"][:3]:
                for metric in ["latency_ns", "luts", "ffs", "power_mw"]:
                    if ref[metric] > 0:
                        expected = (pp[metric] - ref[metric]) / ref[metric] * 100.0
                        actual = pp["differential_ppa"][metric]
                        assert abs(actual - expected) < 0.1, (
                            f"{name} {metric}: diff={actual}, "
                            f"expected={expected:.4f}"
                        )


# ---------- Hypervolume verification ----------

class TestHypervolume:
    def test_hypervolume_positive(self):
        """All designs should have positive hypervolume."""
        with open("/app/output/dse_summary.json") as f:
            summary = json.load(f)
        for name in summary:
            assert summary[name]["hypervolume"] > 0, (
                f"{name}: hypervolume should be positive"
            )

    def test_counter_8bit_hypervolume(self):
        """Independently recompute hypervolume for counter_8bit and verify."""
        designs = _load_designs()
        design = designs["counter_8bit"]
        configs = _expand_configs()

        # Evaluate all configs
        synth_results = []
        for config in configs:
            result = evaluate_config(design, config)
            if result.get("synth_pass"):
                synth_results.append(result)

        # Find non-dominated set
        n = len(synth_results)
        is_pareto = [True] * n
        for i in range(n):
            if not is_pareto[i]:
                continue
            for j in range(n):
                if i == j or not is_pareto[j]:
                    continue
                ri = synth_results[i]
                rj = synth_results[j]
                if (rj["latency_ns"] <= ri["latency_ns"]
                        and rj["composite_area"] <= ri["composite_area"]
                        and rj["power_mw"] <= ri["power_mw"]
                        and (rj["latency_ns"] < ri["latency_ns"]
                             or rj["composite_area"] < ri["composite_area"]
                             or rj["power_mw"] < ri["power_mw"])):
                    is_pareto[i] = False
                    break

        pareto_pts = [synth_results[i] for i in range(n) if is_pareto[i]]

        # Compute reference point: 1.1x max per objective among synth configs
        max_lat = max(r["latency_ns"] for r in synth_results) * 1.1
        max_area = max(r["composite_area"] for r in synth_results) * 1.1
        max_power = max(r["power_mw"] for r in synth_results) * 1.1

        # Compute hypervolume
        pts_3d = [
            (p["latency_ns"], float(p["composite_area"]), p["power_mw"])
            for p in pareto_pts
        ]
        expected_hv = _hypervolume_3d(pts_3d, (max_lat, max_area, max_power))

        with open("/app/output/dse_summary.json") as f:
            summary = json.load(f)

        actual_hv = summary["counter_8bit"]["hypervolume"]
        rel_tol = max(abs(expected_hv) * 0.001, 1e-6)
        assert abs(actual_hv - expected_hv) < rel_tol, (
            f"counter_8bit hypervolume: got {actual_hv}, expected {expected_hv}"
        )

    def test_hypervolume_field_type(self):
        """Hypervolume should be a numeric value."""
        with open("/app/output/dse_summary.json") as f:
            summary = json.load(f)
        for name in summary:
            hv = summary[name]["hypervolume"]
            assert isinstance(hv, (int, float)), (
                f"{name}: hypervolume should be numeric, got {type(hv)}"
            )
