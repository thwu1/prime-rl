"""Reactor network topology and stage processing."""
from . import solver


def _solve_reactor(reactor_type, k, order, ca_in, v0, volume, epsilon_a):
    """Dispatch to PFR or CSTR solver."""
    if reactor_type == "PFR":
        return solver.solve_pfr(k, order, ca_in, v0, volume, epsilon_a)
    else:
        return solver.solve_cstr(k, order, ca_in, v0, volume, epsilon_a)


def solve_network(data):
    """Process reactor network stages sequentially."""
    kin = data["kinetics"]
    k = kin["rate_constant"]
    order = kin["order"]
    eps = kin["epsilon_A"]

    feed = data["feed"]
    ca0 = feed["C_A0"]
    v0 = feed["volumetric_flow_rate"]

    ca = ca0
    results = []

    for stage in data["stages"]:
        st = stage["type"]

        if st == "single":
            r = stage["reactor"]
            ca = _solve_reactor(r["type"], k, order, ca, v0, r["volume"], eps)

        elif st == "parallel":
            total_ca = 0.0
            n_branches = 0
            for branch in stage["branches"]:
                vb = v0 * branch["flow_fraction"]
                r = branch["reactor"]
                ca_b = _solve_reactor(r["type"], k, order, ca, vb, r["volume"], eps)
                total_ca += ca_b
                n_branches += 1
            ca = total_ca / n_branches

        elif st == "recycle":
            r = stage["reactor"]
            R = stage["recycle_ratio"]
            v_total = v0 * (1.0 + R)
            ca_mix = (v0 * ca + R * v0 * ca) / v_total
            ca = _solve_reactor(
                r["type"], k, order, ca_mix, v_total, r["volume"], eps
            )

        xa = 1.0 - ca / ca0
        results.append({"C_A": ca, "X_A": xa})

    outlet = results[-1] if results else {"C_A": ca0, "X_A": 0.0}
    return {"stages": results, "outlet": outlet}
