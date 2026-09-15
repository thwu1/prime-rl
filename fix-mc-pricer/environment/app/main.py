"""Monte Carlo Option Pricing Engine – entry point.

Reads contracts from contracts.json, prices each via QMC,
and prints results alongside Black-Scholes reference (where applicable).
"""
import json
import math
import sys

from mc_pricer import price_option


def _N(x):
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(S0, K, r, sigma, T, opt_type):
    """Closed-form Black-Scholes price for European options."""
    sqrt_T = sigma * math.sqrt(T)
    d1 = (math.log(S0 / K) + (r + 0.5 * sigma ** 2) * T) / sqrt_T
    d2 = d1 - sqrt_T

    if opt_type == "european_call":
        return S0 * _N(d1) - K * math.exp(-r * T) * _N(d2)
    elif opt_type == "european_put":
        return K * math.exp(-r * T) * _N(-d2) - S0 * _N(-d1)
    return None


def main():
    with open("/app/contracts.json") as f:
        data = json.load(f)

    n_paths = data.get("n_paths", 8192)
    contracts = data["contracts"]

    print("Monte Carlo Option Pricer (Sobol QMC + Antithetic)")
    print(f"Paths per contract: {n_paths}")
    print("=" * 72)

    for c in contracts:
        cid = c["id"]
        mc = price_option(c, n_paths)
        bs = black_scholes(c["S0"], c["K"], c["r"], c["sigma"], c["T"], c["type"])

        line = f"  #{cid:2d}  {c['type']:15s}  S0={c['S0']:6.1f}  K={c['K']:6.1f}  MC={mc:8.4f}"
        if bs is not None:
            line += f"  BS={bs:8.4f}  diff={abs(mc - bs):7.4f}"
        else:
            line += "  (no closed-form)"
        print(line)

    print("=" * 72)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
