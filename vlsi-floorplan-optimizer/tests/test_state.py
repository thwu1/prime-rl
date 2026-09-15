"""
Tests for VLSI Floorplan Optimizer with EDA Tool Pipeline.
Verifies placement quality, METIS partition output, Bookshelf format, and gnuplot visualization.

"""

import importlib.util
import json
import os
import sys

import pytest

sys.path.insert(0, "/app")
from evaluator import evaluate_solution, compute_total_score

SCORE_THRESHOLD = 3.0
OUTPUT_DIR = "/app/output"


def _load_optimizer():
    spec = importlib.util.spec_from_file_location("optimizer", "/app/optimizer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FloorplanOptimizer()


def _load_instances():
    instances = []
    d = "/app/instances"
    for fname in sorted(os.listdir(d)):
        if fname.endswith(".json"):
            with open(os.path.join(d, fname)) as f:
                instances.append(json.load(f))
    return instances


@pytest.fixture(scope="module")
def optimizer():
    return _load_optimizer()


@pytest.fixture(scope="module")
def instances():
    return _load_instances()


@pytest.fixture(scope="module")
def all_results(optimizer, instances):
    results = []
    for inst in instances:
        placement = optimizer.solve(inst)
        result = evaluate_solution(inst, placement)
        result["block_count"] = inst["block_count"]
        result["name"] = inst["name"]
        results.append(result)
    return results


def test_optimizer_exists():
    assert os.path.exists("/app/optimizer.py"), (
        "optimizer.py must exist at /app/optimizer.py"
    )


def test_instances_exist():
    d = "/app/instances"
    assert os.path.isdir(d), "/app/instances directory must exist"
    jsons = [f for f in os.listdir(d) if f.endswith(".json")]
    assert len(jsons) >= 5, f"Expected >= 5 instances, found {len(jsons)}"


def test_all_feasible(all_results):
    for r in all_results:
        assert r["feasible"], (
            f"Instance {r['name']}: infeasible — {r.get('error', 'unknown')}"
        )


def test_no_infeasible_cost(all_results):
    for r in all_results:
        assert r["cost"] < 10.0, (
            f"Instance {r['name']}: cost={r['cost']:.4f} (infeasible)"
        )


def test_total_score(all_results):
    pairs = [(r["block_count"], r["cost"]) for r in all_results]
    score = compute_total_score(pairs)
    assert score <= SCORE_THRESHOLD, (
        f"Total score {score:.4f} exceeds threshold {SCORE_THRESHOLD}"
    )


def test_output_directory_exists(all_results):
    """Output directory must exist after solving all instances."""
    assert os.path.isdir(OUTPUT_DIR), f"{OUTPUT_DIR} directory must exist"


def test_metis_graph_files(all_results, instances):
    """METIS graph files must exist with valid format for each instance."""
    for inst in instances:
        name = inst["name"]
        n = inst["block_count"]
        metis_path = os.path.join(OUTPUT_DIR, f"{name}.metis")
        assert os.path.exists(metis_path), f"METIS graph file missing: {metis_path}"

        with open(metis_path) as f:
            lines = f.readlines()

        # Header: n m [fmt]
        header = lines[0].strip().split()
        assert len(header) >= 2, (
            f"METIS header must have >= 2 values: got '{lines[0].strip()}'"
        )
        assert int(header[0]) == n, (
            f"METIS vertex count {header[0]} != block_count {n}"
        )

        # Must have header + n adjacency lines
        assert len(lines) >= n + 1, (
            f"METIS file has {len(lines)} lines, expected >= {n + 1}"
        )

        # Adjacency lines must have pairs of integers (neighbor weight)
        for i in range(1, n + 1):
            tokens = lines[i].strip().split()
            if tokens:
                assert len(tokens) % 2 == 0, (
                    f"METIS line {i}: edge-weight format requires pairs, "
                    f"got {len(tokens)} tokens"
                )


def test_metis_partition_files(all_results, instances):
    """METIS partition output files must exist with correct vertex count."""
    for inst in instances:
        name = inst["name"]
        n = inst["block_count"]

        part_files = [f for f in os.listdir(OUTPUT_DIR)
                      if f.startswith(f"{name}.metis.part.")]
        assert len(part_files) >= 1, (
            f"No METIS partition file for instance '{name}'"
        )

        part_path = os.path.join(OUTPUT_DIR, part_files[0])
        with open(part_path) as f:
            partition_lines = [line.strip() for line in f if line.strip()]

        assert len(partition_lines) == n, (
            f"Partition file has {len(partition_lines)} lines, expected {n}"
        )

        # All values must be non-negative integers
        for i, line in enumerate(partition_lines):
            assert line.isdigit(), (
                f"Partition line {i} not a valid integer: '{line}'"
            )


def test_bookshelf_pl_files(all_results, instances):
    """Bookshelf .pl files must exist with valid UCLA format."""
    for inst in instances:
        name = inst["name"]
        n = inst["block_count"]
        pl_path = os.path.join(OUTPUT_DIR, f"{name}.pl")
        assert os.path.exists(pl_path), f"Bookshelf .pl missing: {pl_path}"

        with open(pl_path) as f:
            lines = [line.strip() for line in f if line.strip()]

        # First line: UCLA pl header
        assert lines[0].startswith("UCLA pl"), (
            f"Bookshelf .pl must start with 'UCLA pl': got '{lines[0]}'"
        )

        # Block entries (skip header and any comment lines)
        block_lines = [l for l in lines[1:] if not l.startswith("#")]
        assert len(block_lines) == n, (
            f"Bookshelf .pl has {len(block_lines)} block entries, expected {n}"
        )

        # Validate format: name x y : orientation [/FIXED]
        for line in block_lines:
            parts = line.split()
            assert len(parts) >= 5, (
                f"Bookshelf .pl line too short: '{line}'"
            )
            assert parts[3] == ":", (
                f"Expected ':' separator at position 3: '{line}'"
            )
            # x and y must be parseable as floats
            try:
                float(parts[1])
                float(parts[2])
            except ValueError:
                pytest.fail(f"Non-numeric coordinates in: '{line}'")


def test_gnuplot_png_files(all_results, instances):
    """Gnuplot PNG visualizations must exist and be valid PNG files."""
    for inst in instances:
        name = inst["name"]
        png_path = os.path.join(OUTPUT_DIR, f"{name}.png")
        assert os.path.exists(png_path), f"Gnuplot PNG missing: {png_path}"

        size = os.path.getsize(png_path)
        assert size > 100, (
            f"PNG file too small ({size} bytes): {png_path}"
        )

        # Verify PNG magic bytes
        with open(png_path, "rb") as f:
            magic = f.read(4)
        assert magic == b'\x89PNG', (
            f"Invalid PNG header in {png_path}: got {magic!r}"
        )
