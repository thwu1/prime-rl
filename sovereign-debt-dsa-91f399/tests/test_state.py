
import json
import os
import pytest

RESULTS_PATH = "/app/output/results.json"
CHART_PATH = "/app/output/trajectories.png"
TOL = 0.1  # absolute tolerance in percentage points of GDP


@pytest.fixture(scope="module")
def results():
    assert os.path.exists(RESULTS_PATH), f"Output file {RESULTS_PATH} does not exist"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, list), "Output must be a JSON array"
    assert len(data) >= 3, "Output must contain at least 3 country results"
    return {r["country_name"]: r for r in data}


# -- Chart output validation ------------------------------------------------

class TestChartOutput:
    def test_png_exists(self):
        assert os.path.exists(CHART_PATH), f"Chart file {CHART_PATH} does not exist"

    def test_png_valid_magic_bytes(self):
        with open(CHART_PATH, "rb") as f:
            magic = f.read(8)
        assert magic[:4] == b"\x89PNG", "Chart is not a valid PNG file"

    def test_png_nontrivial_size(self):
        size = os.path.getsize(CHART_PATH)
        assert size > 1000, f"Chart file too small ({size} bytes), likely empty or corrupt"


# -- Montavia baseline debt trajectory --------------------------------------

class TestMontaviaBaseline:
    EXPECTED_TRAJECTORY = [140.0, 141.5664, 142.3137, 142.1943, 141.7948, 142.0139, 142.5731]

    def test_trajectory_length(self, results):
        traj = results["Montavia"]["baseline"]["debt_trajectory"]
        assert len(traj) == 7, f"Expected 7 values (d0..d6), got {len(traj)}"

    def test_initial_debt(self, results):
        traj = results["Montavia"]["baseline"]["debt_trajectory"]
        assert abs(traj[0] - 140.0) < 0.01

    @pytest.mark.parametrize("year,expected", [
        (1, 141.5664), (2, 142.3137), (3, 142.1943),
        (4, 141.7948), (5, 142.0139), (6, 142.5731),
    ])
    def test_debt_year(self, results, year, expected):
        traj = results["Montavia"]["baseline"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Montavia d_{year}: expected {expected}, got {actual}"
        )


# -- Valdoria baseline debt trajectory --------------------------------------

class TestValdoriaBaseline:
    EXPECTED_TRAJECTORY = [65.0, 66.1973, 66.7185, 64.912, 62.6384, 59.5754, 57.9218]

    def test_trajectory_length(self, results):
        traj = results["Valdoria"]["baseline"]["debt_trajectory"]
        assert len(traj) == 7

    def test_initial_debt(self, results):
        traj = results["Valdoria"]["baseline"]["debt_trajectory"]
        assert abs(traj[0] - 65.0) < 0.01

    @pytest.mark.parametrize("year,expected", [
        (1, 66.1973), (2, 66.7185), (3, 64.912),
        (4, 62.6384), (5, 59.5754), (6, 57.9218),
    ])
    def test_debt_year(self, results, year, expected):
        traj = results["Valdoria"]["baseline"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Valdoria d_{year}: expected {expected}, got {actual}"
        )


# -- Montavia decomposition -------------------------------------------------

class TestMontaviaDecomposition:
    def test_year1_components(self, results):
        dec = results["Montavia"]["baseline"]["decomposition"]
        y1 = dec[0]
        assert abs(y1["real_interest_rate"] - 0.6775) < TOL
        assert abs(y1["real_growth"] - (-1.1111)) < TOL
        assert abs(y1["real_exchange_rate"] - 0.0) < 0.01
        assert abs(y1["relative_inflation"] - 0.0) < 0.01
        assert abs(y1["automatic_debt_dynamics"] - (-0.4336)) < TOL
        assert abs(y1["primary_balance_contribution"] - 0.5) < TOL
        assert abs(y1["sfa"] - 1.5) < 0.01
        assert abs(y1["change_in_debt"] - 1.5664) < TOL

    def test_year4_interest_growth(self, results):
        dec = results["Montavia"]["baseline"]["decomposition"]
        y4 = dec[3]
        assert abs(y4["real_interest_rate"] - 2.2084) < TOL
        assert abs(y4["real_growth"] - (-1.4079)) < TOL
        assert abs(y4["automatic_debt_dynamics"] - 0.8006) < TOL

    def test_change_equals_sum(self, results):
        """Verify change = auto + pbc + sfa for each year."""
        dec = results["Montavia"]["baseline"]["decomposition"]
        for entry in dec:
            expected_change = entry["automatic_debt_dynamics"] + \
                              entry["primary_balance_contribution"] + entry["sfa"]
            assert abs(entry["change_in_debt"] - expected_change) < 0.02, (
                f"Year {entry['year']}: change_in_debt inconsistent with sum"
            )

    def test_auto_equals_component_sum(self, results):
        """Verify auto = ri + rg + rex + rinf for each year."""
        dec = results["Montavia"]["baseline"]["decomposition"]
        for entry in dec:
            expected_auto = (entry["real_interest_rate"] + entry["real_growth"] +
                             entry["real_exchange_rate"] + entry["relative_inflation"])
            assert abs(entry["automatic_debt_dynamics"] - expected_auto) < 0.02, (
                f"Year {entry['year']}: auto inconsistent with component sum"
            )


# -- Valdoria decomposition (FX and inflation differential) -----------------

class TestValdoriaDecomposition:
    def test_year1_fx_components(self, results):
        """Year 1 has 5% real depreciation with 35% FC debt and 4pp inflation gap."""
        dec = results["Valdoria"]["baseline"]["decomposition"]
        y1 = dec[0]
        assert abs(y1["real_exchange_rate"] - 1.0827) < TOL, (
            f"rex: expected 1.0827, got {y1['real_exchange_rate']}"
        )
        assert abs(y1["relative_inflation"] - 0.8171) < TOL, (
            f"rinf: expected 0.8171, got {y1['relative_inflation']}"
        )

    def test_year1_interest_growth(self, results):
        dec = results["Valdoria"]["baseline"]["decomposition"]
        y1 = dec[0]
        assert abs(y1["real_interest_rate"] - 1.1907) < TOL
        assert abs(y1["real_growth"] - (-1.8932)) < TOL

    def test_year3_negative_rex(self, results):
        """Year 3 has -2% RER change (appreciation)."""
        dec = results["Valdoria"]["baseline"]["decomposition"]
        y3 = dec[2]
        assert abs(y3["real_exchange_rate"] - (-0.4445)) < TOL

    def test_year4_zero_rex(self, results):
        """Year 4 has 0% RER change."""
        dec = results["Valdoria"]["baseline"]["decomposition"]
        y4 = dec[3]
        assert abs(y4["real_exchange_rate"] - 0.0) < 0.01

    def test_year1_auto(self, results):
        dec = results["Valdoria"]["baseline"]["decomposition"]
        y1 = dec[0]
        assert abs(y1["automatic_debt_dynamics"] - 1.1973) < TOL

    def test_change_equals_sum(self, results):
        """Verify change = auto + pbc + sfa for each year."""
        dec = results["Valdoria"]["baseline"]["decomposition"]
        for entry in dec:
            expected_change = entry["automatic_debt_dynamics"] + \
                              entry["primary_balance_contribution"] + entry["sfa"]
            assert abs(entry["change_in_debt"] - expected_change) < 0.02, (
                f"Year {entry['year']}: change_in_debt inconsistent with sum"
            )

    def test_auto_equals_component_sum(self, results):
        """Verify auto = ri + rg + rex + rinf for each year."""
        dec = results["Valdoria"]["baseline"]["decomposition"]
        for entry in dec:
            expected_auto = (entry["real_interest_rate"] + entry["real_growth"] +
                             entry["real_exchange_rate"] + entry["relative_inflation"])
            assert abs(entry["automatic_debt_dynamics"] - expected_auto) < 0.02, (
                f"Year {entry['year']}: auto inconsistent with component sum"
            )


# -- Tervalia baseline (endogenous rate, contingent liability) ---------------

class TestTervaliaBaseline:
    """Tervalia has endogenous interest rates and a contingent liability in year 3."""

    def test_trajectory_length(self, results):
        traj = results["Tervalia"]["baseline"]["debt_trajectory"]
        assert len(traj) == 7, f"Expected 7 values, got {len(traj)}"

    def test_initial_debt(self, results):
        traj = results["Tervalia"]["baseline"]["debt_trajectory"]
        assert abs(traj[0] - 82.0) < 0.01

    @pytest.mark.parametrize("year,expected", [
        (1, 83.424), (2, 84.3144), (3, 87.3115),
        (4, 87.313), (5, 86.6376), (6, 86.4269),
    ])
    def test_debt_year(self, results, year, expected):
        traj = results["Tervalia"]["baseline"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Tervalia d_{year}: expected {expected}, got {actual}"
        )

    def test_debt_not_stabilizes(self, results):
        """Tervalia's terminal debt exceeds initial -> debt does not stabilize."""
        traj = results["Tervalia"]["baseline"]["debt_trajectory"]
        assert traj[-1] > traj[0], "Terminal debt should exceed initial for Tervalia"

    def test_year3_contingent_liability_in_sfa(self, results):
        """Year 3 SFA must include the 2.5pp contingent liability shock."""
        dec = results["Tervalia"]["baseline"]["decomposition"]
        y3 = dec[2]
        assert abs(y3["sfa"] - 2.7) < TOL, (
            f"Year 3 SFA should be ~2.7 (0.2 base + 2.5 CL), got {y3['sfa']}"
        )

    def test_year3_large_debt_increase(self, results):
        """Year 3 change should be large due to contingent liability."""
        dec = results["Tervalia"]["baseline"]["decomposition"]
        y3 = dec[2]
        assert y3["change_in_debt"] > 2.5, (
            f"Year 3 change should be > 2.5pp due to CL, got {y3['change_in_debt']}"
        )

    def test_year1_decomposition(self, results):
        dec = results["Tervalia"]["baseline"]["decomposition"]
        y1 = dec[0]
        assert abs(y1["real_interest_rate"] - 1.4135) < TOL
        assert abs(y1["real_growth"] - (-1.6078)) < TOL
        assert abs(y1["real_exchange_rate"] - 0.3153) < TOL
        assert abs(y1["relative_inflation"] - 0.3031) < TOL

    def test_year4_decomposition(self, results):
        dec = results["Tervalia"]["baseline"]["decomposition"]
        y4 = dec[3]
        assert abs(y4["real_interest_rate"] - 2.75) < TOL
        assert abs(y4["real_exchange_rate"] - 0.0) < 0.01

    def test_change_equals_sum(self, results):
        dec = results["Tervalia"]["baseline"]["decomposition"]
        for entry in dec:
            expected_change = entry["automatic_debt_dynamics"] + \
                              entry["primary_balance_contribution"] + entry["sfa"]
            assert abs(entry["change_in_debt"] - expected_change) < 0.02, (
                f"Year {entry['year']}: change_in_debt inconsistent with sum"
            )

    def test_auto_equals_component_sum(self, results):
        dec = results["Tervalia"]["baseline"]["decomposition"]
        for entry in dec:
            expected_auto = (entry["real_interest_rate"] + entry["real_growth"] +
                             entry["real_exchange_rate"] + entry["relative_inflation"])
            assert abs(entry["automatic_debt_dynamics"] - expected_auto) < 0.02, (
                f"Year {entry['year']}: auto inconsistent with component sum"
            )


# -- Gross Financing Needs --------------------------------------------------

class TestGFN:
    def test_montavia_gfn_length(self, results):
        gfn = results["Montavia"]["baseline"]["gfn"]
        assert len(gfn) == 6

    def test_montavia_gfn_year1(self, results):
        gfn = results["Montavia"]["baseline"]["gfn"]
        assert abs(gfn[0] - 24.465) < TOL

    def test_montavia_gfn_year3(self, results):
        gfn = results["Montavia"]["baseline"]["gfn"]
        assert abs(gfn[2] - 22.2254) < TOL

    def test_valdoria_gfn_year1(self, results):
        gfn = results["Valdoria"]["baseline"]["gfn"]
        assert abs(gfn[0] - 11.9628) < TOL

    def test_valdoria_gfn_year4(self, results):
        gfn = results["Valdoria"]["baseline"]["gfn"]
        assert abs(gfn[3] - 8.1198) < TOL

    def test_valdoria_gfn_declining(self, results):
        """Valdoria's GFN should generally decline as debt falls and surpluses grow."""
        gfn = results["Valdoria"]["baseline"]["gfn"]
        assert gfn[0] > gfn[4], "Early GFN should exceed later GFN for Valdoria"

    def test_tervalia_gfn_length(self, results):
        gfn = results["Tervalia"]["baseline"]["gfn"]
        assert len(gfn) == 6

    def test_tervalia_gfn_year1(self, results):
        gfn = results["Tervalia"]["baseline"]["gfn"]
        assert abs(gfn[0] - 14.8055) < TOL

    def test_tervalia_gfn_year4(self, results):
        gfn = results["Tervalia"]["baseline"]["gfn"]
        assert abs(gfn[3] - 12.8634) < TOL

    def test_tervalia_avg_gfn_below_threshold(self, results):
        """Tervalia's avg GFN should be below the 15.0 threshold."""
        gfn = results["Tervalia"]["baseline"]["gfn"]
        avg = sum(gfn) / len(gfn)
        assert avg < 15.0, f"Tervalia avg GFN should be < 15, got {avg}"


# -- Debt-Stabilizing Primary Balance --------------------------------------

class TestDebtStabilizingPB:
    def test_montavia_year1_deficit_stabilizes(self, results):
        """With r < g, Montavia can run a deficit and still stabilize."""
        pb = results["Montavia"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[0] - (-0.4336)) < TOL

    def test_montavia_year5_surplus_needed(self, results):
        """By year 5, r > g so a surplus is needed to stabilize."""
        pb = results["Montavia"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[4] - 1.2191) < TOL

    def test_valdoria_year1(self, results):
        """Includes the relative inflation channel."""
        pb = results["Valdoria"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[0] - 0.1146) < TOL

    def test_valdoria_year4_negative(self, results):
        """With high growth, Valdoria can run a deficit and stabilize."""
        pb = results["Valdoria"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[3] - (-0.2736)) < TOL

    def test_stabilizing_pb_length(self, results):
        pb_m = results["Montavia"]["baseline"]["debt_stabilizing_pb"]
        pb_v = results["Valdoria"]["baseline"]["debt_stabilizing_pb"]
        pb_t = results["Tervalia"]["baseline"]["debt_stabilizing_pb"]
        assert len(pb_m) == 6
        assert len(pb_v) == 6
        assert len(pb_t) == 6

    def test_tervalia_year1(self, results):
        pb = results["Tervalia"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[0] - 0.1088) < TOL

    def test_tervalia_year4(self, results):
        pb = results["Tervalia"]["baseline"]["debt_stabilizing_pb"]
        assert abs(pb[3] - 0.5015) < TOL


# -- Stress Scenario -------------------------------------------------------

class TestStressScenario:
    def test_montavia_stress_trajectory_length(self, results):
        traj = results["Montavia"]["stress"]["debt_trajectory"]
        assert len(traj) == 7

    @pytest.mark.parametrize("year,expected", [
        (1, 146.8863), (2, 152.4945), (3, 155.3569),
        (4, 158.0476), (5, 161.4809), (6, 165.3675),
    ])
    def test_montavia_stress_year(self, results, year, expected):
        traj = results["Montavia"]["stress"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Montavia stress d_{year}: expected {expected}, got {actual}"
        )

    def test_montavia_stress_higher_than_baseline(self, results):
        baseline = results["Montavia"]["baseline"]["debt_trajectory"]
        stressed = results["Montavia"]["stress"]["debt_trajectory"]
        for year in range(1, 7):
            assert stressed[year] > baseline[year], (
                f"Stressed debt should exceed baseline at year {year}"
            )

    @pytest.mark.parametrize("year,expected", [
        (1, 72.9821), (2, 77.4528), (3, 77.396),
        (4, 76.8673), (5, 75.4703), (6, 75.6791),
    ])
    def test_valdoria_stress_year(self, results, year, expected):
        traj = results["Valdoria"]["stress"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Valdoria stress d_{year}: expected {expected}, got {actual}"
        )

    def test_valdoria_stress_year1_fx_impact(self, results):
        """15% FX shock should cause large jump in year 1 for 35% FC country."""
        traj = results["Valdoria"]["stress"]["debt_trajectory"]
        jump = traj[1] - traj[0]
        assert jump > 7.0, f"Year 1 stress jump should be > 7pp, got {jump}"

    def test_tervalia_stress_trajectory_length(self, results):
        traj = results["Tervalia"]["stress"]["debt_trajectory"]
        assert len(traj) == 7

    @pytest.mark.parametrize("year,expected", [
        (1, 88.6838), (2, 93.1692), (3, 97.994),
        (4, 99.9115), (5, 101.1467), (6, 102.9006),
    ])
    def test_tervalia_stress_year(self, results, year, expected):
        traj = results["Tervalia"]["stress"]["debt_trajectory"]
        actual = traj[year]
        assert abs(actual - expected) < TOL, (
            f"Tervalia stress d_{year}: expected {expected}, got {actual}"
        )

    def test_tervalia_stress_higher_than_baseline(self, results):
        baseline = results["Tervalia"]["baseline"]["debt_trajectory"]
        stressed = results["Tervalia"]["stress"]["debt_trajectory"]
        for year in range(1, 7):
            assert stressed[year] > baseline[year], (
                f"Tervalia stressed should exceed baseline at year {year}"
            )

    def test_tervalia_stress_year3_cl_effect(self, results):
        """Year 3 stress should also include the contingent liability jump."""
        traj = results["Tervalia"]["stress"]["debt_trajectory"]
        jump_y3 = traj[3] - traj[2]
        assert jump_y3 > 3.0, (
            f"Year 3 stress jump should be large (CL + shocks), got {jump_y3}"
        )


# -- Risk Assessment -------------------------------------------------------

class TestRiskAssessment:
    def test_montavia_no_stabilization(self, results):
        ra = results["Montavia"]["risk_assessment"]
        assert ra["debt_stabilizes_baseline"] is False

    def test_valdoria_stabilizes(self, results):
        ra = results["Valdoria"]["risk_assessment"]
        assert ra["debt_stabilizes_baseline"] is True

    def test_montavia_signal_high(self, results):
        """Montavia: debt rises, GFN > 15, terminal > 100 => high."""
        ra = results["Montavia"]["risk_assessment"]
        assert ra["signal"] == "high"

    def test_valdoria_signal_low(self, results):
        """Valdoria: debt falls, GFN < 15, terminal < 100 => low."""
        ra = results["Valdoria"]["risk_assessment"]
        assert ra["signal"] == "low"

    def test_tervalia_signal_moderate(self, results):
        """Tervalia: debt rises (1 condition) but GFN < 15 and terminal < 100 => moderate."""
        ra = results["Tervalia"]["risk_assessment"]
        assert ra["signal"] == "moderate"

    def test_montavia_avg_gfn(self, results):
        ra = results["Montavia"]["risk_assessment"]
        assert abs(ra["avg_gfn"] - 22.3347) < 0.2

    def test_valdoria_avg_gfn(self, results):
        ra = results["Valdoria"]["risk_assessment"]
        assert abs(ra["avg_gfn"] - 9.0327) < 0.2

    def test_tervalia_avg_gfn(self, results):
        ra = results["Tervalia"]["risk_assessment"]
        assert abs(ra["avg_gfn"] - 13.1695) < 0.2

    def test_montavia_terminal_debt(self, results):
        ra = results["Montavia"]["risk_assessment"]
        assert abs(ra["terminal_debt"] - 142.5731) < TOL

    def test_valdoria_terminal_debt(self, results):
        ra = results["Valdoria"]["risk_assessment"]
        assert abs(ra["terminal_debt"] - 57.9218) < TOL

    def test_tervalia_terminal_debt(self, results):
        ra = results["Tervalia"]["risk_assessment"]
        assert abs(ra["terminal_debt"] - 86.4269) < TOL

    def test_tervalia_debt_not_stabilized(self, results):
        ra = results["Tervalia"]["risk_assessment"]
        assert ra["debt_stabilizes_baseline"] is False


# -- Convergence (endogenous risk premium) ----------------------------------

class TestConvergence:
    def test_montavia_no_endogenous(self, results):
        """Montavia is not endogenous: 1 iteration, no premium."""
        conv = results["Montavia"]["convergence"]
        assert conv["iterations"] == 1
        assert conv["risk_premium_applied"] == 0.0

    def test_valdoria_no_endogenous(self, results):
        """Valdoria is not endogenous: 1 iteration, no premium."""
        conv = results["Valdoria"]["convergence"]
        assert conv["iterations"] == 1
        assert conv["risk_premium_applied"] == 0.0

    def test_tervalia_multiple_iterations(self, results):
        """Tervalia has endogenous rate and debt > threshold => must iterate."""
        conv = results["Tervalia"]["convergence"]
        assert conv["iterations"] > 1, (
            f"Tervalia should require multiple iterations, got {conv['iterations']}"
        )
        assert conv["iterations"] <= 100, "Should converge within max iterations"

    def test_tervalia_positive_premium(self, results):
        """Tervalia's terminal debt > d_threshold => positive risk premium."""
        conv = results["Tervalia"]["convergence"]
        assert conv["risk_premium_applied"] > 0.0, "Risk premium should be positive"

    def test_tervalia_premium_magnitude(self, results):
        """Premium should be approximately beta1 * (d_T - d_threshold)."""
        conv = results["Tervalia"]["convergence"]
        ra = results["Tervalia"]["risk_assessment"]
        d_T = ra["terminal_debt"]
        beta1 = 0.0002  # from config
        d_threshold = 70.0  # from config
        expected_premium = max(0.0, beta1 * (d_T - d_threshold))
        assert abs(conv["risk_premium_applied"] - expected_premium) < 0.001, (
            f"Premium {conv['risk_premium_applied']} inconsistent with "
            f"terminal debt {d_T}: expected ~{expected_premium:.4f}"
        )

    def test_tervalia_premium_exact(self, results):
        conv = results["Tervalia"]["convergence"]
        assert abs(conv["risk_premium_applied"] - 0.0033) < 0.0005

    def test_tervalia_iterations_exact(self, results):
        conv = results["Tervalia"]["convergence"]
        assert conv["iterations"] == 6, (
            f"Expected 6 convergence iterations, got {conv['iterations']}"
        )

    def test_tervalia_premium_affects_trajectory(self, results):
        """With premium > 0, Tervalia's debt should be higher than it would be
        without premium. We verify by checking that the interest rate contribution
        is substantially higher than what the base rate alone would produce."""
        dec = results["Tervalia"]["baseline"]["decomposition"]
        y1_ri = dec[0]["real_interest_rate"]
        assert y1_ri > 1.15, (
            f"Year 1 RI should exceed base-rate-only value, got {y1_ri}"
        )


# -- Consolidation Path -----------------------------------------------------

class TestConsolidation:
    def test_montavia_requires_consolidation(self, results):
        """Montavia has high signal => consolidation required."""
        cons = results["Montavia"]["consolidation"]
        assert cons["required"] is True

    def test_valdoria_no_consolidation(self, results):
        """Valdoria has low signal => no consolidation."""
        cons = results["Valdoria"]["consolidation"]
        assert cons["required"] is False
        assert cons["adjustment_pp"] == 0.0

    def test_tervalia_no_consolidation(self, results):
        """Tervalia has moderate signal => no consolidation."""
        cons = results["Tervalia"]["consolidation"]
        assert cons["required"] is False
        assert cons["adjustment_pp"] == 0.0

    def test_montavia_adjustment_positive(self, results):
        cons = results["Montavia"]["consolidation"]
        assert cons["adjustment_pp"] > 0.0, "Adjustment must be positive"

    def test_montavia_adjustment_magnitude(self, results):
        """Adjustment should be approximately 6.74 pp."""
        cons = results["Montavia"]["consolidation"]
        assert abs(cons["adjustment_pp"] - 6.7383) < 0.1, (
            f"Expected ~6.74 adjustment, got {cons['adjustment_pp']}"
        )

    def test_montavia_adjusted_terminal_debt(self, results):
        """Adjusted terminal debt should be just above 100 (one condition remains)."""
        cons = results["Montavia"]["consolidation"]
        assert abs(cons["adjusted_terminal_debt"] - 101.4221) < 0.5, (
            f"Expected adjusted terminal debt ~101.4, got {cons['adjusted_terminal_debt']}"
        )

    def test_montavia_adjusted_signal_not_high(self, results):
        """With the adjustment, the implied signal should be at most moderate.
        Check: adjusted_terminal_debt < d_init (condition 1 eliminated),
        and adjusted_terminal_debt >= ceiling (condition 3 remains)."""
        cons = results["Montavia"]["consolidation"]
        d_init = results["Montavia"]["baseline"]["debt_trajectory"][0]
        ceiling = 100.0  # from config
        adj_td = cons["adjusted_terminal_debt"]
        conds = 0
        if adj_td > d_init:
            conds += 1
        if adj_td >= ceiling:
            conds += 1
        assert conds <= 1, (
            f"After adjustment, at most 1 debt/ceiling condition should hold, got {conds}"
        )

    def test_montavia_adjustment_is_minimum(self, results):
        """The adjustment should be within search precision of the boundary."""
        cons = results["Montavia"]["consolidation"]
        assert cons["adjustment_pp"] > 6.0, "Adjustment too low"
        assert cons["adjustment_pp"] < 8.0, "Adjustment too high"


# -- Consistency checks ----------------------------------------------------

class TestConsistency:
    def test_trajectory_matches_decomposition_montavia(self, results):
        """Verify d_t = d_{t-1} + change for Montavia."""
        traj = results["Montavia"]["baseline"]["debt_trajectory"]
        dec = results["Montavia"]["baseline"]["decomposition"]
        for i, entry in enumerate(dec):
            expected = traj[i] + entry["change_in_debt"]
            assert abs(traj[i + 1] - expected) < 0.02, (
                f"Montavia year {i+1}: trajectory inconsistent with decomposition"
            )

    def test_trajectory_matches_decomposition_valdoria(self, results):
        """Verify d_t = d_{t-1} + change for Valdoria."""
        traj = results["Valdoria"]["baseline"]["debt_trajectory"]
        dec = results["Valdoria"]["baseline"]["decomposition"]
        for i, entry in enumerate(dec):
            expected = traj[i] + entry["change_in_debt"]
            assert abs(traj[i + 1] - expected) < 0.02, (
                f"Valdoria year {i+1}: trajectory inconsistent with decomposition"
            )

    def test_trajectory_matches_decomposition_tervalia(self, results):
        """Verify d_t = d_{t-1} + change for Tervalia."""
        traj = results["Tervalia"]["baseline"]["debt_trajectory"]
        dec = results["Tervalia"]["baseline"]["decomposition"]
        for i, entry in enumerate(dec):
            expected = traj[i] + entry["change_in_debt"]
            assert abs(traj[i + 1] - expected) < 0.02, (
                f"Tervalia year {i+1}: trajectory inconsistent with decomposition"
            )

    def test_stress_initial_matches_baseline(self, results):
        """All stress trajectories should start at same d0 as baseline."""
        for country in ["Montavia", "Valdoria", "Tervalia"]:
            base = results[country]["baseline"]["debt_trajectory"][0]
            stress = results[country]["stress"]["debt_trajectory"][0]
            assert abs(base - stress) < 0.01

    def test_all_countries_present(self, results):
        """All three countries must be in the output."""
        assert "Montavia" in results
        assert "Valdoria" in results
        assert "Tervalia" in results

    def test_output_schema_completeness(self, results):
        """Each country result must have all required sections."""
        for name in ["Montavia", "Valdoria", "Tervalia"]:
            r = results[name]
            assert "baseline" in r
            assert "stress" in r
            assert "risk_assessment" in r
            assert "convergence" in r
            assert "consolidation" in r
            assert "debt_trajectory" in r["baseline"]
            assert "decomposition" in r["baseline"]
            assert "gfn" in r["baseline"]
            assert "debt_stabilizing_pb" in r["baseline"]
            assert "iterations" in r["convergence"]
            assert "risk_premium_applied" in r["convergence"]
            assert "required" in r["consolidation"]
            assert "adjustment_pp" in r["consolidation"]
            assert "adjusted_terminal_debt" in r["consolidation"]
