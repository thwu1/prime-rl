
import sys
sys.path.insert(0, '/app')

import numpy as np
import pytest
from sklearn import datasets
from sklearn.utils import check_random_state


iris = datasets.load_iris()
rng = check_random_state(42)
perm = rng.permutation(iris.target.size)
X_iris = iris.data[perm]
y_iris = iris.target[perm]


class TestGlvqBaseline:
    """GLVQ is correct and serves as a sanity baseline."""

    def test_accuracy_iris(self):
        from lvq import GlvqModel
        model = GlvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        score = model.score(X_iris, y_iris)
        assert score > 0.90, f"GLVQ accuracy {score:.3f} should be > 0.90"


class TestGmlvqModel:
    """GMLVQ must learn a proper relevance matrix with correct normalization
    and regularization behavior."""

    def test_accuracy_iris(self):
        from lvq import GmlvqModel
        model = GmlvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        score = model.score(X_iris, y_iris)
        assert score > 0.90, f"GMLVQ accuracy {score:.3f} should be > 0.90"

    def test_omega_trace_normalization(self):
        from lvq import GmlvqModel
        model = GmlvqModel(prototypes_per_class=1, random_state=42)
        model.fit(X_iris, y_iris)
        omega = model.omega_
        trace_val = np.trace(omega.T @ omega)
        assert np.isclose(trace_val, 1.0, atol=1e-6), \
            f"trace(omega^T @ omega) = {trace_val:.8f}, expected 1.0"

    def test_regularization_prevents_degeneracy(self):
        from lvq import GmlvqModel
        model = GmlvqModel(prototypes_per_class=1, random_state=42,
                           regularization=0.1)
        model.fit(X_iris, y_iris)
        omega = model.omega_
        lambda_omega = omega.T @ omega
        eigenvalues = np.linalg.eigvalsh(lambda_omega)
        ev_normalized = eigenvalues / eigenvalues.sum()
        assert ev_normalized.min() > 0.01, \
            ("Regularization should spread eigenvalues to prevent "
             f"degeneracy: normalized eigenvalues = {ev_normalized}")

    def test_omega_structure_2d(self):
        from lvq import GmlvqModel
        rng_data = np.random.RandomState(123)
        nb_ppc = 50
        X = np.vstack([
            rng_data.multivariate_normal([0, 0], [[0.3, 0], [0, 4]],
                                         size=nb_ppc),
            rng_data.multivariate_normal([4, 4], [[0.3, 0], [0, 4]],
                                         size=nb_ppc)
        ])
        y = np.concatenate([np.zeros(nb_ppc, dtype=int),
                            np.ones(nb_ppc, dtype=int)])
        model = GmlvqModel(prototypes_per_class=1, random_state=42)
        model.fit(X, y)
        relevance = np.diag(model.omega_.T @ model.omega_)
        ratio = relevance[0] / relevance.sum()
        assert ratio > 0.5, \
            (f"Feature 0 (low-variance, discriminative) should dominate "
             f"relevance: ratio = {ratio:.3f}, relevance = {relevance}")


class TestRslvqModel:
    """RSLVQ must train properly and compute valid posterior probabilities."""

    def test_accuracy_iris(self):
        from lvq import RslvqModel
        model = RslvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        score = model.score(X_iris, y_iris)
        assert score > 0.85, f"RSLVQ accuracy {score:.3f} should be > 0.85"

    def test_optimizer_converges(self):
        from lvq import RslvqModel
        model = RslvqModel(prototypes_per_class=1, random_state=42)
        model.fit(X_iris, y_iris)
        assert hasattr(model, 'n_iter_'), "Model should have n_iter_ attribute"
        assert model.n_iter_ > 1, \
            f"Optimizer should converge: n_iter_ = {model.n_iter_}"

    def test_posterior_validity(self):
        from lvq import RslvqModel
        model = RslvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)

        for idx in [0, 50, 100]:
            x = X_iris[idx]
            posteriors = []
            for cls in model.classes_:
                p = float(np.squeeze(model.posterior(cls, x)))
                assert 0 <= p <= 1, \
                    f"Posterior p({cls}|x[{idx}]) = {p}, not in [0, 1]"
                posteriors.append(p)
            total = sum(posteriors)
            assert abs(total - 1.0) < 1e-6, \
                f"Posteriors for x[{idx}] should sum to 1.0, got {total}"

    def test_posterior_correct_class_dominant(self):
        from lvq import RslvqModel
        model = RslvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)

        # For well-separated setosa samples, posterior of true class
        # must be dominant
        setosa_indices = np.where(y_iris == 0)[0][:5]
        for idx in setosa_indices:
            x = X_iris[idx]
            posteriors = {int(cls): float(np.squeeze(model.posterior(cls, x)))
                          for cls in model.classes_}
            p_true = posteriors[0]
            assert p_true > 0.5, \
                (f"Posterior p(setosa|x[{idx}]) = {p_true:.4f} should be "
                 f"> 0.5 for well-separated setosa sample. "
                 f"All posteriors: {posteriors}")


class TestGrlvqModel:
    """GRLVQ must learn proper per-feature relevance weights."""

    def test_accuracy_iris(self):
        from lvq.grlvq import GrlvqModel
        model = GrlvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        score = model.score(X_iris, y_iris)
        assert score > 0.90, f"GRLVQ accuracy {score:.3f} should be > 0.90"

    def test_lambda_normalization(self):
        from lvq.grlvq import GrlvqModel
        model = GrlvqModel(prototypes_per_class=1, random_state=42)
        model.fit(X_iris, y_iris)
        assert hasattr(model, 'lambda_'), "Model must have lambda_ attribute"
        assert model.lambda_.shape == (X_iris.shape[1],), \
            f"lambda_ shape {model.lambda_.shape} should be ({X_iris.shape[1]},)"
        assert np.all(model.lambda_ >= 0), \
            f"All lambda_ values must be >= 0, got {model.lambda_}"
        assert np.isclose(model.lambda_.sum(), 1.0, atol=1e-6), \
            f"lambda_ sum = {model.lambda_.sum():.8f}, expected 1.0"

    def test_feature_selection_2d(self):
        from lvq.grlvq import GrlvqModel
        rng_data = np.random.RandomState(123)
        nb_ppc = 50
        X = np.vstack([
            rng_data.multivariate_normal([0, 0], [[0.3, 0], [0, 4]],
                                         size=nb_ppc),
            rng_data.multivariate_normal([4, 4], [[0.3, 0], [0, 4]],
                                         size=nb_ppc)
        ])
        y = np.concatenate([np.zeros(nb_ppc, dtype=int),
                            np.ones(nb_ppc, dtype=int)])
        model = GrlvqModel(prototypes_per_class=1, random_state=42)
        model.fit(X, y)
        assert model.lambda_[0] > model.lambda_[1], \
            (f"lambda_[0] = {model.lambda_[0]:.4f} should be > "
             f"lambda_[1] = {model.lambda_[1]:.4f} for discriminative feature")

    def test_regularization_prevents_degeneracy(self):
        from lvq.grlvq import GrlvqModel
        model = GrlvqModel(prototypes_per_class=1, random_state=42,
                           regularization=0.1)
        model.fit(X_iris, y_iris)
        assert model.lambda_.min() > 0.005, \
            (f"With regularization, min lambda = {model.lambda_.min():.6f} "
             f"should be > 0.005, lambda = {model.lambda_}")

    def test_compute_distance_shape(self):
        from lvq.grlvq import GrlvqModel
        model = GrlvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        dist = model._compute_distance(X_iris)
        n_prototypes = len(model.classes_) * 2
        assert dist.shape == (X_iris.shape[0], n_prototypes), \
            f"Distance shape {dist.shape} should be ({X_iris.shape[0]}, {n_prototypes})"

    def test_predict_consistency(self):
        from lvq.grlvq import GrlvqModel
        model = GrlvqModel(prototypes_per_class=2, random_state=42)
        model.fit(X_iris, y_iris)
        pred = model.predict(X_iris)
        assert pred.shape == y_iris.shape, \
            f"Predict shape {pred.shape} should be {y_iris.shape}"
        assert set(pred).issubset(set(model.classes_)), \
            "Predictions should only contain valid class labels"
