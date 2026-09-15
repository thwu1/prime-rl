#!/usr/bin/env python3
"""Catalytic reactor design and analysis tool.

Supports three subcommands:
  rate      - Evaluate LHHW rate expressions
  arrhenius - Fit Arrhenius parameters from T-k data
  network   - Solve reactor networks (PFR/CSTR, series/parallel/recycle)

"""

import json
import math
import sqlite3
import sys


# ---------------------------------------------------------------------------
# Numerical helpers
# ---------------------------------------------------------------------------

def simpson_integrate(f, a, b, n_intervals=2000):
    """Composite Simpson's 1/3 rule."""
    if n_intervals % 2 != 0:
        n_intervals += 1
    h = (b - a) / n_intervals
    s = f(a) + f(b)
    for i in range(1, n_intervals, 2):
        s += 4.0 * f(a + i * h)
    for i in range(2, n_intervals, 2):
        s += 2.0 * f(a + i * h)
    return s * h / 3.0


def bisect(f, lo, hi, tol=1e-12, max_iter=300):
    """Bisection root finder. f(lo) and f(hi) must have opposite signs."""
    f_lo = f(lo)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < tol or (hi - lo) / 2.0 < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Database lookup
# ---------------------------------------------------------------------------

def load_species_from_db(db_path, species_name):
    """Load adsorption constant K and reference concentration from SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT adsorption_K, ref_conc FROM species_properties WHERE name = ?",
        (species_name,)
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"Species '{species_name}' not found in database")
    return {"K": row[0], "C": row[1]}


# ---------------------------------------------------------------------------
# Subcommand: rate
# ---------------------------------------------------------------------------

def cmd_rate(data):
    """Evaluate LHHW rate for surface-reaction-controlling mechanism."""
    if data.get("source") == "database":
        db_path = data.get("db_path", "/app/properties.db")
        species = {}
        for name in data["species_names"]:
            species[name] = load_species_from_db(db_path, name)
        data = dict(data)
        data["species"] = species

    mechanism = data["mechanism_type"]
    reactants = data["reactants"]
    k_sr = data["k_sr"]
    species = data["species"]

    # Denominator: 1 + sum(K_i * C_i) for ALL adsorbing species
    denom = 1.0
    for props in species.values():
        denom += props["K"] * props["C"]

    # Numerator depends on mechanism type
    if mechanism == "unimolecular":
        r = reactants[0]
        numerator = k_sr * species[r]["K"] * species[r]["C"]
    else:  # bimolecular
        r1, r2 = reactants[0], reactants[1]
        numerator = (
            k_sr
            * species[r1]["K"]
            * species[r2]["K"]
            * species[r1]["C"]
            * species[r2]["C"]
        )

    rate = numerator / (denom ** 2)
    return {"rate": rate}


# ---------------------------------------------------------------------------
# Subcommand: arrhenius
# ---------------------------------------------------------------------------

def cmd_arrhenius(data):
    """OLS fit of Arrhenius equation: ln(k) = ln(k0) - E/(R*T)."""
    temps = data["temperatures"]
    k_vals = data["rate_constants"]
    R = data["R"]
    n = len(temps)

    x = [1.0 / t for t in temps]
    y = [math.log(k) for k in k_vals]

    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sx2 = sum(xi * xi for xi in x)

    slope = (n * sxy - sx * sy) / (n * sx2 - sx ** 2)
    intercept = (sy - slope * sx) / n

    E = -slope * R
    k0 = math.exp(intercept)

    y_mean = sy / n
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    ss_res = sum((yi - intercept - slope * xi) ** 2 for xi, yi in zip(x, y))
    r_squared = 1.0 - ss_res / ss_tot

    return {
        "activation_energy": E,
        "pre_exponential_factor": k0,
        "r_squared": r_squared,
    }


# ---------------------------------------------------------------------------
# Reactor solvers
# ---------------------------------------------------------------------------

def solve_pfr_liquid(k, order, ca_in, tau):
    """PFR exit concentration, liquid phase (constant density)."""
    if order == 1:
        return ca_in * math.exp(-k * tau)
    elif order == 2:
        return ca_in / (1.0 + k * tau * ca_in)
    else:
        raise ValueError(f"Unsupported order {order}")


def solve_cstr_liquid(k, order, ca_in, tau):
    """CSTR exit concentration, liquid phase (constant density)."""
    if order == 1:
        return ca_in / (1.0 + k * tau)
    elif order == 2:
        a = k * tau
        b = 1.0
        c = -ca_in
        discriminant = b * b - 4.0 * a * c
        return (-b + math.sqrt(discriminant)) / (2.0 * a)
    else:
        raise ValueError(f"Unsupported order {order}")


def solve_pfr_gas(k, order, ca0, v_over_v0, epsilon_a, xa_in=0.0):
    """PFR exit conversion, gas phase (variable density)."""
    target = k * (ca0 ** (order - 1)) * v_over_v0

    def integrand(x):
        return ((1.0 + epsilon_a * x) ** order) / ((1.0 - x) ** order)

    def objective(xa_out):
        integral = simpson_integrate(integrand, xa_in, xa_out, 4000)
        return integral - target

    xa_out = bisect(objective, xa_in + 1e-14, 0.9999)
    return xa_out


def solve_cstr_gas(k, order, ca0, v_over_v0, epsilon_a, xa_in=0.0):
    """CSTR exit conversion, gas phase (variable density)."""
    target = k * (ca0 ** (order - 1)) * v_over_v0

    def objective(xa_out):
        val = (
            (xa_out - xa_in)
            * ((1.0 + epsilon_a * xa_out) ** order)
            / ((1.0 - xa_out) ** order)
        )
        return val - target

    xa_out = bisect(objective, xa_in + 1e-14, 0.9999)
    return xa_out


# ---------------------------------------------------------------------------
# Subcommand: network
# ---------------------------------------------------------------------------

def cmd_network(data):
    """Solve a reactor network stage by stage."""
    kinetics = data["kinetics"]
    k = kinetics["rate_constant"]
    order = kinetics["order"]
    epsilon_a = kinetics["epsilon_A"]

    feed = data["feed"]
    ca0 = feed["C_A0"]
    v0 = feed["volumetric_flow_rate"]

    is_gas = abs(epsilon_a) > 1e-15

    ca_current = ca0
    v_current = v0
    xa_current = 0.0
    stage_results = []

    for stage in data["stages"]:
        stype = stage["type"]

        if stype == "single":
            reactor = stage["reactor"]
            rtype = reactor["type"]
            volume = reactor["volume"]

            if is_gas:
                v_over_v0 = volume / v0
                if rtype == "PFR":
                    xa_out = solve_pfr_gas(
                        k, order, ca0, v_over_v0, epsilon_a, xa_current
                    )
                else:
                    xa_out = solve_cstr_gas(
                        k, order, ca0, v_over_v0, epsilon_a, xa_current
                    )
                ca_current = ca0 * (1.0 - xa_out) / (1.0 + epsilon_a * xa_out)
                v_current = v0 * (1.0 + epsilon_a * xa_out)
                xa_current = xa_out
            else:
                tau = volume / v_current
                if rtype == "PFR":
                    ca_current = solve_pfr_liquid(k, order, ca_current, tau)
                else:
                    ca_current = solve_cstr_liquid(k, order, ca_current, tau)
                xa_current = 1.0 - ca_current / ca0

        elif stype == "parallel":
            branches = stage["branches"]
            fa_total = 0.0
            v_total = 0.0

            for branch in branches:
                frac = branch["flow_fraction"]
                reactor = branch["reactor"]
                rtype = reactor["type"]
                volume = reactor["volume"]

                v_branch = frac * v_current
                tau_branch = volume / v_branch

                if rtype == "PFR":
                    ca_branch = solve_pfr_liquid(k, order, ca_current, tau_branch)
                else:
                    ca_branch = solve_cstr_liquid(k, order, ca_current, tau_branch)

                fa_total += ca_branch * v_branch
                v_total += v_branch

            ca_current = fa_total / v_total
            v_current = v_total
            xa_current = 1.0 - ca_current / ca0

        elif stype == "recycle":
            reactor = stage["reactor"]
            rtype = reactor["type"]
            volume = reactor["volume"]
            r_ratio = stage["recycle_ratio"]

            ca_recycle = ca_current

            for iteration in range(50000):
                v_total_reactor = v_current * (1.0 + r_ratio)
                ca_mixed = (
                    v_current * ca_current + r_ratio * v_current * ca_recycle
                ) / v_total_reactor

                tau_reactor = volume / v_total_reactor

                if rtype == "PFR":
                    ca_exit = solve_pfr_liquid(k, order, ca_mixed, tau_reactor)
                else:
                    ca_exit = solve_cstr_liquid(k, order, ca_mixed, tau_reactor)

                if abs(ca_exit - ca_recycle) < 1e-10:
                    break

                ca_recycle = ca_exit

            ca_current = ca_exit
            xa_current = 1.0 - ca_current / ca0

        else:
            raise ValueError(f"Unknown stage type: {stype}")

        stage_results.append({"C_A": ca_current, "X_A": xa_current})

    return {
        "stages": stage_results,
        "outlet": {"C_A": ca_current, "X_A": xa_current},
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python3 catreactor.py <subcommand> <input.json> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    subcommand = sys.argv[1]
    input_path = sys.argv[2]
    output_path = sys.argv[3]

    with open(input_path) as f:
        data = json.load(f)

    if subcommand == "rate":
        result = cmd_rate(data)
    elif subcommand == "arrhenius":
        result = cmd_arrhenius(data)
    elif subcommand == "network":
        result = cmd_network(data)
    else:
        print(f"Unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    main()
