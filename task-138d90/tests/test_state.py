
"""Tests for the 3D Object Detection Evaluation Pipeline.

Verifies that the pipeline at /app/ has been correctly audited and fixed
by testing individual function behavior, end-to-end output properties,
Makefile orchestration, git-annotated audit report with severity ratings,
and the agent-designed pipeline validator.
"""

import json
import math
import os
import re
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, '/app')


# ============================================================
# Unit tests: Range filtering (Bug 1 — L2 vs L-inf)
# ============================================================

class TestRangeFilter:
    """Verify range filtering uses L2 norm, not L-infinity."""

    def test_l2_excludes_diagonal_beyond_range(self):
        """Object at (107, 107, 0): L-inf=107 < 150, L2=151.3 >= 150.
        Must be excluded if L2 is used correctly."""
        from pipeline.preprocessing import filter_by_range
        entries = [{'tx': 107.0, 'ty': 107.0, 'tz': 0.0}]
        result = filter_by_range(entries, 150.0)
        assert len(result) == 0, (
            "Object at (107,107,0) has L2=151.3, should be excluded")

    def test_l2_keeps_within_range(self):
        """Object at (100, 100, 0): L2=141.4 < 150, should be kept."""
        from pipeline.preprocessing import filter_by_range
        entries = [{'tx': 100.0, 'ty': 100.0, 'tz': 0.0}]
        result = filter_by_range(entries, 150.0)
        assert len(result) == 1

    def test_boundary_excluded(self):
        """Object at exactly max_range must be excluded (strict <)."""
        from pipeline.preprocessing import filter_by_range
        entries = [{'tx': 150.0, 'ty': 0.0, 'tz': 0.0}]
        assert len(filter_by_range(entries, 150.0)) == 0

    def test_3d_component_included(self):
        """Z component must participate in L2 computation."""
        from pipeline.preprocessing import filter_by_range
        # sqrt(100² + 100² + 50²) = sqrt(22500) = 150.0 → excluded
        entries = [{'tx': 100.0, 'ty': 100.0, 'tz': 50.0}]
        assert len(filter_by_range(entries, 150.0)) == 0

    def test_empty_list(self):
        from pipeline.preprocessing import filter_by_range
        assert filter_by_range([], 150.0) == []

    def test_close_objects_kept(self):
        from pipeline.preprocessing import filter_by_range
        entries = [
            {'tx': 1.0, 'ty': 2.0, 'tz': 0.0},
            {'tx': -5.0, 'ty': 3.0, 'tz': 1.0},
        ]
        assert len(filter_by_range(entries, 150.0)) == 2


# ============================================================
# Unit tests: Greedy assignment (Bug 3 — sort order)
# ============================================================

class TestGreedyAssign:
    """Verify greedy assignment processes detections by descending score."""

    def test_high_score_wins(self):
        """Higher-score detection must claim the match over lower-score."""
        from pipeline.assignment import greedy_assign
        dts = [
            {'tx': 1.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.3},
            {'tx': 1.2, 'ty': 0.0, 'tz': 0.0, 'score': 0.9},
        ]
        gts = [{'tx': 1.1, 'ty': 0.0, 'tz': 0.0}]
        assignments = greedy_assign(dts, gts, 2.0)
        assert 1 in assignments, "High-score detection (idx 1) must get match"
        assert 0 not in assignments, "Low-score detection (idx 0) should be FP"

    def test_empty_dts(self):
        from pipeline.assignment import greedy_assign
        assert greedy_assign([], [{'tx': 0, 'ty': 0, 'tz': 0}], 2.0) == {}

    def test_empty_gts(self):
        from pipeline.assignment import greedy_assign
        dts = [{'tx': 0, 'ty': 0, 'tz': 0, 'score': 0.5}]
        assert greedy_assign(dts, [], 2.0) == {}

    def test_threshold_enforced(self):
        from pipeline.assignment import greedy_assign
        dts = [{'tx': 0.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.9}]
        gts = [{'tx': 3.0, 'ty': 0.0, 'tz': 0.0}]
        assert greedy_assign(dts, gts, 2.0) == {}
        assert len(greedy_assign(dts, gts, 4.0)) == 1

    def test_one_gt_per_detection(self):
        """Each GT can only be matched once."""
        from pipeline.assignment import greedy_assign
        dts = [
            {'tx': 0.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.9},
            {'tx': 0.1, 'ty': 0.0, 'tz': 0.0, 'score': 0.5},
        ]
        gts = [{'tx': 0.05, 'ty': 0.0, 'tz': 0.0}]
        assignments = greedy_assign(dts, gts, 2.0)
        assert len(assignments) == 1
        assert 0 in assignments


# ============================================================
# Unit tests: AP computation (Bug 4 — VOC envelope direction)
# ============================================================

class TestComputeAP:
    """Verify AP with correct VOC-style precision interpolation."""

    def test_all_tp(self):
        from pipeline.metrics import compute_average_precision
        tps = np.array([True] * 5, dtype=bool)
        ap = compute_average_precision(tps, 5)
        assert abs(ap - 1.0) < 0.02

    def test_no_detections(self):
        from pipeline.metrics import compute_average_precision
        assert compute_average_precision(np.array([], dtype=bool), 5) == 0.0

    def test_no_gts(self):
        from pipeline.metrics import compute_average_precision
        assert compute_average_precision(np.array([True], dtype=bool), 0) == 0.0

    def test_voc_envelope_direction(self):
        """Test that VOC envelope is applied in reverse direction.

        Pattern [F, F, T, T] with 2 GTs: precision increases with recall.
        Correct reverse envelope boosts early precision → AP ≈ 0.5.
        Buggy forward envelope has minimal effect → AP ≈ 0.3.
        """
        from pipeline.metrics import compute_average_precision
        tps = np.array([False, False, True, True], dtype=bool)
        ap = compute_average_precision(tps, 2)
        assert ap > 0.40, (
            f"AP={ap:.4f}, expected > 0.40. "
            "VOC envelope may be applied in wrong direction (forward instead of reverse).")

    def test_ap_in_range(self):
        from pipeline.metrics import compute_average_precision
        rng = np.random.RandomState(123)
        for _ in range(15):
            n = rng.randint(1, 20)
            tps = rng.choice([True, False], size=n).astype(bool)
            num_gts = max(1, int(np.sum(tps)) + rng.randint(0, 5))
            ap = compute_average_precision(tps, num_gts)
            assert 0.0 <= ap <= 1.0 + 1e-6

    def test_partial_recall(self):
        from pipeline.metrics import compute_average_precision
        tps = np.array([True, True, False, False], dtype=bool)
        ap = compute_average_precision(tps, 10)
        assert ap < 0.25


# ============================================================
# Unit tests: Orientation error (Bug 5 — angle wrapping)
# ============================================================

class TestOrientationError:
    """Verify orientation error handles circular angle wrapping."""

    def test_wrapping_near_pi(self):
        """Headings near +pi and -pi should have small error, not ~2*pi."""
        from pipeline.metrics import compute_orientation_error
        err = compute_orientation_error(3.1, -3.1)
        assert err < 0.2, f"Expected small error near ±π, got {err}"
        assert err > 0.0

    def test_same_angle(self):
        from pipeline.metrics import compute_orientation_error
        assert abs(compute_orientation_error(1.5, 1.5)) < 1e-10

    def test_opposite_directions(self):
        from pipeline.metrics import compute_orientation_error
        err = compute_orientation_error(0.0, np.pi)
        assert abs(err - np.pi) < 0.01

    def test_output_in_range(self):
        """Error must be in [0, pi] for any pair of angles."""
        from pipeline.metrics import compute_orientation_error
        rng = np.random.RandomState(789)
        for _ in range(30):
            y1 = rng.uniform(-np.pi, np.pi)
            y2 = rng.uniform(-np.pi, np.pi)
            err = compute_orientation_error(y1, y2)
            assert 0 <= err <= np.pi + 1e-6, f"Error {err} outside [0,π]"

    def test_symmetry(self):
        from pipeline.metrics import compute_orientation_error
        err1 = compute_orientation_error(1.0, 2.5)
        err2 = compute_orientation_error(2.5, 1.0)
        assert abs(err1 - err2) < 1e-10

    def test_known_value(self):
        """90-degree difference should give π/2."""
        from pipeline.metrics import compute_orientation_error
        err = compute_orientation_error(0.0, np.pi / 2)
        assert abs(err - np.pi / 2) < 0.001


# ============================================================
# Unit tests: Composite Detection Score (Bug 6 — mean vs sum)
# ============================================================

class TestCompositeScore:
    """Verify CDS uses mean of TP measures, not sum."""

    def test_perfect(self):
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        cds = compute_composite_score(1.0, 0.0, 0.0, 0.0, tp_norms)
        assert abs(cds - 1.0) < 0.01

    def test_zero_ap(self):
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        cds = compute_composite_score(0.0, 1.0, 0.5, 1.0, tp_norms)
        assert abs(cds) < 0.01

    def test_mean_not_sum(self):
        """CDS must use mean of TP measures, keeping CDS in [0,1]."""
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        # ATM = 1 - 1.0/2.0 = 0.5
        # ASM = 1 - 0.5/1.0 = 0.5
        # AOM = 1 - (π/2)/π = 0.5
        # mean = 0.5 → CDS = 1.0 * 0.5 = 0.5  (sum would give 1.5)
        cds = compute_composite_score(1.0, 1.0, 0.5, np.pi / 2, tp_norms)
        assert abs(cds - 0.5) < 0.02, f"Expected CDS≈0.5, got {cds}"
        assert cds <= 1.0 + 1e-6, (
            "CDS > 1 indicates sum was used instead of mean")

    def test_cds_range(self):
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        rng = np.random.RandomState(456)
        for _ in range(30):
            ap = rng.uniform(0, 1)
            ate = rng.uniform(0, 2)
            ase = rng.uniform(0, 1)
            aoe = rng.uniform(0, np.pi)
            cds = compute_composite_score(ap, ate, ase, aoe, tp_norms)
            assert 0 <= cds <= 1.0 + 1e-6, f"CDS={cds} outside [0,1]"

    def test_clamping(self):
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        cds = compute_composite_score(1.0, 3.0, 1.5, 4.0, tp_norms)
        assert cds >= 0.0


# ============================================================
# Unit tests: Configuration (Bug 2 — YAML override)
# ============================================================

class TestConfig:
    """Verify configuration loads the correct protocol values."""

    def test_tp_threshold_is_2(self):
        """Per spec Section 5, tp_threshold_m must be 2.0."""
        from pipeline.config import load_config
        config = load_config()
        assert config['evaluation']['tp_threshold_m'] == 2.0, (
            f"tp_threshold_m = {config['evaluation']['tp_threshold_m']}, "
            "expected 2.0 per specification")

    def test_affinity_thresholds(self):
        from pipeline.config import load_config
        config = load_config()
        expected = [0.5, 1.0, 2.0, 4.0]
        assert config['evaluation']['affinity_thresholds_m'] == expected

    def test_tp_norms_present(self):
        from pipeline.config import load_config
        config = load_config()
        norms = config['evaluation']['tp_norms']
        assert 'ATE' in norms and 'ASE' in norms and 'AOE' in norms
        assert abs(norms['ATE'] - 2.0) < 0.01
        assert abs(norms['ASE'] - 1.0) < 0.01
        assert abs(norms['AOE'] - math.pi) < 0.01


# ============================================================
# End-to-end tests: run evaluator on dataset
# ============================================================

@pytest.fixture(scope="module")
def run_eval():
    result = subprocess.run(
        ["python3", "/app/run_eval.py"],
        capture_output=True, text=True, timeout=120, cwd="/app")
    return result


@pytest.fixture(scope="module")
def results(run_eval):
    assert run_eval.returncode == 0, (
        f"Evaluator failed with code {run_eval.returncode}.\n"
        f"stderr: {run_eval.stderr}")
    with open("/app/results.json") as f:
        return json.load(f)


class TestEndToEnd:
    """Verify end-to-end evaluation output on the dataset."""

    EXPECTED_CATEGORIES = {
        "REGULAR_VEHICLE", "PEDESTRIAN", "BICYCLE", "BUS", "MOTORCYCLIST"}

    def test_evaluator_succeeds(self, run_eval):
        assert run_eval.returncode == 0, f"stderr: {run_eval.stderr}"

    def test_results_file_exists(self, run_eval):
        assert os.path.isfile("/app/results.json")

    def test_expected_categories(self, results):
        cats = set(results.keys()) - {"AVERAGE_METRICS"}
        assert cats == self.EXPECTED_CATEGORIES

    def test_has_average_metrics(self, results):
        assert "AVERAGE_METRICS" in results

    def test_all_metrics_present(self, results):
        required = {"AP", "ATE", "ASE", "AOE", "CDS"}
        for cat, metrics in results.items():
            assert required.issubset(set(metrics.keys())), (
                f"{cat} missing: {required - set(metrics.keys())}")

    def test_cds_in_range(self, results):
        for cat, m in results.items():
            assert 0 <= m["CDS"] <= 1.0 + 1e-4, (
                f"CDS for {cat} = {m['CDS']} outside [0,1]")

    def test_ap_in_range(self, results):
        for cat, m in results.items():
            assert 0 <= m["AP"] <= 1.0 + 1e-4, (
                f"AP for {cat} = {m['AP']} outside [0,1]")

    def test_aoe_in_range(self, results):
        for cat, m in results.items():
            assert 0 <= m["AOE"] <= math.pi + 0.01, (
                f"AOE for {cat} = {m['AOE']} exceeds π")

    def test_ase_in_range(self, results):
        for cat, m in results.items():
            assert 0 <= m["ASE"] <= 1.0 + 1e-4

    def test_ate_in_range(self, results):
        for cat, m in results.items():
            assert 0 <= m["ATE"] <= 2.0 + 1e-4

    def test_average_is_mean(self, results):
        cats = [k for k in results if k != "AVERAGE_METRICS"]
        for metric in ["AP", "ATE", "ASE", "AOE", "CDS"]:
            expected = sum(results[c][metric] for c in cats) / len(cats)
            actual = results["AVERAGE_METRICS"][metric]
            assert abs(actual - expected) < 0.01, (
                f"AVERAGE_METRICS/{metric}: mean={expected:.4f}, got={actual}")


# ============================================================
# Cross-validation on controlled micro-scenario
# ============================================================

class TestCrossValidation:
    """Cross-validate function chain on a known micro-scenario."""

    def test_assignment_and_ap(self):
        from pipeline.assignment import greedy_assign
        from pipeline.metrics import compute_average_precision

        gts = [
            {'tx': 10.0, 'ty': 0.0, 'tz': 0.0},
            {'tx': 20.0, 'ty': 0.0, 'tz': 0.0},
            {'tx': 30.0, 'ty': 0.0, 'tz': 0.0},
        ]
        dts = [
            {'tx': 10.5, 'ty': 0.0, 'tz': 0.0, 'score': 0.9},
            {'tx': 20.3, 'ty': 0.0, 'tz': 0.0, 'score': 0.7},
            {'tx': 50.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.5},
            {'tx': 60.0, 'ty': 0.0, 'tz': 0.0, 'score': 0.3},
        ]

        assignments = greedy_assign(dts, gts, 2.0)
        assert len(assignments) == 2
        assert 0 in assignments
        assert 1 in assignments

        tp_flags = np.array([True, True, False, False], dtype=bool)
        ap = compute_average_precision(tp_flags, 3)
        assert 0.60 < ap < 0.72, f"Expected AP ≈ 0.67, got {ap}"

    def test_cds_chain(self):
        from pipeline.metrics import compute_composite_score
        tp_norms = {'ATE': 2.0, 'ASE': 1.0, 'AOE': math.pi}
        cds = compute_composite_score(0.8, 0.5, 0.2, 0.3, tp_norms)
        assert 0.60 < cds < 0.70, f"Expected CDS ≈ 0.655, got {cds}"

    def test_angle_wrapping_cross_check(self):
        from pipeline.metrics import compute_orientation_error
        gt_yaw = 3.0
        dt_yaw = -3.0
        err = compute_orientation_error(dt_yaw, gt_yaw)
        expected = abs(np.arctan2(np.sin(dt_yaw - gt_yaw),
                                   np.cos(dt_yaw - gt_yaw)))
        assert abs(err - expected) < 1e-6
        assert err < 0.5, f"Wrapping failed: error={err}, expected ≈ 0.283"


# ============================================================
# Makefile integration tests (Bug 7 — env var override)
# ============================================================

class TestMakefileIntegration:
    """Verify Makefile orchestration and environment variable handling."""

    def test_makefile_recall_samples_value(self):
        """Makefile must not export EVAL_NUM_RECALL_SAMPLES != 101."""
        with open('/app/Makefile', 'r') as f:
            content = f.read()
        matches = re.findall(
            r'EVAL_NUM_RECALL_SAMPLES\s*[:?]?=\s*(\d+)', content)
        for val_str in matches:
            val = int(val_str)
            assert val == 101, (
                f"Makefile exports EVAL_NUM_RECALL_SAMPLES={val}, "
                "spec requires 101 recall samples")

    def test_make_eval_succeeds(self):
        """make eval must complete successfully after all fixes."""
        result = subprocess.run(
            ["make", "eval"], capture_output=True, text=True,
            timeout=120, cwd="/app")
        assert result.returncode == 0, (
            f"make eval failed:\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}")

    def test_make_eval_produces_valid_results(self):
        """Results from make eval must have valid metric ranges."""
        subprocess.run(
            ["make", "eval"], capture_output=True, text=True,
            timeout=120, cwd="/app")
        assert os.path.isfile("/app/results.json"), (
            "make eval did not produce results.json")
        with open("/app/results.json") as f:
            results = json.load(f)
        for cat, m in results.items():
            assert 0 <= m["CDS"] <= 1.0 + 1e-4, (
                f"{cat} CDS={m['CDS']} outside [0,1]")
            assert 0 <= m["AP"] <= 1.0 + 1e-4, (
                f"{cat} AP={m['AP']} outside [0,1]")


# ============================================================
# Git-annotated audit report validation with severity
# ============================================================

class TestAuditReport:
    """Verify the audit report documents bugs with git commit SHAs and severity."""

    def test_report_exists(self):
        assert os.path.isfile("/app/audit_report.json"), (
            "Missing /app/audit_report.json")

    def test_report_is_valid_json(self):
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        assert isinstance(data, list), "audit_report.json must be a JSON array"

    def test_report_has_minimum_entries(self):
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        assert len(data) >= 6, (
            f"Expected at least 6 bug entries, found {len(data)}")

    def test_report_entry_structure(self):
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        for i, entry in enumerate(data):
            assert "file" in entry, f"Entry {i} missing 'file' field"
            assert "bug" in entry, f"Entry {i} missing 'bug' field"
            assert isinstance(entry["file"], str) and len(entry["file"]) > 0
            assert isinstance(entry["bug"], str) and len(entry["bug"]) > 5

    def test_report_entries_have_commit_sha(self):
        """Each audit entry must include a commit_sha field."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        for i, entry in enumerate(data):
            assert "commit_sha" in entry, (
                f"Entry {i} missing 'commit_sha' field — "
                "use git log/blame to identify introducing commits")
            sha = entry["commit_sha"]
            assert isinstance(sha, str) and len(sha) >= 7, (
                f"Entry {i} commit_sha too short: {sha!r}")
            assert all(c in '0123456789abcdef' for c in sha.lower()), (
                f"Entry {i} commit_sha not valid hex: {sha!r}")

    def test_commit_shas_exist_in_repo(self):
        """All reported commit SHAs must exist in the git repository."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        for entry in data:
            sha = entry["commit_sha"]
            result = subprocess.run(
                ["git", "cat-file", "-t", sha],
                capture_output=True, text=True, cwd="/app")
            assert result.returncode == 0, (
                f"commit_sha {sha} not found in git repo at /app/")

    def test_report_entries_have_severity(self):
        """Each audit entry must include a severity assessment."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        valid_severities = {"critical", "major", "minor"}
        for i, entry in enumerate(data):
            assert "severity" in entry, (
                f"Entry {i} missing 'severity' field")
            assert entry["severity"] in valid_severities, (
                f"Entry {i} severity '{entry['severity']}' not in "
                f"{valid_severities}")

    def test_report_entries_have_severity_justification(self):
        """Each entry must justify its severity rating."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        for i, entry in enumerate(data):
            assert "severity_justification" in entry, (
                f"Entry {i} missing 'severity_justification' field")
            justification = entry["severity_justification"]
            assert isinstance(justification, str) and len(justification) >= 15, (
                f"Entry {i} severity_justification too short: {justification!r}")

    def test_report_has_at_least_one_critical(self):
        """At least one bug must be rated critical given the metric corruption."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        severities = [e.get("severity") for e in data]
        assert "critical" in severities, (
            "No bug rated 'critical' despite fundamental metric corruption")

    def test_report_has_multiple_severity_levels(self):
        """Report should use at least 2 distinct severity levels."""
        with open("/app/audit_report.json") as f:
            data = json.load(f)
        severities = set(e.get("severity") for e in data)
        assert len(severities) >= 2, (
            f"Only {severities} used — severity assessment should "
            "differentiate between bugs with different impacts")


# ============================================================
# Pipeline validator verification
# ============================================================

class TestPipelineValidator:
    """Verify the agent-designed pipeline validator."""

    def test_validator_exists(self):
        """pipeline_validator.py must exist at /app/."""
        assert os.path.isfile("/app/pipeline_validator.py"), (
            "Missing /app/pipeline_validator.py")

    def test_validator_passes_on_fixed_pipeline(self):
        """Validator must exit 0 on the correctly fixed pipeline."""
        result = subprocess.run(
            ["python3", "/app/pipeline_validator.py"],
            capture_output=True, text=True, timeout=60, cwd="/app")
        assert result.returncode == 0, (
            f"pipeline_validator.py failed with exit code "
            f"{result.returncode}:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}")

    def test_validator_has_sufficient_checks(self):
        """Validator must contain at least 8 independent validation checks."""
        with open("/app/pipeline_validator.py") as f:
            content = f.read()
        # Count distinct validation actions: assert statements,
        # check() method calls, or named check/test/validate functions
        indicators = re.findall(
            r'\bassert\s+|\.check\s*\(|(?<!\w)check\s*\('
            r'|^def\s+(?:check|test|validate|verify)_\w+',
            content, re.MULTILINE)
        assert len(indicators) >= 8, (
            f"pipeline_validator.py has {len(indicators)} validation "
            f"points, need >= 8 independent checks")

    def test_validator_is_standalone_script(self):
        """Validator must be a self-contained executable script."""
        with open("/app/pipeline_validator.py") as f:
            content = f.read()
        assert "sys.exit" in content or "exit(" in content, (
            "Validator must use sys.exit() or exit() for return code")
        assert "import" in content, (
            "Validator should import modules it checks")

    def test_validator_checks_multiple_modules(self):
        """Validator should check across multiple pipeline modules."""
        with open("/app/pipeline_validator.py") as f:
            content = f.read()
        module_refs = set()
        if 'preprocessing' in content or 'filter_by_range' in content:
            module_refs.add('preprocessing')
        if 'assignment' in content or 'greedy_assign' in content:
            module_refs.add('assignment')
        if 'metrics' in content or 'compute_' in content:
            module_refs.add('metrics')
        if 'config' in content or 'load_config' in content:
            module_refs.add('config')
        if 'Makefile' in content:
            module_refs.add('makefile')
        assert len(module_refs) >= 3, (
            f"Validator only references {module_refs} — should check "
            f"at least 3 distinct pipeline components")
