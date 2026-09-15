
"""
Tests for the Census Data Privatization Pipeline.
Verifies output formats, mathematical correctness, structural constraints,
and pipeline generality (anti-cheat).
"""

import json
import os
import shutil
import subprocess
from functools import reduce

import numpy as np
import pytest

CONFIG_PATH = "/app/config.json"
DATA_DIR = "/app/data"
OUTPUT_DIR = "/app/output"
SYNTH_DIR = "/app/output/synthetic"
PIPELINE = "/app/pipeline.py"


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def true_data():
    data = {}
    for fname in os.listdir(DATA_DIR):
        if fname.endswith(".json"):
            geo = fname[:-5]
            with open(os.path.join(DATA_DIR, fname)) as f:
                data[geo] = np.array(json.load(f), dtype=int)
    return data


@pytest.fixture(scope="session")
def sensitivities():
    path = os.path.join(OUTPUT_DIR, "sensitivities.json")
    assert os.path.exists(path), "sensitivities.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def budget():
    path = os.path.join(OUTPUT_DIR, "budget.json")
    assert os.path.exists(path), "budget.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def synthetic(config):
    data = {}
    hierarchy = config["hierarchy"]
    tree = hierarchy["tree"]
    root = hierarchy["root"]
    all_geos = _collect_all_geos(config)
    for geo in all_geos:
        path = os.path.join(SYNTH_DIR, f"{geo}.json")
        assert os.path.exists(path), f"synthetic/{geo}.json not found"
        with open(path) as f:
            data[geo] = np.array(json.load(f))
    return data


# ---- Helpers ----

def _collect_all_geos(cfg):
    tree = cfg["hierarchy"]["tree"]
    root = cfg["hierarchy"]["root"]
    result = [root]
    queue = [root]
    while queue:
        g = queue.pop(0)
        if g in tree:
            for c in tree[g]:
                result.append(c)
                queue.append(c)
    return result


def _compute_zero_flat_indices(cfg):
    dim_sizes = cfg["schema"]["dim_sizes"]
    indices = set()
    for pos in cfg["constraints"]["structural_zeros"]:
        idx = 0
        for d, p in enumerate(pos):
            stride = int(np.prod(dim_sizes[d + 1:])) if d + 1 < len(dim_sizes) else 1
            idx += p * stride
        indices.add(idx)
    return indices


def _build_operator(dim_sizes, sum_over_dims):
    """Construct the linear query operator from dimension spec."""
    factors = []
    for d, sz in enumerate(dim_sizes):
        if d in sum_over_dims:
            factors.append(np.ones((1, sz)))
        else:
            factors.append(np.eye(sz))
    return reduce(np.kron, factors)


# ---- Pipeline executable ----

class TestPipelineExecutable:
    def test_pipeline_exists(self):
        assert os.path.exists(PIPELINE), f"{PIPELINE} not found"


# ---- Output existence ----

class TestOutputExists:
    def test_sensitivities_file(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "sensitivities.json"))

    def test_budget_file(self):
        assert os.path.exists(os.path.join(OUTPUT_DIR, "budget.json"))

    def test_synthetic_dir(self):
        assert os.path.isdir(SYNTH_DIR)

    def test_all_synthetic_files(self, config):
        for geo in _collect_all_geos(config):
            assert os.path.exists(os.path.join(SYNTH_DIR, f"{geo}.json")), \
                f"Missing synthetic/{geo}.json"


# ---- Sensitivity tests ----

class TestSensitivities:
    def test_all_queries_present(self, config, sensitivities):
        for q in config["queries"]:
            assert q["name"] in sensitivities

    def test_sensitivity_keys(self, config, sensitivities):
        required = {"l1_unbounded", "l2_unbounded", "l1_bounded", "l2_bounded"}
        for q in config["queries"]:
            assert required.issubset(set(sensitivities[q["name"]].keys()))

    def test_sensitivity_values(self, config, sensitivities):
        """Verify sensitivities against independently computed column norms."""
        dim_sizes = config["schema"]["dim_sizes"]
        mult = config["privacy"]["bounded_dp_multiplier"]
        for q in config["queries"]:
            M = _build_operator(dim_sizes, q["sum_over_dims"])
            exp_l1 = float(np.max(np.abs(M).sum(axis=0)))
            exp_l2 = float(np.max(np.sqrt((M ** 2).sum(axis=0))))
            s = sensitivities[q["name"]]
            assert abs(s["l1_unbounded"] - exp_l1) < 1e-10, \
                f"{q['name']} l1_unbounded: {s['l1_unbounded']} != {exp_l1}"
            assert abs(s["l2_unbounded"] - exp_l2) < 1e-10, \
                f"{q['name']} l2_unbounded: {s['l2_unbounded']} != {exp_l2}"
            assert abs(s["l1_bounded"] - exp_l1 * mult) < 1e-10, \
                f"{q['name']} l1_bounded wrong"
            assert abs(s["l2_bounded"] - exp_l2 * mult) < 1e-10, \
                f"{q['name']} l2_bounded wrong"


# ---- Budget tests ----

class TestBudget:
    def test_all_levels_present(self, config, budget):
        for level in config["hierarchy"]["level_names"]:
            assert level in budget

    def test_all_queries_per_level(self, config, budget):
        for level in config["hierarchy"]["level_names"]:
            for q in config["queries"]:
                assert q["name"] in budget[level]

    def test_rho_values(self, config, budget):
        total_rho = config["privacy"]["total_rho"]
        level_props = config["privacy"]["level_proportions"]
        levels = config["hierarchy"]["level_names"]
        for l_idx, level in enumerate(levels):
            rho_level = level_props[l_idx] * total_rho
            for q in config["queries"]:
                expected = q["proportion"] * rho_level
                actual = budget[level][q["name"]]["rho"]
                assert abs(actual - expected) < 1e-10, \
                    f"rho at {level}/{q['name']}: {actual} != {expected}"

    def test_sigma_values(self, config, budget, sensitivities):
        total_rho = config["privacy"]["total_rho"]
        level_props = config["privacy"]["level_proportions"]
        levels = config["hierarchy"]["level_names"]
        for l_idx, level in enumerate(levels):
            rho_level = level_props[l_idx] * total_rho
            for q in config["queries"]:
                rho_q = q["proportion"] * rho_level
                delta2 = sensitivities[q["name"]]["l2_bounded"]
                expected = delta2 / np.sqrt(2 * rho_q)
                actual = budget[level][q["name"]]["sigma"]
                assert abs(actual - expected) < 1e-6, \
                    f"sigma at {level}/{q['name']}: {actual} != {expected}"

    def test_total_rho_consumption(self, config, budget):
        total = sum(
            budget[level][q["name"]]["rho"]
            for level in config["hierarchy"]["level_names"]
            for q in config["queries"]
        )
        expected = config["privacy"]["total_rho"]
        assert abs(total - expected) < 1e-10


# ---- Synthetic histogram structural tests ----

class TestSyntheticProperties:
    def test_nonnegative(self, synthetic):
        for geo, hist in synthetic.items():
            assert np.all(hist >= 0), f"{geo} has negative values"

    def test_integer_valued(self, synthetic):
        for geo, hist in synthetic.items():
            assert np.allclose(hist, np.round(hist)), f"{geo} non-integer"

    def test_correct_shape(self, config, synthetic):
        expected = int(np.prod(config["schema"]["dim_sizes"]))
        for geo, hist in synthetic.items():
            assert len(hist) == expected, f"{geo}: {len(hist)} != {expected}"

    def test_structural_zeros(self, config, synthetic):
        zero_indices = _compute_zero_flat_indices(config)
        for geo, hist in synthetic.items():
            for zi in zero_indices:
                assert hist[zi] == 0, \
                    f"{geo} structural zero at {zi} = {hist[zi]}"


class TestTotalInvariance:
    def test_total_population_preserved(self, true_data, synthetic):
        for geo in synthetic:
            if geo not in true_data:
                continue
            expected = int(true_data[geo].sum())
            actual = int(np.sum(synthetic[geo]))
            assert actual == expected, \
                f"{geo}: total {actual} != {expected}"


class TestParentChildConsistency:
    def test_children_sum_to_parent(self, config, synthetic):
        tree = config["hierarchy"]["tree"]
        for parent, children in tree.items():
            parent_hist = synthetic[parent]
            child_sum = sum(synthetic[c] for c in children)
            assert np.array_equal(parent_hist, child_sum), \
                f"Children of {parent} don't sum to parent"


# ---- Anti-cheat: pipeline generality ----

def _verify_output_properties(cfg, data_dir, output_dir):
    """Verify all structural properties of pipeline output."""
    synth_dir = os.path.join(output_dir, "synthetic")
    dim_sizes = cfg["schema"]["dim_sizes"]
    n_cells = int(np.prod(dim_sizes))
    tree = cfg["hierarchy"]["tree"]
    zero_indices = _compute_zero_flat_indices(cfg)
    all_geos = _collect_all_geos(cfg)

    synth = {}
    true_d = {}
    for geo in all_geos:
        spath = os.path.join(synth_dir, f"{geo}.json")
        assert os.path.exists(spath), f"Missing {spath}"
        with open(spath) as f:
            synth[geo] = np.array(json.load(f))
        dpath = os.path.join(data_dir, f"{geo}.json")
        with open(dpath) as f:
            true_d[geo] = np.array(json.load(f), dtype=int)

    for geo in all_geos:
        h = synth[geo]
        assert np.all(h >= 0), f"{geo} negatives in re-run"
        assert np.allclose(h, np.round(h)), f"{geo} non-integer in re-run"
        assert len(h) == n_cells, f"{geo} shape mismatch in re-run"
        for zi in zero_indices:
            assert h[zi] == 0, f"{geo} zero violation at {zi} in re-run"
        assert int(np.sum(h)) == int(true_d[geo].sum()), \
            f"{geo} total mismatch in re-run"

    for parent, children in tree.items():
        child_sum = sum(synth[c] for c in children)
        assert np.array_equal(synth[parent], child_sum), \
            f"Parent-child mismatch for {parent} in re-run"


def _clean_stale_backups(*paths):
    for p in paths:
        if os.path.isfile(p):
            os.remove(p)
        elif os.path.isdir(p):
            shutil.rmtree(p)


class TestPipelineGenerality:
    """Verify the pipeline is a general-purpose program, not hardcoded."""

    def test_different_seed_produces_different_output(self):
        """Changing the random seed must change synthetic output."""
        # Read current synthetic
        orig = {}
        for fname in os.listdir(SYNTH_DIR):
            if fname.endswith(".json"):
                with open(os.path.join(SYNTH_DIR, fname)) as f:
                    orig[fname] = json.load(f)
        assert len(orig) > 0, "No synthetic outputs to compare"

        bak_cfg = CONFIG_PATH + ".seedbak"
        bak_out = OUTPUT_DIR + ".seedbak"
        _clean_stale_backups(bak_cfg, bak_out)

        shutil.copy(CONFIG_PATH, bak_cfg)
        shutil.copytree(OUTPUT_DIR, bak_out)

        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
            cfg["seed"] = cfg["seed"] + 7777
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f)

            shutil.rmtree(OUTPUT_DIR)
            os.makedirs(os.path.join(OUTPUT_DIR, "synthetic"), exist_ok=True)

            result = subprocess.run(
                ["python3", PIPELINE],
                capture_output=True, timeout=180,
                cwd="/app"
            )
            assert result.returncode == 0, \
                f"Pipeline failed with altered seed: {result.stderr.decode()[:500]}"

            any_diff = False
            for fname in orig:
                p = os.path.join(SYNTH_DIR, fname)
                if os.path.exists(p):
                    with open(p) as f:
                        new_data = json.load(f)
                    if new_data != orig[fname]:
                        any_diff = True
                        break
            assert any_diff, \
                "Identical synthetic output with different seed — pipeline may not use randomness"
        finally:
            shutil.move(bak_cfg, CONFIG_PATH)
            if os.path.isdir(OUTPUT_DIR):
                shutil.rmtree(OUTPUT_DIR)
            shutil.move(bak_out, OUTPUT_DIR)

    def test_pipeline_on_fresh_random_data(self):
        """Pipeline must produce valid output on entirely new random data."""
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)

        dim_sizes = cfg["schema"]["dim_sizes"]
        n_cells = int(np.prod(dim_sizes))
        tree = cfg["hierarchy"]["tree"]
        root = cfg["hierarchy"]["root"]
        zero_indices = _compute_zero_flat_indices(cfg)

        # Generate consistent random data: leaves first, then aggregate up
        rng = np.random.RandomState(55555)
        all_geos = _collect_all_geos(cfg)
        leaves = [g for g in all_geos if g not in tree]
        new_data = {}
        for leaf in leaves:
            h = rng.randint(5, 150, size=n_cells)
            for zi in zero_indices:
                h[zi] = 0
            new_data[leaf] = h.tolist()

        def _aggregate(geo):
            if geo not in tree:
                return np.array(new_data[geo], dtype=int)
            s = np.zeros(n_cells, dtype=int)
            for c in tree[geo]:
                s += _aggregate(c)
            new_data[geo] = s.tolist()
            return s

        _aggregate(root)

        bak_data = DATA_DIR + ".databak"
        bak_out = OUTPUT_DIR + ".databak"
        _clean_stale_backups(bak_data, bak_out)

        shutil.copytree(DATA_DIR, bak_data)
        shutil.copytree(OUTPUT_DIR, bak_out)

        try:
            for geo, hist in new_data.items():
                with open(os.path.join(DATA_DIR, f"{geo}.json"), "w") as f:
                    json.dump(hist, f)

            shutil.rmtree(OUTPUT_DIR)
            os.makedirs(os.path.join(OUTPUT_DIR, "synthetic"), exist_ok=True)

            result = subprocess.run(
                ["python3", PIPELINE],
                capture_output=True, timeout=180,
                cwd="/app"
            )
            assert result.returncode == 0, \
                f"Pipeline failed on fresh data: {result.stderr.decode()[:500]}"

            _verify_output_properties(cfg, DATA_DIR, OUTPUT_DIR)
        finally:
            shutil.rmtree(DATA_DIR)
            shutil.move(bak_data, DATA_DIR)
            if os.path.isdir(OUTPUT_DIR):
                shutil.rmtree(OUTPUT_DIR)
            shutil.move(bak_out, OUTPUT_DIR)
