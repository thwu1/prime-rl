"""Classification accuracy assessment."""

import numpy as np
from .taxonomy import get_classes, get_mapping


def assess(predictions, ground_truth, level=3):
    predictions = np.asarray(predictions, dtype=int)
    ground_truth = np.asarray(ground_truth, dtype=int)

    if level < 3:
        mapping = get_mapping(level)
        predictions = np.array([mapping[int(p)] for p in predictions])
        ground_truth = np.array([mapping[int(g)] for g in ground_truth])

    class_names = get_classes(level)
    num_classes = len(class_names)
    n = len(predictions)

    cm = np.zeros((num_classes, num_classes), dtype=int)
    for t, p in zip(ground_truth, predictions):
        cm[int(p), int(t)] += 1

    oa = float(np.trace(cm)) / n if n > 0 else 0.0

    row_sums = cm.sum(axis=1).astype(float)
    col_sums = cm.sum(axis=0).astype(float)
    p_e = float(np.sum(row_sums * col_sums)) / (n * n) if n > 0 else 0.0

    if abs(1.0 - p_e) < 1e-15:
        kappa = 0.0
    else:
        kappa = (oa - p_e) / (1.0 - p_e)

    per_class = {}
    for c in range(num_classes):
        tp = float(cm[c, c])
        fp = float(col_sums[c] - tp)
        fn = float(row_sums[c] - tp)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2.0 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class[class_names[c]] = {
            "f1": f1,
            "precision": precision,
            "recall": recall
        }

    return {
        "overall_accuracy": oa,
        "cohens_kappa": kappa,
        "per_class": per_class,
        "confusion_matrix": cm.tolist()
    }
