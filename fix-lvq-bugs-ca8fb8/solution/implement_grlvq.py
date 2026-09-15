#!/usr/bin/env python3
"""Implement GRLVQ (Generalized Relevance LVQ) model.

Creates /app/lvq/grlvq.py with a complete GrlvqModel implementation
that extends GlvqModel with per-feature diagonal relevance weighting.

The implementation uses:
- Per-feature lambda_ weights for weighted squared Euclidean distance
- 3-phase L-BFGS-B optimization (prototypes only -> relevances only -> both)
- Post-training normalization of lambda_ to sum to 1.0
- Regularization via gradient-based log-determinant penalty
"""


GRLVQ_SOURCE = r'''from __future__ import division

import numpy as np
from scipy.optimize import minimize

from .glvq import GlvqModel, _squared_euclidean
from sklearn.utils import validation


class GrlvqModel(GlvqModel):
    """Generalized Relevance Learning Vector Quantization

    Learns per-feature relevance weights for prototype-based classification.

    Parameters
    ----------
    prototypes_per_class : int or list of int, optional (default=1)
        Number of prototypes per class.

    initial_prototypes : array-like, shape = [n_prototypes, n_features + 1],
     optional
        Prototypes to start with.

    initial_relevances : array-like, shape = [n_features], optional
        Relevance weights to start with. If not given all relevances are equal.

    regularization : float, optional (default=0.0)
        Regularization strength. Prevents relevance weights from degenerating
        to zero.

    max_iter : int, optional (default=2500)
        The maximum number of iterations.

    gtol : float, optional (default=1e-5)
        Gradient norm must be less than gtol before successful termination.

    beta : int, optional (default=2)
        Used inside phi.

    c : array-like, shape = [2,3], optional
        Weights for wrong classification.

    display : boolean, optional (default=False)
        Print information about the bfgs steps.

    random_state : int, RandomState instance or None, optional

    Attributes
    ----------
    w_ : array-like, shape = [n_prototypes, n_features]
        Prototype vectors.

    c_w_ : array-like, shape = [n_prototypes]
        Prototype classes.

    classes_ : array-like, shape = [n_classes]
        Array containing labels.

    lambda_ : array-like, shape = [n_features]
        Per-feature relevance weights summing to 1.0.
    """

    def __init__(self, prototypes_per_class=1, initial_prototypes=None,
                 initial_relevances=None, regularization=0.0,
                 max_iter=2500, gtol=1e-5, beta=2, c=None, display=False,
                 random_state=None):
        super(GrlvqModel, self).__init__(prototypes_per_class,
                                         initial_prototypes, max_iter,
                                         gtol, beta, c, display, random_state)
        self.regularization = regularization
        self.initial_relevances = initial_relevances

    def _optgrad(self, variables, training_data, label_equals_prototype,
                 random_state, lr_relevances=0, lr_prototypes=1):
        n_data, n_dim = training_data.shape
        nb_prototypes = self.c_w_.shape[0]
        prototypes = variables.reshape(variables.size // n_dim, n_dim)[
                     :nb_prototypes]
        lambd = variables[prototypes.size:]
        lambd[lambd < 0] = 0.0000001

        dist = _squared_euclidean(lambd * training_data,
                                  lambd * prototypes)
        d_wrong = dist.copy()
        d_wrong[label_equals_prototype] = np.inf
        distwrong = d_wrong.min(1)
        pidxwrong = d_wrong.argmin(1)

        d_correct = dist
        d_correct[np.invert(label_equals_prototype)] = np.inf
        distcorrect = d_correct.min(1)
        pidxcorrect = d_correct.argmin(1)

        distcorrectpluswrong = distcorrect + distwrong
        distcorectminuswrong = distcorrect - distwrong
        mu = distcorectminuswrong / distcorrectpluswrong
        mu = np.vectorize(self.phi_prime)(mu)

        g = np.zeros(prototypes.shape)
        distcorrectpluswrong = 4 / distcorrectpluswrong ** 2
        gw = np.zeros(lambd.size)

        for i in range(nb_prototypes):
            idxc = i == pidxcorrect
            idxw = i == pidxwrong

            dcd = mu[idxw] * distcorrect[idxw] * distcorrectpluswrong[idxw]
            dwd = mu[idxc] * distwrong[idxc] * distcorrectpluswrong[idxc]
            if lr_relevances > 0:
                difc = training_data[idxc] - prototypes[i]
                difw = training_data[idxw] - prototypes[i]
                gw -= dcd.dot(difw ** 2) - dwd.dot(difc ** 2)
                if lr_prototypes > 0:
                    g[i] = dcd.dot(difw) - dwd.dot(difc)
            elif lr_prototypes > 0:
                g[i] = dcd.dot(training_data[idxw]) - \
                       dwd.dot(training_data[idxc]) + \
                       (dwd.sum(0) - dcd.sum(0)) * prototypes[i]
        f3 = 0
        if self.regularization:
            f3 = np.diag(np.linalg.pinv(np.sqrt(np.diag(lambd))))
        if lr_relevances > 0:
            gw = 2 / n_data * lr_relevances * \
                 gw - self.regularization * f3
        if lr_prototypes > 0:
            g[:nb_prototypes] = 1 / n_data * lr_prototypes * \
                                g[:nb_prototypes] * lambd
        g = np.append(g.ravel(), gw, axis=0)
        g = g * (1 + 0.0001 * (random_state.rand(*g.shape) - 0.5))
        return g

    def _optfun(self, variables, training_data, label_equals_prototype):
        n_data, n_dim = training_data.shape
        nb_prototypes = self.c_w_.shape[0]
        prototypes = variables.reshape(variables.size // n_dim, n_dim)[
                     :nb_prototypes]
        lambd = variables[prototypes.size:]

        dist = _squared_euclidean(lambd * training_data,
                                  lambd * prototypes)
        d_wrong = dist.copy()
        d_wrong[label_equals_prototype] = np.inf
        distwrong = d_wrong.min(1)

        d_correct = dist
        d_correct[np.invert(label_equals_prototype)] = np.inf
        distcorrect = d_correct.min(1)

        distcorrectpluswrong = distcorrect + distwrong
        distcorectminuswrong = distcorrect - distwrong
        mu = distcorectminuswrong / distcorrectpluswrong
        mu *= self.c_[label_equals_prototype.argmax(1), d_wrong.argmin(1)]

        return np.vectorize(self.phi)(mu).sum(0)

    def _optimize(self, x, y, random_state):
        if not isinstance(self.regularization,
                          float) or self.regularization < 0:
            raise ValueError("regularization must be a positive float")
        nb_prototypes, nb_features = self.w_.shape
        if self.initial_relevances is None:
            self.lambda_ = np.ones([nb_features])
        else:
            self.lambda_ = validation.column_or_1d(
                validation.check_array(self.initial_relevances, dtype='float',
                                       ensure_2d=False))
            if self.lambda_.size != nb_features:
                raise ValueError(
                    "length of initial relevances is wrong"
                    "features=%d"
                    "length=%d" % (nb_features, self.lambda_.size))
        self.lambda_ /= np.sum(self.lambda_)
        variables = np.append(self.w_.ravel(), self.lambda_, axis=0)
        label_equals_prototype = y[np.newaxis].T == self.c_w_
        method = 'l-bfgs-b'
        res = minimize(
            fun=lambda vs: self._optfun(
                vs, x, label_equals_prototype=label_equals_prototype),
            jac=lambda vs: self._optgrad(
                vs, x, label_equals_prototype=label_equals_prototype,
                lr_prototypes=1, lr_relevances=0, random_state=random_state),
            method=method, x0=variables,
            options={'disp': self.display, 'gtol': self.gtol,
                     'maxiter': self.max_iter})
        n_iter = res.nit
        res = minimize(
            fun=lambda vs: self._optfun(
                vs, x, label_equals_prototype=label_equals_prototype),
            jac=lambda vs: self._optgrad(
                vs, x, label_equals_prototype=label_equals_prototype,
                lr_prototypes=0, lr_relevances=1, random_state=random_state),
            method=method, x0=res.x,
            options={'disp': self.display, 'gtol': self.gtol,
                     'maxiter': self.max_iter})
        n_iter = max(n_iter, res.nit)
        res = minimize(
            fun=lambda vs: self._optfun(
                vs, x, label_equals_prototype=label_equals_prototype),
            jac=lambda vs: self._optgrad(
                vs, x, label_equals_prototype=label_equals_prototype,
                lr_prototypes=1, lr_relevances=1, random_state=random_state),
            method=method, x0=res.x,
            options={'disp': self.display, 'gtol': self.gtol,
                     'maxiter': self.max_iter})
        n_iter = max(n_iter, res.nit)
        self.w_ = res.x.reshape(
            res.x.size // nb_features, nb_features)[:nb_prototypes]
        self.lambda_ = res.x[self.w_.size:]
        self.lambda_[self.lambda_ < 0] = 0.0000001
        self.lambda_ = self.lambda_ / self.lambda_.sum()
        self.n_iter_ = n_iter

    def _compute_distance(self, x, w=None, lambda_=None):
        if w is None:
            w = self.w_
        if lambda_ is None:
            lambda_ = self.lambda_
        nb_samples = x.shape[0]
        nb_prototypes = w.shape[0]
        distance = np.zeros([nb_prototypes, nb_samples])
        for i in range(nb_prototypes):
            delta = x - w[i]
            distance[i] = np.sum(delta ** 2 * lambda_, 1)
        return distance.T

    def project(self, x, dims, print_variance_covered=False):
        idx = self.lambda_.argsort()[::-1]
        if print_variance_covered:
            print('variance covered by projection:',
                  self.lambda_[idx][:dims].sum() / self.lambda_.sum() * 100)
        return x.dot(np.diag(self.lambda_)[idx][:, :dims])
'''


if __name__ == '__main__':
    with open('/app/lvq/grlvq.py', 'w') as f:
        f.write(GRLVQ_SOURCE)
    print("Created /app/lvq/grlvq.py with GrlvqModel implementation")
