
import json
import subprocess
import os
import math
import sqlite3
import csv
import tempfile
import pytest

TOLERANCE = 0.011  # HMRC allows 0.01


def run_payroll(input_data, fmt="json"):
    """Write input, run payroll tool, return parsed output."""
    if fmt == "json":
        input_path = "/app/_test_input.json"
        with open(input_path, "w") as f:
            json.dump(input_data, f)
        result = subprocess.run(
            ["/app/payroll", "--format", "json", input_path],
            capture_output=True, text=True, timeout=60, cwd="/app"
        )
    elif fmt == "csv":
        input_path = "/app/_test_input.csv"
        with open(input_path, "w") as f:
            writer = csv.writer(f)
            writer.writerow(["employee_id", "pay_frequency", "ni_category",
                             "period_number", "gross_pay", "tax_code", "w1m1",
                             "student_loans"])
            for emp in input_data["employees"]:
                sl = "|".join(emp.get("student_loans", []))
                for p in emp["periods"]:
                    writer.writerow([
                        emp["id"], emp["pay_frequency"], emp["ni_category"],
                        p["period_number"], p["gross_pay"], p["tax_code"],
                        str(p.get("w1m1", False)).lower(), sl
                    ])
        result = subprocess.run(
            ["/app/payroll", "--format", "csv", input_path],
            capture_output=True, text=True, timeout=60, cwd="/app"
        )
    assert result.returncode == 0, f"payroll failed: {result.stderr}"
    output = json.loads(result.stdout)
    return output


def find_employee(output, emp_id):
    for emp in output["employees"]:
        if emp["id"] == emp_id:
            return emp
    raise KeyError(f"Employee {emp_id} not found in output")


def assert_close(actual, expected, field_name, tolerance=TOLERANCE):
    assert abs(actual - expected) <= tolerance, \
        f"{field_name}: expected {expected}, got {actual}, diff={abs(actual-expected)}"


def make_input(employees):
    return {"tax_year": "2026-27", "employees": employees}


def make_employee(eid, freq, ni_cat, periods, student_loans=None):
    return {
        "id": eid,
        "pay_frequency": freq,
        "ni_category": ni_cat,
        "student_loans": student_loans or [],
        "periods": periods
    }


def make_period(num, gp, code, w1m1=False):
    return {"period_number": num, "gross_pay": gp, "tax_code": code, "w1m1": w1m1}


# ============================================================
# TEST GROUP A: PAYE Income Tax -- Cumulative Suffix Codes
# ============================================================

class TestPAYE_UK_Cumulative_Weekly:
    """UK cumulative weekly with mid-year code changes (1257L -> BR -> NT)."""

    PERIODS = [
        (1, 267.07, "1257L", False),
        (2, 266.08, "1257L", False),
        (3, 853.05, "1257L", False),
        (4, 2021.09, "1257L", False),
        (5, 9834.16, "1257L", False),
        (6, 15000.00, "1257L", False),
        (7, 242.84, "1257L", False),
        (8, 243.83, "1257L", False),
        (9, 632.84, "BR", False),
        (10, 2893.83, "NT", False),
    ]
    EXPECTED_TAX_DUE = [5.0, 4.8, 122.2, 355.8, 3599.6, 6375.68, -264.87, -264.43, -4061.78, -5872.0]
    EXPECTED_TAX_TO_DATE = [5.0, 9.8, 132.0, 487.8, 4087.4, 10463.08, 10198.21, 9933.78, 5872.0, 0.0]

    def setup_method(self):
        periods = [make_period(p[0], p[1], p[2], p[3]) for p in self.PERIODS]
        emp = make_employee("UK_CUM_W", "weekly", "A", periods)
        inp = make_input([emp])
        self.output = run_payroll(inp)
        self.emp = find_employee(self.output, "UK_CUM_W")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_due(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due"], self.EXPECTED_TAX_DUE[idx],
                      f"period {idx+1} tax_due")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_to_date(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due_to_date"], self.EXPECTED_TAX_TO_DATE[idx],
                      f"period {idx+1} tax_due_to_date")


class TestPAYE_UK_Cumulative_Monthly:
    """UK cumulative monthly with code changes (1257L -> BR -> NT)."""

    PERIODS = [
        (1, 1156.25, "1257L", False),
        (2, 1156.26, "1257L", False),
        (3, 31123.26, "1257L", False),
        (4, 14465.71, "1257L", False),
        (5, 52681.25, "1257L", False),
        (6, 50000.00, "1257L", False),
        (7, 15000.00, "1257L", False),
        (8, 14000.55, "1257L", False),
        (9, 12590.45, "BR", False),
        (10, 11245.05, "NT", False),
    ]
    EXPECTED_TAX_DUE = [21.4, 21.6, 10188.0, 4838.6, 22085.1, 20878.65, 5128.2, 4679.1, -29406.05, -38434.6]
    EXPECTED_TAX_TO_DATE = [21.4, 43.0, 10231.0, 15069.6, 37154.7, 58033.35, 63161.55, 67840.65, 38434.6, 0.0]

    def setup_method(self):
        periods = [make_period(p[0], p[1], p[2], p[3]) for p in self.PERIODS]
        emp = make_employee("UK_CUM_M", "monthly", "A", periods)
        inp = make_input([emp])
        self.output = run_payroll(inp)
        self.emp = find_employee(self.output, "UK_CUM_M")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_due(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due"], self.EXPECTED_TAX_DUE[idx],
                      f"month {idx+1} tax_due")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_to_date(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due_to_date"], self.EXPECTED_TAX_TO_DATE[idx],
                      f"month {idx+1} tax_due_to_date")


class TestPAYE_Scottish_Cumulative_Weekly:
    """Scottish cumulative weekly with mid-year code changes (S1257L -> SBR -> NT)."""

    PERIODS = [
        (1, 267.07, "S1257L", False),
        (2, 266.08, "S1257L", False),
        (3, 853.05, "S1257L", False),
        (4, 2021.09, "S1257L", False),
        (5, 9834.16, "S1257L", False),
        (6, 15000.00, "S1257L", False),
        (7, 242.84, "S1257L", False),
        (8, 243.83, "S1257L", False),
        (9, 632.84, "SBR", False),
        (10, 2893.83, "NT", False),
    ]
    EXPECTED_TAX_DUE = [4.75, 4.56, 120.4, 376.31, 4079.9, 6845.99, -237.32, -236.84, -5085.75, -5872.0]
    EXPECTED_TAX_TO_DATE = [4.75, 9.31, 129.71, 506.02, 4585.92, 11431.91, 11194.59, 10957.75, 5872.0, 0.0]

    def setup_method(self):
        periods = [make_period(p[0], p[1], p[2], p[3]) for p in self.PERIODS]
        emp = make_employee("SCOT_CUM_W", "weekly", "A", periods)
        inp = make_input([emp])
        self.output = run_payroll(inp)
        self.emp = find_employee(self.output, "SCOT_CUM_W")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_due(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due"], self.EXPECTED_TAX_DUE[idx],
                      f"period {idx+1} tax_due")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_to_date(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due_to_date"], self.EXPECTED_TAX_TO_DATE[idx],
                      f"period {idx+1} tax_due_to_date")


class TestPAYE_Welsh_Cumulative_Weekly:
    """Welsh cumulative weekly with code changes (C1257L -> CBR -> NT)."""

    PERIODS = [
        (1, 267.07, "C1257L", False),
        (2, 266.08, "C1257L", False),
        (3, 853.05, "C1257L", False),
        (4, 2021.09, "C1257L", False),
        (5, 9834.16, "C1257L", False),
        (6, 15000.00, "C1257L", False),
        (7, 242.84, "C1257L", False),
        (8, 243.83, "C1257L", False),
        (9, 632.84, "CBR", False),
        (10, 2893.83, "NT", False),
    ]
    EXPECTED_TAX_DUE = [5.0, 4.8, 122.2, 355.8, 3599.6, 6375.68, -264.87, -264.43, -4061.78, -5872.0]
    EXPECTED_TAX_TO_DATE = [5.0, 9.8, 132.0, 487.8, 4087.4, 10463.08, 10198.21, 9933.78, 5872.0, 0.0]

    def setup_method(self):
        periods = [make_period(p[0], p[1], p[2], p[3]) for p in self.PERIODS]
        emp = make_employee("WELSH_W", "weekly", "A", periods)
        inp = make_input([emp])
        self.output = run_payroll(inp)
        self.emp = find_employee(self.output, "WELSH_W")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_due(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due"], self.EXPECTED_TAX_DUE[idx],
                      f"Welsh wk {idx+1} tax_due")

    @pytest.mark.parametrize("idx", range(10))
    def test_tax_to_date(self, idx):
        r = self.emp["results"][idx]
        assert_close(r["paye"]["tax_due_to_date"], self.EXPECTED_TAX_TO_DATE[idx],
                      f"Welsh wk {idx+1} tax_to_date")


# ============================================================
# TEST GROUP B: PAYE -- K Codes
# ============================================================

class TestPAYE_KCode_Cumulative:
    """K-code cumulative weekly and monthly."""

    def test_k630_weekly(self):
        periods = [
            make_period(1, 150.0, "K630", False),
            make_period(2, 300.0, "K630", False),
            make_period(3, 245.0, "K630", False),
        ]
        emp = make_employee("K630_W", "weekly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "K630_W")
        expected_due = [54.2, 84.2, 73.4]
        expected_td = [54.2, 138.4, 211.8]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i], f"K630 wk {i+1} tax_due")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i], f"K630 wk {i+1} tax_td")

    def test_k585_monthly(self):
        periods = [
            make_period(1, 895.0, "K585", False),
            make_period(2, 1250.0, "K585", False),
            make_period(3, 765.0, "K585", False),
        ]
        emp = make_employee("K585_M", "monthly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "K585_M")
        expected_due = [276.6, 347.6, 250.6]
        expected_td = [276.6, 624.2, 874.8]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i], f"K585 mo {i+1} tax_due")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i], f"K585 mo {i+1} tax_td")


class TestPAYE_Scottish_K_Code:
    """Scottish K-code cumulative weekly."""

    def test_sk630_weekly(self):
        periods = [
            make_period(1, 150.0, "SK630", False),
            make_period(2, 300.0, "SK630", False),
            make_period(3, 245.0, "SK630", False),
        ]
        emp = make_employee("SK630_W", "weekly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "SK630_W")
        expected_due = [53.43, 83.84, 73.04]
        expected_td = [53.43, 137.27, 210.31]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i], f"SK630 wk {i+1}")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i], f"SK630 wk {i+1} td")


# ============================================================
# TEST GROUP C: PAYE -- Flat Rate Codes (BR, D0, D1)
# ============================================================

class TestPAYE_BR_Cumulative:
    """Cumulative BR code weekly and monthly."""

    def test_br_weekly(self):
        periods = [
            make_period(1, 650.15, "BR", False),
            make_period(2, 995.55, "BR", False),
            make_period(3, 7100.35, "BR", False),
        ]
        emp = make_employee("BR_W", "weekly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "BR_W")
        expected_due = [130.0, 199.0, 1420.2]
        expected_td = [130.0, 329.0, 1749.2]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i], f"BR wk {i+1} tax_due")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i], f"BR wk {i+1} tax_td")

    def test_br_monthly(self):
        periods = [
            make_period(1, 2870.55, "BR", False),
            make_period(2, 3500.95, "BR", False),
            make_period(3, 32000.0, "BR", False),
        ]
        emp = make_employee("BR_M", "monthly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "BR_M")
        expected_due = [574.0, 700.2, 6400.0]
        expected_td = [574.0, 1274.2, 7674.2]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i], f"BR mo {i+1} tax_due")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i], f"BR mo {i+1} tax_td")


class TestPAYE_W1M1:
    """Week1/Month1 basis suffix and special codes."""

    def test_w1m1_suffix_weekly(self):
        cases = [
            (29.05, 0.0),
            (29.06, 0.2),
            (750.06, 144.4),
        ]
        employees = []
        for i, (gp, expected_tax) in enumerate(cases):
            p = [make_period(1, gp, "145L", True)]
            employees.append(make_employee(f"W1M1_{i}", "weekly", "A", p))
        out = run_payroll(make_input(employees))
        for i, (gp, expected_tax) in enumerate(cases):
            e = find_employee(out, f"W1M1_{i}")
            assert_close(e["results"][0]["paye"]["tax_due"], expected_tax,
                          f"W1M1 145L gp={gp}")

    def test_w1m1_br_weekly(self):
        p = [make_period(1, 101.99, "BR", True)]
        emp = make_employee("W1M1_BR", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "W1M1_BR")
        assert_close(e["results"][0]["paye"]["tax_due"], 20.2, "W1M1 BR")

    def test_w1m1_d0_weekly(self):
        p = [make_period(1, 101.99, "D0", True)]
        emp = make_employee("W1M1_D0", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "W1M1_D0")
        assert_close(e["results"][0]["paye"]["tax_due"], 40.4, "W1M1 D0")

    def test_w1m1_d1_weekly(self):
        p = [make_period(1, 101.99, "D1", True)]
        emp = make_employee("W1M1_D1", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "W1M1_D1")
        assert_close(e["results"][0]["paye"]["tax_due"], 45.45, "W1M1 D1")


# ============================================================
# TEST GROUP D: PAYE -- Large Codes (>500) and Regulatory Limit
# ============================================================

class TestPAYE_LargeCode:
    """Codes > 500 requiring split free pay calculation."""

    def test_large_codes_weekly(self):
        cases = [
            (750.0, "999L", 111.4),
            (900.0, "1000L", 141.4),
            (1500.0, "1001L", 377.8),
        ]
        employees = []
        for i, (gp, code, expected_tax) in enumerate(cases):
            p = [make_period(1, gp, code, False)]
            employees.append(make_employee(f"LARGE_{i}", "weekly", "A", p))
        out = run_payroll(make_input(employees))
        for i, (gp, code, expected_tax) in enumerate(cases):
            e = find_employee(out, f"LARGE_{i}")
            assert_close(e["results"][0]["paye"]["tax_due"], expected_tax,
                          f"Large code {code} gp={gp}")


class TestPAYE_RegulatoryLimit:
    """Regulatory limit (Maxrate 50%) caps tax on positive pay for K codes."""

    def test_k_code_regulatory_limit(self):
        periods = [
            make_period(1, 50.0, "K630", False),
            make_period(2, 50.0, "K630", False),
            make_period(3, 50.0, "K630", False),
        ]
        emp = make_employee("REGLIM", "weekly", "A", periods)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "REGLIM")
        expected_due = [25.0, 25.0, 25.0]
        expected_td = [25.0, 50.0, 75.0]
        for i in range(3):
            assert_close(e["results"][i]["paye"]["tax_due"], expected_due[i],
                          f"RegLimit wk {i+1} tax_due")
            assert_close(e["results"][i]["paye"]["tax_due_to_date"], expected_td[i],
                          f"RegLimit wk {i+1} tax_td")


# ============================================================
# TEST GROUP E: National Insurance Contributions
# ============================================================

class TestNIC_CatA_Weekly:
    """NIC Category A weekly - various threshold boundaries."""

    CASES = [
        (96.03, 0.0, 0.0, 0.0),
        (96.04, 0.0, 0.01, 0.01),
        (242.07, 0.0, 21.91, 21.91),
        (242.08, 0.01, 21.91, 21.92),
        (481.03, 19.12, 57.75, 76.87),
        (966.64, 57.97, 130.6, 188.57),
        (967.04, 58.0, 130.66, 188.66),
    ]

    @pytest.mark.parametrize("case_idx", range(7))
    def test_nic(self, case_idx):
        gp, exp_ee, exp_er, exp_tot = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"NIC_A_W_{case_idx}", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"NIC_A_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["nic"]["employee_nic"], exp_ee, f"Cat A wkly gp={gp} ee_nic")
        assert_close(r["nic"]["employer_nic"], exp_er, f"Cat A wkly gp={gp} er_nic")
        assert_close(r["nic"]["total_nic"], exp_tot, f"Cat A wkly gp={gp} total")


class TestNIC_CatA_Monthly:
    """NIC Category A monthly."""

    CASES = [
        (417.03, 0.0, 0.0, 0.0),
        (417.04, 0.0, 0.01, 0.01),
        (1048.07, 0.0, 94.66, 94.66),
        (1048.08, 0.01, 94.66, 94.67),
        (2083.05, 82.8, 249.91, 332.71),
        (4188.53, 251.24, 565.73, 816.97),
        (4189.04, 251.28, 565.81, 817.09),
    ]

    @pytest.mark.parametrize("case_idx", range(7))
    def test_nic(self, case_idx):
        gp, exp_ee, exp_er, exp_tot = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"NIC_A_M_{case_idx}", "monthly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"NIC_A_M_{case_idx}")
        r = e["results"][0]
        assert_close(r["nic"]["employee_nic"], exp_ee, f"Cat A mthly gp={gp} ee_nic")
        assert_close(r["nic"]["employer_nic"], exp_er, f"Cat A mthly gp={gp} er_nic")
        assert_close(r["nic"]["total_nic"], exp_tot, f"Cat A mthly gp={gp} total")


class TestNIC_CatH_Weekly:
    """NIC Category H weekly -- same employee rates as A, zero employer below UEL."""

    CASES = [
        (242.08, 0.01, 0.0, 0.01),
        (481.03, 19.12, 0.0, 19.12),
        (967.04, 58.0, 0.01, 58.01),
    ]

    @pytest.mark.parametrize("case_idx", range(3))
    def test_nic(self, case_idx):
        gp, exp_ee, exp_er, exp_tot = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"NIC_H_W_{case_idx}", "weekly", "H", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"NIC_H_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["nic"]["employee_nic"], exp_ee, f"Cat H wkly gp={gp} ee_nic")
        assert_close(r["nic"]["employer_nic"], exp_er, f"Cat H wkly gp={gp} er_nic")
        assert_close(r["nic"]["total_nic"], exp_tot, f"Cat H wkly gp={gp} total")


class TestNIC_CatJ_Weekly:
    """NIC Category J weekly -- reduced employee rate."""

    CASES = [
        (242.08, 0.0, 21.91, 21.91),
        (242.31, 0.01, 21.95, 21.96),
        (481.03, 4.78, 57.75, 62.53),
        (967.04, 14.5, 130.66, 145.16),
    ]

    @pytest.mark.parametrize("case_idx", range(4))
    def test_nic(self, case_idx):
        gp, exp_ee, exp_er, exp_tot = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"NIC_J_W_{case_idx}", "weekly", "J", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"NIC_J_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["nic"]["employee_nic"], exp_ee, f"Cat J wkly gp={gp} ee_nic")
        assert_close(r["nic"]["employer_nic"], exp_er, f"Cat J wkly gp={gp} er_nic")
        assert_close(r["nic"]["total_nic"], exp_tot, f"Cat J wkly gp={gp} total")


class TestNIC_CatM_Weekly:
    """NIC Category M weekly -- zero employer below UEL, same employee as A."""

    CASES = [
        (242.08, 0.01, 0.0, 0.01),
        (481.03, 19.12, 0.0, 19.12),
        (967.04, 58.0, 0.01, 58.01),
    ]

    @pytest.mark.parametrize("case_idx", range(3))
    def test_nic(self, case_idx):
        gp, exp_ee, exp_er, exp_tot = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"NIC_M_W_{case_idx}", "weekly", "M", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"NIC_M_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["nic"]["employee_nic"], exp_ee, f"Cat M wkly gp={gp} ee_nic")
        assert_close(r["nic"]["employer_nic"], exp_er, f"Cat M wkly gp={gp} er_nic")
        assert_close(r["nic"]["total_nic"], exp_tot, f"Cat M wkly gp={gp} total")


# ============================================================
# TEST GROUP F: Student Loan Deductions
# ============================================================

class TestStudentLoan_Plan1_Weekly:
    """Student Loan Plan 1 weekly deductions."""

    CASES = [
        (528.41, 0.0),
        (528.42, 1.0),
        (661.75, 13.0),
        (1783.97, 114.0),
        (2106.29, 143.0),
    ]

    @pytest.mark.parametrize("case_idx", range(5))
    def test_deduction(self, case_idx):
        gp, expected = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"SL1_W_{case_idx}", "weekly", "A", p, student_loans=["plan_1"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"SL1_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["student_loans"]["plan_1"], expected, f"Plan1 wkly gp={gp}")


class TestStudentLoan_Plan2_Weekly:
    """Student Loan Plan 2 weekly deductions."""

    CASES = [
        (576.20, 0.0),
        (576.21, 1.0),
        (709.54, 13.0),
        (2154.08, 143.0),
    ]

    @pytest.mark.parametrize("case_idx", range(4))
    def test_deduction(self, case_idx):
        gp, expected = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"SL2_W_{case_idx}", "weekly", "A", p, student_loans=["plan_2"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"SL2_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["student_loans"]["plan_2"], expected, f"Plan2 wkly gp={gp}")


class TestStudentLoan_Plan4_Weekly:
    """Student Loan Plan 4 weekly deductions."""

    CASES = [
        (661.01, 0.0),
        (661.02, 1.0),
        (794.35, 13.0),
        (1916.57, 114.0),
    ]

    @pytest.mark.parametrize("case_idx", range(4))
    def test_deduction(self, case_idx):
        gp, expected = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"SL4_W_{case_idx}", "weekly", "A", p, student_loans=["plan_4"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"SL4_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["student_loans"]["plan_4"], expected, f"Plan4 wkly gp={gp}")


class TestStudentLoan_Plan5_Monthly:
    """Student Loan Plan 5 monthly deductions."""

    CASES = [
        (2094.44, 0.0),
        (2094.45, 1.0),
        (2127.78, 4.0),
        (2583.44, 45.0),
        (8427.78, 571.0),
    ]

    @pytest.mark.parametrize("case_idx", range(5))
    def test_deduction(self, case_idx):
        gp, expected = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"SL5_M_{case_idx}", "monthly", "A", p, student_loans=["plan_5"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"SL5_M_{case_idx}")
        r = e["results"][0]
        assert_close(r["student_loans"]["plan_5"], expected, f"Plan5 mthly gp={gp}")


class TestStudentLoan_PGL_Weekly:
    """Postgraduate Loan weekly deductions."""

    CASES = [
        (420.50, 0.0),
        (420.51, 1.0),
        (620.51, 13.0),
        (2303.85, 114.0),
    ]

    @pytest.mark.parametrize("case_idx", range(4))
    def test_deduction(self, case_idx):
        gp, expected = self.CASES[case_idx]
        p = [make_period(1, gp, "NT", False)]
        emp = make_employee(f"PGL_W_{case_idx}", "weekly", "A", p, student_loans=["postgraduate"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, f"PGL_W_{case_idx}")
        r = e["results"][0]
        assert_close(r["student_loans"]["postgraduate"], expected, f"PGL wkly gp={gp}")


# ============================================================
# TEST GROUP G: Combined Scenarios
# ============================================================

class TestCombined:
    """Employee with PAYE + NIC + student loan all active."""

    def test_combined_weekly(self):
        """Weekly employee with 1257L code, Cat A NIC, Plan 1 student loan."""
        p = [make_period(1, 2000.0, "1257L", False)]
        emp = make_employee("COMBINED", "weekly", "A", p, student_loans=["plan_1"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "COMBINED")
        r = e["results"][0]

        assert_close(r["paye"]["tax_due"], 558.2, "combined paye")
        assert_close(r["nic"]["employee_nic"], 78.66, "combined ee_nic")
        assert_close(r["nic"]["employer_nic"], 285.6, "combined er_nic")
        assert_close(r["student_loans"]["plan_1"], 133.0, "combined sl1")

    def test_multiple_loans(self):
        """Employee with both plan_1 and postgraduate loan."""
        p = [make_period(1, 1000.0, "NT", False)]
        emp = make_employee("MULTI_LOAN", "weekly", "A", p,
                           student_loans=["plan_1", "postgraduate"])
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "MULTI_LOAN")
        r = e["results"][0]
        assert_close(r["student_loans"]["plan_1"], 43.0, "multi plan_1")
        assert_close(r["student_loans"]["postgraduate"], 35.0, "multi pgl")

    def test_employee_output_order(self):
        """Employee output order must match input order."""
        emps = [
            make_employee("ZZZ", "weekly", "A", [make_period(1, 500.0, "NT", False)]),
            make_employee("AAA", "weekly", "A", [make_period(1, 500.0, "NT", False)]),
            make_employee("MMM", "weekly", "A", [make_period(1, 500.0, "NT", False)]),
        ]
        out = run_payroll(make_input(emps))
        assert out["employees"][0]["id"] == "ZZZ"
        assert out["employees"][1]["id"] == "AAA"
        assert out["employees"][2]["id"] == "MMM"

    def test_no_student_loans_omitted(self):
        """Employee without student loans should not have student_loans in results."""
        p = [make_period(1, 500.0, "NT", False)]
        emp = make_employee("NO_SL", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "NO_SL")
        r = e["results"][0]
        assert "student_loans" not in r or r.get("student_loans") == {}, \
            "student_loans should be absent or empty when no loans assigned"

    def test_monetary_precision(self):
        """All monetary values should be rounded to 2 decimal places."""
        p = [make_period(1, 267.07, "1257L", False)]
        emp = make_employee("PREC", "weekly", "A", p)
        out = run_payroll(make_input([emp]))
        e = find_employee(out, "PREC")
        r = e["results"][0]
        tax_due = r["paye"]["tax_due"]
        assert round(tax_due, 2) == tax_due, f"tax_due {tax_due} not 2dp"
        ee_nic = r["nic"]["employee_nic"]
        assert round(ee_nic, 2) == ee_nic, f"employee_nic {ee_nic} not 2dp"


# ============================================================
# TEST GROUP H: CSV Input Mode
# ============================================================

class TestCSVInput:
    """Verify the payroll engine accepts --format csv input."""

    def test_csv_basic_paye(self):
        """CSV input produces same PAYE results as JSON input."""
        periods = [make_period(1, 2000.0, "1257L", False)]
        emp = make_employee("CSV_PAYE", "weekly", "A", periods, student_loans=["plan_1"])
        inp = make_input([emp])
        out = run_payroll(inp, fmt="csv")
        e = find_employee(out, "CSV_PAYE")
        r = e["results"][0]
        assert_close(r["paye"]["tax_due"], 558.2, "csv paye tax_due")
        assert_close(r["nic"]["employee_nic"], 78.66, "csv ee_nic")
        assert_close(r["student_loans"]["plan_1"], 133.0, "csv sl1")

    def test_csv_multi_period(self):
        """CSV input with multiple periods for one employee."""
        periods = [
            make_period(1, 267.07, "1257L", False),
            make_period(2, 266.08, "1257L", False),
            make_period(3, 853.05, "1257L", False),
        ]
        emp = make_employee("CSV_MULTI", "weekly", "A", periods)
        inp = make_input([emp])
        out = run_payroll(inp, fmt="csv")
        e = find_employee(out, "CSV_MULTI")
        assert_close(e["results"][0]["paye"]["tax_due"], 5.0, "csv multi p1")
        assert_close(e["results"][1]["paye"]["tax_due"], 4.8, "csv multi p2")
        assert_close(e["results"][2]["paye"]["tax_due"], 122.2, "csv multi p3")

    def test_csv_multi_employee(self):
        """CSV input with multiple employees."""
        emps = [
            make_employee("CSV_E1", "weekly", "A", [make_period(1, 500.0, "NT", False)]),
            make_employee("CSV_E2", "weekly", "J", [make_period(1, 500.0, "NT", False)]),
        ]
        out = run_payroll(make_input(emps), fmt="csv")
        e1 = find_employee(out, "CSV_E1")
        e2 = find_employee(out, "CSV_E2")
        # Cat A: employee pays 8% on earnings above PT(242)
        assert_close(e1["results"][0]["nic"]["employee_nic"], 20.64, "csv e1 ee_nic")
        # Cat J: employee pays 2% on earnings above PT(242)
        assert_close(e2["results"][0]["nic"]["employee_nic"], 5.16, "csv e2 ee_nic")

    def test_csv_w1m1(self):
        """CSV input correctly parses w1m1 flag."""
        p = [make_period(1, 101.99, "BR", True)]
        emp = make_employee("CSV_W1M1", "weekly", "A", p)
        out = run_payroll(make_input([emp]), fmt="csv")
        e = find_employee(out, "CSV_W1M1")
        assert_close(e["results"][0]["paye"]["tax_due"], 20.2, "csv w1m1 br")


# ============================================================
# TEST GROUP I: SQLite Database Output
# ============================================================

class TestSQLiteOutput:
    """Verify the payroll engine writes results to /app/payroll.db."""

    def _run_and_get_db(self):
        """Run a payroll computation and return a database connection."""
        # Remove existing db to ensure fresh state
        if os.path.exists("/app/payroll.db"):
            os.remove("/app/payroll.db")

        periods = [
            make_period(1, 2000.0, "1257L", False),
            make_period(2, 3000.0, "1257L", False),
        ]
        emp = make_employee("DB_TEST", "weekly", "A", periods, student_loans=["plan_1"])
        inp = make_input([emp])
        run_payroll(inp)

        assert os.path.exists("/app/payroll.db"), "payroll.db was not created"
        return sqlite3.connect("/app/payroll.db")

    def test_db_exists(self):
        """Database file is created after running payroll."""
        conn = self._run_and_get_db()
        conn.close()

    def test_payroll_results_table_schema(self):
        """payroll_results table has correct columns."""
        conn = self._run_and_get_db()
        cursor = conn.execute("PRAGMA table_info(payroll_results)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {"employee_id", "period_number", "gross_pay", "tax_due",
                    "tax_due_to_date", "employee_nic", "employer_nic", "total_nic"}
        assert expected.issubset(columns), \
            f"Missing columns: {expected - columns}, found: {columns}"
        conn.close()

    def test_student_loan_deductions_table_schema(self):
        """student_loan_deductions table has correct columns."""
        conn = self._run_and_get_db()
        cursor = conn.execute("PRAGMA table_info(student_loan_deductions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {"employee_id", "period_number", "loan_type", "deduction"}
        assert expected.issubset(columns), \
            f"Missing columns: {expected - columns}, found: {columns}"
        conn.close()

    def test_payroll_results_data(self):
        """payroll_results contains correct computation data."""
        conn = self._run_and_get_db()
        cursor = conn.execute(
            "SELECT tax_due, tax_due_to_date, employee_nic, employer_nic, total_nic "
            "FROM payroll_results WHERE employee_id='DB_TEST' AND period_number=1"
        )
        row = cursor.fetchone()
        assert row is not None, "No data for DB_TEST period 1"
        tax_due, tax_td, ee_nic, er_nic, tot_nic = row
        assert_close(tax_due, 558.2, "db tax_due")
        assert_close(ee_nic, 78.66, "db ee_nic")
        assert_close(er_nic, 285.6, "db er_nic")
        conn.close()

    def test_payroll_results_gross_pay(self):
        """payroll_results contains correct gross_pay values."""
        conn = self._run_and_get_db()
        cursor = conn.execute(
            "SELECT gross_pay FROM payroll_results "
            "WHERE employee_id='DB_TEST' ORDER BY period_number"
        )
        rows = cursor.fetchall()
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert_close(rows[0][0], 2000.0, "db gross_pay p1")
        assert_close(rows[1][0], 3000.0, "db gross_pay p2")
        conn.close()

    def test_student_loan_deductions_data(self):
        """student_loan_deductions contains correct deduction data."""
        conn = self._run_and_get_db()
        cursor = conn.execute(
            "SELECT deduction FROM student_loan_deductions "
            "WHERE employee_id='DB_TEST' AND period_number=1 AND loan_type='plan_1'"
        )
        row = cursor.fetchone()
        assert row is not None, "No student loan data for DB_TEST period 1"
        assert_close(row[0], 133.0, "db plan_1 deduction")
        conn.close()

    def test_db_primary_key_constraint(self):
        """payroll_results has proper primary key on (employee_id, period_number)."""
        conn = self._run_and_get_db()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM payroll_results "
            "WHERE employee_id='DB_TEST'"
        )
        count = cursor.fetchone()[0]
        assert count == 2, f"Expected exactly 2 rows for DB_TEST, got {count}"
        conn.close()

    def test_no_student_loans_no_rows(self):
        """Employees without student loans should have no rows in student_loan_deductions."""
        if os.path.exists("/app/payroll.db"):
            os.remove("/app/payroll.db")

        p = [make_period(1, 500.0, "NT", False)]
        emp = make_employee("NO_SL_DB", "weekly", "A", p)
        run_payroll(make_input([emp]))

        conn = sqlite3.connect("/app/payroll.db")
        cursor = conn.execute(
            "SELECT COUNT(*) FROM student_loan_deductions "
            "WHERE employee_id='NO_SL_DB'"
        )
        count = cursor.fetchone()[0]
        assert count == 0, f"Expected 0 student loan rows for NO_SL_DB, got {count}"
        conn.close()

    def test_db_csv_input_mode(self):
        """SQLite output works correctly when using CSV input mode."""
        if os.path.exists("/app/payroll.db"):
            os.remove("/app/payroll.db")

        p = [make_period(1, 2000.0, "1257L", False)]
        emp = make_employee("CSV_DB", "weekly", "A", p, student_loans=["plan_1"])
        run_payroll(make_input([emp]), fmt="csv")

        assert os.path.exists("/app/payroll.db"), "payroll.db not created in csv mode"
        conn = sqlite3.connect("/app/payroll.db")
        cursor = conn.execute(
            "SELECT tax_due FROM payroll_results WHERE employee_id='CSV_DB'"
        )
        row = cursor.fetchone()
        assert row is not None, "No data in db from csv input"
        assert_close(row[0], 558.2, "csv db tax_due")

        cursor = conn.execute(
            "SELECT deduction FROM student_loan_deductions "
            "WHERE employee_id='CSV_DB' AND loan_type='plan_1'"
        )
        row = cursor.fetchone()
        assert row is not None, "No student loan data in db from csv input"
        assert_close(row[0], 133.0, "csv db plan_1")
        conn.close()
