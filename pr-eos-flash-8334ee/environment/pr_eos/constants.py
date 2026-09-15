"""Peng-Robinson EOS universal constants.

"""
import math

R = 8.314462618153241  # J/(mol*K) CODATA 2018

_sqrt2 = math.sqrt(2.0)

# Analytical PR critical-point constants
_X_PR = (
    -1.0
    + (6.0 * _sqrt2 + 8.0) ** (1.0 / 3.0)
    - (6.0 * _sqrt2 - 8.0) ** (1.0 / 3.0)
) / 3.0
OMEGA_A = 8.0 * (5.0 * _X_PR + 1.0) / (49.0 - 37.0 * _X_PR)
OMEGA_B = _X_PR / (_X_PR + 3.0)
