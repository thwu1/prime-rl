"""

Tests for ternary LLE solver with SQLite parameter extraction and
gnuplot ternary phase diagram generation.
"""

import json
import math
import os
import sqlite3
import xml.etree.ElementTree as ET

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Independent UNIFAC implementation for verification
# ---------------------------------------------------------------------------

def _load_unifac_from_sql():
    """Load UNIFAC parameters from SQL dump, selecting highest-priority entries."""
    conn = sqlite3.connect(":memory:")
    with open("/app/unifac_params.sql") as f:
        conn.executescript(f.read())

    # Subgroup parameters
    subgroups = {}
    for name, mg_name, rk, qk in conn.execute(
        "SELECT s.name, mg.name, s.rk, s.qk "
        "FROM subgroups s JOIN main_groups mg ON s.main_group_id = mg.id"
    ):
        subgroups[name] = {"main_group": mg_name, "Rk": rk, "Qk": qk}

    # Interaction parameters — highest priority per (source, target) pair
    interactions = {}
    for mg1, mg2, a_val in conn.execute("""
        SELECT mg1.name, mg2.name, ip.a_value
        FROM interaction_params ip
        JOIN main_groups mg1 ON ip.source_group_id = mg1.id
        JOIN main_groups mg2 ON ip.target_group_id = mg2.id
        JOIN parameter_sources ps ON ip.param_source_id = ps.id
        WHERE ps.priority = (
            SELECT MAX(ps2.priority)
            FROM interaction_params ip2
            JOIN parameter_sources ps2 ON ip2.param_source_id = ps2.id
            WHERE ip2.source_group_id = ip.source_group_id
              AND ip2.target_group_id = ip.target_group_id
        )
    """):
        interactions[(mg1, mg2)] = a_val

    # Compound decompositions
    with open("/app/system.json") as f:
        system = json.load(f)

    components = []
    for comp_name in system["components"]:
        row = conn.execute(
            "SELECT id FROM compounds WHERE name = ?", (comp_name,)
        ).fetchone()
        assert row is not None, f"Compound '{comp_name}' not in database"
        cid = row[0]
        groups = {}
        for sg_name, cnt in conn.execute(
            "SELECT s.name, cs.count "
            "FROM compound_subgroups cs "
            "JOIN subgroups s ON cs.subgroup_id = s.id "
            "WHERE cs.compound_id = ?",
            (cid,),
        ):
            groups[sg_name] = cnt
        components.append({"name": comp_name, "groups": groups})

    conn.close()
    return subgroups, interactions, components


def _unifac_gamma(x, components, subgroups, interactions, T):
    """Compute UNIFAC activity coefficients (original Fredenslund/Gmehling)."""
    nc = len(components)
    x = np.asarray(x, dtype=float).copy()
    x = np.maximum(x, 1e-15)
    x /= x.sum()

    r = np.zeros(nc)
    q = np.zeros(nc)
    for i, comp in enumerate(components):
        for sg_name, count in comp["groups"].items():
            r[i] += count * subgroups[sg_name]["Rk"]
            q[i] += count * subgroups[sg_name]["Qk"]

    # Combinatorial
    sum_rx = r @ x
    sum_qx = q @ x
    phi = r * x / sum_rx
    theta = q * x / sum_qx

    ln_gC = np.zeros(nc)
    for i in range(nc):
        px = phi[i] / x[i]
        pt = phi[i] / theta[i]
        ln_gC[i] = math.log(px) + 1 - px - 5 * q[i] * (math.log(pt) + 1 - pt)

    # Residual — collect unique subgroups
    all_sgs = []
    sg_set = set()
    for comp in components:
        for sg in comp["groups"]:
            if sg not in sg_set:
                all_sgs.append(sg)
                sg_set.add(sg)
    nsg = len(all_sgs)
    sg_idx = {sg: k for k, sg in enumerate(all_sgs)}

    main_g = [subgroups[sg]["main_group"] for sg in all_sgs]
    Qk = np.array([subgroups[sg]["Qk"] for sg in all_sgs])

    nu = np.zeros((nc, nsg))
    for i, comp in enumerate(components):
        for sg_name, count in comp["groups"].items():
            nu[i, sg_idx[sg_name]] = count

    psi = np.ones((nsg, nsg))
    for m in range(nsg):
        for n in range(nsg):
            a_mn = interactions.get((main_g[m], main_g[n]), 0.0)
            psi[m, n] = math.exp(-a_mn / T)

    def _ln_Gamma(Xk):
        s_QX = Qk @ Xk
        if s_QX < 1e-30:
            return np.zeros(nsg)
        th = Qk * Xk / s_QX
        ln_G = np.zeros(nsg)
        for k in range(nsg):
            s1 = th @ psi[:, k]
            s2 = 0.0
            for m_idx in range(nsg):
                denom = th @ psi[:, m_idx]
                if denom > 1e-30:
                    s2 += th[m_idx] * psi[k, m_idx] / denom
            if s1 > 1e-30:
                ln_G[k] = Qk[k] * (1.0 - math.log(s1) - s2)
        return ln_G

    Xmix = np.zeros(nsg)
    for k in range(nsg):
        for i in range(nc):
            Xmix[k] += nu[i, k] * x[i]
    tot = Xmix.sum()
    if tot > 0:
        Xmix /= tot
    ln_G_mix = _ln_Gamma(Xmix)

    ln_G_pure = np.zeros((nc, nsg))
    for i in range(nc):
        tot_i = nu[i].sum()
        Xp = nu[i] / tot_i if tot_i > 0 else np.zeros(nsg)
        ln_G_pure[i] = _ln_Gamma(Xp)

    ln_gR = np.zeros(nc)
    for i in range(nc):
        for k in range(nsg):
            ln_gR[i] += nu[i, k] * (ln_G_mix[k] - ln_G_pure[i, k])

    return np.exp(ln_gC + ln_gR)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def system():
    with open("/app/system.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def unifac_data():
    return _load_unifac_from_sql()


# ---------------------------------------------------------------------------
# Tests — Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:
    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_valid_json(self):
        with open("/app/results.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_top_keys(self, results):
        assert "system" in results
        assert "tie_lines" in results
        assert "binary_mutual_solubility" in results

    def test_tie_line_count(self, results, system):
        assert len(results["tie_lines"]) == len(system["feeds"])

    def test_tie_line_fields(self, results):
        required = [
            "feed", "aqueous_phase", "organic_phase",
            "activity_coefficients_aqueous", "activity_coefficients_organic",
            "phase_fraction_aqueous", "distribution_coefficients",
            "selectivity_solute_over_carrier",
        ]
        for tl in results["tie_lines"]:
            for key in required:
                assert key in tl, f"Missing key: {key}"

    def test_tie_line_array_lengths(self, results):
        for tl in results["tie_lines"]:
            assert len(tl["aqueous_phase"]) == 3
            assert len(tl["organic_phase"]) == 3
            assert len(tl["activity_coefficients_aqueous"]) == 3
            assert len(tl["activity_coefficients_organic"]) == 3

    def test_distribution_coefficient_keys(self, results, system):
        names = system["components"]
        for tl in results["tie_lines"]:
            for n in names:
                assert n in tl["distribution_coefficients"], \
                    f"Missing K for {n}"


# ---------------------------------------------------------------------------
# Tests — Composition validity
# ---------------------------------------------------------------------------

class TestCompositionValidity:
    def test_mole_fractions_in_range(self, results):
        for tl in results["tie_lines"]:
            for phase in ("aqueous_phase", "organic_phase"):
                for xi in tl[phase]:
                    assert 0.0 <= xi <= 1.0, \
                        f"{phase}: x = {xi} out of [0, 1]"

    def test_mole_fractions_sum_to_one(self, results):
        for tl in results["tie_lines"]:
            for phase in ("aqueous_phase", "organic_phase"):
                s = sum(tl[phase])
                assert abs(s - 1.0) < 1e-4, f"{phase}: sum = {s}"

    def test_phases_are_distinct(self, results):
        for tl in results["tie_lines"]:
            aq = np.array(tl["aqueous_phase"])
            org = np.array(tl["organic_phase"])
            max_diff = np.max(np.abs(aq - org))
            assert max_diff > 0.05, \
                f"Phases too similar: max diff = {max_diff}"

    def test_aqueous_has_more_water(self, results):
        for tl in results["tie_lines"]:
            assert tl["aqueous_phase"][0] > tl["organic_phase"][0], \
                "Aqueous phase should have higher water content"

    def test_organic_has_more_toluene(self, results):
        for tl in results["tie_lines"]:
            assert tl["organic_phase"][2] > tl["aqueous_phase"][2], \
                "Organic phase should have higher toluene content"


# ---------------------------------------------------------------------------
# Tests — Isoactivity (independently computed UNIFAC)
# ---------------------------------------------------------------------------

class TestIsoactivity:
    """Verify equilibrium using independently computed UNIFAC gammas
    with parameters extracted from the SQL database."""

    def test_isoactivity_all_feeds(self, results, system, unifac_data):
        sg, inter, comps = unifac_data
        T = system["temperature_K"]

        for idx, tl in enumerate(results["tie_lines"]):
            x_aq = np.array(tl["aqueous_phase"])
            x_org = np.array(tl["organic_phase"])

            g_aq = _unifac_gamma(x_aq, comps, sg, inter, T)
            g_org = _unifac_gamma(x_org, comps, sg, inter, T)

            for i in range(3):
                a_aq = x_aq[i] * g_aq[i]
                a_org = x_org[i] * g_org[i]
                denom = max(a_aq, a_org, 1e-10)
                rel_err = abs(a_aq - a_org) / denom
                assert rel_err < 0.03, (
                    f"Feed {idx}, comp {i}: isoactivity violated. "
                    f"a_aq={a_aq:.6f}, a_org={a_org:.6f}, "
                    f"rel_err={rel_err:.4f}"
                )


# ---------------------------------------------------------------------------
# Tests — Mass balance
# ---------------------------------------------------------------------------

class TestMassBalance:
    def test_mass_balance_all_feeds(self, results, system):
        feeds = system["feeds"]
        for idx, tl in enumerate(results["tie_lines"]):
            z = np.array(feeds[idx])
            x_aq = np.array(tl["aqueous_phase"])
            x_org = np.array(tl["organic_phase"])
            beta = tl["phase_fraction_aqueous"]

            assert 0.0 < beta < 1.0, f"Feed {idx}: beta={beta} out of (0,1)"

            z_calc = beta * x_aq + (1 - beta) * x_org
            for i in range(3):
                assert abs(z_calc[i] - z[i]) < 0.005, (
                    f"Feed {idx}, comp {i}: mass balance error "
                    f"|{z_calc[i]:.6f} - {z[i]:.6f}| = "
                    f"{abs(z_calc[i] - z[i]):.6f}"
                )


# ---------------------------------------------------------------------------
# Tests — Derived quantities
# ---------------------------------------------------------------------------

class TestDerivedQuantities:
    def test_distribution_coefficients(self, results, system):
        names = system["components"]
        for idx, tl in enumerate(results["tie_lines"]):
            x_aq = tl["aqueous_phase"]
            x_org = tl["organic_phase"]
            K = tl["distribution_coefficients"]
            for i, name in enumerate(names):
                if x_aq[i] > 1e-10:
                    K_calc = x_org[i] / x_aq[i]
                    rel = abs(K[name] - K_calc) / max(K_calc, 1e-10)
                    assert rel < 0.01, (
                        f"Feed {idx}, {name}: K mismatch "
                        f"{K[name]:.6f} vs {K_calc:.6f}"
                    )

    def test_selectivity(self, results, system):
        solute = system["components"][1]
        carrier = system["components"][0]
        for idx, tl in enumerate(results["tie_lines"]):
            K = tl["distribution_coefficients"]
            S = tl["selectivity_solute_over_carrier"]
            S_calc = K[solute] / K[carrier]
            rel = abs(S - S_calc) / max(S_calc, 1e-10)
            assert rel < 0.01, (
                f"Feed {idx}: selectivity mismatch "
                f"{S:.4f} vs {S_calc:.4f}"
            )


# ---------------------------------------------------------------------------
# Tests — Activity coefficients reasonable
# ---------------------------------------------------------------------------

class TestActivityCoefficientsReasonable:
    def test_positive_gammas(self, results):
        for tl in results["tie_lines"]:
            for phase in ("activity_coefficients_aqueous",
                          "activity_coefficients_organic"):
                for gi in tl[phase]:
                    assert gi > 0, f"Negative gamma: {gi}"

    def test_water_gamma_aqueous_near_one(self, results):
        for tl in results["tie_lines"]:
            g_water_aq = tl["activity_coefficients_aqueous"][0]
            assert 0.5 < g_water_aq < 3.0, \
                f"gamma_water in aq phase unreasonable: {g_water_aq}"

    def test_toluene_gamma_organic_near_one(self, results):
        for tl in results["tie_lines"]:
            g_tol_org = tl["activity_coefficients_organic"][2]
            assert 0.5 < g_tol_org < 3.0, \
                f"gamma_toluene in org phase unreasonable: {g_tol_org}"


# ---------------------------------------------------------------------------
# Tests — Binary mutual solubility
# ---------------------------------------------------------------------------

class TestBinaryMutualSolubility:
    def test_water_in_organic_reasonable(self, results):
        bms = results["binary_mutual_solubility"]
        w = bms["water_in_organic"]
        assert 0.0 < w < 0.15, f"water_in_organic = {w} out of (0, 0.15)"

    def test_toluene_in_aqueous_reasonable(self, results):
        bms = results["binary_mutual_solubility"]
        t = bms["toluene_in_aqueous"]
        assert 0.0 < t < 0.05, f"toluene_in_aqueous = {t} out of (0, 0.05)"

    def test_binary_isoactivity(self, results, system, unifac_data):
        """Binary mutual solubility must also satisfy isoactivity."""
        sg, inter, comps = unifac_data
        T = system["temperature_K"]

        bms = results["binary_mutual_solubility"]
        w_org = bms["water_in_organic"]
        t_aq = bms["toluene_in_aqueous"]

        x_aq = np.array([1.0 - t_aq, 0.0, t_aq])
        x_org = np.array([w_org, 0.0, 1.0 - w_org])

        x_aq[1] = 1e-15
        x_org[1] = 1e-15
        x_aq /= x_aq.sum()
        x_org /= x_org.sum()

        g_aq = _unifac_gamma(x_aq, comps, sg, inter, T)
        g_org = _unifac_gamma(x_org, comps, sg, inter, T)

        for i in [0, 2]:
            a_aq = x_aq[i] * g_aq[i]
            a_org = x_org[i] * g_org[i]
            denom = max(a_aq, a_org, 1e-10)
            rel_err = abs(a_aq - a_org) / denom
            assert rel_err < 0.05, (
                f"Binary isoactivity violated for comp {i}: "
                f"a_aq={a_aq:.6f}, a_org={a_org:.6f}, "
                f"rel_err={rel_err:.4f}"
            )


# ---------------------------------------------------------------------------
# Tests — Phase diagram SVG
# ---------------------------------------------------------------------------

class TestPhaseDiagram:
    def test_svg_file_exists(self):
        assert os.path.isfile("/app/phase_diagram.svg"), \
            "phase_diagram.svg not found"

    def test_svg_non_trivial(self):
        size = os.path.getsize("/app/phase_diagram.svg")
        assert size > 500, f"SVG file too small ({size} bytes)"

    def test_svg_well_formed_xml(self):
        """SVG must be parseable as XML."""
        tree = ET.parse("/app/phase_diagram.svg")
        root = tree.getroot()
        tag = root.tag.lower()
        assert "svg" in tag, f"Root element is '{root.tag}', expected svg"

    def test_svg_contains_component_labels(self):
        with open("/app/phase_diagram.svg") as f:
            content = f.read().lower()
        for name in ("water", "acetone", "toluene"):
            assert name in content, \
                f"Component label '{name}' not found in SVG"

    def test_svg_has_graphical_content(self):
        """SVG must contain drawing elements (lines, paths, or polylines)."""
        with open("/app/phase_diagram.svg") as f:
            content = f.read()
        has_lines = ("<line" in content or "<polyline" in content
                     or "<path" in content or "points=" in content
                     or "d=" in content)
        assert has_lines, "SVG lacks graphical elements (line/polyline/path)"
