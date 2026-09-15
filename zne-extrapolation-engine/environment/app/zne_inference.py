"""Zero-noise extrapolation inference module.


Implements extrapolation factories for estimating the zero-noise limit
E(0) from noisy expectation values measured at various noise scale factors.

Each factory models the relationship E(lambda) between the expectation value
and the noise scale factor lambda, then extrapolates to lambda = 0.

The fit_and_predict method must support prediction at arbitrary scale factor
values (not just lambda=0), because model selection requires predicting at
held-out data points.
"""

import numpy as np


class ExtrapolationFactory:
    """Base class for ZNE extrapolation factories."""

    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        """Fit model to (scale_factors, exp_values) and predict at predict_at.

        Args:
            scale_factors: Array of noise scale factors (lambda values).
            exp_values: Array of measured expectation values at each scale factor.
            predict_at: The scale factor value at which to predict.

        Returns:
            The predicted expectation value at predict_at.
        """
        raise NotImplementedError

    @classmethod
    def extrapolate(cls, scale_factors, exp_values):
        """Extrapolate to the zero-noise limit (scale_factor = 0).

        Args:
            scale_factors: Array of noise scale factors.
            exp_values: Array of measured expectation values.

        Returns:
            The estimated zero-noise expectation value E(0).
        """
        return cls.fit_and_predict(
            np.asarray(scale_factors, dtype=float),
            np.asarray(exp_values, dtype=float),
            0.0,
        )


class LinearFactory(ExtrapolationFactory):
    """Linear fit: E(lambda) = a + b*lambda.

    This factory is IMPLEMENTED and serves as a reference for the interface.
    """

    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        sf = np.asarray(scale_factors, dtype=float)
        ev = np.asarray(exp_values, dtype=float)
        coeffs = np.polyfit(sf, ev, 1)
        return float(np.polyval(coeffs, predict_at))


class RichardsonFactory(ExtrapolationFactory):
    """Polynomial interpolation through all data points.

    Must handle arbitrary non-uniform scale factors.
    Must be numerically stable for up to 7 data points.
    """

    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        raise NotImplementedError("RichardsonFactory.fit_and_predict not implemented")


class ExpFactory(ExtrapolationFactory):
    """Exponential model: E(lambda) = a + b * exp(c * lambda).

    Three free parameters. Requires at least 3 data points.
    """

    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at):
        raise NotImplementedError("ExpFactory.fit_and_predict not implemented")


class PolyExpFactory(ExtrapolationFactory):
    """Generalized exponential model: E(lambda) = a + s * exp(z(lambda))

    where z(lambda) is a polynomial of specified order and s = +/-1.
    Default polynomial order is 2. Requires at least (order + 2) data points.
    """

    @classmethod
    def fit_and_predict(cls, scale_factors, exp_values, predict_at, order=2):
        raise NotImplementedError("PolyExpFactory.fit_and_predict not implemented")
