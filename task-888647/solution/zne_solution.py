"""Zero-Noise Extrapolation implementation."""

import sys
sys.path.insert(0, '/app')

import numpy as np
from scipy.optimize import curve_fit
from typing import List, Optional, Tuple

from simulator import Gate, Circuit, simulate, expectation_value


def fold_global(circuit: Circuit, scale_factor: int) -> Circuit:
    """Global circuit folding: C -> C (C† C)^((s-1)/2)."""
    if scale_factor < 1 or scale_factor % 2 == 0:
        raise ValueError(
            f"scale_factor must be a positive odd integer, got {scale_factor}"
        )
    if scale_factor == 1:
        return list(circuit)

    inverse = [g.dagger() for g in reversed(circuit)]
    result = list(circuit)
    for _ in range((scale_factor - 1) // 2):
        result = result + list(inverse) + list(circuit)
    return result


def fold_gates(circuit: Circuit, scale_factor: int) -> Circuit:
    """Per-gate folding: each G -> G (G† G)^((s-1)/2)."""
    if scale_factor < 1 or scale_factor % 2 == 0:
        raise ValueError(
            f"scale_factor must be a positive odd integer, got {scale_factor}"
        )
    if scale_factor == 1:
        return list(circuit)

    repeats = (scale_factor - 1) // 2
    result = []
    for gate in circuit:
        result.append(gate)
        dag = gate.dagger()
        for _ in range(repeats):
            result.append(dag)
            result.append(gate)
    return result


def richardson_extrapolate(scale_factors: List[float],
                           values: List[float]) -> float:
    """Lagrange interpolation at lambda=0."""
    n = len(scale_factors)
    if n != len(values):
        raise ValueError("scale_factors and values must have the same length")

    result = 0.0
    for i in range(n):
        weight = 1.0
        for j in range(n):
            if j != i:
                weight *= (0.0 - scale_factors[j]) / (
                    scale_factors[i] - scale_factors[j]
                )
        result += values[i] * weight
    return result


def polynomial_extrapolate(scale_factors: List[float],
                           values: List[float], order: int) -> float:
    """Polynomial fit of given degree, evaluated at lambda=0."""
    if order >= len(scale_factors):
        raise ValueError(
            "Need more data points than polynomial order"
        )
    coeffs = np.polyfit(scale_factors, values, order)
    return float(np.polyval(coeffs, 0.0))


def exponential_extrapolate(scale_factors: List[float],
                            values: List[float],
                            asymptote: Optional[float] = None) -> float:
    """Fit a + b * exp(c * lambda) and return f(0) = a + b."""
    x = np.array(scale_factors, dtype=float)
    y = np.array(values, dtype=float)

    if asymptote is not None:
        y_shifted = y - asymptote
        if np.all(y_shifted > 1e-15):
            log_y = np.log(y_shifted)
            c, ln_b = np.polyfit(x, log_y, 1)
            b = np.exp(ln_b)
            return asymptote + b
        elif np.all(y_shifted < -1e-15):
            log_y = np.log(-y_shifted)
            c, ln_b = np.polyfit(x, log_y, 1)
            b = -np.exp(ln_b)
            return asymptote + b

    def exp_model(lam, a, b, c):
        return a + b * np.exp(c * lam)

    a0 = y[-1]
    b0 = y[0] - a0
    c0 = -0.5
    try:
        popt, _ = curve_fit(exp_model, x, y, p0=[a0, b0, c0], maxfev=10000)
        return float(exp_model(0.0, *popt))
    except (RuntimeError, ValueError):
        return polynomial_extrapolate(
            scale_factors, values, min(2, len(scale_factors) - 1)
        )


def _lagrange_predict(scale_factors, values, x_pred):
    """Lagrange interpolation evaluated at x_pred."""
    n = len(scale_factors)
    result = 0.0
    for i in range(n):
        w = 1.0
        for j in range(n):
            if j != i:
                w *= (x_pred - scale_factors[j]) / (
                    scale_factors[i] - scale_factors[j]
                )
        result += values[i] * w
    return result


def adaptive_extrapolate(scale_factors: List[float],
                         values: List[float]) -> Tuple[float, str]:
    """Select best method via leave-one-out cross-validation."""
    n = len(scale_factors)
    if n < 3:
        return richardson_extrapolate(scale_factors, values), 'richardson'

    candidates = {}

    # Richardson: predict via Lagrange interpolation
    candidates['richardson'] = {
        'predict': lambda sf, v, xp: _lagrange_predict(sf, v, xp),
        'extrapolate': lambda sf, v: richardson_extrapolate(sf, v),
    }

    # Polynomial order 1
    def _poly_predict(sf, v, xp, order):
        coeffs = np.polyfit(sf, v, order)
        return float(np.polyval(coeffs, xp))

    candidates['polynomial_1'] = {
        'predict': lambda sf, v, xp: _poly_predict(sf, v, xp, 1),
        'extrapolate': lambda sf, v: polynomial_extrapolate(sf, v, 1),
    }

    # Polynomial order 2
    if n >= 4:
        candidates['polynomial_2'] = {
            'predict': lambda sf, v, xp: _poly_predict(sf, v, xp, 2),
            'extrapolate': lambda sf, v: polynomial_extrapolate(sf, v, 2),
        }

    # Exponential
    def _exp_predict(sf, v, xp):
        x = np.array(sf, dtype=float)
        y = np.array(v, dtype=float)

        def exp_model(lam, a, b, c):
            return a + b * np.exp(c * lam)

        a0 = y[-1]
        b0 = y[0] - a0
        c0 = -0.5
        popt, _ = curve_fit(exp_model, x, y, p0=[a0, b0, c0], maxfev=10000)
        return float(exp_model(xp, *popt))

    if n >= 4:
        candidates['exponential'] = {
            'predict': _exp_predict,
            'extrapolate': lambda sf, v: exponential_extrapolate(sf, v),
        }

    # LOO cross-validation
    loo_errors = {}
    for name, funcs in candidates.items():
        total_err = 0.0
        valid = True
        for i in range(n):
            sf_loo = [scale_factors[j] for j in range(n) if j != i]
            v_loo = [values[j] for j in range(n) if j != i]
            try:
                pred = funcs['predict'](sf_loo, v_loo, scale_factors[i])
                total_err += (pred - values[i]) ** 2
            except Exception:
                valid = False
                break
        if valid:
            loo_errors[name] = total_err

    if not loo_errors:
        return richardson_extrapolate(scale_factors, values), 'richardson'

    best = min(loo_errors, key=loo_errors.get)
    result = candidates[best]['extrapolate'](scale_factors, values)
    return result, best


def execute_with_zne(circuit: Circuit, n_qubits: int,
                     observable: np.ndarray, noise_level: float,
                     scale_factors: List[int] = None,
                     extrapolation: str = 'richardson',
                     fold_method: str = 'global') -> float:
    """Full ZNE pipeline: fold, simulate, extrapolate."""
    if scale_factors is None:
        scale_factors = [1, 3, 5]

    fold_fn = fold_global if fold_method == 'global' else fold_gates

    exp_values = []
    for sf in scale_factors:
        folded = fold_fn(circuit, sf)
        rho = simulate(folded, n_qubits, noise_level=noise_level)
        exp_values.append(expectation_value(rho, observable))

    sf_float = [float(s) for s in scale_factors]

    if extrapolation == 'richardson':
        return richardson_extrapolate(sf_float, exp_values)
    elif extrapolation.startswith('polynomial_'):
        order = int(extrapolation.split('_')[1])
        return polynomial_extrapolate(sf_float, exp_values, order)
    elif extrapolation == 'exponential':
        return exponential_extrapolate(sf_float, exp_values)
    elif extrapolation == 'adaptive':
        result, _ = adaptive_extrapolate(sf_float, exp_values)
        return result
    else:
        raise ValueError(f"Unknown extrapolation method: {extrapolation}")
