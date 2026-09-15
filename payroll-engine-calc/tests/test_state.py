
import csv
import json
import subprocess
import os
import pytest

TOLERANCE = 0.01


@pytest.fixture(scope="module", autouse=True)
def ensure_engine_output():
    """Run the payroll engine once before all tests in this module."""
    result = subprocess.run(
        ["python3", "/app/payroll_engine.py"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Engine failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists("/app/payroll_output.json"), "payroll_output.json not created"


@pytest.fixture(scope="module")
def results():
    with open("/app/payroll_output.json") as f:
        data = json.load(f)
    assert "results" in data, "Output missing 'results' key"
    results_map = {r["id"]: r for r in data["results"]}
    return results_map


def assert_close(actual, expected, field_name, scenario_id):
    assert abs(actual - expected) <= TOLERANCE, (
        f"Scenario '{scenario_id}', field '{field_name}': "
        f"expected {expected}, got {actual} (diff {abs(actual - expected):.4f})"
    )


# --- Scenario 1: chen_regular ---
# Regular paycheck with SS wage base crossing + group-term life imputed income
# Salary $195,000/yr biweekly = $7,500.00/period
# Age 61: Table 2-2 cost $0.66/month per $1K
# Coverage $200K, employee pays $10/month
# Imputed: ($200K-$50K)/1000 * $0.66 * 12 - $10*12 = $1,068/yr -> $41.08/period
# 401k 6% = $450.00, S125 health = $300.00
# FIT taxable: $7500 - $450 - $300 + $41.08 = $6,791.08
# After SD: $6,791.08 - $576.92 = $6,214.16
# FIT bracket 4: $678.89 + 0.24 * ($6,214.16 - $3,975.00) = $1,216.29
# FICA wages: $7500 - $300 + $41.08 = $7,241.08
# SS remaining: $176,100 - $173,500 = $2,600
# SS tax: $2,600 * 0.062 = $161.20
# Medicare: $7,241.08 * 0.0145 = $105.00
# State CO: $6,791.08 * 0.044 = $298.81
# Net: $7,500 - $450 - $300 - $1,216.29 - $161.20 - $105.00 - $298.81 = $4,968.70

class TestChenRegular:
    def test_gross_pay(self, results):
        r = results["chen_regular"]
        assert_close(r["gross_pay"], 7500.00, "gross_pay", "chen_regular")

    def test_imputed_income(self, results):
        r = results["chen_regular"]
        assert_close(r["imputed_income"], 41.08, "imputed_income", "chen_regular")

    def test_pretax_401k(self, results):
        r = results["chen_regular"]
        assert_close(r["pretax_401k"], 450.00, "pretax_401k", "chen_regular")

    def test_pretax_health(self, results):
        r = results["chen_regular"]
        assert_close(r["pretax_health"], 300.00, "pretax_health", "chen_regular")

    def test_fit_taxable_wages(self, results):
        r = results["chen_regular"]
        assert_close(r["fit_taxable_wages"], 6791.08, "fit_taxable_wages", "chen_regular")

    def test_fit_withholding(self, results):
        r = results["chen_regular"]
        assert_close(r["fit_withholding"], 1216.29, "fit_withholding", "chen_regular")

    def test_ss_taxable_wages(self, results):
        r = results["chen_regular"]
        assert_close(r["ss_taxable_wages"], 2600.00, "ss_taxable_wages", "chen_regular")

    def test_ss_tax(self, results):
        r = results["chen_regular"]
        assert_close(r["ss_tax"], 161.20, "ss_tax", "chen_regular")

    def test_medicare_taxable_wages(self, results):
        r = results["chen_regular"]
        assert_close(r["medicare_taxable_wages"], 7241.08, "medicare_taxable_wages", "chen_regular")

    def test_medicare_tax(self, results):
        r = results["chen_regular"]
        assert_close(r["medicare_tax"], 105.00, "medicare_tax", "chen_regular")

    def test_additional_medicare_tax(self, results):
        r = results["chen_regular"]
        assert_close(r["additional_medicare_tax"], 0.00, "additional_medicare_tax", "chen_regular")

    def test_state_tax(self, results):
        r = results["chen_regular"]
        assert_close(r["state_tax"], 298.81, "state_tax", "chen_regular")

    def test_net_pay(self, results):
        r = results["chen_regular"]
        assert_close(r["net_pay"], 4968.70, "net_pay", "chen_regular")


# --- Scenario 2: martinez_bonus ---
# Aggregate method: regular $4,800 + bonus $4,000, Single, PA
# FIT regular only: SD $576.92 -> adjusted $4,223.08 -> bracket 4
#   $678.89 + 0.24 * ($4,223.08 - $3,975.00) = $738.43
# FIT combined: $8,800 - $576.92 = $8,223.08 -> bracket 5
#   $1,546.12 + 0.32 * ($8,223.08 - $7,588.46) = $1,749.20
# FIT on bonus: $1,749.20 - $738.43 = $1,010.77
# SS: $4,000 * 0.062 = $248.00
# Medicare: $4,000 * 0.0145 = $58.00
# State PA: $4,000 * 0.0307 = $122.80
# Total: $1,439.57, Net bonus: $2,560.43

class TestMartinezBonus:
    def test_regular_gross(self, results):
        r = results["martinez_bonus"]
        assert_close(r["regular_gross"], 4800.00, "regular_gross", "martinez_bonus")

    def test_bonus_gross(self, results):
        r = results["martinez_bonus"]
        assert_close(r["bonus_gross"], 4000.00, "bonus_gross", "martinez_bonus")

    def test_fit_regular_only(self, results):
        r = results["martinez_bonus"]
        assert_close(r["fit_regular_only"], 738.43, "fit_regular_only", "martinez_bonus")

    def test_fit_combined(self, results):
        r = results["martinez_bonus"]
        assert_close(r["fit_combined"], 1749.20, "fit_combined", "martinez_bonus")

    def test_fit_on_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["fit_on_bonus"], 1010.77, "fit_on_bonus", "martinez_bonus")

    def test_ss_on_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["ss_on_bonus"], 248.00, "ss_on_bonus", "martinez_bonus")

    def test_medicare_on_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["medicare_on_bonus"], 58.00, "medicare_on_bonus", "martinez_bonus")

    def test_additional_medicare_on_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["additional_medicare_on_bonus"], 0.00, "additional_medicare_on_bonus", "martinez_bonus")

    def test_state_on_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["state_on_bonus"], 122.80, "state_on_bonus", "martinez_bonus")

    def test_total_bonus_taxes(self, results):
        r = results["martinez_bonus"]
        assert_close(r["total_bonus_taxes"], 1439.57, "total_bonus_taxes", "martinez_bonus")

    def test_net_bonus(self, results):
        r = results["martinez_bonus"]
        assert_close(r["net_bonus"], 2560.43, "net_bonus", "martinez_bonus")


# --- Scenario 3: johnson_grossup ---
# Gross-up with SS wage base boundary
# Desired net: $2,500, YTD FICA: $174,000, SS remaining: $2,100
# Rates: FIT 22%, SS 6.2% (on first $2,100), Medicare 1.45%, IL 4.95%
# Piecewise: G > $2,100 so SS capped at $2,100
# G*(1-0.284) - $130.20 = $2,500 -> G = $3,672.63 (estimate)
# Search yields G = $3,673.47:
# FIT: $808.16, SS: $130.20, Medicare: $53.27, State: $181.84
# Total taxes: $1,173.47, actual_net: $2,500.00

class TestJohnsonGrossup:
    def test_desired_net(self, results):
        r = results["johnson_grossup"]
        assert_close(r["desired_net"], 2500.00, "desired_net", "johnson_grossup")

    def test_computed_gross(self, results):
        r = results["johnson_grossup"]
        assert_close(r["computed_gross"], 3673.47, "computed_gross", "johnson_grossup")

    def test_fit(self, results):
        r = results["johnson_grossup"]
        assert_close(r["fit"], 808.16, "fit", "johnson_grossup")

    def test_ss_tax(self, results):
        r = results["johnson_grossup"]
        assert_close(r["ss_tax"], 130.20, "ss_tax", "johnson_grossup")

    def test_medicare_tax(self, results):
        r = results["johnson_grossup"]
        assert_close(r["medicare_tax"], 53.27, "medicare_tax", "johnson_grossup")

    def test_additional_medicare_tax(self, results):
        r = results["johnson_grossup"]
        assert_close(r["additional_medicare_tax"], 0.00, "additional_medicare_tax", "johnson_grossup")

    def test_state_tax(self, results):
        r = results["johnson_grossup"]
        assert_close(r["state_tax"], 181.84, "state_tax", "johnson_grossup")

    def test_total_taxes(self, results):
        r = results["johnson_grossup"]
        assert_close(r["total_taxes"], 1173.47, "total_taxes", "johnson_grossup")

    def test_actual_net(self, results):
        r = results["johnson_grossup"]
        assert_close(r["actual_net"], 2500.00, "actual_net", "johnson_grossup")


# --- Scenario 4: patel_retro ---
# Retro pay with OT recalculation
# Old rate $24, new rate $27, diff $3, OT diff $4.50
# Week 1: 46hrs -> reg_diff $120, ot_diff $27, total $147
# Week 2: 40hrs -> reg_diff $120, ot_diff $0, total $120
# Week 3: 44hrs -> reg_diff $120, ot_diff $18, total $138
# Total retro: $405
# FIT: $89.10, SS: $25.11, Medicare: $5.87, State PA: $12.43
# Total taxes: $132.51, Net: $272.49

class TestPatelRetro:
    def test_week1(self, results):
        r = results["patel_retro"]
        w = r["weeks"][0]
        assert_close(w["regular_diff"], 120.00, "week1.regular_diff", "patel_retro")
        assert_close(w["ot_diff"], 27.00, "week1.ot_diff", "patel_retro")
        assert_close(w["total_diff"], 147.00, "week1.total_diff", "patel_retro")

    def test_week2(self, results):
        r = results["patel_retro"]
        w = r["weeks"][1]
        assert_close(w["regular_diff"], 120.00, "week2.regular_diff", "patel_retro")
        assert_close(w["ot_diff"], 0.00, "week2.ot_diff", "patel_retro")
        assert_close(w["total_diff"], 120.00, "week2.total_diff", "patel_retro")

    def test_week3(self, results):
        r = results["patel_retro"]
        w = r["weeks"][2]
        assert_close(w["regular_diff"], 120.00, "week3.regular_diff", "patel_retro")
        assert_close(w["ot_diff"], 18.00, "week3.ot_diff", "patel_retro")
        assert_close(w["total_diff"], 138.00, "week3.total_diff", "patel_retro")

    def test_total_retro_gross(self, results):
        r = results["patel_retro"]
        assert_close(r["total_retro_gross"], 405.00, "total_retro_gross", "patel_retro")

    def test_fit(self, results):
        r = results["patel_retro"]
        assert_close(r["fit"], 89.10, "fit", "patel_retro")

    def test_ss_tax(self, results):
        r = results["patel_retro"]
        assert_close(r["ss_tax"], 25.11, "ss_tax", "patel_retro")

    def test_medicare_tax(self, results):
        r = results["patel_retro"]
        assert_close(r["medicare_tax"], 5.87, "medicare_tax", "patel_retro")

    def test_additional_medicare_tax(self, results):
        r = results["patel_retro"]
        assert_close(r["additional_medicare_tax"], 0.00, "additional_medicare_tax", "patel_retro")

    def test_state_tax(self, results):
        r = results["patel_retro"]
        assert_close(r["state_tax"], 12.43, "state_tax", "patel_retro")

    def test_total_taxes(self, results):
        r = results["patel_retro"]
        assert_close(r["total_taxes"], 132.51, "total_taxes", "patel_retro")

    def test_net_retro(self, results):
        r = results["patel_retro"]
        assert_close(r["net_retro"], 272.49, "net_retro", "patel_retro")


# --- Scenario 5: kim_medicare ---
# Regular paycheck with Additional Medicare Tax crossing
# $220K/yr MFJ biweekly = $8,461.54, no deductions, IL
# YTD FICA: $194,000, SS already maxed ($194K > $176.1K cap)
# FIT MFJ: $8,461.54 - $1,153.85 = $7,307.69 -> bracket 3
#   $429.11 + 0.22 * ($7,307.69 - $3,728.85) = $1,216.45
# SS: $0
# Medicare: $8,461.54 * 0.0145 = $122.69
# Additional Medicare: ($194K + $8,461.54 - $200K) = $2,461.54
#   $2,461.54 * 0.009 = $22.15
# State IL: $8,461.54 * 0.0495 = $418.85
# Net: $8,461.54 - $1,216.45 - $122.69 - $22.15 - $418.85 = $6,681.40

class TestKimMedicare:
    def test_gross_pay(self, results):
        r = results["kim_medicare"]
        assert_close(r["gross_pay"], 8461.54, "gross_pay", "kim_medicare")

    def test_fit_withholding(self, results):
        r = results["kim_medicare"]
        assert_close(r["fit_withholding"], 1216.45, "fit_withholding", "kim_medicare")

    def test_ss_taxable_wages(self, results):
        r = results["kim_medicare"]
        assert_close(r["ss_taxable_wages"], 0.00, "ss_taxable_wages", "kim_medicare")

    def test_ss_tax(self, results):
        r = results["kim_medicare"]
        assert_close(r["ss_tax"], 0.00, "ss_tax", "kim_medicare")

    def test_medicare_taxable_wages(self, results):
        r = results["kim_medicare"]
        assert_close(r["medicare_taxable_wages"], 8461.54, "medicare_taxable_wages", "kim_medicare")

    def test_medicare_tax(self, results):
        r = results["kim_medicare"]
        assert_close(r["medicare_tax"], 122.69, "medicare_tax", "kim_medicare")

    def test_additional_medicare_tax(self, results):
        r = results["kim_medicare"]
        assert_close(r["additional_medicare_tax"], 22.15, "additional_medicare_tax", "kim_medicare")

    def test_state_tax(self, results):
        r = results["kim_medicare"]
        assert_close(r["state_tax"], 418.85, "state_tax", "kim_medicare")

    def test_net_pay(self, results):
        r = results["kim_medicare"]
        assert_close(r["net_pay"], 6681.40, "net_pay", "kim_medicare")


# --- Scenario 6: davis_garnishment ---
# Regular paycheck with child support garnishment, CCPA limit hit
# $78K/yr single CO biweekly = $3,000.00/period, age 52
# Group-term life: $150K, $5/mo contrib
#   Age 52: $0.23/month per $1K, coverage over $50K = $100K = 100 units
#   Monthly cost: 100 * $0.23 = $23.00
#   Annual imputed: $23*12 - $5*12 = $216, per-period = $216/26 = $8.31
# 401k 4% = $120.00, S125 health = $150.00
# FIT taxable: $3000 - $120 - $150 + $8.31 = $2,738.31
# After SD: $2,738.31 - $576.92 = $2,161.39
# FIT bracket 3: $214.56 + 0.22 * ($2,161.39 - $1,864.42) = $279.89
# FICA wages: $3000 - $150 + $8.31 = $2,858.31
# SS: $2,858.31 * 0.062 = $177.22
# Medicare: $2,858.31 * 0.0145 = $41.45
# Additional Medicare: $0 (YTD $42K + $2,858 < $200K)
# State CO: $2,738.31 * 0.044 = $120.49
# Net before garnishment: $3000 - $120 - $150 - $279.89 - $177.22 - $41.45 - $120.49 = $2,110.95
# Disposable: $3000 - $279.89 - $177.22 - $41.45 - $120.49 = $2,380.95
# CCPA: unmarried, no other dependents, >12wk arrears -> 65%
# Max garnishment: $2,380.95 * 0.65 = $1,547.62
# Order: $1,600 -> actual: min($1600, $1547.62) = $1,547.62
# Net after garnishment: $2,110.95 - $1,547.62 = $563.33

class TestDavisGarnishment:
    def test_gross_pay(self, results):
        r = results["davis_garnishment"]
        assert_close(r["gross_pay"], 3000.00, "gross_pay", "davis_garnishment")

    def test_imputed_income(self, results):
        r = results["davis_garnishment"]
        assert_close(r["imputed_income"], 8.31, "imputed_income", "davis_garnishment")

    def test_pretax_401k(self, results):
        r = results["davis_garnishment"]
        assert_close(r["pretax_401k"], 120.00, "pretax_401k", "davis_garnishment")

    def test_pretax_health(self, results):
        r = results["davis_garnishment"]
        assert_close(r["pretax_health"], 150.00, "pretax_health", "davis_garnishment")

    def test_fit_taxable_wages(self, results):
        r = results["davis_garnishment"]
        assert_close(r["fit_taxable_wages"], 2738.31, "fit_taxable_wages", "davis_garnishment")

    def test_fit_withholding(self, results):
        r = results["davis_garnishment"]
        assert_close(r["fit_withholding"], 279.89, "fit_withholding", "davis_garnishment")

    def test_ss_taxable_wages(self, results):
        r = results["davis_garnishment"]
        assert_close(r["ss_taxable_wages"], 2858.31, "ss_taxable_wages", "davis_garnishment")

    def test_ss_tax(self, results):
        r = results["davis_garnishment"]
        assert_close(r["ss_tax"], 177.22, "ss_tax", "davis_garnishment")

    def test_medicare_taxable_wages(self, results):
        r = results["davis_garnishment"]
        assert_close(r["medicare_taxable_wages"], 2858.31, "medicare_taxable_wages", "davis_garnishment")

    def test_medicare_tax(self, results):
        r = results["davis_garnishment"]
        assert_close(r["medicare_tax"], 41.45, "medicare_tax", "davis_garnishment")

    def test_additional_medicare_tax(self, results):
        r = results["davis_garnishment"]
        assert_close(r["additional_medicare_tax"], 0.00, "additional_medicare_tax", "davis_garnishment")

    def test_state_tax(self, results):
        r = results["davis_garnishment"]
        assert_close(r["state_tax"], 120.49, "state_tax", "davis_garnishment")

    def test_net_pay(self, results):
        r = results["davis_garnishment"]
        assert_close(r["net_pay"], 2110.95, "net_pay", "davis_garnishment")

    def test_disposable_earnings(self, results):
        r = results["davis_garnishment"]
        assert_close(r["disposable_earnings"], 2380.95, "disposable_earnings", "davis_garnishment")

    def test_ccpa_limit_pct(self, results):
        r = results["davis_garnishment"]
        assert_close(r["ccpa_limit_pct"], 0.65, "ccpa_limit_pct", "davis_garnishment")

    def test_max_garnishment(self, results):
        r = results["davis_garnishment"]
        assert_close(r["max_garnishment"], 1547.62, "max_garnishment", "davis_garnishment")

    def test_actual_garnishment(self, results):
        r = results["davis_garnishment"]
        assert_close(r["actual_garnishment"], 1547.62, "actual_garnishment", "davis_garnishment")

    def test_net_pay_after_garnishment(self, results):
        r = results["davis_garnishment"]
        assert_close(r["net_pay_after_garnishment"], 563.33, "net_pay_after_garnishment", "davis_garnishment")


# --- Cross-scenario consistency checks ---

class TestConsistency:
    def test_all_scenarios_present(self, results):
        expected_ids = {
            "chen_regular", "martinez_bonus", "johnson_grossup",
            "patel_retro", "kim_medicare", "davis_garnishment"
        }
        assert set(results.keys()) == expected_ids, (
            f"Expected scenarios {expected_ids}, got {set(results.keys())}"
        )

    def test_chen_net_decomposition(self, results):
        """Verify net_pay = gross - pretax - taxes."""
        r = results["chen_regular"]
        computed_net = (
            r["gross_pay"]
            - r["pretax_401k"]
            - r["pretax_health"]
            - r["fit_withholding"]
            - r["ss_tax"]
            - r["medicare_tax"]
            - r["additional_medicare_tax"]
            - r["state_tax"]
        )
        assert_close(computed_net, r["net_pay"], "net_decomposition", "chen_regular")

    def test_martinez_bonus_decomposition(self, results):
        """Verify net_bonus = bonus - total_taxes."""
        r = results["martinez_bonus"]
        assert_close(
            r["bonus_gross"] - r["total_bonus_taxes"],
            r["net_bonus"],
            "bonus_decomposition",
            "martinez_bonus",
        )

    def test_johnson_grossup_decomposition(self, results):
        """Verify actual_net = gross - total_taxes."""
        r = results["johnson_grossup"]
        assert_close(
            r["computed_gross"] - r["total_taxes"],
            r["actual_net"],
            "grossup_decomposition",
            "johnson_grossup",
        )

    def test_patel_retro_decomposition(self, results):
        """Verify net = gross - taxes."""
        r = results["patel_retro"]
        assert_close(
            r["total_retro_gross"] - r["total_taxes"],
            r["net_retro"],
            "retro_decomposition",
            "patel_retro",
        )

    def test_kim_net_decomposition(self, results):
        """Verify net_pay = gross - taxes (no pretax deductions for Kim)."""
        r = results["kim_medicare"]
        computed_net = (
            r["gross_pay"]
            - r["fit_withholding"]
            - r["ss_tax"]
            - r["medicare_tax"]
            - r["additional_medicare_tax"]
            - r["state_tax"]
        )
        assert_close(computed_net, r["net_pay"], "net_decomposition", "kim_medicare")

    def test_davis_net_decomposition(self, results):
        """Verify net_pay and net_pay_after_garnishment for Davis."""
        r = results["davis_garnishment"]
        computed_net = (
            r["gross_pay"]
            - r["pretax_401k"]
            - r["pretax_health"]
            - r["fit_withholding"]
            - r["ss_tax"]
            - r["medicare_tax"]
            - r["additional_medicare_tax"]
            - r["state_tax"]
        )
        assert_close(computed_net, r["net_pay"], "net_decomposition", "davis_garnishment")
        assert_close(
            r["net_pay"] - r["actual_garnishment"],
            r["net_pay_after_garnishment"],
            "garnishment_decomposition",
            "davis_garnishment",
        )

    def test_davis_disposable_earnings(self, results):
        """Verify disposable = gross - legally required taxes."""
        r = results["davis_garnishment"]
        computed_disposable = (
            r["gross_pay"]
            - r["fit_withholding"]
            - r["ss_tax"]
            - r["medicare_tax"]
            - r["additional_medicare_tax"]
            - r["state_tax"]
        )
        assert_close(
            computed_disposable,
            r["disposable_earnings"],
            "disposable_decomposition",
            "davis_garnishment",
        )


# --- Makefile pipeline tests ---

class TestMakePipeline:
    def test_makefile_exists(self):
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_run(self):
        result = subprocess.run(
            ["make", "-C", "/app", "run"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make run failed: {result.stderr}"
        assert os.path.exists("/app/payroll_output.json"), "make run did not produce payroll_output.json"

    def test_make_validate(self):
        # Ensure output exists first
        subprocess.run(["make", "-C", "/app", "run"], capture_output=True, timeout=60)
        result = subprocess.run(
            ["make", "-C", "/app", "validate"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make validate failed: {result.stderr}\n{result.stdout}"

    def test_make_report(self):
        # Ensure output exists first
        subprocess.run(["make", "-C", "/app", "run"], capture_output=True, timeout=60)
        result = subprocess.run(
            ["make", "-C", "/app", "report"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make report failed: {result.stderr}"
        assert os.path.exists("/app/payroll_report.csv"), "make report did not produce payroll_report.csv"


# --- jq validator tests ---

class TestValidator:
    def test_validator_exists(self):
        assert os.path.exists("/app/payroll_validator.jq"), "payroll_validator.jq not found"

    def test_validator_output(self):
        # Ensure output exists
        subprocess.run(["make", "-C", "/app", "run"], capture_output=True, timeout=60)
        result = subprocess.run(
            ["jq", "-ef", "/app/payroll_validator.jq", "/app/payroll_output.json"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"Validator failed: {result.stderr}"
        output = json.loads(result.stdout.strip())
        assert output["valid"] is True, f"Validator output valid != true: {output}"
        assert output["scenarios_checked"] == 6, (
            f"Expected 6 scenarios_checked, got {output['scenarios_checked']}"
        )


# --- CSV report tests ---

class TestCSVReport:
    @pytest.fixture(scope="class", autouse=True)
    def generate_report(self):
        """Ensure the report CSV exists."""
        subprocess.run(["make", "-C", "/app", "run"], capture_output=True, timeout=60)
        result = subprocess.run(
            ["make", "-C", "/app", "report"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"make report failed: {result.stderr}"

    def test_csv_exists(self):
        assert os.path.exists("/app/payroll_report.csv"), "payroll_report.csv not found"

    def test_csv_header(self):
        with open("/app/payroll_report.csv") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["scenario_id", "type", "gross", "net"], f"Bad header: {header}"

    def test_csv_row_count(self):
        with open("/app/payroll_report.csv") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            rows = list(reader)
        assert len(rows) == 6, f"Expected 6 data rows, got {len(rows)}"

    def test_csv_sorted_by_id(self):
        with open("/app/payroll_report.csv") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            ids = [row[0] for row in reader]
        assert ids == sorted(ids), f"CSV not sorted by scenario_id: {ids}"

    def test_csv_values(self):
        expected = {
            "chen_regular": ("regular", 7500.00, 4968.70),
            "davis_garnishment": ("regular_with_garnishment", 3000.00, 563.33),
            "johnson_grossup": ("gross_up", 3673.47, 2500.00),
            "kim_medicare": ("regular", 8461.54, 6681.40),
            "martinez_bonus": ("bonus_aggregate", 4000.00, 2560.43),
            "patel_retro": ("retro_pay", 405.00, 272.49),
        }
        with open("/app/payroll_report.csv") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            for row in reader:
                sid = row[0]
                stype = row[1]
                gross = float(row[2])
                net = float(row[3])
                assert sid in expected, f"Unexpected scenario in CSV: {sid}"
                exp_type, exp_gross, exp_net = expected[sid]
                assert stype == exp_type, f"{sid}: expected type {exp_type}, got {stype}"
                assert abs(gross - exp_gross) <= TOLERANCE, (
                    f"{sid}: gross expected {exp_gross}, got {gross}"
                )
                assert abs(net - exp_net) <= TOLERANCE, (
                    f"{sid}: net expected {exp_net}, got {net}"
                )
