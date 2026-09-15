
import sys
import json
import math

import torch

sys.path.insert(0, "/app")

import pytest


@pytest.fixture(scope="module")
def report():
    """Run the analyzer once and return the report for all tests."""
    from model import TargetModel
    from roofline_analyzer import RooflineAnalyzer

    with open("/app/hardware_spec.json") as f:
        hw_spec = json.load(f)

    model = TargetModel()
    model.eval()

    analyzer = RooflineAnalyzer(hw_spec, model=model)
    x = torch.randn(64, 127)
    with torch.no_grad():
        with analyzer:
            _ = model(x)
    r = analyzer.get_report()
    analyzer.remove_hooks()
    return r


# ── Structure ────────────────────────────────────────────────────────────

def test_report_top_level_keys(report):
    required = {
        "total_matmul_flops",
        "total_memory_bytes",
        "overall_arithmetic_intensity",
        "overall_classification",
        "ridge_point",
        "per_module",
        "operations",
    }
    assert required.issubset(report.keys()), (
        f"Missing keys: {required - report.keys()}"
    )


def test_per_module_keys(report):
    expected_modules = {"embed", "fc1", "fc2", "classifier"}
    actual_modules = set(report["per_module"].keys())
    assert expected_modules.issubset(actual_modules), (
        f"Missing modules: {expected_modules - actual_modules}"
    )
    per_mod_keys = {
        "total_flops",
        "total_memory_bytes",
        "arithmetic_intensity",
        "classification",
        "num_matmul_ops",
        "aligned",
    }
    for name in expected_modules:
        assert per_mod_keys.issubset(report["per_module"][name].keys()), (
            f"Module {name} missing keys: "
            f"{per_mod_keys - report['per_module'][name].keys()}"
        )


def test_operations_list(report):
    ops = report["operations"]
    assert len(ops) >= 4, f"Expected >= 4 matmul ops, got {len(ops)}"
    required_op_keys = {
        "op", "module", "flops", "memory_bytes",
        "arithmetic_intensity", "classification", "alignment",
    }
    for i, op in enumerate(ops):
        assert required_op_keys.issubset(op.keys()), (
            f"Op {i} missing keys: {required_op_keys - op.keys()}"
        )
    alignment_keys = {"aligned", "operand_innermost_dims", "suggested_padding"}
    for i, op in enumerate(ops):
        assert alignment_keys.issubset(op["alignment"].keys()), (
            f"Op {i} alignment missing keys: "
            f"{alignment_keys - op['alignment'].keys()}"
        )


# ── FLOP counts ──────────────────────────────────────────────────────────

EXPECTED_FLOPS = {
    "embed": 8_339_328,
    "fc1": 134_479_872,
    "fc2": 134_217_728,
    "classifier": 655_360,
}
EXPECTED_TOTAL_FLOPS = sum(EXPECTED_FLOPS.values())


def test_total_flops(report):
    assert report["total_matmul_flops"] == EXPECTED_TOTAL_FLOPS, (
        f"Expected total FLOPs {EXPECTED_TOTAL_FLOPS}, "
        f"got {report['total_matmul_flops']}"
    )


def test_per_module_flops(report):
    for name, expected in EXPECTED_FLOPS.items():
        actual = report["per_module"][name]["total_flops"]
        assert actual == expected, (
            f"Module {name}: expected {expected} FLOPs, got {actual}"
        )


# ── Memory bytes ─────────────────────────────────────────────────────────

EXPECTED_MEM = {
    "embed": 424_444,
    "fc1": 4_866_304,
    "fc2": 4_851_712,
    "classifier": 154_152,
}


def test_per_module_memory_bytes(report):
    for name, expected in EXPECTED_MEM.items():
        actual = report["per_module"][name]["total_memory_bytes"]
        low = int(expected * 0.98)
        high = int(expected * 1.02)
        assert low <= actual <= high, (
            f"Module {name}: expected ~{expected} bytes, got {actual}"
        )


# ── Arithmetic intensity & classification ────────────────────────────────

def test_ridge_point(report):
    assert abs(report["ridge_point"] - 20.0) < 0.01, (
        f"Expected ridge_point ~20.0, got {report['ridge_point']}"
    )


def test_per_module_classification(report):
    expected_class = {
        "embed": "memory_bound",
        "fc1": "compute_bound",
        "fc2": "compute_bound",
        "classifier": "memory_bound",
    }
    for name, expected in expected_class.items():
        actual = report["per_module"][name]["classification"]
        assert actual == expected, (
            f"Module {name}: expected '{expected}', got '{actual}'"
        )


def test_overall_classification(report):
    assert report["overall_classification"] == "compute_bound", (
        f"Expected overall 'compute_bound', got {report['overall_classification']}"
    )


def test_arithmetic_intensity_values(report):
    for name in EXPECTED_FLOPS:
        ai = report["per_module"][name]["arithmetic_intensity"]
        expected_ai = EXPECTED_FLOPS[name] / EXPECTED_MEM[name]
        assert abs(ai - expected_ai) < 1.0, (
            f"Module {name}: expected AI ~{expected_ai:.2f}, got {ai:.2f}"
        )


# ── Shape alignment ─────────────────────────────────────────────────────

def _find_op_for_module(report, module_name):
    """Find the first operation belonging to a given module."""
    for op in report["operations"]:
        if op["module"] == module_name:
            return op
    raise AssertionError(f"No operation found for module '{module_name}'")


def test_alignment_embed(report):
    mod = report["per_module"]["embed"]
    assert mod["aligned"] is False, "embed should be misaligned (dim 127)"

    op = _find_op_for_module(report, "embed")
    dims = op["alignment"]["operand_innermost_dims"]
    assert all(d == 127 for d in dims), (
        f"embed innermost dims should all be 127, got {dims}"
    )
    assert op["alignment"]["aligned"] is False
    padding = op["alignment"]["suggested_padding"]
    assert padding is not None
    assert all(p == 128 for p in padding), (
        f"embed padding should be 128, got {padding}"
    )


def test_alignment_fc1(report):
    mod = report["per_module"]["fc1"]
    assert mod["aligned"] is False, "fc1 should be misaligned (dim 513)"

    op = _find_op_for_module(report, "fc1")
    dims = op["alignment"]["operand_innermost_dims"]
    assert all(d == 513 for d in dims), (
        f"fc1 innermost dims should all be 513, got {dims}"
    )
    assert op["alignment"]["aligned"] is False
    padding = op["alignment"]["suggested_padding"]
    assert padding is not None
    assert all(p == 520 for p in padding), (
        f"fc1 padding should be 520, got {padding}"
    )


def test_alignment_fc2(report):
    mod = report["per_module"]["fc2"]
    assert mod["aligned"] is True, "fc2 should be aligned (dim 2048)"

    op = _find_op_for_module(report, "fc2")
    dims = op["alignment"]["operand_innermost_dims"]
    assert all(d % 8 == 0 for d in dims), (
        f"fc2 innermost dims should all be div by 8, got {dims}"
    )
    assert op["alignment"]["aligned"] is True
    assert op["alignment"]["suggested_padding"] is None


def test_alignment_classifier(report):
    mod = report["per_module"]["classifier"]
    assert mod["aligned"] is True, "classifier should be aligned (dim 512)"

    op = _find_op_for_module(report, "classifier")
    dims = op["alignment"]["operand_innermost_dims"]
    assert all(d % 8 == 0 for d in dims), (
        f"classifier innermost dims should all be div by 8, got {dims}"
    )
    assert op["alignment"]["aligned"] is True
    assert op["alignment"]["suggested_padding"] is None


# ── Num matmul ops per module ────────────────────────────────────────────

def test_num_matmul_ops_per_module(report):
    for name in EXPECTED_FLOPS:
        actual = report["per_module"][name]["num_matmul_ops"]
        assert actual == 1, (
            f"Module {name}: expected 1 matmul op, got {actual}"
        )
