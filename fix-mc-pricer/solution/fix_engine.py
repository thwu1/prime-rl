#!/usr/bin/env python3
"""Fix all bugs in the hybrid C/Python Monte Carlo engine.

Writes complete corrected versions of each buggy file to eliminate
fragile pattern-matching. Each fix is documented inline.

Fixes span:
  1. Makefile: ar archive -> gcc -shared (produces valid ELF .so)
  2. sobol.c: Gray code off-by-one (rightmost_zero_bit(i) -> (i-1))
  3. norm_inv.c: missing factor of 2 in tail sqrt
  4. gbm_paths.py: Ito drift correction
  5. payoffs.py: Asian average excludes S0, implement barrier_up_out_call
  6. mc_pricer.py: antithetic variates (1-z -> -z), control variate formula
  7. geo_asian.py: correct lognormal distribution parameters for discrete case
"""
import pathlib

APP = pathlib.Path("/app")

# ---------------------------------------------------------------------------
# Fix 1: Makefile — use gcc -shared instead of ar rcs
# ---------------------------------------------------------------------------
(APP / "Makefile").write_text(
    "CC = gcc\n"
    "CFLAGS = -O2 -Wall -fPIC\n"
    "\n"
    "all: libqrng.so\n"
    "\n"
    "libqrng.so: sobol.o norm_inv.o\n"
    "\t$(CC) -shared $^ -o $@ -lm\n"
    "\n"
    "sobol.o: sobol.c qrng.h\n"
    "\t$(CC) $(CFLAGS) -c sobol.c -o sobol.o\n"
    "\n"
    "norm_inv.o: norm_inv.c qrng.h\n"
    "\t$(CC) $(CFLAGS) -c norm_inv.c -o norm_inv.o\n"
    "\n"
    "clean:\n"
    "\trm -f *.o libqrng.so\n"
)

# ---------------------------------------------------------------------------
# Fix 2: sobol.c — Gray code index off-by-one
# The standard Sobol Gray code enumeration XORs direction number at
# position c = rightmost_zero_bit(i - 1), not rightmost_zero_bit(i).
# ---------------------------------------------------------------------------
(APP / "sobol.c").write_text("""\
/* Sobol quasi-random sequence generator using Gray code enumeration.
   Direction numbers from Joe & Kuo (2010). */

#include <string.h>
#include "qrng.h"

#define BITS 30
#define MAX_DIM 6

static const int jk_degree[] = {1, 2, 3, 3, 4};
static const int jk_a[] = {0, 1, 1, 2, 1};
static const int jk_m_init[][4] = {
    {1, 0, 0, 0},
    {1, 1, 0, 0},
    {1, 1, 1, 0},
    {1, 3, 1, 0},
    {1, 1, 3, 3},
};

static unsigned int direction_numbers[MAX_DIM][BITS];

static int rightmost_zero_bit(unsigned int n) {
    int pos = 0;
    while ((n >> pos) & 1) pos++;
    return pos;
}

void sobol_init(int dim) {
    int d, i, k, s, a;
    unsigned int v[BITS];

    if (dim < 1 || dim > MAX_DIM) return;

    /* Dimension 1: Van der Corput base-2 */
    for (i = 0; i < BITS; i++) {
        direction_numbers[0][i] = 1u << (BITS - 1 - i);
    }

    for (d = 1; d < dim; d++) {
        s = jk_degree[d - 1];
        a = jk_a[d - 1];

        for (i = 0; i < BITS; i++) v[i] = 0;

        for (i = 0; i < s && i < BITS; i++) {
            v[i] = (unsigned int)jk_m_init[d - 1][i] << (BITS - 1 - i);
        }
        for (i = s; i < BITS; i++) {
            v[i] = v[i - s] ^ (v[i - s] >> s);
            for (k = 1; k < s; k++) {
                if ((a >> (s - 1 - k)) & 1) {
                    v[i] ^= v[i - k];
                }
            }
        }
        for (i = 0; i < BITS; i++) {
            direction_numbers[d][i] = v[i];
        }
    }
}

void sobol_generate(int dim, int n, double *output) {
    double scale = 1.0 / (1u << BITS);
    unsigned int x[MAX_DIM];
    int i, d, c;

    memset(x, 0, sizeof(unsigned int) * MAX_DIM);

    for (i = 0; i < n; i++) {
        if (i == 0) {
            for (d = 0; d < dim; d++) {
                output[d] = 0.0;
            }
        } else {
            c = rightmost_zero_bit(i - 1);
            for (d = 0; d < dim; d++) {
                x[d] ^= direction_numbers[d][c];
                output[i * dim + d] = x[d] * scale;
            }
        }
    }
}
""")

# ---------------------------------------------------------------------------
# Fix 3: norm_inv.c — tail regions use sqrt(-2*log(u)), not sqrt(-log(u))
# Acklam's algorithm requires the standard form q = sqrt(-2 ln p) for tails.
# ---------------------------------------------------------------------------
(APP / "norm_inv.c").write_text("""\
/* Inverse standard normal CDF using Acklam's rational approximation.
   Reference: Peter Acklam, "An algorithm for computing the inverse
   normal cumulative distribution function" (2010). */

#include <math.h>
#include "qrng.h"

static const double A[] = {
    -3.969683028665376e+01, 2.209460984245205e+02,
    -2.759285104469687e+02, 1.383577518672690e+02,
    -3.066479806614716e+01, 2.506628277459239e+00
};

static const double B[] = {
    -5.447609879822406e+01, 1.615858368580409e+02,
    -1.556989798598866e+02, 6.680131188771972e+01,
    -1.328068155288572e+01
};

static const double C[] = {
    -7.784894002430293e-03, -3.223964580411365e-01,
    -2.400758277161838e+00, -2.549732539343734e+00,
     4.374664141464968e+00,  2.938163982698783e+00
};

static const double D[] = {
    7.784695709041462e-03, 3.224671290700398e-01,
    2.445134137142996e+00, 3.754408661907416e+00
};

#define P_LOW  0.02425
#define P_HIGH (1.0 - P_LOW)

double norm_inv(double u) {
    double q, r, x;

    if (u < P_LOW) {
        /* Lower tail region */
        q = sqrt(-2.0 * log(u));
        x = (((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
            ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0);
    } else if (u <= P_HIGH) {
        /* Central region */
        q = u - 0.5;
        r = q * q;
        x = (((((A[0]*r + A[1])*r + A[2])*r + A[3])*r + A[4])*r + A[5]) * q /
            (((((B[0]*r + B[1])*r + B[2])*r + B[3])*r + B[4])*r + 1.0);
    } else {
        /* Upper tail region */
        q = sqrt(-2.0 * log(1.0 - u));
        x = -(((((C[0]*q + C[1])*q + C[2])*q + C[3])*q + C[4])*q + C[5]) /
             ((((D[0]*q + D[1])*q + D[2])*q + D[3])*q + 1.0);
    }

    return x;
}
""")

# ---------------------------------------------------------------------------
# Fix 4: gbm_paths.py — Ito drift correction
# Risk-neutral GBM: drift must be (r - 0.5*sigma^2)*dt, not r*dt.
# ---------------------------------------------------------------------------
(APP / "gbm_paths.py").write_text("""\
\"\"\"Geometric Brownian Motion path simulation under risk-neutral measure.\"\"\"
import math


def simulate_paths(S0, r, sigma, T, n_steps, normals):
    \"\"\"Simulate a GBM price path given a sequence of standard normal draws.

    Parameters
    ----------
    S0 : float      - initial stock price
    r  : float      - risk-free rate (annualised)
    sigma : float   - volatility (annualised)
    T  : float      - time to maturity in years
    n_steps : int   - number of discrete time steps
    normals : list   - list of *n_steps* standard-normal random numbers

    Returns
    -------
    list of float - stock prices [S_1, S_2, ..., S_{n_steps}] at each step.
    \"\"\"
    dt = T / n_steps
    drift = (r - 0.5 * sigma ** 2) * dt
    diffusion = sigma * math.sqrt(dt)

    path = []
    S = S0
    for z in normals:
        S = S * math.exp(drift + diffusion * z)
        path.append(S)
    return path
""")

# ---------------------------------------------------------------------------
# Fix 5: payoffs.py — Asian average excludes S0 + implement barrier
# The arithmetic average should cover monitoring prices only: sum(path)/len(path).
# The barrier_up_out_call was unimplemented (raised NotImplementedError).
# ---------------------------------------------------------------------------
(APP / "payoffs.py").write_text("""\
\"\"\"Option payoff functions for European, Asian, and barrier contracts.\"\"\"
import math


def european_call(path, K, r, T):
    \"\"\"Discounted European call payoff: e^{-rT} max(S_T - K, 0).\"\"\"
    S_T = path[-1]
    return math.exp(-r * T) * max(S_T - K, 0.0)


def european_put(path, K, r, T):
    \"\"\"Discounted European put payoff: e^{-rT} max(K - S_T, 0).\"\"\"
    S_T = path[-1]
    return math.exp(-r * T) * max(K - S_T, 0.0)


def asian_call(path, K, r, T, S0):
    \"\"\"Discounted arithmetic-average Asian call payoff.

    The arithmetic average is taken over the monitoring prices
    (the discrete stock prices along the path).
    Payoff = e^{-rT} max(A - K, 0)
    \"\"\"
    avg = sum(path) / len(path)
    return math.exp(-r * T) * max(avg - K, 0.0)


def barrier_up_out_call(path, K, r, T, S0, barrier):
    \"\"\"Discounted up-and-out barrier call payoff with discrete monitoring.

    The option pays max(S_T - K, 0) * e^{-rT} if the stock never touches
    or exceeds the barrier during monitoring. Returns 0 if breached.
    \"\"\"
    for S in path:
        if S >= barrier:
            return 0.0
    S_T = path[-1]
    return math.exp(-r * T) * max(S_T - K, 0.0)
""")

# ---------------------------------------------------------------------------
# Fix 6: mc_pricer.py — antithetic uses negation; CV subtracts analytical mean
# Bug A: antithetic variates formed as (1 - z) instead of (-z).
# Bug B: control variate adjustment is Y - beta*X instead of Y - beta*(X - E[X]).
# ---------------------------------------------------------------------------
(APP / "mc_pricer.py").write_text("""\
\"\"\"Monte Carlo option pricing engine.
Supports three variance reduction strategies:
  - crude: no variance reduction
  - antithetic: antithetic variates
  - control_variate: geometric Asian control variate (for Asian options only)
\"\"\"
import math

from qrng_wrapper import SobolEngine, norm_inv
from gbm_paths import simulate_paths
from payoffs import european_call, european_put, asian_call, barrier_up_out_call
from geo_asian import geometric_asian_call


def _geo_avg_payoff(path, K, r, T):
    \"\"\"Geometric-average call payoff for use as control variate.\"\"\"
    g = 1.0
    for S in path:
        g *= S
    g = g ** (1.0 / len(path))
    return math.exp(-r * T) * max(g - K, 0.0)


def price_option(contract, n_paths=16384, method="antithetic"):
    \"\"\"Price a single option contract via Quasi-Monte Carlo.

    Parameters
    ----------
    contract : dict  - must contain keys: type, S0, K, r, sigma, T
                       and optionally n_steps, barrier.
    n_paths  : int   - number of Sobol sample paths (should be power of 2).
    method   : str   - "crude", "antithetic", or "control_variate"

    Returns
    -------
    float - estimated discounted option price.
    \"\"\"
    S0    = contract["S0"]
    K     = contract["K"]
    r     = contract["r"]
    sigma = contract["sigma"]
    T     = contract["T"]
    opt_type = contract["type"]

    n_steps = 1 if opt_type.startswith("european") else contract.get("n_steps", 4)

    engine = SobolEngine(n_steps)
    sobol_points = engine.generate(n_paths)

    payoffs_list = []
    geo_payoffs = []

    for i in range(n_paths):
        uniforms = sobol_points[i]

        # Transform Sobol uniforms -> standard normals
        normals = []
        for u in uniforms:
            u_c = max(1e-10, min(1.0 - 1e-10, u))
            normals.append(norm_inv(u_c))

        # Primary path
        path = simulate_paths(S0, r, sigma, T, n_steps, normals)

        # Evaluate payoff
        if opt_type == "european_call":
            p = european_call(path, K, r, T)
        elif opt_type == "european_put":
            p = european_put(path, K, r, T)
        elif opt_type == "asian_call":
            p = asian_call(path, K, r, T, S0)
        elif opt_type == "barrier_up_out_call":
            p = barrier_up_out_call(path, K, r, T, S0, contract["barrier"])
        else:
            raise ValueError(f"Unknown option type: {opt_type}")

        if method == "antithetic":
            # Antithetic variates: negate the normals
            anti_normals = [-z for z in normals]
            anti_path = simulate_paths(S0, r, sigma, T, n_steps, anti_normals)

            if opt_type == "european_call":
                p2 = european_call(anti_path, K, r, T)
            elif opt_type == "european_put":
                p2 = european_put(anti_path, K, r, T)
            elif opt_type == "asian_call":
                p2 = asian_call(anti_path, K, r, T, S0)
            elif opt_type == "barrier_up_out_call":
                p2 = barrier_up_out_call(anti_path, K, r, T, S0, contract["barrier"])
            p = 0.5 * (p + p2)

        payoffs_list.append(p)

        if method == "control_variate" and opt_type == "asian_call":
            geo_payoffs.append(_geo_avg_payoff(path, K, r, T))

    # Control variate adjustment for Asian options
    if method == "control_variate" and opt_type == "asian_call" and len(geo_payoffs) > 1:
        mean_p = sum(payoffs_list) / len(payoffs_list)
        mean_g = sum(geo_payoffs) / len(geo_payoffs)

        cov = sum((payoffs_list[i] - mean_p) * (geo_payoffs[i] - mean_g)
                  for i in range(len(payoffs_list))) / (len(payoffs_list) - 1)
        var_g = sum((geo_payoffs[i] - mean_g) ** 2
                    for i in range(len(payoffs_list))) / (len(payoffs_list) - 1)

        if var_g > 1e-15:
            beta = cov / var_g
            geo_analytical = geometric_asian_call(S0, K, r, sigma, T, n_steps)
            adjusted = [payoffs_list[i] - beta * (geo_payoffs[i] - geo_analytical)
                        for i in range(len(payoffs_list))]
            return sum(adjusted) / len(adjusted)

    return sum(payoffs_list) / len(payoffs_list)
""")

# ---------------------------------------------------------------------------
# Fix 7: geo_asian.py — correct lognormal distribution parameters
# Bug A: mean used r instead of (r - sigma^2/2) [missing Ito correction]
# Bug B: variance used (2n+1)/(6n) instead of (n+1)(2n+1)/(6n^2)
# ---------------------------------------------------------------------------
(APP / "geo_asian.py").write_text("""\
\"\"\"Closed-form geometric Asian call option pricing.

The geometric average of lognormal prices is itself lognormal,
which allows a Black-Scholes-type closed-form solution.

Reference: Kemna & Vorst (1990).
\"\"\"
import math


def _N(x):
    \"\"\"Standard normal CDF via error function.\"\"\"
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def geometric_asian_call(S0, K, r, sigma, T, n_steps):
    \"\"\"Closed-form price of a discrete geometric Asian call option.

    Parameters
    ----------
    S0      : float - initial stock price
    K       : float - strike price
    r       : float - risk-free rate (annualised)
    sigma   : float - volatility (annualised)
    T       : float - time to maturity in years
    n_steps : int   - number of equally-spaced monitoring dates

    Returns
    -------
    float - discounted geometric Asian call price
    \"\"\"
    n = n_steps

    # Mean of log(G) under risk-neutral measure
    m = math.log(S0) + (r - 0.5 * sigma ** 2) * T * (n + 1) / (2 * n)

    # Variance of log(G)
    v_sq = sigma ** 2 * T * (n + 1) * (2 * n + 1) / (6 * n ** 2)

    v = math.sqrt(v_sq)

    d1 = (m - math.log(K) + v_sq) / v
    d2 = d1 - v

    price = math.exp(-r * T) * (math.exp(m + v_sq / 2) * _N(d1) - K * _N(d2))
    return price
""")

print("All fixes applied successfully.")
