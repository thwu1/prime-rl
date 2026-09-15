"""Consensus labeling from multiple annotators."""

import numpy as np


def compute_consensus(annotations, weights, num_classes=7):
    annotations = [np.asarray(a, dtype=int) for a in annotations]
    n_annotators = len(annotations)
    n_pixels = len(annotations[0])

    max_weight = max(weights)
    norm_weights = [w / max_weight for w in weights]

    labels = np.zeros(n_pixels, dtype=int)
    scores = np.zeros(n_pixels, dtype=float)

    for p in range(n_pixels):
        probs = np.zeros(num_classes)
        for i in range(n_annotators):
            label = int(annotations[i][p])
            acc = weights[i]
            for j in range(num_classes):
                if j == label:
                    probs[j] += norm_weights[i] * acc
                else:
                    probs[j] += norm_weights[i] * (1.0 - acc) / num_classes
        labels[p] = np.argmax(probs)
        scores[p] = np.max(probs)

    return labels, scores
