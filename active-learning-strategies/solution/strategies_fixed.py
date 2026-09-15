"""Corrected Active Learning Query Strategies.

"""

import numpy as np
from scipy.stats import entropy as scipy_entropy
from sklearn.metrics import pairwise_distances


def least_confidence(proba, n):
    """Select n samples with lowest prediction confidence."""
    confidence = np.amax(proba, axis=1)
    indices = np.argpartition(confidence, n)[:n]
    return np.sort(indices)


def breaking_ties(proba, n):
    """Select n samples with smallest margin between top two classes."""
    margins = np.array([np.sort(row)[-1] - np.sort(row)[-2] for row in proba])
    # FIX: use margins (not -margins) to select SMALLEST margins
    indices = np.argpartition(margins, n)[:n]
    return np.sort(indices)


def prediction_entropy(proba, n):
    """Select n samples with highest Shannon entropy."""
    ent = np.array([scipy_entropy(row) for row in proba])
    indices = np.argpartition(-ent, n)[:n]
    return np.sort(indices)


def bald_scores(proba_mc, n, eps=1e-8):
    """Select n samples with highest BALD score."""
    p_mean = np.mean(proba_mc, axis=1)
    model_entropy = -np.sum(p_mean * np.log2(p_mean + eps), axis=-1)
    expected_entropy = -np.mean(
        np.sum(proba_mc * np.log2(proba_mc + eps), axis=-1), axis=1
    )
    # FIX: model_entropy - expected_entropy (not swapped)
    scores = model_entropy - expected_entropy
    indices = np.argpartition(-scores, n)[:n]
    return np.sort(indices)


def _cosine_distance(a, b):
    """Compute pairwise cosine distance."""
    sim = a @ b.T
    norms_a = np.linalg.norm(a, axis=1)[:, np.newaxis]
    # FIX: also divide by norms_b
    norms_b = np.linalg.norm(b, axis=1)[np.newaxis, :]
    sim = sim / (norms_a * norms_b)
    sim = np.clip(sim, -1.0, 1.0)
    return np.arccos(sim) / np.pi


def _euclidean_distance(a, b):
    """Compute pairwise euclidean distance."""
    return pairwise_distances(a, b, metric='euclidean')


def greedy_coreset(embeddings, indices_unlabeled, indices_labeled, n,
                   distance_metric='cosine', batch_size=100):
    """Select n samples using greedy coreset."""
    if distance_metric == 'cosine':
        dist_func = _cosine_distance
    elif distance_metric == 'euclidean':
        dist_func = _euclidean_distance
    else:
        raise ValueError(f"Unknown distance metric: {distance_metric}")

    num_batches = int(np.ceil(indices_unlabeled.shape[0] / batch_size))
    selected = []

    for _ in range(n):
        if len(selected) > 0:
            # FIX: map local indices through indices_unlabeled to get global indices
            selected_as_global = np.array(
                [indices_unlabeled[i] for i in selected], dtype=np.int64
            )
            indices_s = np.concatenate(
                [indices_labeled, selected_as_global]
            ).astype(np.int64)
        else:
            indices_s = indices_labeled.astype(np.int64)

        dists = np.array([], dtype=np.float64)
        for batch in np.array_split(
            embeddings[indices_unlabeled], num_batches, axis=0
        ):
            dist = dist_func(batch, embeddings[indices_s])
            min_dists = np.amin(dist, axis=1)
            dists = np.append(dists, min_dists)

        for s in selected:
            dists[s] = -np.inf

        index_new = int(np.argmax(dists))
        selected.append(index_new)

    return np.sort(np.array(selected))


def lightweight_coreset(embeddings, n, distance_metric='cosine', seed=None):
    """Select n samples using lightweight coreset importance sampling."""
    rng = np.random.RandomState(seed)

    centroid = np.mean(embeddings, axis=0, keepdims=True)

    if distance_metric == 'cosine':
        dists = _cosine_distance(embeddings, centroid).ravel()
    elif distance_metric == 'euclidean':
        dists = _euclidean_distance(embeddings, centroid).ravel()
    else:
        raise ValueError(f"Unknown distance metric: {distance_metric}")

    dsq = np.square(dists)
    p = 0.5 / embeddings.shape[0] + 0.5 * dsq / dsq.sum()
    p = p / p.sum()

    indices = rng.choice(embeddings.shape[0], size=n, replace=False, p=p)
    return np.sort(indices)
