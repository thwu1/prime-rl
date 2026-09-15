"""Submission validation and cross-entropy scoring."""

import numpy as np


def validate_submission(submission, field_ids, num_classes):
    errors = []

    for fid in field_ids:
        if fid not in submission:
            errors.append(f"Missing field ID: {fid}")

    for fid, probs in submission.items():
        if len(probs) != num_classes:
            errors.append(
                f"Field {fid}: expected {num_classes} probabilities, got {len(probs)}"
            )
            continue
        for i, p in enumerate(probs):
            if p < 0 or p > 1:
                errors.append(
                    f"Field {fid}: probability at index {i} is {p}, not in [0, 1]"
                )
        row_sum = sum(probs)
        if abs(row_sum - 1.0) > 1e-6:
            errors.append(
                f"Field {fid}: probabilities sum to {row_sum}, expected 1.0"
            )

    valid = len(errors) == 0
    return valid, errors


def cross_entropy_score(submission, ground_truth):
    submission = np.asarray(submission, dtype=float)
    ground_truth = np.asarray(ground_truth, dtype=int)

    clipped = np.clip(submission, 1e-15, 1.0 - 1e-15)

    n = len(ground_truth)
    total = 0.0
    for i in range(n):
        total -= np.log(clipped[i, ground_truth[i]])

    return float(total / n)
