"""Data valuation pipeline.

Loads a dataset, computes marginal contributions via permutation-based
Monte Carlo sampling, derives data values using three semivalue weighting
schemes, a leave-one-out evaluator, and an out-of-bag evaluator, runs
ensemble detection, and writes results to JSON.
"""

import json
import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import accuracy_score

from valuation.sampler import PermutationSampler
from valuation.evaluators import (
    ShapleyEvaluator,
    BetaShapleyEvaluator,
    BanzhafEvaluator,
)
from valuation.loo import LeaveOneOutEvaluator
from valuation.oob import DataOOBEvaluator
from valuation.detector import NoisyLabelDetector


def main():
    # Load dataset
    data = np.load("/app/data/dataset.npz")
    x_train = data["x_train"]
    y_train = data["y_train"]
    x_valid = data["x_valid"]
    y_valid = data["y_valid"]

    n = len(x_train)

    # Utility function: train KNN on coalition, evaluate on validation set
    def utility(coalition_indices):
        if len(coalition_indices) < 2:
            return 0.0
        k = min(5, len(coalition_indices) - 1)
        if k < 1:
            return 0.0

        xi = x_train[coalition_indices]
        yi = y_train[coalition_indices]

        # Need at least 2 distinct classes for meaningful classification
        if len(np.unique(yi)) < 2:
            return 0.0

        clf = KNeighborsClassifier(n_neighbors=k)
        clf.fit(xi, yi)
        y_pred = clf.predict(x_valid)
        return accuracy_score(y_valid, y_pred)

    # Compute marginal contributions
    sampler = PermutationSampler(
        n, mc_epochs=300, min_cardinality=3, min_samples=100, random_state=42
    )
    sampler.set_utility(utility)
    print("Computing marginal contributions...")
    marginal_contribs = sampler.compute_marginal_contributions()
    print(f"Completed after {len(sampler.increment_stack)} epochs")

    # Compute data values with each evaluator
    evaluators = {
        "shapley": ShapleyEvaluator(),
        "beta_shapley": BetaShapleyEvaluator(alpha=4, beta=1),
        "banzhaf": BanzhafEvaluator(),
        "loo": LeaveOneOutEvaluator(),
    }

    detector = NoisyLabelDetector()
    noise_rate = 0.2

    results = {}
    evaluator_values = {}
    for name, evaluator in evaluators.items():
        values = evaluator.compute_values(marginal_contribs)
        detected = detector.detect(values, noise_rate)
        results[name] = {
            "data_values": values.tolist(),
            "detected_indices": sorted(detected.tolist()),
        }
        evaluator_values[name] = values
        print(f"{name}: detected {len(detected)} noisy points")

    # Out-of-bag evaluation
    oob = DataOOBEvaluator(num_models=200, sample_fraction=0.7, random_state=42)
    oob_values = oob.evaluate(
        x_train, y_train, x_valid, y_valid,
        lambda: KNeighborsClassifier(n_neighbors=min(5, n - 1)),
    )
    oob_detected = detector.detect(oob_values, noise_rate)
    results["data_oob"] = {
        "data_values": oob_values.tolist(),
        "detected_indices": sorted(oob_detected.tolist()),
    }
    evaluator_values["data_oob"] = oob_values
    print(f"data_oob: detected {len(oob_detected)} noisy points")

    # Ensemble detection using Borda count
    ensemble_detected = detector.ensemble_detect(evaluator_values, noise_rate, n)
    results["ensemble"] = {
        "detected_indices": sorted(ensemble_detected.tolist()),
        "method": "borda_count",
    }
    print(f"ensemble: detected {len(ensemble_detected)} noisy points")

    # Convergence diagnostics
    results["convergence"] = {
        "gr_statistic": float(sampler._compute_gr_statistic()),
        "epochs_run": int(len(sampler.increment_stack)),
    }

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to", output_path)


if __name__ == "__main__":
    main()
