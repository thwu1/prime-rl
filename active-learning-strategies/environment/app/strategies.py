"""Active Learning Query Strategies

Acquisition functions for pool-based active learning. Each function takes a
probability matrix or embedding matrix and selects the n most informative
sample indices according to its criterion.

Some implementations contain bugs. Some are unimplemented stubs.

"""

import numpy as np
from sklearn.metrics import pairwise_distances


def least_confidence(proba, n):
    """Select n samples with the lowest prediction confidence.

    Confidence is defined as the maximum predicted class probability for each
    sample. Lower max-probability indicates higher uncertainty.

    Parameters
    ----------
    proba : np.ndarray, shape (num_samples, num_classes)
        Predicted class probabilities.
    n : int
        Number of samples to select.

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Indices of selected samples, sorted ascending.
    """
    raise NotImplementedError("least_confidence not implemented")


def breaking_ties(proba, n):
    """Select n samples with the smallest margin between the top two classes.

    Margin = (highest class probability) - (second-highest class probability).
    Smaller margins indicate more ambiguity between the top two predictions.

    Parameters
    ----------
    proba : np.ndarray, shape (num_samples, num_classes)
        Predicted class probabilities.
    n : int
        Number of samples to select.

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Indices of selected samples, sorted ascending.
    """
    margins = np.array([np.sort(row)[-1] - np.sort(row)[-2] for row in proba])
    indices = np.argpartition(-margins, n)[:n]
    return np.sort(indices)


def prediction_entropy(proba, n):
    """Select n samples with the highest Shannon entropy (natural log).

    Parameters
    ----------
    proba : np.ndarray, shape (num_samples, num_classes)
        Predicted class probabilities.
    n : int
        Number of samples to select.

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Indices of selected samples, sorted ascending.
    """
    raise NotImplementedError("prediction_entropy not implemented")


def bald_scores(proba_mc, n, eps=1e-8):
    """Select n samples with the highest BALD score.

    BALD = H[E_theta[p(y|x,theta)]] - E_theta[H[p(y|x,theta)]]

    where H is Shannon entropy (base 2) and E_theta is the expectation over
    Monte Carlo dropout samples (axis 1 of proba_mc).

    Parameters
    ----------
    proba_mc : np.ndarray, shape (num_samples, num_mc_samples, num_classes)
        MC dropout predicted probabilities.
    n : int
        Number of samples to select.
    eps : float
        Small constant to prevent log(0).

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Indices of selected samples, sorted ascending.
    """
    p_mean = np.mean(proba_mc, axis=1)
    model_entropy = -np.sum(p_mean * np.log2(p_mean + eps), axis=-1)
    expected_entropy = -np.mean(
        np.sum(proba_mc * np.log2(proba_mc + eps), axis=-1), axis=1
    )
    scores = expected_entropy - model_entropy
    indices = np.argpartition(-scores, n)[:n]
    return np.sort(indices)


def _cosine_distance(a, b):
    """Compute pairwise cosine distance between rows of a and rows of b.

    Cosine distance = arccos(cosine_similarity) / pi, yielding values in [0, 1].

    Parameters
    ----------
    a : np.ndarray, shape (m, d)
    b : np.ndarray, shape (k, d)

    Returns
    -------
    distances : np.ndarray, shape (m, k)
    """
    sim = a @ b.T
    norms_a = np.linalg.norm(a, axis=1)[:, np.newaxis]
    sim = sim / norms_a
    sim = np.clip(sim, -1.0, 1.0)
    return np.arccos(sim) / np.pi


def _euclidean_distance(a, b):
    """Compute pairwise euclidean distance between rows of a and rows of b."""
    return pairwise_distances(a, b, metric='euclidean')


def greedy_coreset(embeddings, indices_unlabeled, indices_labeled, n,
                   distance_metric='cosine', batch_size=100):
    """Select n samples using greedy coreset construction.

    Iteratively selects the unlabeled point whose minimum distance to the
    current set of labeled + previously-selected points is largest
    (farthest-first traversal).

    Parameters
    ----------
    embeddings : np.ndarray, shape (num_total, embedding_dim)
        Embeddings for ALL samples (labeled and unlabeled).
    indices_unlabeled : np.ndarray
        Global indices into embeddings for unlabeled samples.
    indices_labeled : np.ndarray
        Global indices into embeddings for labeled samples.
    n : int
        Number of samples to select.
    distance_metric : str
        'cosine' or 'euclidean'.
    batch_size : int
        Batch size for distance computation.

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Local indices (into indices_unlabeled) of selected samples, sorted ascending.
    """
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
            selected_as_global = np.array(selected, dtype=np.int64)
            indices_s = np.concatenate([indices_labeled, selected_as_global]).astype(np.int64)
        else:
            indices_s = indices_labeled.astype(np.int64)

        dists = np.array([], dtype=np.float64)
        for batch in np.array_split(embeddings[indices_unlabeled], num_batches, axis=0):
            dist = dist_func(batch, embeddings[indices_s])
            min_dists = np.amin(dist, axis=1)
            dists = np.append(dists, min_dists)

        for s in selected:
            dists[s] = -np.inf

        index_new = int(np.argmax(dists))
        selected.append(index_new)

    return np.sort(np.array(selected))


def lightweight_coreset(embeddings, n, distance_metric='cosine', seed=None):
    """Select n samples using lightweight coreset importance sampling.

    Constructs a sampling distribution that combines uniform coverage with
    distance-weighted preference for outliers:

        p(i) = 0.5 * (1/N) + 0.5 * (d(i)^2 / sum_j d(j)^2)

    where d(i) is the distance from embedding i to the centroid of all
    embeddings. The distribution is then L1-normalized before sampling
    n points without replacement.

    Parameters
    ----------
    embeddings : np.ndarray, shape (num_samples, embedding_dim)
        Embeddings for the candidate pool.
    n : int
        Number of samples to select.
    distance_metric : str
        'cosine' or 'euclidean'.
    seed : int or None
        Random seed for reproducible sampling.

    Returns
    -------
    indices : np.ndarray, shape (n,)
        Indices of selected samples, sorted ascending.
    """
    raise NotImplementedError("lightweight_coreset not implemented")
