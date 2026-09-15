"""Out-of-bag data valuation evaluator."""

import numpy as np
from sklearn.utils import check_random_state


class DataOOBEvaluator:
    """Evaluates training data quality via out-of-bag prediction accuracy.

    Trains an ensemble of models on random subsets of training data and
    uses out-of-bag predictions to estimate per-datum quality scores.
    Points whose labels are consistently predicted correctly when excluded
    from training receive higher values.

    Parameters
    ----------
    num_models : int
        Number of models in the ensemble.
    sample_fraction : float
        Fraction of training data to include in each bootstrap sample.
    random_state : int or RandomState or None
        Random seed for reproducibility.
    """

    def __init__(self, num_models=200, sample_fraction=0.7, random_state=None):
        self.num_models = num_models
        self.sample_fraction = sample_fraction
        self.random_state = check_random_state(random_state)

    def evaluate(self, x_train, y_train, x_valid, y_valid, model_factory):
        """Compute per-datum data values using out-of-bag estimation.

        For each ensemble member, trains on a random subset and measures
        model quality using out-of-bag data to estimate per-datum scores.

        Parameters
        ----------
        x_train : np.ndarray
            Training features (n_samples, n_features).
        y_train : np.ndarray
            Training labels (n_samples,).
        x_valid : np.ndarray
            Validation features.
        y_valid : np.ndarray
            Validation labels.
        model_factory : callable
            Returns a fresh model with fit() and predict() methods.

        Returns
        -------
        np.ndarray
            Data values in [0, 1], shape (n_samples,).
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

            # Evaluate model quality and attribute to OOB points
            val_pred = model.predict(x_valid)
            val_acc = np.mean(val_pred == y_valid)
            oob_correct[out_of_bag] += val_acc
            oob_count[out_of_bag] += 1

        data_values = np.zeros(n)
        valid = oob_count > 0
        data_values[valid] = oob_correct[valid] / oob_count[valid]

        return data_values
