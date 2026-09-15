"""
Independent verification of Peng-Robinson isothermal flash results.

Implements a complete reference PR EOS to independently compute fugacity
coefficients for reported phase compositions and verify thermodynamic
consistency (equal-fugacity criterion, material balance, normalization).

"""

import pytest
import math
import os

R_GAS = 8.314462618
SQRT2 = math.sqrt(2.0)

# ── Component database — must match component_db.h exactly ──

COMP_DB = [
    {"name": "Methane",   "Tc": 190.564,  "Pc": 4599200.0, "omega": 0.01142},
    {"name": "Ethane",    "Tc": 305.322,  "Pc": 4872200.0, "omega": 0.09952},
    {"name": "Propane",   "Tc": 369.830,  "Pc": 4251200.0, "omega": 0.15229},
    {"name": "n-Butane",  "Tc": 425.125,  "Pc": 3796000.0, "omega": 0.20081},
    {"name": "n-Pentane", "Tc": 469.700,  "Pc": 3367500.0, "omega": 0.25137},
    {"name": "n-Hexane",  "Tc": 507.600,  "Pc": 3025000.0, "omega": 0.30131},
    {"name": "n-Decane",  "Tc": 617.700,  "Pc": 2110000.0, "omega": 0.49217},
    {"name": "Nitrogen",  "Tc": 126.192,  "Pc": 3395800.0, "omega": 0.03720},
    {"name": "CO2",       "Tc": 304.128,  "Pc": 7377300.0, "omega": 0.22520},
    {"name": "H2S",       "Tc": 373.100,  "Pc": 8962900.0, "omega": 0.09417},
]

# Binary interaction parameters — must match component_db.h
_KIJ_TABLE = {
    (0, 1): 0.0026, (0, 2): 0.0140, (0, 3): 0.0133, (0, 4): 0.0230,
    (0, 5): 0.0300, (0, 6): 0.0422, (0, 7): 0.0311, (0, 8): 0.0919,
    (0, 9): 0.0800, (1, 7): 0.0515, (1, 8): 0.1300, (2, 7): 0.0852,
    (2, 8): 0.1250, (8, 9): 0.0974,
}


def get_kij(i, j):
    if i == j:
        return 0.0
    lo, hi = min(i, j), max(i, j)
    return _KIJ_TABLE.get((lo, hi), 0.0)


# ── Reference Peng-Robinson EOS ──

def pr_m(omega):
    if omega <= 0.491:
        return 0.37464 + 1.54226 * omega - 0.26992 * omega ** 2
    return 0.379642 + 1.48503 * omega - 0.164423 * omega ** 2 + 0.016666 * omega ** 3


def pr_alpha(T, Tc, omega):
    m = pr_m(omega)
    return (1.0 + m * (1.0 - math.sqrt(T / Tc))) ** 2


def pr_ai(Tc, Pc, omega, T):
    return 0.45723553 * R_GAS ** 2 * Tc ** 2 / Pc * pr_alpha(T, Tc, omega)


def pr_bi(Tc, Pc):
    return 0.07779607 * R_GAS * Tc / Pc


def solve_cubic(A, B):
    """Solve PR cubic via Cardano, return valid Z roots sorted ascending."""
    c2 = -(1.0 - B)
    c1 = A - 3.0 * B * B - 2.0 * B
    c0 = -(A * B - B * B - B * B * B)

    p = c1 - c2 * c2 / 3.0
    q = c0 - c1 * c2 / 3.0 + 2.0 * c2 * c2 * c2 / 27.0
    D = q * q / 4.0 + p * p * p / 27.0
    shift = -c2 / 3.0

    roots = []
    if D > 1e-12:
        sd = math.sqrt(D)
        u_arg = -q / 2.0 + sd
        v_arg = -q / 2.0 - sd
        u = math.copysign(abs(u_arg) ** (1.0 / 3.0), u_arg)
        v = math.copysign(abs(v_arg) ** (1.0 / 3.0), v_arg)
        roots.append(u + v + shift)
    elif D < -1e-12:
        r = math.sqrt(-p * p * p / 27.0)
        theta = math.acos(max(-1.0, min(1.0, -q / (2.0 * r))))
        m_val = 2.0 * r ** (1.0 / 3.0)
        for k in range(3):
            roots.append(m_val * math.cos((theta + 2.0 * math.pi * k) / 3.0) + shift)
    else:
        u_arg = -q / 2.0
        u = math.copysign(abs(u_arg) ** (1.0 / 3.0), u_arg) if abs(u_arg) > 1e-30 else 0.0
        roots.append(2.0 * u + shift)
        roots.append(-u + shift)

    valid = sorted([z for z in roots if z > B + 1e-12])
    if not valid:
        valid = sorted([z for z in roots if z > 0])
    if not valid:
        valid = [max(roots)]
    return valid


def compute_ln_phi(x, ai, bi, comp_idx, T, P, want_liquid):
    """Correct PR fugacity coefficient computation with kij."""
    nc = len(x)

    a_mix = 0.0
    b_mix = 0.0
    for i in range(nc):
        b_mix += x[i] * bi[i]
        for j in range(nc):
            kij = get_kij(comp_idx[i], comp_idx[j])
            aij = math.sqrt(ai[i] * ai[j]) * (1.0 - kij)
            a_mix += x[i] * x[j] * aij

    A = a_mix * P / (R_GAS ** 2 * T ** 2)
    B = b_mix * P / (R_GAS * T)

    roots = solve_cubic(A, B)
    Z = roots[0] if want_liquid else roots[-1]

    ln_phi = []
    for i in range(nc):
        Si = 0.0
        for j in range(nc):
            kij = get_kij(comp_idx[i], comp_idx[j])
            aij = math.sqrt(ai[i] * ai[j]) * (1.0 - kij)
            Si += x[j] * aij

        bi_bm = bi[i] / b_mix
        log_arg = (Z + (1.0 + SQRT2) * B) / (Z + (1.0 - SQRT2) * B)
        val = (bi_bm * (Z - 1.0)
               - math.log(Z - B)
               - A / (2.0 * SQRT2 * B) * (2.0 * Si / a_mix - bi_bm) * math.log(log_arg))
        ln_phi.append(val)

    return ln_phi, Z


# ── Test problems — must match main.cpp ──

TEST_PROBLEMS = {
    "michelsen_7comp": {
        "T": 200.0, "P": 4.0e6,
        "comp": [0, 1, 2, 3, 4, 5, 7],
        "z": [0.9430, 0.0270, 0.0074, 0.0049, 0.0027, 0.0010, 0.0140],
        "expected_phase": "two_phase",
    },
    "ch4_co2_binary": {
        "T": 220.0, "P": 3.0e6,
        "comp": [0, 8],
        "z": [0.5, 0.5],
        "expected_phase": "two_phase",
    },
    "ch4_c10_asymmetric": {
        "T": 310.0, "P": 2.0e6,
        "comp": [0, 6],
        "z": [0.7, 0.3],
        "expected_phase": "two_phase",
    },
    "nitrogen_supercrit": {
        "T": 200.0, "P": 1.0e6,
        "comp": [7],
        "z": [1.0],
        "expected_phase": "single_phase",
    },
    "co2_supercrit": {
        "T": 350.0, "P": 1.0e7,
        "comp": [8],
        "z": [1.0],
        "expected_phase": "single_phase",
    },
    "ternary_flash": {
        "T": 190.0, "P": 2.5e6,
        "comp": [0, 1, 2],
        "z": [0.70, 0.20, 0.10],
        "expected_phase": "two_phase",
    },
}


# ── Output parser ──

def parse_results(filepath):
    """Parse results.txt into dict of problem result dicts."""
    if not os.path.exists(filepath):
        return {}

    results = {}
    current = None
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("PROBLEM:"):
                current = {"name": line.split(":", 1)[1].strip()}
            elif line == "END" and current:
                results[current["name"]] = current
                current = None
            elif current and ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key in ("NC",):
                    current[key] = int(val)
                elif key in ("V", "Z_L", "Z_V", "Z_FACTOR"):
                    current[key] = float(val)
                elif key == "COMP":
                    current[key] = [int(x) for x in val.split()]
                elif key in ("FEED", "LIQUID", "VAPOR", "LN_PHI_L", "LN_PHI_V", "LN_PHI"):
                    current[key] = [float(x) for x in val.split()]
                else:
                    current[key] = val

    return results


# ── Test class ──

class TestFlashResults:
    """Verify PR flash calculator output against independent reference."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        self.results = parse_results("/app/results.txt")
        assert len(self.results) > 0, \
            "No results in /app/results.txt — build or execution failed"

    def _get(self, name):
        assert name in self.results, f"Problem '{name}' missing from output"
        return self.results[name]

    def _verify_two_phase(self, name):
        prob = TEST_PROBLEMS[name]
        res = self._get(name)

        assert res["STATUS"] == "converged", f"{name}: not converged"
        assert res["PHASE"] == "two_phase", \
            f"{name}: expected two_phase, got {res['PHASE']}"

        nc = len(prob["z"])
        z = prob["z"]
        T, P = prob["T"], prob["P"]
        comp_idx = prob["comp"]

        V = res["V"]
        x = res["LIQUID"]
        y = res["VAPOR"]

        # Vapor fraction in (0, 1)
        assert 0.0 < V < 1.0, f"{name}: V={V} not in (0,1)"

        # Composition normalization
        assert abs(sum(x) - 1.0) < 1e-8, f"{name}: sum(x)={sum(x)}"
        assert abs(sum(y) - 1.0) < 1e-8, f"{name}: sum(y)={sum(y)}"

        # Material balance: z_i = (1-V)*x_i + V*y_i
        for i in range(nc):
            mb = abs(z[i] - (1.0 - V) * x[i] - V * y[i])
            assert mb < 1e-6, \
                f"{name}: material balance error comp {i}: {mb:.3e}"

        # Independent reference fugacity coefficients
        ai = [pr_ai(COMP_DB[c]["Tc"], COMP_DB[c]["Pc"],
                     COMP_DB[c]["omega"], T) for c in comp_idx]
        bi = [pr_bi(COMP_DB[c]["Tc"], COMP_DB[c]["Pc"]) for c in comp_idx]

        ref_lnpL, _ = compute_ln_phi(x, ai, bi, comp_idx, T, P, True)
        ref_lnpV, _ = compute_ln_phi(y, ai, bi, comp_idx, T, P, False)

        rep_lnpL = res["LN_PHI_L"]
        rep_lnpV = res["LN_PHI_V"]

        # Reported fugacity coefficients must agree with reference
        for i in range(nc):
            err_L = abs(rep_lnpL[i] - ref_lnpL[i])
            assert err_L < 1e-5, \
                f"{name}: ln_phi_L[{i}] error={err_L:.3e} " \
                f"(reported={rep_lnpL[i]:.8e}, ref={ref_lnpL[i]:.8e})"
            err_V = abs(rep_lnpV[i] - ref_lnpV[i])
            assert err_V < 1e-5, \
                f"{name}: ln_phi_V[{i}] error={err_V:.3e} " \
                f"(reported={rep_lnpV[i]:.8e}, ref={ref_lnpV[i]:.8e})"

        # Equal-fugacity criterion
        for i in range(nc):
            if x[i] > 1e-10 and y[i] > 1e-10:
                fug_eq = abs(ref_lnpL[i] + math.log(x[i])
                             - ref_lnpV[i] - math.log(y[i]))
                assert fug_eq < 1e-5, \
                    f"{name}: fugacity equality error comp {i}: {fug_eq:.3e}"

    def _verify_single_phase(self, name):
        prob = TEST_PROBLEMS[name]
        res = self._get(name)

        assert res["STATUS"] == "converged", f"{name}: not converged"
        assert res["PHASE"] == "single_phase", \
            f"{name}: expected single_phase, got {res['PHASE']}"

        T, P = prob["T"], prob["P"]
        comp_idx = prob["comp"]
        z = prob["z"]
        nc = len(z)

        # Independent reference fugacity coefficients
        ai = [pr_ai(COMP_DB[c]["Tc"], COMP_DB[c]["Pc"],
                     COMP_DB[c]["omega"], T) for c in comp_idx]
        bi = [pr_bi(COMP_DB[c]["Tc"], COMP_DB[c]["Pc"]) for c in comp_idx]

        ref_lnp_liq, _ = compute_ln_phi(z, ai, bi, comp_idx, T, P, True)
        ref_lnp_vap, _ = compute_ln_phi(z, ai, bi, comp_idx, T, P, False)

        reported_lnp = res["LN_PHI"]

        # Match either liquid or vapor reference
        err_liq = max(abs(reported_lnp[i] - ref_lnp_liq[i]) for i in range(nc))
        err_vap = max(abs(reported_lnp[i] - ref_lnp_vap[i]) for i in range(nc))

        best = min(err_liq, err_vap)
        assert best < 1e-6, \
            f"{name}: single-phase fugacity error={best:.3e}"

    # ── Individual test methods ──

    def test_all_problems_present(self):
        for name in TEST_PROBLEMS:
            assert name in self.results, f"Missing problem: {name}"

    def test_michelsen_7comp(self):
        self._verify_two_phase("michelsen_7comp")

    def test_ch4_co2_binary(self):
        self._verify_two_phase("ch4_co2_binary")

    def test_ch4_c10_asymmetric(self):
        self._verify_two_phase("ch4_c10_asymmetric")

    def test_nitrogen_supercrit(self):
        self._verify_single_phase("nitrogen_supercrit")

    def test_co2_supercrit(self):
        self._verify_single_phase("co2_supercrit")

    def test_ternary_flash(self):
        self._verify_two_phase("ternary_flash")
