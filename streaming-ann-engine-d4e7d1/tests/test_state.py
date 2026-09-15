#!/usr/bin/env python3
"""Verification tests for the streaming ANN search engine with
category-filtered queries and weighted distance."""


import json
import os
import struct

import numpy as np
import pytest
import yaml


# ── Binary I/O helpers ──────────────────────────────────────────────────

def read_fbin(filepath):
    """Read float32 vectors in BigANN .fbin format."""
    with open(filepath, "rb") as f:
        n, d = struct.unpack("<II", f.read(8))
        data = np.frombuffer(f.read(n * d * 4), dtype=np.float32).reshape(n, d)
    return data.copy()


def read_ibin(filepath):
    """Read int32 vectors in BigANN .ibin format."""
    with open(filepath, "rb") as f:
        n, d = struct.unpack("<II", f.read(8))
        data = np.frombuffer(f.read(n * d * 4), dtype=np.int32).reshape(n, d)
    return data.copy()


def read_metadata(filepath):
    """Read the custom metadata binary file.

    Layout:
        uint32  num_vectors
        uint32  num_dimensions
        uint8[num_vectors]       category labels
        float32[num_dimensions]  per-dimension weights
    """
    with open(filepath, "rb") as f:
        num_vecs = struct.unpack("<I", f.read(4))[0]
        num_dims = struct.unpack("<I", f.read(4))[0]
        categories = np.frombuffer(f.read(num_vecs), dtype=np.uint8).copy()
        weights = np.frombuffer(f.read(num_dims * 4), dtype=np.float32).copy()
    return categories, weights


# ── Runbook simulation ──────────────────────────────────────────────────

def simulate_runbook(entries):
    """Replay the runbook to obtain (step, tag_to_id, cat_filter) at each
    search checkpoint."""
    tag_to_id = {}
    search_snapshots = []

    step_nums = sorted(k for k in entries.keys() if isinstance(k, int))
    for step_num in step_nums:
        entry = entries[step_num]
        op = entry["operation"]

        if op == "insert":
            for i in range(entry["start"], entry["end"]):
                tag_to_id[i] = i
        elif op == "delete":
            for i in range(entry["start"], entry["end"]):
                tag_to_id.pop(i, None)
        elif op == "replace":
            for i in range(entry["tags_end"] - entry["tags_start"]):
                tag = entry["tags_start"] + i
                vec_id = entry["ids_start"] + i
                tag_to_id[tag] = vec_id
        elif op == "search":
            cat_filter = set(entry.get("category_filter", list(range(5))))
            search_snapshots.append((step_num, dict(tag_to_id), cat_filter))

    return search_snapshots


# ── Ground truth (brute-force weighted k-NN with category filter) ──────

def brute_force_knn(base_data, tag_to_id, categories, cat_filter, queries,
                    weights, k):
    """Exact k-NN with weighted squared-L2 and category filtering."""
    valid_tags = sorted(
        t for t, vid in tag_to_id.items() if categories[vid] in cat_filter
    )

    if not valid_tags:
        nq = queries.shape[0]
        return (np.full((nq, k), -1, dtype="int32"),
                np.full((nq, k), np.inf, dtype="float32"))

    vec_ids = [tag_to_id[t] for t in valid_tags]
    active_vecs = base_data[vec_ids]               # (n_valid, d)

    nq = queries.shape[0]
    result_tags = np.full((nq, k), -1, dtype="int32")
    result_dists = np.full((nq, k), np.inf, dtype="float32")

    for qi in range(nq):
        diffs = active_vecs - queries[qi]                    # (n_valid, d)
        dists = np.sum(weights[np.newaxis, :] * diffs ** 2, axis=1)
        actual_k = min(k, len(valid_tags))
        topk = np.argsort(dists)[:actual_k]
        for ri in range(actual_k):
            result_tags[qi, ri] = valid_tags[topk[ri]]
            result_dists[qi, ri] = dists[topk[ri]]

    return result_tags, result_dists


def compute_recall(gt_tags, result_tags, k):
    """Mean recall@k via set overlap, ignoring -1 sentinel values."""
    nq = gt_tags.shape[0]
    total = 0.0
    for i in range(nq):
        gt_set = set(int(x) for x in gt_tags[i, :k] if x != -1)
        res_set = set(int(x) for x in result_tags[i, :k] if x != -1)
        if gt_set:
            total += len(gt_set & res_set) / len(gt_set)
        else:
            total += 1.0  # no valid neighbours → vacuously correct
    return total / nq


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ctx():
    """Load all data and pre-compute ground truth at every search step."""
    base = read_fbin("/app/data/base.fbin")
    queries = read_fbin("/app/data/queries.fbin")
    categories, weights = read_metadata("/app/data/metadata.bin")

    with open("/app/data/runbook.yaml") as f:
        runbook = yaml.safe_load(f)

    dataset_name = list(runbook.keys())[0]
    entries = runbook[dataset_name]
    snapshots = simulate_runbook(entries)

    k = 10
    ground_truth = {}
    for step_num, tag_to_id, cat_filter in snapshots:
        gt_tags, gt_dists = brute_force_knn(
            base, tag_to_id, categories, cat_filter, queries, weights, k,
        )
        ground_truth[step_num] = {
            "tag_to_id": tag_to_id,
            "cat_filter": cat_filter,
            "gt_tags": gt_tags,
            "gt_dists": gt_dists,
        }

    return {
        "base": base,
        "queries": queries,
        "categories": categories,
        "weights": weights,
        "k": k,
        "snapshots": snapshots,
        "ground_truth": ground_truth,
    }


# ── Tests ────────────────────────────────────────────────────────────────

class TestSummaryFile:
    def test_exists(self, ctx):
        assert os.path.exists("/app/results/summary.json"), \
            "summary.json not found"

    def test_structure(self, ctx):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        assert "search_steps" in summary
        assert len(summary["search_steps"]) == len(ctx["snapshots"]), \
            f"Expected {len(ctx['snapshots'])} search steps"

    def test_active_point_counts(self, ctx):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        for i, (step_num, tag_to_id, _) in enumerate(ctx["snapshots"]):
            entry = summary["search_steps"][i]
            assert entry["step"] == step_num
            expected = len(tag_to_id)
            assert entry["num_active_points"] == expected, \
                (f"Step {step_num}: active count {entry['num_active_points']}"
                 f" != expected {expected}")

    def test_category_lists(self, ctx):
        with open("/app/results/summary.json") as f:
            summary = json.load(f)
        for i, (step_num, _, cat_filter) in enumerate(ctx["snapshots"]):
            entry = summary["search_steps"][i]
            expected = sorted(cat_filter)
            actual = sorted(entry.get("categories", []))
            assert actual == expected, \
                (f"Step {step_num}: categories {actual} != {expected}")


class TestOutputFiles:
    def test_files_exist(self, ctx):
        for step_num, _, _ in ctx["snapshots"]:
            nb = f"/app/results/step{step_num}_neighbors.ibin"
            ds = f"/app/results/step{step_num}_distances.fbin"
            assert os.path.exists(nb), f"Missing {nb}"
            assert os.path.exists(ds), f"Missing {ds}"

    def test_shapes(self, ctx):
        nq = ctx["queries"].shape[0]
        k = ctx["k"]
        for step_num, _, _ in ctx["snapshots"]:
            nb = read_ibin(f"/app/results/step{step_num}_neighbors.ibin")
            ds = read_fbin(f"/app/results/step{step_num}_distances.fbin")
            assert nb.shape == (nq, k), \
                f"Neighbors shape {nb.shape} != ({nq}, {k}) at step {step_num}"
            assert ds.shape == (nq, k), \
                f"Distances shape {ds.shape} != ({nq}, {k}) at step {step_num}"


class TestCategoryFiltering:
    def test_returned_tags_match_filter(self, ctx):
        """Every returned tag must belong to a vector whose category is in
        the step's category_filter list."""
        categories = ctx["categories"]
        for step_num, tag_to_id, cat_filter in ctx["snapshots"]:
            nb = read_ibin(f"/app/results/step{step_num}_neighbors.ibin")
            for qi in range(nb.shape[0]):
                for ri in range(nb.shape[1]):
                    tag = int(nb[qi, ri])
                    if tag == -1:
                        continue
                    assert tag in tag_to_id, \
                        (f"Tag {tag} at step {step_num}, q{qi}, r{ri}"
                         " not in active set")
                    vec_id = tag_to_id[tag]
                    assert categories[vec_id] in cat_filter, \
                        (f"Tag {tag} (vec {vec_id}, cat "
                         f"{categories[vec_id]}) does not match "
                         f"filter {cat_filter} at step {step_num}")


class TestDistances:
    def test_nondecreasing(self, ctx):
        for step_num, _, _ in ctx["snapshots"]:
            ds = read_fbin(f"/app/results/step{step_num}_distances.fbin")
            for qi in range(ds.shape[0]):
                for ri in range(1, ds.shape[1]):
                    assert ds[qi, ri] >= ds[qi, ri - 1] - 1e-4, \
                        (f"Step {step_num}, q{qi}: d[{ri-1}]="
                         f"{ds[qi,ri-1]:.6f} > d[{ri}]={ds[qi,ri]:.6f}")

    def test_weighted_distance_values(self, ctx):
        """Verify a sample of reported distances match the weighted metric
        within tolerance."""
        weights = ctx["weights"]
        base = ctx["base"]
        queries = ctx["queries"]
        for step_num, tag_to_id, _ in ctx["snapshots"]:
            nb = read_ibin(f"/app/results/step{step_num}_neighbors.ibin")
            ds = read_fbin(f"/app/results/step{step_num}_distances.fbin")
            # Spot-check first 10 queries, top-1 result
            for qi in range(min(10, nb.shape[0])):
                tag = int(nb[qi, 0])
                if tag == -1:
                    continue
                vec_id = tag_to_id[tag]
                expected = np.sum(
                    weights * (queries[qi] - base[vec_id]) ** 2
                )
                actual = float(ds[qi, 0])
                assert abs(actual - expected) < 1e-2, \
                    (f"Step {step_num}, q{qi}: distance {actual:.6f}"
                     f" != expected {expected:.6f}")


class TestRecall:
    def test_per_step(self, ctx):
        k = ctx["k"]
        for step_num, gt_data in ctx["ground_truth"].items():
            nb = read_ibin(f"/app/results/step{step_num}_neighbors.ibin")
            recall = compute_recall(gt_data["gt_tags"], nb, k)
            assert recall >= 0.7, \
                f"recall@{k} at step {step_num}: {recall:.4f} < 0.7"

    def test_average(self, ctx):
        k = ctx["k"]
        recalls = []
        for step_num, gt_data in ctx["ground_truth"].items():
            nb = read_ibin(f"/app/results/step{step_num}_neighbors.ibin")
            recalls.append(compute_recall(gt_data["gt_tags"], nb, k))
        avg = np.mean(recalls)
        assert avg >= 0.8, \
            f"Average recall@{k}: {avg:.4f} < 0.8"
