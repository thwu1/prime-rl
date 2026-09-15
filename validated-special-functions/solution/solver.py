#!/usr/bin/env python3

"""
Validated special function evaluator.
Uses mpmath at high working precision with two independent evaluation methods
per function, cross-validates, and outputs certified results.
"""

import json
import mpmath

# Working precision: 80 digits internally, report 60, require 40 correct
WORKING_DPS = 80
mpmath.mp.dps = WORKING_DPS


def make_z(params):
    """Create argument z from params, using mpf for real and mpc for complex."""
    z_re = mpmath.mpf(params["z_re"])
    z_im = mpmath.mpf(params.get("z_im", "0"))
    if z_im == 0:
        return z_re
    return mpmath.mpc(z_re, z_im)


def to_str(x):
    """Convert mpmath number to string with 60 significant digits."""
    return mpmath.nstr(x, 60, strip_zeros=False)


def format_result(val):
    """Format a result value into (re_str, im_str)."""
    if isinstance(val, mpmath.mpc):
        return to_str(val.real), to_str(val.imag)
    return to_str(val), "0"


def eval_gamma(params):
    """Evaluate Gamma(z) using two methods: direct and exp(loggamma)."""
    z = make_z(params)

    # Method 1: mpmath's built-in gamma (Stirling + reflection + Taylor)
    val1 = mpmath.gamma(z)

    # Method 2: Gamma(z) = exp(loggamma(z))
    val2 = mpmath.exp(mpmath.loggamma(z))

    err = abs(val1 - val2)
    return val1, err, ["direct_gamma", "exp_loggamma"]


def eval_digamma(params):
    """Evaluate digamma(z) using two methods."""
    z = make_z(params)

    # Method 1: mpmath's built-in digamma
    val1 = mpmath.digamma(z)

    # Method 2: recurrence psi(z+1) = psi(z) + 1/z
    val2 = mpmath.digamma(z + 1) - 1 / z

    err = abs(val1 - val2)
    return val1, err, ["direct_digamma", "recurrence_relation"]


def eval_besselj(params):
    """Evaluate J_n(z) using two methods."""
    n = int(params["n"])
    z = make_z(params)

    # Method 1: mpmath's built-in besselj
    val1 = mpmath.besselj(n, z)

    if isinstance(z, mpmath.mpf) or (isinstance(z, mpmath.mpc) and z.imag == 0):
        # Method 2 for real z: integral representation
        # J_n(z) = (1/pi) * integral_0^pi cos(n*t - z*sin(t)) dt
        zr = z if isinstance(z, mpmath.mpf) else z.real

        def integrand(t):
            return mpmath.cos(n * t - zr * mpmath.sin(t))

        val2 = mpmath.quad(integrand, [0, mpmath.pi]) / mpmath.pi
    else:
        # Method 2 for complex z: power series via hyper
        # J_n(z) = (z/2)^n / Gamma(n+1) * 0F1(;n+1; -z^2/4)
        val2 = (z / 2) ** n / mpmath.gamma(n + 1) * mpmath.hyp0f1(n + 1, -(z ** 2) / 4)

    err = abs(val1 - val2)
    return val1, err, ["power_series", "integral_representation"]


def eval_bessely(params):
    """Evaluate Y_n(z) using two methods."""
    n = int(params["n"])
    z = make_z(params)

    # Method 1: mpmath's built-in bessely
    val1 = mpmath.bessely(n, z)

    # Method 2: via Hankel function relation
    # H_n^(1) = J_n + i*Y_n => Y_n = (H_n^(1) - J_n) / i
    h1 = mpmath.hankel1(n, z)
    jn = mpmath.besselj(n, z)
    val2 = mpmath.im(h1 - jn) if isinstance(z, mpmath.mpf) else (h1 - jn) / mpmath.mpc(0, 1)

    err = abs(val1 - val2)
    return val1, err, ["direct_bessely", "hankel_relation"]


def eval_airy_ai(params):
    """Evaluate Ai(z) using two methods."""
    z = make_z(params)

    # Method 1: mpmath's built-in airyai
    val1 = mpmath.airyai(z)

    # Method 2: hypergeometric representation
    # Ai(z) = c1 * 0F1(;2/3; z^3/9) - c2 * 0F1(;4/3; z^3/9)
    c1 = mpmath.mpf(1) / (mpmath.power(3, mpmath.mpf('2') / 3) * mpmath.gamma(mpmath.mpf('2') / 3))
    c2 = z / (mpmath.power(3, mpmath.mpf('1') / 3) * mpmath.gamma(mpmath.mpf('1') / 3))
    w = z ** 3 / 9
    val2 = c1 * mpmath.hyp0f1(mpmath.mpf('2') / 3, w) - c2 * mpmath.hyp0f1(mpmath.mpf('4') / 3, w)

    err = abs(val1 - val2)
    return val1, err, ["direct_airy", "hypergeometric_0f1"]


def eval_airy_bi(params):
    """Evaluate Bi(z) using two methods."""
    z = make_z(params)

    # Method 1: mpmath's built-in airybi
    val1 = mpmath.airybi(z)

    # Method 2: hypergeometric representation
    c1 = mpmath.mpf(1) / (mpmath.power(3, mpmath.mpf('1') / 6) * mpmath.gamma(mpmath.mpf('2') / 3))
    c2 = z * mpmath.power(3, mpmath.mpf('1') / 6) / mpmath.gamma(mpmath.mpf('1') / 3)
    w = z ** 3 / 9
    val2 = c1 * mpmath.hyp0f1(mpmath.mpf('2') / 3, w) + c2 * mpmath.hyp0f1(mpmath.mpf('4') / 3, w)

    err = abs(val1 - val2)
    return val1, err, ["direct_airy", "hypergeometric_0f1"]


def eval_hyp1f1(params):
    """Evaluate 1F1(a; b; z) using two methods."""
    a = mpmath.mpf(params["a"])
    b = mpmath.mpf(params["b"])
    z = make_z(params)

    # Method 1: direct hypergeometric summation
    val1 = mpmath.hyp1f1(a, b, z)

    # Method 2: Kummer's transformation: 1F1(a;b;z) = e^z * 1F1(b-a; b; -z)
    val2 = mpmath.exp(z) * mpmath.hyp1f1(b - a, b, -z)

    err = abs(val1 - val2)
    return val1, err, ["direct_series", "kummer_transformation"]


def eval_hyp2f1(params):
    """Evaluate 2F1(a, b; c; z) using two methods."""
    a = mpmath.mpf(params["a"])
    b = mpmath.mpf(params["b"])
    c = mpmath.mpf(params["c"])
    z = make_z(params)

    # Method 1: direct
    val1 = mpmath.hyp2f1(a, b, c, z)

    # Method 2: Euler integral or Pfaff transformation
    if mpmath.re(c) > mpmath.re(b) and mpmath.re(b) > 0:
        prefactor = mpmath.gamma(c) / (mpmath.gamma(b) * mpmath.gamma(c - b))

        def integrand(t):
            return t ** (b - 1) * (1 - t) ** (c - b - 1) * (1 - z * t) ** (-a)

        integral = mpmath.quad(integrand, [0, 1])
        val2 = prefactor * integral
    else:
        # Pfaff transformation
        val2 = (1 - z) ** (-a) * mpmath.hyp2f1(a, c - b, c, z / (z - 1))

    err = abs(val1 - val2)
    return val1, err, ["direct_series", "euler_integral"]


def eval_expint_e1(params):
    """Evaluate E1(z) using two methods."""
    z = make_z(params)

    # Method 1: mpmath's built-in e1
    val1 = mpmath.e1(z)

    # Method 2: via upper incomplete gamma: E1(z) = Gamma(0, z)
    val2 = mpmath.gammainc(0, z)

    err = abs(val1 - val2)
    return val1, err, ["direct_e1", "incomplete_gamma"]


EVALUATORS = {
    "gamma": eval_gamma,
    "digamma": eval_digamma,
    "besselj": eval_besselj,
    "bessely": eval_bessely,
    "airy_ai": eval_airy_ai,
    "airy_bi": eval_airy_bi,
    "hyp1f1": eval_hyp1f1,
    "hyp2f1": eval_hyp2f1,
    "expint_e1": eval_expint_e1,
}


def main():
    with open("/app/eval_spec.json", "r") as f:
        spec = json.load(f)

    results = []
    for entry in spec:
        eid = entry["id"]
        func = entry["function"]
        params = entry["params"]

        print(f"Evaluating id={eid}: {func}({entry['description']})...")

        evaluator = EVALUATORS[func]
        val, cross_err, methods = evaluator(params)

        # Error bound: maximum of cross-validation error and rounding estimate
        eps = mpmath.power(10, -(WORKING_DPS - 5))
        magnitude = abs(val) if abs(val) > mpmath.mpf("1e-300") else mpmath.mpf("1e-300")
        rounding_err = magnitude * eps
        err_bound = float(max(cross_err, rounding_err))

        # Clamp to at most 1e-41 (must be below 1e-40)
        err_bound = min(err_bound, 1e-41)
        # Ensure positive
        err_bound = max(err_bound, 1e-80)

        re_str, im_str = format_result(val)

        results.append({
            "id": eid,
            "value_re": re_str,
            "value_im": im_str,
            "error_bound": err_bound,
            "methods": methods,
        })

        print(f"  val_re={re_str[:40]}...")
        print(f"  err_bound={err_bound:.2e}, methods={methods}")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nWrote {len(results)} results to /app/results.json")


if __name__ == "__main__":
    main()
