
import numpy as np
import h5py
import pytest
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import KFold, cross_val_score

C2ST_THRESHOLD = 0.57
PRIOR_LOW = -1.0
PRIOR_HIGH = 1.0
EXPECTED_SHAPE = (10000, 2)
REF_SEEDS = {1: 12345, 2: 23456, 3: 34567}


def _sample_reference_posterior(observation, num_samples, seed):
    """Generate exact posterior samples via closed-form model inversion.

    This function analytically inverts the generative model to produce
    ground-truth posterior samples by rejection sampling within the prior.
    """
    rng = np.random.RandomState(seed)
    obs = observation.flatten()
    ang = np.pi / 4.0
    c, s = np.cos(ang), np.sin(ang)

    samples = []
    while len(samples) < num_samples:
        a_val = rng.uniform(-np.pi / 2, np.pi / 2)
        r_val = rng.normal(0.1, 0.01)
        p = np.array([np.cos(a_val) * r_val + 0.25, np.sin(a_val) * r_val])
        q0 = p[0] - obs[0]
        q1 = obs[1] - p[1]
        if rng.rand() < 0.5:
            q0 = -q0
        theta = np.array([c * q0 - s * q1, s * q0 + c * q1])
        if np.all(np.abs(theta) <= 1.0):
            samples.append(theta)

    return np.array(samples)


def _get_reference(obs_idx):
    """Load observation and generate fresh reference posterior at test time."""
    with h5py.File('/app/observations.h5', 'r') as f:
        obs = np.array(f[f'obs_{obs_idx}'])
    return _sample_reference_posterior(obs, 10000, REF_SEEDS[obs_idx])


def compute_c2st(X, Y, seed=1, n_folds=5):
    """Classifier Two-Sample Test following sbibm methodology."""
    X = np.asarray(X, dtype=np.float64)
    Y = np.asarray(Y, dtype=np.float64)

    X_mean = np.mean(X, axis=0)
    X_std = np.std(X, axis=0)
    X_std = np.where(X_std > 0, X_std, 1.0)
    X_z = (X - X_mean) / X_std
    Y_z = (Y - X_mean) / X_std

    ndim = X.shape[1]
    clf = MLPClassifier(
        activation='relu',
        hidden_layer_sizes=(10 * ndim, 10 * ndim),
        max_iter=10000,
        solver='adam',
        random_state=seed,
    )

    data = np.vstack([X_z, Y_z])
    labels = np.concatenate([np.zeros(len(X_z)), np.ones(len(Y_z))])

    kf = KFold(n_splits=n_folds, shuffle=True, random_state=seed)
    scores = cross_val_score(clf, data, labels, cv=kf, scoring='accuracy')
    return float(np.mean(scores))


@pytest.fixture(params=[1, 2, 3])
def obs_idx(request):
    return request.param


def test_result_hdf5_exists():
    """Result HDF5 file must exist and be readable."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        assert len(f.keys()) > 0, "HDF5 file is empty"


def test_dataset_present(obs_idx):
    """Each posterior dataset must be present in the HDF5 file."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        assert f'posterior_{obs_idx}' in f, \
            f"Missing dataset posterior_{obs_idx}"


def test_result_shape(obs_idx):
    """Posterior samples must have shape (10000, 2)."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    assert samples.shape == EXPECTED_SHAPE, \
        f"Expected shape {EXPECTED_SHAPE}, got {samples.shape}"


def test_no_nans(obs_idx):
    """Posterior samples must contain no NaN values."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    assert not np.any(np.isnan(samples)), "Posterior samples contain NaN"


def test_within_prior_bounds(obs_idx):
    """All samples must lie within the prior bounds [-1, 1]^2."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    assert np.all(samples >= PRIOR_LOW - 1e-6), \
        f"Samples below prior lower bound"
    assert np.all(samples <= PRIOR_HIGH + 1e-6), \
        f"Samples above prior upper bound"


def test_nontrivial_variance(obs_idx):
    """Posterior samples must have non-degenerate spread."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    std = np.std(samples, axis=0)
    assert np.all(std > 0.01), f"Variance too low: std={std}"
    assert np.all(std < 1.5), f"Variance too high: std={std}"


def test_not_uniform_prior(obs_idx):
    """Samples should be more concentrated than the prior."""
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    # Uniform[-1,1] has std ~0.577; a good posterior is tighter
    std = np.std(samples, axis=0)
    assert np.any(std < 0.5), \
        f"Samples look like prior draws (std={std})"


def test_c2st_quality(obs_idx):
    """Posterior must achieve C2ST < 0.57 against true reference samples."""
    ref = _get_reference(obs_idx)
    with h5py.File('/app/results/posteriors.h5', 'r') as f:
        samples = np.array(f[f'posterior_{obs_idx}'])
    score = compute_c2st(ref, samples, seed=1)
    assert score < C2ST_THRESHOLD, \
        f"C2ST for obs {obs_idx} is {score:.4f}, must be < {C2ST_THRESHOLD}"
