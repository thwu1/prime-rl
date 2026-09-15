
"""Tests for DDoS traffic classification task.
Verifies agent output against deterministic ground truth
regenerated at test time (no ground truth stored in image)."""

import json
import os
import sys
import pytest

sys.path.insert(0, "/tests")
from gen_ground_truth import generate as gen_gt

ATTACK_TYPES = ["syn_flood", "slowloris", "dns_amp"]
OUTPUT_DIR = "/app/output"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_metrics(pred_set, truth_set):
    tp = len(pred_set & truth_set)
    fp = len(pred_set - truth_set)
    fn = len(truth_set - pred_set)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return precision, recall


@pytest.fixture(scope="session")
def ground_truth():
    return gen_gt()


@pytest.fixture(scope="session")
def predictions():
    results = {}
    for attack_type in ATTACK_TYPES:
        path = os.path.join(OUTPUT_DIR, f"{attack_type}.json")
        if os.path.exists(path):
            data = load_json(path)
            results[attack_type] = set(data.get("flow_ids", []))
        else:
            results[attack_type] = set()
    return results


# --- Structural tests ---

class TestOutputStructure:
    def test_output_directory_exists(self):
        assert os.path.isdir(OUTPUT_DIR), f"Output directory {OUTPUT_DIR} does not exist"

    @pytest.mark.parametrize("attack_type", ATTACK_TYPES)
    def test_output_file_exists(self, attack_type):
        path = os.path.join(OUTPUT_DIR, f"{attack_type}.json")
        assert os.path.exists(path), f"Missing output file: {path}"

    @pytest.mark.parametrize("attack_type", ATTACK_TYPES)
    def test_output_format(self, attack_type):
        path = os.path.join(OUTPUT_DIR, f"{attack_type}.json")
        data = load_json(path)
        assert "flow_ids" in data, f"Missing 'flow_ids' key in {path}"
        assert isinstance(data["flow_ids"], list), f"'flow_ids' must be a list in {path}"
        for fid in data["flow_ids"]:
            assert isinstance(fid, str), f"Flow IDs must be strings, got {type(fid)}"

    @pytest.mark.parametrize("attack_type", ATTACK_TYPES)
    def test_nonempty_predictions(self, attack_type):
        path = os.path.join(OUTPUT_DIR, f"{attack_type}.json")
        data = load_json(path)
        assert len(data["flow_ids"]) > 0, f"No flows classified as {attack_type}"


# --- Detection accuracy tests ---

class TestSynFloodDetection:
    def test_precision(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["syn_flood"], ground_truth["syn_flood"])
        assert p >= 0.85, f"SYN flood precision {p:.4f} < 0.85"

    def test_recall(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["syn_flood"], ground_truth["syn_flood"])
        assert r >= 0.80, f"SYN flood recall {r:.4f} < 0.80"

    def test_reasonable_count(self, ground_truth, predictions):
        gt_count = len(ground_truth["syn_flood"])
        pred_count = len(predictions["syn_flood"])
        assert pred_count <= gt_count * 3, (
            f"SYN flood: {pred_count} predictions vs {gt_count} ground truth (>3x)")


class TestSlowlorisDetection:
    def test_precision(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["slowloris"], ground_truth["slowloris"])
        assert p >= 0.85, f"Slowloris precision {p:.4f} < 0.85"

    def test_recall(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["slowloris"], ground_truth["slowloris"])
        assert r >= 0.80, f"Slowloris recall {r:.4f} < 0.80"

    def test_reasonable_count(self, ground_truth, predictions):
        gt_count = len(ground_truth["slowloris"])
        pred_count = len(predictions["slowloris"])
        assert pred_count <= gt_count * 3, (
            f"Slowloris: {pred_count} predictions vs {gt_count} ground truth (>3x)")


class TestDnsAmpDetection:
    def test_precision(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["dns_amp"], ground_truth["dns_amp"])
        assert p >= 0.85, f"DNS amp precision {p:.4f} < 0.85"

    def test_recall(self, ground_truth, predictions):
        p, r = compute_metrics(predictions["dns_amp"], ground_truth["dns_amp"])
        assert r >= 0.80, f"DNS amp recall {r:.4f} < 0.80"

    def test_reasonable_count(self, ground_truth, predictions):
        gt_count = len(ground_truth["dns_amp"])
        pred_count = len(predictions["dns_amp"])
        assert pred_count <= gt_count * 3, (
            f"DNS amp: {pred_count} predictions vs {gt_count} ground truth (>3x)")


class TestOverallQuality:
    def test_overall_precision(self, ground_truth, predictions):
        all_truth = set()
        for ids in ground_truth.values():
            all_truth.update(ids)
        all_pred = set()
        for ids in predictions.values():
            all_pred.update(ids)
        if len(all_pred) == 0:
            pytest.fail("No predictions made at all")
        tp = len(all_pred & all_truth)
        fp = len(all_pred - all_truth)
        overall_precision = tp / (tp + fp)
        assert overall_precision >= 0.80, (
            f"Overall precision {overall_precision:.4f} < 0.80 "
            f"({fp} false positives out of {len(all_pred)} total predictions)")

    def test_no_category_overlap(self, predictions):
        seen = set()
        for attack_type in ATTACK_TYPES:
            overlap = seen & predictions[attack_type]
            assert len(overlap) == 0, (
                f"Flow IDs classified in multiple categories: {list(overlap)[:5]}...")
            seen.update(predictions[attack_type])
