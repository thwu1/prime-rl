#!/usr/bin/env python3
"""
PhysioNet Challenge 2026 — Scoring Functions

Official implementation of the Challenge evaluation metrics.
Do not edit this script.
"""

import numpy as np


def compute_challenge_score(labels, outputs, fraction_capacity=0.05, num_permutations=10**4, seed=12345):
    """
    Compute the capacity-constrained true positive rate.

    This metric simulates a resource-constrained clinical screening scenario.
    Given a fixed screening capacity (as a fraction of the total population),
    the score measures how effectively the model identifies positive cases
    within the top-ranked predictions.

    To handle tied probabilities fairly, the metric averages over many random
    permutations of the data before ranking.

    Args:
        labels: Binary ground truth labels (1 = positive, 0 = negative).
        outputs: Predicted probabilities (higher = more likely positive).
        fraction_capacity: Fraction of population that can be screened.
        num_permutations: Number of random permutations for tie-breaking.
        seed: Random seed for reproducibility.

    Returns:
        float: Mean true positive rate across permutations.
    """
    assert len(labels) == len(outputs)
    num_instances = len(labels)
    capacity = int(fraction_capacity * num_instances)

    labels = np.asarray(labels, dtype=np.float64)
    outputs = np.asarray(outputs, dtype=np.float64)

    tp = np.zeros(num_permutations)
    fp = np.zeros(num_permutations)
    fn = np.zeros(num_permutations)
    tn = np.zeros(num_permutations)

    if seed is not None:
        np.random.seed(seed)

    for i in range(num_permutations):
        permuted_idx = np.random.permutation(np.arange(num_instances))
        permuted_labels = labels[permuted_idx]
        permuted_outputs = outputs[permuted_idx]

        ordered_idx = np.argsort(permuted_outputs, stable=True)[::-1]
        ordered_labels = permuted_labels[ordered_idx]

        tp[i] = np.sum(ordered_labels[:capacity] == 1)
        fp[i] = np.sum(ordered_labels[:capacity] == 0)
        fn[i] = np.sum(ordered_labels[capacity:] == 1)
        tn[i] = np.sum(ordered_labels[capacity:] == 0)

    tp = np.mean(tp)
    fp = np.mean(fp)
    fn = np.mean(fn)
    tn = np.mean(tn)

    if tp + fn > 0:
        tpr = tp / (tp + fn)
    else:
        tpr = float('nan')

    return tpr


def compute_auc(labels, outputs):
    """Compute AUROC and AUPRC."""
    from sklearn.metrics import roc_auc_score, average_precision_score

    auroc = roc_auc_score(labels, outputs)
    auprc = average_precision_score(labels, outputs)

    return auroc, auprc


def compute_accuracy(labels, outputs):
    """Compute classification accuracy."""
    from sklearn.metrics import accuracy_score

    return accuracy_score(labels, outputs)


def compute_f_measure(labels, outputs):
    """Compute F1 score (positive label = 1)."""
    from sklearn.metrics import f1_score

    return f1_score(labels, outputs, pos_label=1, average='binary')
