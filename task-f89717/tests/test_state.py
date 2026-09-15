"""
Tests for the adaptive Gauss-Kronrod quadrature library.

"""

import json
import math
import sys

sys.path.insert(0, '/app')

TOL = 1e-8


def test_smooth_finite():
    """int_0^1 4/(1+x^2) dx = pi."""
    from quadrature import integrate
    r, e, n, c = integrate(lambda x: 4.0 / (1.0 + x * x), 0, 1,
                           epsabs=TOL, epsrel=TOL)
    assert abs(r - math.pi) < TOL, \
        f"smooth: expected pi={math.pi}, got {r}, err={abs(r - math.pi)}"


def test_oscillatory_finite():
    """int_0^1 2/(2+sin(10*pi*x)) dx = 2/sqrt(3)."""
    from quadrature import integrate
    exact = 2.0 / math.sqrt(3.0)
    r, e, n, c = integrate(
        lambda x: 2.0 / (2.0 + math.sin(10.0 * math.pi * x)),
        0, 1, epsabs=TOL, epsrel=TOL, limit=1000,
    )
    assert abs(r - exact) < TOL, \
        f"oscillatory: expected {exact}, got {r}, err={abs(r - exact)}"


def test_singular_algebraic():
    """int_0^1 x^(-1/4) dx = 4/3."""
    from quadrature import integrate
    exact = 4.0 / 3.0
    r, e, n, c = integrate(
        lambda x: x ** (-0.25) if x > 0 else 0.0,
        0, 1, epsabs=TOL, epsrel=TOL, limit=1000,
    )
    assert abs(r - exact) < TOL, \
        f"singular: expected {exact}, got {r}, err={abs(r - exact)}"


def test_gaussian_semi_infinite():
    """int_0^inf exp(-x^2) dx = sqrt(pi)/2."""
    from quadrature import integrate
    exact = math.sqrt(math.pi) / 2.0
    r, e, n, c = integrate(
        lambda x: math.exp(-x * x), 0, math.inf,
        epsabs=TOL, epsrel=TOL,
    )
    assert abs(r - exact) < TOL, \
        f"gaussian: expected {exact}, got {r}, err={abs(r - exact)}"


def test_gamma_semi_infinite():
    """int_0^inf x^2*exp(-x) dx = Gamma(3) = 2."""
    from quadrature import integrate
    r, e, n, c = integrate(
        lambda x: x * x * math.exp(-x), 0, math.inf,
        epsabs=TOL, epsrel=TOL,
    )
    assert abs(r - 2.0) < TOL, \
        f"gamma: expected 2, got {r}, err={abs(r - 2.0)}"


def test_lorentzian_semi_infinite():
    """int_0^inf 1/(1+x^2) dx = pi/2."""
    from quadrature import integrate
    exact = math.pi / 2.0
    r, e, n, c = integrate(
        lambda x: 1.0 / (1.0 + x * x), 0, math.inf,
        epsabs=TOL, epsrel=TOL,
    )
    assert abs(r - exact) < TOL, \
        f"lorentzian: expected {exact}, got {r}, err={abs(r - exact)}"


def test_wynn_epsilon_convergence():
    """Wynn epsilon algorithm must accelerate the alternating harmonic series to ln(2)."""
    from quadrature import _wynn_epsilon
    sums = []
    s = 0.0
    for k in range(12):
        s += (-1.0) ** k / (k + 1)
        sums.append(s)
    result = _wynn_epsilon(sums)
    expected = math.log(2.0)
    assert abs(result - expected) < 1e-6, \
        f"epsilon: expected ln2={expected}, got {result}, err={abs(result - expected)}"


def test_results_json_exists():
    """results.json must exist with all six integral keys."""
    with open('/app/results.json') as fh:
        data = json.load(fh)
    expected_keys = [
        "smooth_pi", "oscillatory", "singular_algebraic",
        "gaussian_inf", "gamma3_inf", "lorentzian_inf",
    ]
    for k in expected_keys:
        assert k in data, f"missing key '{k}' in results.json"


def test_results_json_accuracy():
    """All computed values in results.json must be within tolerance of exact values."""
    with open('/app/results.json') as fh:
        data = json.load(fh)
    ref = {
        "smooth_pi": math.pi,
        "oscillatory": 2.0 / math.sqrt(3.0),
        "singular_algebraic": 4.0 / 3.0,
        "gaussian_inf": math.sqrt(math.pi) / 2.0,
        "gamma3_inf": 2.0,
        "lorentzian_inf": math.pi / 2.0,
    }
    for key, exact in ref.items():
        computed = data[key]["computed"]
        err = abs(computed - exact)
        assert err < TOL, \
            f"{key}: expected {exact}, got {computed}, err={err}"
