
import csv
import os
import pytest


GOLD_STANDARD_PATH = "/tests/gold_standard.csv"
OUTPUT_PATH = "/app/alignment_output.csv"
VALID_RELATIONS = {"=", ">", "<", "~", "!"}
F1_THRESHOLD = 0.45


def load_csv_pairs(filepath):
    """Load alignment CSV into dict of (source_id, target_id) -> relation."""
    pairs = {}
    with open(filepath, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["source_id"].strip(), row["target_id"].strip())
            pairs[key] = row["relation"].strip()
    return pairs


def compute_weighted_f1(gold, predicted):
    """Compute weighted macro F1 across all relation types."""
    classes = sorted(VALID_RELATIONS)
    per_class_f1 = {}
    per_class_support = {}

    for cls in classes:
        tp = 0
        fp = 0
        fn = 0
        for key in gold:
            gold_rel = gold[key]
            pred_rel = predicted.get(key, None)
            if gold_rel == cls:
                if pred_rel == cls:
                    tp += 1
                else:
                    fn += 1
            elif pred_rel == cls:
                fp += 1

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        support = tp + fn
        per_class_f1[cls] = f1
        per_class_support[cls] = support

    total_support = sum(per_class_support.values())
    if total_support == 0:
        return 0.0, per_class_f1, per_class_support

    weighted_f1 = sum(
        per_class_f1[cls] * per_class_support[cls] for cls in classes
    ) / total_support

    return weighted_f1, per_class_f1, per_class_support


class TestAlignmentOutput:
    """Tests for the ontology alignment output."""

    def test_output_file_exists(self):
        assert os.path.isfile(OUTPUT_PATH), (
            f"Output file not found at {OUTPUT_PATH}"
        )

    def test_output_is_valid_csv(self):
        with open(OUTPUT_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            assert "source_id" in reader.fieldnames, "Missing 'source_id' column"
            assert "target_id" in reader.fieldnames, "Missing 'target_id' column"
            assert "relation" in reader.fieldnames, "Missing 'relation' column"

    def test_all_relations_are_valid(self):
        predictions = load_csv_pairs(OUTPUT_PATH)
        for key, rel in predictions.items():
            assert rel in VALID_RELATIONS, (
                f"Invalid relation '{rel}' for pair {key}. "
                f"Must be one of {VALID_RELATIONS}"
            )

    def test_all_candidate_pairs_present(self):
        gold = load_csv_pairs(GOLD_STANDARD_PATH)
        predictions = load_csv_pairs(OUTPUT_PATH)
        missing = []
        for key in gold:
            if key not in predictions:
                missing.append(key)
        assert len(missing) == 0, (
            f"{len(missing)} candidate pairs missing from output: "
            f"{missing[:10]}..."
        )

    def test_no_duplicate_pairs(self):
        seen = set()
        duplicates = []
        with open(OUTPUT_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["source_id"].strip(), row["target_id"].strip())
                if key in seen:
                    duplicates.append(key)
                seen.add(key)
        assert len(duplicates) == 0, (
            f"Duplicate pairs found in output: {duplicates[:10]}"
        )

    def test_weighted_f1_above_threshold(self):
        gold = load_csv_pairs(GOLD_STANDARD_PATH)
        predictions = load_csv_pairs(OUTPUT_PATH)
        weighted_f1, per_class_f1, per_class_support = compute_weighted_f1(
            gold, predictions
        )

        detail = "\n".join(
            f"  {cls}: F1={per_class_f1[cls]:.3f} (support={per_class_support[cls]})"
            for cls in sorted(VALID_RELATIONS)
        )
        assert weighted_f1 >= F1_THRESHOLD, (
            f"Weighted macro F1 = {weighted_f1:.4f} is below threshold "
            f"{F1_THRESHOLD}.\nPer-class breakdown:\n{detail}"
        )

    def test_multiple_relation_types_predicted(self):
        predictions = load_csv_pairs(OUTPUT_PATH)
        predicted_types = set(predictions.values())
        assert len(predicted_types) >= 3, (
            f"Only {len(predicted_types)} relation type(s) predicted: "
            f"{predicted_types}. The system must distinguish at least 3 types."
        )
