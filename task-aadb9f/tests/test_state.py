
import json
import os
import sys
import math
import pytest

RESULTS_PATH = "/app/results.json"
SPECS_DIR = "/app/specs"
KERNELS_DIR = "/app/kernels"

# ---- Expected prediction values for each workload_id ----
EXPECTED_PREDICTIONS = {
    1: {"active_blocks_per_sm": 3, "active_warps_per_sm": 48,
        "occupancy": 0.75, "limiting_resource": "registers"},
    2: {"active_blocks_per_sm": 9, "active_warps_per_sm": 36,
        "occupancy": 0.5625, "limiting_resource": "registers"},
    3: {"active_blocks_per_sm": 10, "active_warps_per_sm": 40,
        "occupancy": 0.625, "limiting_resource": "shared_memory"},
    4: {"active_blocks_per_sm": 1, "active_warps_per_sm": 16,
        "occupancy": 0.25, "limiting_resource": "shared_memory"},
    5: {"active_blocks_per_sm": 2, "active_warps_per_sm": 32,
        "occupancy": 0.5, "limiting_resource": "registers"},
    6: {"active_blocks_per_sm": 5, "active_warps_per_sm": 40,
        "occupancy": 0.625, "limiting_resource": "registers"},
    7: {"active_blocks_per_sm": 2, "active_warps_per_sm": 32,
        "occupancy": 0.5, "limiting_resource": "shared_memory"},
    8: {"active_blocks_per_sm": 8, "active_warps_per_sm": 64,
        "occupancy": 1.0, "limiting_resource": "warps"},
}

# ---- Validation configs for testing the fixed model directly ----
VALIDATION_CONFIGS = [
    # From measurements
    {"arch": "volta", "kernel": "stencil_3d", "block_size": 256,
     "expected_blocks": 4, "expected_occ": 0.5, "expected_lim": "registers"},
    {"arch": "ampere", "kernel": "matmul_tiled", "block_size": 256,
     "expected_blocks": 6, "expected_occ": 0.75, "expected_lim": "registers"},
    {"arch": "volta", "kernel": "attention", "block_size": 256,
     "expected_error": "invalid_configuration"},
    {"arch": "hopper", "kernel": "reduce_warp", "block_size": 256,
     "expected_blocks": 8, "expected_occ": 1.0, "expected_lim": "warps"},
    # New configs NOT in measurements or workloads (anti-cheating)
    {"arch": "hopper", "kernel": "scan_block", "block_size": 128,
     "expected_blocks": 16, "expected_occ": 1.0, "expected_lim": "warps"},
    {"arch": "volta", "kernel": "conv_shared", "block_size": 128,
     "expected_blocks": 10, "expected_occ": 0.625, "expected_lim": "registers"},
    {"arch": "ampere", "kernel": "reduce_warp", "block_size": 128,
     "expected_blocks": 16, "expected_occ": 1.0, "expected_lim": "warps"},
    {"arch": "hopper", "kernel": "matmul_tiled", "block_size": 512,
     "expected_blocks": 3, "expected_occ": 0.75, "expected_lim": "registers"},
    {"arch": "ampere", "kernel": "fft_radix", "block_size": 512,
     "expected_blocks": 1, "expected_occ": 0.25, "expected_lim": "shared_memory"},
]

# ---- Expected proposal evaluation verdicts ----
EXPECTED_PROPOSALS = {
    1: {"verdict": "improves", "original_occ": 0.625, "proposed_occ": 1.0},
    2: {"verdict": "neutral", "original_occ": 0.5, "proposed_occ": 0.5},
    3: {"verdict": "degrades", "original_occ": 0.75, "proposed_occ": 0.5},
    4: {"verdict": "neutral", "original_occ": 0.75, "proposed_occ": 0.75},
    5: {"verdict": "invalid"},
}

# ---- Expected optimal configurations ----
EXPECTED_OPTIMAL = {
    ("volta", "reduce_warp"): {
        "optimal_block_size": 64, "active_blocks_per_sm": 32,
        "occupancy": 1.0, "limiting_resource": "warps"},
    ("ampere", "fft_radix"): {
        "optimal_block_size": 1024, "active_blocks_per_sm": 1,
        "occupancy": 0.5, "limiting_resource": "registers"},
    ("hopper", "stencil_3d"): {
        "optimal_block_size": 64, "active_blocks_per_sm": 18,
        "occupancy": 0.5625, "limiting_resource": "registers"},
}


def _approx_eq(a, b, tol=1e-4):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < tol
    return a == b


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def predictions(results):
    assert "predictions" in results, "results.json must contain 'predictions' key"
    by_id = {}
    for p in results["predictions"]:
        by_id[p["workload_id"]] = p
    return by_id


@pytest.fixture(scope="module")
def evaluations(results):
    assert "optimization_evaluations" in results, (
        "results.json must contain 'optimization_evaluations' key"
    )
    by_id = {}
    for ev in results["optimization_evaluations"]:
        by_id[ev["proposal_id"]] = ev
    return by_id


@pytest.fixture(scope="module")
def optimal_configs(results):
    assert "optimal_configurations" in results, (
        "results.json must contain 'optimal_configurations' key"
    )
    by_key = {}
    for cfg in results["optimal_configurations"]:
        by_key[(cfg["architecture"], cfg["kernel"])] = cfg
    return by_key


@pytest.fixture(scope="module")
def model_module():
    """Import the (presumably fixed) model.py."""
    sys.path.insert(0, "/app")
    if "model" in sys.modules:
        del sys.modules["model"]
    import model
    return model


class TestResultsSchema:
    """Verify results.json exists and conforms to the required schema."""

    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_has_diagnostics(self, results):
        assert "diagnostics" in results, "Missing 'diagnostics' key"
        assert isinstance(results["diagnostics"], list)
        assert len(results["diagnostics"]) >= 2, (
            "Expected at least 2 diagnostics (code + data issues)"
        )

    def test_diagnostics_schema(self, results):
        for diag in results["diagnostics"]:
            assert "file" in diag, "Each diagnostic must have 'file'"
            assert "issue" in diag, "Each diagnostic must have 'issue'"
            assert "fix" in diag, "Each diagnostic must have 'fix'"

    def test_has_predictions(self, results):
        assert "predictions" in results, "Missing 'predictions' key"
        assert isinstance(results["predictions"], list)
        assert len(results["predictions"]) == 8, (
            f"Expected 8 predictions, got {len(results['predictions'])}"
        )

    def test_prediction_ids_complete(self, predictions):
        for wid in range(1, 9):
            assert wid in predictions, f"Missing prediction for workload_id {wid}"

    def test_has_optimization_evaluations(self, results):
        assert "optimization_evaluations" in results
        assert isinstance(results["optimization_evaluations"], list)
        assert len(results["optimization_evaluations"]) == 5, (
            f"Expected 5 evaluations, got {len(results['optimization_evaluations'])}"
        )

    def test_has_optimal_configurations(self, results):
        assert "optimal_configurations" in results
        assert isinstance(results["optimal_configurations"], list)
        assert len(results["optimal_configurations"]) == 3, (
            f"Expected 3 optimal configs, got {len(results['optimal_configurations'])}"
        )


class TestPredictionValues:
    """Verify each prediction matches the expected correct occupancy."""

    @pytest.mark.parametrize("wid", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_active_blocks(self, predictions, wid):
        assert wid in predictions, f"Missing workload {wid}"
        expected = EXPECTED_PREDICTIONS[wid]
        if "error" in expected:
            assert predictions[wid].get("error") == expected["error"]
            return
        assert predictions[wid]["active_blocks_per_sm"] == expected["active_blocks_per_sm"], (
            f"W{wid}: active_blocks expected {expected['active_blocks_per_sm']}, "
            f"got {predictions[wid]['active_blocks_per_sm']}"
        )

    @pytest.mark.parametrize("wid", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_active_warps(self, predictions, wid):
        assert wid in predictions
        expected = EXPECTED_PREDICTIONS[wid]
        if "error" in expected:
            return
        assert predictions[wid]["active_warps_per_sm"] == expected["active_warps_per_sm"], (
            f"W{wid}: active_warps expected {expected['active_warps_per_sm']}, "
            f"got {predictions[wid]['active_warps_per_sm']}"
        )

    @pytest.mark.parametrize("wid", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_occupancy(self, predictions, wid):
        assert wid in predictions
        expected = EXPECTED_PREDICTIONS[wid]
        if "error" in expected:
            return
        assert _approx_eq(predictions[wid]["occupancy"], expected["occupancy"]), (
            f"W{wid}: occupancy expected {expected['occupancy']}, "
            f"got {predictions[wid]['occupancy']}"
        )

    @pytest.mark.parametrize("wid", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_limiting_resource(self, predictions, wid):
        assert wid in predictions
        expected = EXPECTED_PREDICTIONS[wid]
        if "error" in expected:
            return
        assert predictions[wid]["limiting_resource"] == expected["limiting_resource"], (
            f"W{wid}: limiting_resource expected {expected['limiting_resource']}, "
            f"got {predictions[wid]['limiting_resource']}"
        )


class TestModelValidation:
    """Import the fixed model and run it on validation configs directly."""

    @pytest.mark.parametrize("idx", range(len(VALIDATION_CONFIGS)))
    def test_model_prediction(self, model_module, idx):
        cfg = VALIDATION_CONFIGS[idx]
        arch = model_module.load_arch_spec(SPECS_DIR, cfg["arch"])
        kernel = model_module.load_kernel_spec(KERNELS_DIR, cfg["kernel"])
        result = model_module.compute_occupancy(arch, kernel, cfg["block_size"])

        desc = f"{cfg['arch']}/{cfg['kernel']}/bs={cfg['block_size']}"

        if "expected_error" in cfg:
            assert "error" in result, (
                f"{desc}: expected error '{cfg['expected_error']}', got {result}"
            )
            assert result["error"] == cfg["expected_error"]
        else:
            assert "error" not in result, (
                f"{desc}: expected valid config, got error: {result}"
            )
            assert result["active_blocks_per_sm"] == cfg["expected_blocks"], (
                f"{desc}: blocks expected {cfg['expected_blocks']}, "
                f"got {result['active_blocks_per_sm']}"
            )
            assert _approx_eq(result["occupancy"], cfg["expected_occ"]), (
                f"{desc}: occupancy expected {cfg['expected_occ']}, "
                f"got {result['occupancy']}"
            )
            assert result["limiting_resource"] == cfg["expected_lim"], (
                f"{desc}: limiting expected {cfg['expected_lim']}, "
                f"got {result['limiting_resource']}"
            )


class TestSpecCorrections:
    """Verify architecture specification files have been corrected."""

    def test_ampere_register_alloc_unit(self):
        with open(os.path.join(SPECS_DIR, "ampere.json")) as f:
            spec = json.load(f)
        assert spec["register_alloc_unit_size"] == 256, (
            f"Ampere register_alloc_unit_size should be 256, "
            f"got {spec['register_alloc_unit_size']}"
        )

    def test_ampere_max_smem_per_block(self):
        with open(os.path.join(SPECS_DIR, "ampere.json")) as f:
            spec = json.load(f)
        assert spec["max_shared_memory_per_block"] == 167936, (
            f"Ampere max_shared_memory_per_block should be 167936, "
            f"got {spec['max_shared_memory_per_block']}"
        )

    def test_volta_unchanged(self):
        with open(os.path.join(SPECS_DIR, "volta.json")) as f:
            spec = json.load(f)
        assert spec["register_alloc_unit_size"] == 256
        assert spec["max_shared_memory_per_block"] == 49152
        assert spec["max_shared_memory_per_multiprocessor"] == 98304

    def test_hopper_unchanged(self):
        with open(os.path.join(SPECS_DIR, "hopper.json")) as f:
            spec = json.load(f)
        assert spec["register_alloc_unit_size"] == 256
        assert spec["max_shared_memory_per_block"] == 233472


class TestProposalEvaluations:
    """Verify optimization proposal evaluations are correct."""

    @pytest.mark.parametrize("pid", [1, 2, 3, 4, 5])
    def test_proposal_verdict(self, evaluations, pid):
        assert pid in evaluations, f"Missing evaluation for proposal_id {pid}"
        expected = EXPECTED_PROPOSALS[pid]
        assert evaluations[pid]["verdict"] == expected["verdict"], (
            f"P{pid}: verdict expected '{expected['verdict']}', "
            f"got '{evaluations[pid]['verdict']}'"
        )

    @pytest.mark.parametrize("pid", [1, 2, 3, 4])
    def test_proposal_original_occupancy(self, evaluations, pid):
        expected = EXPECTED_PROPOSALS[pid]
        assert _approx_eq(
            evaluations[pid]["original_occupancy"], expected["original_occ"]
        ), (
            f"P{pid}: original_occupancy expected {expected['original_occ']}, "
            f"got {evaluations[pid]['original_occupancy']}"
        )

    @pytest.mark.parametrize("pid", [1, 2, 3, 4])
    def test_proposal_proposed_occupancy(self, evaluations, pid):
        expected = EXPECTED_PROPOSALS[pid]
        assert _approx_eq(
            evaluations[pid]["proposed_occupancy"], expected["proposed_occ"]
        ), (
            f"P{pid}: proposed_occupancy expected {expected['proposed_occ']}, "
            f"got {evaluations[pid]['proposed_occupancy']}"
        )


class TestOptimalConfigurations:
    """Verify optimal block size configurations from results.json."""

    @pytest.mark.parametrize("arch,kernel", [
        ("volta", "reduce_warp"),
        ("ampere", "fft_radix"),
        ("hopper", "stencil_3d"),
    ])
    def test_optimal_block_size(self, optimal_configs, arch, kernel):
        key = (arch, kernel)
        assert key in optimal_configs, f"Missing optimal config for {arch}/{kernel}"
        expected = EXPECTED_OPTIMAL[key]
        cfg = optimal_configs[key]
        assert cfg["optimal_block_size"] == expected["optimal_block_size"], (
            f"{arch}/{kernel}: block_size expected {expected['optimal_block_size']}, "
            f"got {cfg['optimal_block_size']}"
        )

    @pytest.mark.parametrize("arch,kernel", [
        ("volta", "reduce_warp"),
        ("ampere", "fft_radix"),
        ("hopper", "stencil_3d"),
    ])
    def test_optimal_blocks_per_sm(self, optimal_configs, arch, kernel):
        key = (arch, kernel)
        expected = EXPECTED_OPTIMAL[key]
        cfg = optimal_configs[key]
        assert cfg["active_blocks_per_sm"] == expected["active_blocks_per_sm"], (
            f"{arch}/{kernel}: blocks expected {expected['active_blocks_per_sm']}, "
            f"got {cfg['active_blocks_per_sm']}"
        )

    @pytest.mark.parametrize("arch,kernel", [
        ("volta", "reduce_warp"),
        ("ampere", "fft_radix"),
        ("hopper", "stencil_3d"),
    ])
    def test_optimal_occupancy(self, optimal_configs, arch, kernel):
        key = (arch, kernel)
        expected = EXPECTED_OPTIMAL[key]
        cfg = optimal_configs[key]
        assert _approx_eq(cfg["occupancy"], expected["occupancy"]), (
            f"{arch}/{kernel}: occupancy expected {expected['occupancy']}, "
            f"got {cfg['occupancy']}"
        )


class TestFindOptimalBlockSizeFunction:
    """Call find_optimal_block_size directly to prevent hardcoding."""

    def test_function_exists(self, model_module):
        assert hasattr(model_module, "find_optimal_block_size"), (
            "model.py must define find_optimal_block_size(arch, kernel)"
        )

    @pytest.mark.parametrize("arch_name,kernel_name,expected", [
        ("volta", "reduce_warp",
         {"optimal_block_size": 64, "active_blocks_per_sm": 32,
          "occupancy": 1.0, "limiting_resource": "warps"}),
        ("ampere", "fft_radix",
         {"optimal_block_size": 1024, "active_blocks_per_sm": 1,
          "occupancy": 0.5, "limiting_resource": "registers"}),
        ("hopper", "stencil_3d",
         {"optimal_block_size": 64, "active_blocks_per_sm": 18,
          "occupancy": 0.5625, "limiting_resource": "registers"}),
    ])
    def test_optimal_from_files(self, model_module, arch_name, kernel_name, expected):
        arch = model_module.load_arch_spec(SPECS_DIR, arch_name)
        kernel = model_module.load_kernel_spec(KERNELS_DIR, kernel_name)
        result = model_module.find_optimal_block_size(arch, kernel)

        desc = f"{arch_name}/{kernel_name}"
        assert "error" not in result, f"{desc}: unexpected error: {result}"
        assert result["optimal_block_size"] == expected["optimal_block_size"], (
            f"{desc}: block_size expected {expected['optimal_block_size']}, "
            f"got {result['optimal_block_size']}"
        )
        assert result["active_blocks_per_sm"] == expected["active_blocks_per_sm"], (
            f"{desc}: blocks expected {expected['active_blocks_per_sm']}, "
            f"got {result['active_blocks_per_sm']}"
        )
        assert _approx_eq(result["occupancy"], expected["occupancy"]), (
            f"{desc}: occupancy expected {expected['occupancy']}, "
            f"got {result['occupancy']}"
        )

    def test_optimal_synthetic_kernel(self, model_module):
        """Test with a synthetic kernel not in any file to prevent hardcoding."""
        arch = model_module.load_arch_spec(SPECS_DIR, "volta")
        synthetic_kernel = {
            "name": "synthetic_test",
            "registers_per_thread": 16,
            "shared_memory_bytes": 0,
        }
        result = model_module.find_optimal_block_size(arch, synthetic_kernel)
        assert "error" not in result, f"Unexpected error: {result}"
        # regs=16, smem=0 on volta: max occ=1.0 at bs=64 (32 blocks)
        assert result["optimal_block_size"] == 64, (
            f"Synthetic: block_size expected 64, got {result['optimal_block_size']}"
        )
        assert result["active_blocks_per_sm"] == 32, (
            f"Synthetic: blocks expected 32, got {result['active_blocks_per_sm']}"
        )
        assert _approx_eq(result["occupancy"], 1.0), (
            f"Synthetic: occupancy expected 1.0, got {result['occupancy']}"
        )
