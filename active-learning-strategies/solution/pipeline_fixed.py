"""Completed Active Learning Evaluation Pipeline.

"""

import json
import os
import numpy as np

from strategies import (
    least_confidence, breaking_ties, prediction_entropy,
    bald_scores, greedy_coreset, lightweight_coreset
)
from stopping import (
    classification_change_stop, kappa_average_stop, overall_uncertainty_stop
)


def generate_probability_matrix(seed=42, n_samples=50, n_classes=4):
    rng = np.random.RandomState(seed)
    alpha = rng.uniform(0.1, 2.0, size=n_classes)
    return rng.dirichlet(alpha, size=n_samples)


def generate_embeddings(seed=42, n_samples=50, n_dims=16):
    return np.random.RandomState(seed).randn(n_samples, n_dims)


def generate_mc_dropout_proba(seed=42, n_samples=50, n_mc=10, n_classes=4):
    rng = np.random.RandomState(seed)
    base = rng.dirichlet(np.ones(n_classes), size=n_samples)
    proba_mc = np.zeros((n_samples, n_mc, n_classes))
    for t in range(n_mc):
        noise = rng.normal(0, 0.1, size=(n_samples, n_classes))
        noisy = np.clip(base + noise, 1e-6, None)
        proba_mc[:, t, :] = noisy / noisy.sum(axis=1, keepdims=True)
    return proba_mc


def generate_predictions_history(seed=42, n_samples=30, n_classes=4, n_steps=6):
    rng = np.random.RandomState(seed)
    base = rng.randint(0, n_classes, size=n_samples)
    history = [base.copy()]
    for step in range(1, n_steps):
        prev = history[-1].copy()
        n_changes = max(0, n_samples // (step + 1))
        idx = rng.choice(n_samples, size=n_changes, replace=False)
        prev[idx] = rng.randint(0, n_classes, size=n_changes)
        history.append(prev)
    return history


def run_validation(predictions_history, proba, indices_unlabeled, n_classes):
    """Cross-validate custom stopping criteria against small-text library."""
    from small_text.stopping_criteria import (
        KappaAverage, OverallUncertainty, ClassificationChange
    )

    # KappaAverage: single stateful instance called in sequence
    ka = KappaAverage(n_classes, window_size=3, kappa=0.99)
    kappa_lib_decisions = []
    for preds in predictions_history:
        kappa_lib_decisions.append(ka.stop(predictions=preds))

    # OverallUncertainty: correct keyword is indices_stopping
    ou = OverallUncertainty(n_classes, threshold=0.05)
    ou_lib_result = ou.stop(proba=proba, indices_stopping=indices_unlabeled)

    # ClassificationChange: call twice to establish state then compare
    cc = ClassificationChange(n_classes, threshold=0.0)
    cc.stop(predictions=predictions_history[-2])
    cc_lib_result = cc.stop(predictions=predictions_history[-1])

    return {
        "kappa_average_library": kappa_lib_decisions,
        "overall_uncertainty_library": ou_lib_result,
        "classification_change_library": cc_lib_result,
    }


def run_pipeline():
    os.makedirs('/app/results', exist_ok=True)

    n_query = 5

    proba = generate_probability_matrix(seed=42, n_samples=50, n_classes=4)
    embeddings = generate_embeddings(seed=42, n_samples=50, n_dims=16)
    proba_mc = generate_mc_dropout_proba(seed=42, n_samples=50, n_mc=10, n_classes=4)
    predictions_history = generate_predictions_history(
        seed=42, n_samples=30, n_classes=4, n_steps=6
    )

    indices_labeled = np.arange(10)
    indices_unlabeled = np.arange(10, 50)

    strategy_results = {
        "least_confidence": least_confidence(proba, n_query).tolist(),
        "breaking_ties": breaking_ties(proba, n_query).tolist(),
        "prediction_entropy": prediction_entropy(proba, n_query).tolist(),
        "bald": bald_scores(proba_mc, n_query).tolist(),
        "greedy_coreset": greedy_coreset(
            embeddings, indices_unlabeled, indices_labeled, n_query,
            distance_metric='cosine'
        ).tolist(),
        "lightweight_coreset": lightweight_coreset(
            embeddings, n_query, distance_metric='cosine', seed=123
        ).tolist(),
    }

    stopping_results = {
        "kappa_average": kappa_average_stop(
            predictions_history, 4, window_size=3, kappa_threshold=0.99
        ),
        "overall_uncertainty": overall_uncertainty_stop(
            proba, indices_unlabeled, 4, threshold=0.05
        ),
        "classification_change": classification_change_stop(
            predictions_history[-1], predictions_history[-2], threshold=0.0
        ),
    }

    # Cross-validate against small-text library
    validation_raw = run_validation(
        predictions_history, proba, indices_unlabeled, 4
    )

    kappa_match = (
        validation_raw["kappa_average_library"]
        == stopping_results["kappa_average"]
    )
    uncertainty_match = (
        validation_raw["overall_uncertainty_library"]
        == stopping_results["overall_uncertainty"]
    )
    change_match = (
        validation_raw["classification_change_library"]
        == stopping_results["classification_change"]
    )

    validation_results = {
        "kappa_average_match": kappa_match,
        "overall_uncertainty_match": uncertainty_match,
        "classification_change_match": change_match,
        "all_match": kappa_match and uncertainty_match and change_match,
    }

    with open('/app/results/strategy_rankings.json', 'w') as f:
        json.dump(strategy_results, f, indent=2)

    with open('/app/results/stopping_decisions.json', 'w') as f:
        json.dump(stopping_results, f, indent=2)

    with open('/app/results/validation.json', 'w') as f:
        json.dump(validation_results, f, indent=2)

    print("Pipeline complete. Results written to /app/results/")


if __name__ == '__main__':
    run_pipeline()
