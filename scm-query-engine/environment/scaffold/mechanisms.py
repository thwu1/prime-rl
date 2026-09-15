"""
Structural equation definitions for the SCM variables.
Import MECHANISMS dict and pass individual functions to scm.set_mechanism().
"""
import numpy as np


def mechanism_X(pv):
    return (pv["U_X"] >= 0.5).astype(float)


def mechanism_H(pv):
    return (pv["U_H"] >= 0.5).astype(float)


def mechanism_T(pv):
    u_disc = (pv["U_T"] >= 0.5).astype(float)
    return ((pv["X"] + pv["H"] + u_disc) % 2).astype(float)


def mechanism_M(pv):
    return (pv["T"] * (pv["U_M"] >= 0.3)).astype(float)


def mechanism_Y(pv):
    u_disc = (pv["U_Y"] >= 0.3).astype(float)
    return ((pv["M"] + pv["H"] + u_disc) >= 2).astype(float)


MECHANISMS = {
    "X": mechanism_X,
    "H": mechanism_H,
    "T": mechanism_T,
    "M": mechanism_M,
    "Y": mechanism_Y,
}
