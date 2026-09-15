"""Active Learning Evaluation Pipeline

Generates synthetic data with fixed seeds, runs all query strategies and
stopping criteria, cross-validates stopping criteria against the small-text
library, and writes results to /app/results/.

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
    """Generate a probability matrix via Dirichlet distribution."""
    rng = np.random.RandomState(seed)
    alpha = rng.uniform(0.1, 2.0, size=n_classes)
    return rng.dirichlet(alpha, size=n_samples)


def generate_embeddings(seed=42, n_samples=50, n_dims=16):
    """Generate embedding vectors from standard normal."""
    return np.random.RandomState(seed).randn(n_samples, n_dims)


def generate_mc_dropout_proba(seed=42, n_samples=50, n_mc=10, n_classes=4):
    """Generate MC dropout probability samples."""
    rng = np.random.RandomState(seed)
    base = rng.dirichlet(np.ones(n_classes), size=n_samples)
    proba_mc = np.zeros((n_samples, n_mc, n_classes))
    for t in range(n_mc):
        noise = rng.normal(0, 0.1, size=(n_samples, n_classes))
        noisy = np.clip(base + noise, 1e-6, None)
        proba_mc[:, t, :] = noisy / noisy.sum(axis=1, keepdims=True)
    return proba_mc


def generate_predictions_history(seed=42, n_samples=30, n_classes=4, n_steps=6):
    """Generate a sequence of prediction arrays that gradually stabilize."""
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
    """Cross-validate custom stopping criteria against small-text library.

    Uses small-text's KappaAverage, OverallUncertainty, and ClassificationChange
    stopping criterion classes to verify custom implementations produce
    identical results to the library's reference implementations.
    """
    from small_text.stopping_criteria import (
        KappaAverage, OverallUncertainty, ClassificationChange
    )

    # --- KappaAverage validation ---
    kappa_lib_decisions = []
    for i, preds in enumerate(predictions_history):
        ka = KappaAverage(n_classes, window_size=3, kappa=0.99)
        if i > 0:
            ka.stop(predictions=predictions_history[i - 1])
        kappa_lib_decisions.append(ka.stop(predictions=preds))

    # --- OverallUncertainty validation ---
    ou = OverallUncertainty(n_classes, threshold=0.05)
    ou_lib_result = ou.stop(proba=proba, indices=indices_unlabeled)

    # --- ClassificationChange validation ---
    cc = ClassificationChange(n_classes, threshold=0.0)
    cc_lib_result = cc.stop(predictions=predictions_history[-1])

    return {
        "kappa_average_library": kappa_lib_decisions,
        "overall_uncertainty_library": ou_lib_result,
        "classification_change_library": cc_lib_result,
    }


def run_pipeline():
    """Run the full evaluation pipeline and write results."""
    os.makedirs('/app/results', exist_ok=True)

    n_query = 5

    # Generate data
    proba = generate_probability_matrix(seed=42, n_samples=50, n_classes=4)
    embeddings = generate_embeddings(seed=42, n_samples=50, n_dims=16)
    proba_mc = generate_mc_dropout_proba(seed=42, n_samples=50, n_mc=10, n_classes=4)
    predictions_history = generate_predictions_history(
        seed=42, n_samples=30, n_classes=4, n_steps=6
    )

    indices_labeled = np.arange(10)
    indices_unlabeled = np.arange(10, 50)

    # --- Run query strategies ---
    # TODO: Call each strategy and collect results into strategy_results dict.
    # Keys: least_confidence, breaking_ties, prediction_entropy, bald,
    #        greedy_coreset, lightweight_coreset
    # Each value: sorted list of n_query selected indices (.tolist()).
    # For greedy_coreset: use distance_metric='cosine'.
    # For lightweight_coreset: use distance_metric='cosine', seed=123.
    strategy_results = {}

    # --- Run stopping criteria ---
    # TODO: Call each stopping criterion and collect results into stopping_results.
    # kappa_average: pass predictions_history, num_classes=4, window_size=3,
    #                kappa_threshold=0.99. Value: list of bool.
    # overall_uncertainty: pass proba, indices_unlabeled, num_classes=4,
    #                      threshold=0.05. Value: single bool.
    # classification_change: compare predictions_history[-1] vs
    #                        predictions_history[-2], threshold=0.0.
    #                        Value: single bool.
    stopping_results = {}

    # --- Cross-validate stopping criteria against small-text library ---
    validation_raw = run_validation(
        predictions_history, proba, indices_unlabeled, 4
    )

    kappa_match = (
        validation_raw["kappa_average_library"]
        == stopping_results.get("kappa_average", [])
    )
    uncertainty_match = (
        validation_raw["overall_uncertainty_library"]
        == stopping_results.get("overall_uncertainty")
    )
    change_match = (
        validation_raw["classification_change_library"]
        == stopping_results.get("classification_change")
    )

    validation_results = {
        "kappa_average_match": kappa_match,
        "overall_uncertainty_match": uncertainty_match,
        "classification_change_match": change_match,
        "all_match": kappa_match and uncertainty_match and change_match,
    }

    # Write results
    with open('/app/results/strategy_rankings.json', 'w') as f:
        json.dump(strategy_results, f, indent=2)

    with open('/app/results/stopping_decisions.json', 'w') as f:
        json.dump(stopping_results, f, indent=2)

    with open('/app/results/validation.json', 'w') as f:
        json.dump(validation_results, f, indent=2)

    print("Pipeline complete. Results written to /app/results/")


if __name__ == '__main__':
    run_pipeline()
