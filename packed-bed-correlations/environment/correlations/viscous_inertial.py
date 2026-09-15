"""Viscous-inertial packed-bed pressure drop correlations."""

import math


def ergun(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Ergun (1952) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 1.56 * (Re / h)) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def kuo_nydegger(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Kuo & Nydegger (1978) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (276.23 + 5.05 * (Re / h) ** 0.87) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def tallmadge(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Tallmadge (1970) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 4.2 * (Re / h) ** (5.0 / 6.0)) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def jones_krier(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Jones & Krier (1983) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (150.0 + 3.89 * (Re / h) ** 0.87) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp


def carman(dp, voidage, vs, rho, mu, L=1.0, **_):
    """Carman (1937) packed-bed pressure drop correlation."""
    Re = dp * rho * vs / mu
    h = 1.0 - voidage
    e3 = voidage * voidage * voidage
    fp = (180.0 + 2.871 * (Re / h) ** 0.9) * h * h / (e3 * Re)
    return fp * rho * vs * vs * L / dp
