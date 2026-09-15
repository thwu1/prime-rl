"""Fix all bugs in the data valuation framework and add missing components.

Issues resolved:
1. sampler.py: Truncation counter logic inverted (increments on significant,
   resets on negligible - should be the opposite).
2. sampler.py: GR statistic formula uses subtraction instead of addition for
   the between-chain variance term.
3. evaluators.py: BetaShapleyEvaluator has alpha/beta swapped in beta_func.
4. evaluators.py: BanzhafEvaluator uses comb(n,j) instead of comb(n-1,j).
5. oob.py: DataOOBEvaluator measures aggregate model quality on validation
   set instead of per-point OOB prediction accuracy on training features.
6. detector.py: ensemble_detect selects highest rank sum (least suspicious)
   instead of lowest rank sum (most suspicious).
7. pipeline.py: output_path variable undefined.
8. pipeline.py: removal_validation section missing from output.
9. loo.py: compute_loo_values returns zeros - must implement correctly.
10. pipeline.py: LOO processed in semivalue loop via compute_values which
    raises NotImplementedError - must restructure to use compute_loo_values.
11. pipeline.py: stability analysis missing from output.
"""


import os

# --- Fix 1 & 2: sampler.py ---
SAMPLER_FIXED = '''\
"""Permutation-based Monte Carlo sampler for marginal contribution estimation."""

import numpy as np
from sklearn.utils import check_random_state


class PermutationSampler:
    """Samples random permutations to estimate marginal contributions.

    Parameters
    ----------
    num_points : int
        Number of data points in the training set.
    mc_epochs : int
        Maximum number of permutation samples.
    min_cardinality : int
        Minimum coalition size before recording marginal contributions.
    gr_threshold : float
        Gelman-Rubin statistic threshold for MCMC convergence.
    min_samples : int
        Minimum permutation samples before checking convergence.
    random_state : int or RandomState or None
        Random seed for reproducibility.
    """

    def __init__(
        self,
        num_points,
        mc_epochs=300,
        min_cardinality=5,
        gr_threshold=1.05,
        min_samples=100,
        random_state=None,
    ):
        self.num_points = num_points
        self.mc_epochs = mc_epochs
        self.min_cardinality = min_cardinality
        self.gr_threshold = gr_threshold
        self.min_samples = min_samples
        self.random_state = check_random_state(random_state)

        self.marginal_contrib_sum = np.zeros((num_points, num_points))
        self.marginal_count = np.zeros((num_points, num_points)) + 1e-8
        self.increment_stack = np.zeros((0, num_points))

    def set_utility(self, utility_func):
        """Set the utility function that scores a coalition of data points."""
        self.compute_utility = utility_func

    def compute_marginal_contributions(self):
        """Run MCMC sampling and return average marginal contributions."""
        for epoch in range(self.mc_epochs):
            increment = self._sample_one_permutation()
            self.increment_stack = np.vstack([self.increment_stack, increment])

            if len(self.increment_stack) >= self.min_samples:
                gr = self._compute_gr_statistic()
                if gr < self.gr_threshold:
                    break

        return self.marginal_contrib_sum / self.marginal_count

    def _sample_one_permutation(self):
        """Sample one random permutation and record marginal contributions."""
        perm = self.random_state.permutation(self.num_points)
        marginal_increment = np.zeros(self.num_points) + 1e-8
        coalition = list(perm[: self.min_cardinality])
        truncation_counter = 0

        prev_perf = self.compute_utility(coalition)

        for cutoff, idx in enumerate(
            perm[self.min_cardinality :], start=self.min_cardinality
        ):
            coalition.append(idx)
            curr_perf = self.compute_utility(coalition)
            marginal_increment[idx] = curr_perf - prev_perf

            self.marginal_contrib_sum[idx, cutoff] += curr_perf - prev_perf
            self.marginal_count[idx, cutoff] += 1

            # FIX 1: Truncation logic corrected.
            # Increment counter when contribution is negligible,
            # reset when contribution is significant.
            relative_change = abs(curr_perf - prev_perf) / max(
                np.sum(np.abs(marginal_increment)), 1e-8
            )
            if relative_change < 1e-8:
                truncation_counter += 1
            else:
                truncation_counter = 0

            if truncation_counter == 10:
                remaining = perm[(cutoff + 1) :]
                remaining_positions = np.arange(cutoff + 1, len(perm))
                if len(remaining) > 0:
                    self.marginal_count[remaining, remaining_positions] += 1
                break

            prev_perf = curr_perf

        return marginal_increment.reshape(1, -1)

    def _compute_gr_statistic(self, num_chains=10):
        """Compute Gelman-Rubin convergence diagnostic."""
        samples = self.increment_stack
        num_samples, num_datapoints = samples.shape

        if num_samples < self.min_samples:
            return 100.0

        num_per_chain, offset = divmod(num_samples, num_chains)
        if num_per_chain < 2:
            return 100.0
        samples = samples[offset:]

        chains = samples.reshape(num_chains, num_per_chain, num_datapoints)

        W = np.mean(np.var(chains, axis=1, ddof=1), axis=0)
        chain_means = np.mean(chains, axis=1)
        B = num_per_chain * np.var(chain_means, axis=0, ddof=1)

        # FIX 2: Use addition, not subtraction, for the B/(W*m) term.
        gr_stats = np.sqrt(
            (num_per_chain - 1) / num_per_chain
            + (B / (W * num_per_chain + 1e-10))
        )

        return np.nanmax(np.abs(gr_stats))
'''

# --- Fix 3 & 4: evaluators.py ---
EVALUATORS_FIXED = '''\
"""Semivalue evaluators that compute data values from marginal contributions."""

import numpy as np
from math import comb
from scipy.special import beta as beta_func


class ShapleyEvaluator:
    """Data Shapley evaluator with uniform semivalue weights."""

    def compute_weights(self, n):
        return np.ones(n) / n

    def compute_values(self, marginal_contribs):
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)


class BetaShapleyEvaluator:
    """Beta Shapley evaluator using Beta-function semivalue weights."""

    def __init__(self, alpha=4, beta=1):
        self.alpha = alpha
        self.beta = beta

    def compute_weights(self, n):
        """FIX 3: Corrected beta_func argument order.
        Uses Beta(j + beta, n - j - 1 + alpha) / Beta(j+1, n-j).
        """
        weight_list = [
            beta_func(j + self.beta, n - (j + 1) + self.alpha)
            / beta_func(j + 1, n - j)
            for j in range(n)
        ]
        return np.array(weight_list) / np.sum(weight_list)

    def compute_values(self, marginal_contribs):
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)


class BanzhafEvaluator:
    """Data Banzhaf evaluator using binomial coefficient weights."""

    def compute_weights(self, n):
        """FIX 4: Use comb(n-1, j), not comb(n, j)."""
        weights = np.array([comb(n - 1, j) for j in range(n)], dtype=float)
        return weights / weights.sum()

    def compute_values(self, marginal_contribs):
        n = marginal_contribs.shape[0]
        weights = self.compute_weights(n)
        return np.sum(marginal_contribs * weights[np.newaxis, :], axis=1)
'''

# --- Fix 5: oob.py ---
OOB_FIXED = '''\
"""Out-of-bag data valuation evaluator."""

import numpy as np
from sklearn.utils import check_random_state


class DataOOBEvaluator:
    """Evaluates training data quality via out-of-bag prediction accuracy."""

    def __init__(self, num_models=200, sample_fraction=0.7, random_state=None):
        self.num_models = num_models
        self.sample_fraction = sample_fraction
        self.random_state = check_random_state(random_state)

    def evaluate(self, x_train, y_train, x_valid, y_valid, model_factory):
        """FIX 5: Compute per-point OOB prediction accuracy on training
        features instead of aggregate model quality on validation set.
        """
        n = len(x_train)
        sample_size = max(1, int(n * self.sample_fraction))

        oob_correct = np.zeros(n)
        oob_count = np.zeros(n)

        for _ in range(self.num_models):
            in_bag = self.random_state.choice(n, size=sample_size, replace=False)
            out_of_bag = np.setdiff1d(np.arange(n), in_bag)

            if len(out_of_bag) == 0:
                continue

            model = model_factory()
            x_sub = x_train[in_bag]
            y_sub = y_train[in_bag]

            if len(np.unique(y_sub)) < 2:
                continue

            model.fit(x_sub, y_sub)

            # Predict on OOB training features and check per-point accuracy
            oob_pred = model.predict(x_train[out_of_bag])
            correct = (oob_pred == y_train[out_of_bag]).astype(float)
            oob_correct[out_of_bag] += correct
            oob_count[out_of_bag] += 1

        data_values = np.zeros(n)
        valid = oob_count > 0
        data_values[valid] = oob_correct[valid] / oob_count[valid]

        return data_values
'''

# --- Fix 6: detector.py ---
DETECTOR_FIXED = '''\
"""Noisy label detector using data valuation scores."""

import numpy as np


class NoisyLabelDetector:
    """Detects noisy training points via data value ranking and rank aggregation."""

    def detect(self, data_values, noise_rate):
        """Flag the lowest-valued training points as noisy."""
        n = len(data_values)
        k = int(n * noise_rate)
        return np.sort(np.argsort(data_values)[:k])

    def ensemble_detect(self, evaluator_results, noise_rate, n_points):
        """FIX 6: Select points with lowest rank sum (most suspicious),
        not highest rank sum (least suspicious).
        """
        rank_sum = np.zeros(n_points)
        for name, values in evaluator_results.items():
            values = np.array(values)
            ranks = np.argsort(np.argsort(values))
            rank_sum += ranks

        k = int(n_points * noise_rate)
        return np.sort(np.argsort(rank_sum)[:k])
'''

# --- Fix 9: loo.py ---
LOO_FIXED = '''\
"""Leave-one-out data valuation evaluator."""

import numpy as np


class LeaveOneOutEvaluator:
    """Leave-one-out data valuation evaluator.

    Computes the change in utility when each individual training point
    is excluded from the dataset.
    """

    def compute_values(self, marginal_contribs):
        """LOO values cannot be accurately derived from the marginal
        contribution matrix via semivalue reweighting.
        """
        raise NotImplementedError(
            "LOO evaluation requires direct utility computation."
        )

    def compute_loo_values(self, utility_func, n):
        """FIX 9: Compute LOO values by direct utility evaluation.
        v_i = U(D) - U(D \\ {i}) for each training point i.
        """
        all_indices = list(range(n))
        full_utility = utility_func(all_indices)

        values = np.zeros(n)
        for i in range(n):
            leave_out = [j for j in range(n) if j != i]
            values[i] = full_utility - utility_func(leave_out)

        return values
'''

# --- Fix 7, 8, 10, 11: pipeline.py ---
PIPELINE_FIXED = '''\
"""Data valuation pipeline."""

import json
import numpy as np
from scipy.stats import spearmanr
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
    data = np.load("/app/data/dataset.npz")
    x_train = data["x_train"]
    y_train = data["y_train"]
    x_valid = data["x_valid"]
    y_valid = data["y_valid"]

    n = len(x_train)

    def utility(coalition_indices):
        if len(coalition_indices) < 2:
            return 0.0
        k = min(5, len(coalition_indices) - 1)
        if k < 1:
            return 0.0

        xi = x_train[coalition_indices]
        yi = y_train[coalition_indices]

        if len(np.unique(yi)) < 2:
            return 0.0

        clf = KNeighborsClassifier(n_neighbors=k)
        clf.fit(xi, yi)
        y_pred = clf.predict(x_valid)
        return accuracy_score(y_valid, y_pred)

    sampler = PermutationSampler(
        n, mc_epochs=300, min_cardinality=3, min_samples=100, random_state=42
    )
    sampler.set_utility(utility)
    print("Computing marginal contributions...")
    marginal_contribs = sampler.compute_marginal_contributions()
    print(f"Completed after {len(sampler.increment_stack)} epochs")

    # FIX 10: Process semivalue evaluators separately from LOO
    semivalue_evaluators = {
        "shapley": ShapleyEvaluator(),
        "beta_shapley": BetaShapleyEvaluator(alpha=4, beta=1),
        "banzhaf": BanzhafEvaluator(),
    }

    detector = NoisyLabelDetector()
    noise_rate = 0.2

    results = {}
    evaluator_values = {}
    for name, evaluator in semivalue_evaluators.items():
        values = evaluator.compute_values(marginal_contribs)
        detected = detector.detect(values, noise_rate)
        results[name] = {
            "data_values": values.tolist(),
            "detected_indices": sorted(detected.tolist()),
        }
        evaluator_values[name] = values
        print(f"{name}: detected {len(detected)} noisy points")

    # FIX 10: LOO uses compute_loo_values with utility function directly
    loo_evaluator = LeaveOneOutEvaluator()
    print("Computing LOO values...")
    loo_values = loo_evaluator.compute_loo_values(utility, n)
    loo_detected = detector.detect(loo_values, noise_rate)
    results["loo"] = {
        "data_values": loo_values.tolist(),
        "detected_indices": sorted(loo_detected.tolist()),
    }
    evaluator_values["loo"] = loo_values
    print(f"loo: detected {len(loo_detected)} noisy points")

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

    # FIX 11: Split-half stability analysis
    stack = sampler.increment_stack
    half = len(stack) // 2
    if half > 0:
        first_half_means = np.mean(stack[:half], axis=0)
        second_half_means = np.mean(stack[half:2 * half], axis=0)
        corr, _ = spearmanr(first_half_means, second_half_means)
    else:
        corr = 0.0
    results["stability"] = {
        "split_half_correlation": float(corr),
    }

    # FIX 8: Removal validation
    ensemble_indices = results["ensemble"]["detected_indices"]
    clean_mask = np.ones(n, dtype=bool)
    clean_mask[ensemble_indices] = False

    clf_full = KNeighborsClassifier(n_neighbors=5)
    clf_full.fit(x_train, y_train)
    orig_acc = accuracy_score(y_valid, clf_full.predict(x_valid))

    n_clean = clean_mask.sum()
    k_clean = min(5, n_clean - 1)
    if k_clean >= 1 and len(np.unique(y_train[clean_mask])) >= 2:
        clf_clean = KNeighborsClassifier(n_neighbors=k_clean)
        clf_clean.fit(x_train[clean_mask], y_train[clean_mask])
        clean_acc = accuracy_score(y_valid, clf_clean.predict(x_valid))
    else:
        clean_acc = orig_acc

    results["removal_validation"] = {
        "original_accuracy": float(orig_acc),
        "cleaned_accuracy": float(clean_acc),
    }

    # FIX 7: Define output_path
    output_path = "/app/results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print("Pipeline complete. Results written to", output_path)


if __name__ == "__main__":
    main()
'''


def main():
    """Write all corrected files."""
    files = {
        "/app/valuation/sampler.py": SAMPLER_FIXED,
        "/app/valuation/evaluators.py": EVALUATORS_FIXED,
        "/app/valuation/oob.py": OOB_FIXED,
        "/app/valuation/detector.py": DETECTOR_FIXED,
        "/app/valuation/loo.py": LOO_FIXED,
        "/app/pipeline.py": PIPELINE_FIXED,
    }
    for path, content in files.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        print(f"Fixed: {path}")


if __name__ == "__main__":
    main()
