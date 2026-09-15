
import json
import os
import pytest

RESULTS_PATH = "/app/results.json"
TOL = 1e-4


@pytest.fixture(scope="module")
def results():
    assert os.path.isfile(RESULTS_PATH), f"results.json not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "hardware_parameters" in data, "results.json must contain 'hardware_parameters'"
    assert "architecture_mapping" in data, "results.json must contain 'architecture_mapping'"
    assert "corrupted_row_ids" in data, "results.json must contain 'corrupted_row_ids'"
    assert "optimal_configs" in data, "results.json must contain 'optimal_configs'"
    return data


# ═══════════════════════════════════════════════════════════════
# Hardware parameter verification
# ═══════════════════════════════════════════════════════════════

EXPECTED_HW = {
    "GPU_A": {"max_warps_per_sm": 64, "max_blocks_per_sm": 32, "total_shared_mem_per_sm": 98304, "shared_mem_alloc_granularity": 256, "register_alloc_granularity": 256},
    "GPU_B": {"max_warps_per_sm": 32, "max_blocks_per_sm": 16, "total_shared_mem_per_sm": 65536, "shared_mem_alloc_granularity": 256, "register_alloc_granularity": 256},
    "GPU_C": {"max_warps_per_sm": 64, "max_blocks_per_sm": 32, "total_shared_mem_per_sm": 167936, "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256},
    "GPU_D": {"max_warps_per_sm": 48, "max_blocks_per_sm": 24, "total_shared_mem_per_sm": 102400, "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256},
    "GPU_E": {"max_warps_per_sm": 64, "max_blocks_per_sm": 32, "total_shared_mem_per_sm": 233472, "shared_mem_alloc_granularity": 128, "register_alloc_granularity": 256},
}

ALL_GPUS = ["GPU_A", "GPU_B", "GPU_C", "GPU_D", "GPU_E"]
HW_PARAMS = ["max_warps_per_sm", "max_blocks_per_sm", "total_shared_mem_per_sm",
             "shared_mem_alloc_granularity", "register_alloc_granularity"]


@pytest.mark.parametrize("gpu_id", ALL_GPUS)
@pytest.mark.parametrize("param", HW_PARAMS)
def test_hardware_parameter(results, gpu_id, param):
    assert gpu_id in results["hardware_parameters"], f"Missing GPU {gpu_id}"
    actual = results["hardware_parameters"][gpu_id][param]
    expected = EXPECTED_HW[gpu_id][param]
    assert actual == expected, (
        f"{gpu_id}/{param}: expected {expected}, got {actual}"
    )


def test_hardware_completeness(results):
    """All GPUs and all parameters must be present."""
    for gid in ALL_GPUS:
        assert gid in results["hardware_parameters"], f"Missing {gid}"
        for p in HW_PARAMS:
            assert p in results["hardware_parameters"][gid], f"Missing {gid}/{p}"


# ═══════════════════════════════════════════════════════════════
# Architecture mapping verification
# ═══════════════════════════════════════════════════════════════

EXPECTED_ARCH = {
    "GPU_A": "sm_70",
    "GPU_B": "sm_75",
    "GPU_C": "sm_80",
    "GPU_D": "sm_89",
    "GPU_E": "sm_90",
}


@pytest.mark.parametrize("gpu_id", ALL_GPUS)
def test_architecture_mapping(results, gpu_id):
    actual = results["architecture_mapping"][gpu_id]
    expected = EXPECTED_ARCH[gpu_id]
    assert actual == expected, (
        f"{gpu_id}: expected architecture {expected}, got {actual}"
    )


# ═══════════════════════════════════════════════════════════════
# Corrupted row detection verification
# ═══════════════════════════════════════════════════════════════

EXPECTED_CORRUPTED = [41, 53, 57, 64, 85, 109, 118, 130]


def test_corrupted_row_ids(results):
    actual = sorted(results["corrupted_row_ids"])
    assert actual == EXPECTED_CORRUPTED, (
        f"Corrupted rows mismatch.\n"
        f"  Expected: {EXPECTED_CORRUPTED}\n"
        f"  Got:      {actual}\n"
        f"  Missing:  {sorted(set(EXPECTED_CORRUPTED) - set(actual))}\n"
        f"  Extra:    {sorted(set(actual) - set(EXPECTED_CORRUPTED))}"
    )


def test_corrupted_count(results):
    actual = results["corrupted_row_ids"]
    assert len(actual) == len(EXPECTED_CORRUPTED), (
        f"Expected {len(EXPECTED_CORRUPTED)} corrupted rows, got {len(actual)}"
    )


# ═══════════════════════════════════════════════════════════════
# Optimal configuration verification
# ═══════════════════════════════════════════════════════════════

EXPECTED_OPTIMAL = {
    "TK1_gemm": {
        "GPU_A": {"optimal_block_size": 672, "predicted_occupancy": 0.65625},
        "GPU_B": {"optimal_block_size": 1024, "predicted_occupancy": 1.0},
        "GPU_C": {"optimal_block_size": 672, "predicted_occupancy": 0.65625},
        "GPU_D": {"optimal_block_size": 672, "predicted_occupancy": 0.875},
        "GPU_E": {"optimal_block_size": 672, "predicted_occupancy": 0.65625},
    },
    "TK2_softmax": {
        "GPU_A": {"optimal_block_size": 576, "predicted_occupancy": 0.5625},
        "GPU_B": {"optimal_block_size": 1024, "predicted_occupancy": 1.0},
        "GPU_C": {"optimal_block_size": 576, "predicted_occupancy": 0.5625},
        "GPU_D": {"optimal_block_size": 576, "predicted_occupancy": 0.75},
        "GPU_E": {"optimal_block_size": 576, "predicted_occupancy": 0.5625},
    },
    "TK3_layernorm": {
        "GPU_A": {"optimal_block_size": 544, "predicted_occupancy": 0.796875},
        "GPU_B": {"optimal_block_size": 1024, "predicted_occupancy": 1.0},
        "GPU_C": {"optimal_block_size": 544, "predicted_occupancy": 0.796875},
        "GPU_D": {"optimal_block_size": 768, "predicted_occupancy": 1.0},
        "GPU_E": {"optimal_block_size": 544, "predicted_occupancy": 0.796875},
    },
    "TK4_conv2d": {
        "GPU_A": {"optimal_block_size": 896, "predicted_occupancy": 0.4375},
        "GPU_B": {"optimal_block_size": 896, "predicted_occupancy": 0.875},
        "GPU_C": {"optimal_block_size": 896, "predicted_occupancy": 0.4375},
        "GPU_D": {"optimal_block_size": 896, "predicted_occupancy": 0.583333},
        "GPU_E": {"optimal_block_size": 896, "predicted_occupancy": 0.4375},
    },
}

ALL_KERNELS = ["TK1_gemm", "TK2_softmax", "TK3_layernorm", "TK4_conv2d"]


@pytest.mark.parametrize("kernel_id", ALL_KERNELS)
@pytest.mark.parametrize("gpu_id", ALL_GPUS)
def test_optimal_block_size(results, kernel_id, gpu_id):
    entry = results["optimal_configs"][kernel_id][gpu_id]
    expected = EXPECTED_OPTIMAL[kernel_id][gpu_id]
    assert entry["optimal_block_size"] == expected["optimal_block_size"], (
        f"{kernel_id}/{gpu_id}: expected block_size={expected['optimal_block_size']}, "
        f"got {entry['optimal_block_size']}"
    )


@pytest.mark.parametrize("kernel_id", ALL_KERNELS)
@pytest.mark.parametrize("gpu_id", ALL_GPUS)
def test_optimal_occupancy(results, kernel_id, gpu_id):
    entry = results["optimal_configs"][kernel_id][gpu_id]
    expected = EXPECTED_OPTIMAL[kernel_id][gpu_id]
    assert abs(entry["predicted_occupancy"] - expected["predicted_occupancy"]) < TOL, (
        f"{kernel_id}/{gpu_id}: expected occupancy={expected['predicted_occupancy']}, "
        f"got {entry['predicted_occupancy']}"
    )


def test_optimal_completeness(results):
    """All kernels and GPUs must be present in optimal configs."""
    for kid in ALL_KERNELS:
        assert kid in results["optimal_configs"], f"Missing kernel {kid}"
        for gid in ALL_GPUS:
            assert gid in results["optimal_configs"][kid], (
                f"Missing {gid} for kernel {kid}"
            )


def test_optimal_block_sizes_are_warp_aligned(results):
    """All optimal block sizes must be multiples of 32."""
    for kid in ALL_KERNELS:
        for gid in ALL_GPUS:
            bs = results["optimal_configs"][kid][gid]["optimal_block_size"]
            assert bs > 0, f"{kid}/{gid}: block_size must be positive"
            assert bs % 32 == 0, f"{kid}/{gid}: block_size {bs} not warp-aligned"
            assert bs <= 1024, f"{kid}/{gid}: block_size {bs} exceeds max"


def test_optimal_occupancy_range(results):
    """All predicted occupancies must be in (0.0, 1.0]."""
    for kid in ALL_KERNELS:
        for gid in ALL_GPUS:
            occ = results["optimal_configs"][kid][gid]["predicted_occupancy"]
            assert 0.0 < occ <= 1.0, f"{kid}/{gid}: occupancy {occ} out of range"
