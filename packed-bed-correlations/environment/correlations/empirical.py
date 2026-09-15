"""Empirical packed-bed pressure drop correlations."""

import math


def hicks(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Hicks (1970) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = 6.8 * h ** 1.0 / (Re ** 0.2 * e3)
    return fp * rho * vs * vs * L / dp


def brauer(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Brauer (1971) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (160.0 + 3.1 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def kta(dp, voidage, vs, rho, mu, L=1.0, **_):
    """KTA (1981) pebble-bed reactor pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (160.0 + 3.0 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp
