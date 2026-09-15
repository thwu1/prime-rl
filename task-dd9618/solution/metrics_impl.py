import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.model_selection import KFold, cross_val_score
from scipy.spatial.distance import pdist, squareform


def c2st(X, Y, seed=1):
    """Classifier Two-Sample Test.

    Z-scores using X's statistics, trains MLP classifier with 5-fold CV.
    Returns mean accuracy (0.5 = identical, 1.0 = perfectly distinguishable).
    """
    X = np.array(X, dtype=np.float64)
    Y = np.array(Y, dtype=np.float64)

    X_mean = np.mean(X, axis=0)
    X_std = np.std(X, axis=0)
    X_std = np.where(X_std > 0, X_std, 1.0)
    X = (X - X_mean) / X_std
    Y = (Y - X_mean) / X_std

    ndim = X.shape[1]
    clf = MLPClassifier(
        activation='relu',
        hidden_layer_sizes=(10 * ndim, 10 * ndim),
        max_iter=10000,
        solver='adam',
        random_state=seed,
    )

    data = np.concatenate([X, Y])
    target = np.concatenate([np.zeros(X.shape[0]), np.ones(Y.shape[0])])

    shuffle = KFold(n_splits=5, shuffle=True, random_state=seed)
    scores = cross_val_score(clf, data, target, cv=shuffle, scoring='accuracy')

    return float(np.mean(scores))


def mmd(X, Y):
    """Unbiased MMD^2 U-statistic with Gaussian kernel.

    Bandwidth sigma = median of pairwise Euclidean distances in X.
    Kernel: k(x, y) = exp(-||x - y||^2 / (2 * sigma^2))
    """
    X = np.array(X, dtype=np.float64)
    Y = np.array(Y, dtype=np.float64)
    n = X.shape[0]
    m = Y.shape[0]

    dists_X = pdist(X)
    sigma = float(np.median(dists_X))
    if sigma == 0:
        sigma = 1.0
    gamma = 1.0 / (2.0 * sigma ** 2)

    K_XX = np.exp(-gamma * squareform(pdist(X, 'sqeuclidean')))
    K_YY = np.exp(-gamma * squareform(pdist(Y, 'sqeuclidean')))

    dists_XY_sq = np.sum((X[:, None, :] - Y[None, :, :]) ** 2, axis=2)
    K_XY = np.exp(-gamma * dists_XY_sq)

    np.fill_diagonal(K_XX, 0)
    np.fill_diagonal(K_YY, 0)

    mmd2 = (np.sum(K_XX) / (n * (n - 1))
            + np.sum(K_YY) / (m * (m - 1))
            - 2.0 * np.sum(K_XY) / (n * m))

    return float(mmd2)
