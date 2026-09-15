#!/usr/bin/env python3

"""
UK Payroll Deduction Engine for tax year 2026-27.
Implements PAYE income tax (PAYErout v24), NIC (exact percentage method),
and Student Loan deductions per HMRC specifications.
Supports JSON and CSV input, outputs JSON to stdout and SQLite to /app/payroll.db.
"""

import json
import sys
import math
import argparse
import csv
import sqlite3
import os

# ============================================================
# PAYE Parameters for 2026-27
# ============================================================

UK_RATES = [0.10, 0.20, 0.40, 0.45]
UK_CUM_BANDWIDTHS = [0, 37700, 125140]
UK_CUM_TAX = [0, 7540, 42516]
UK_G = 2
UK_M = 0.50

SCOT_RATES = [0.19, 0.20, 0.21, 0.42, 0.45, 0.48]
SCOT_CUM_BANDWIDTHS = [3967, 16956, 31092, 62430, 125140]
SCOT_CUM_TAX = [753.73, 3351.53, 6320.09, 19482.05, 47701.55]
SCOT_G1 = 2
SCOT_M = 0.50

WELSH_RATES = [0.10, 0.20, 0.40, 0.45]
WELSH_CUM_BANDWIDTHS = [0, 37700, 125140]
WELSH_CUM_TAX = [0, 7540, 42516]
WELSH_G2 = 2
WELSH_M = 0.50

# ============================================================
# NIC Parameters for 2026-27
# ============================================================

NI_THRESHOLDS = {
    "weekly": {"ST": 96, "LEL": 129, "PT": 242, "FUST": 481, "UEL": 967},
    "monthly": {"ST": 417, "LEL": 559, "PT": 1048, "FUST": 2083, "UEL": 4189},
}

NI_EE_RATES = {
    "A": {"DE": 0.08, "F": 0.02},
    "M": {"DE": 0.08, "F": 0.02},
    "H": {"DE": 0.08, "F": 0.02},
    "V": {"DE": 0.08, "F": 0.02},
    "J": {"DE": 0.02, "F": 0.02},
    "B": {"DE": 0.0185, "F": 0.02},
    "C": {"DE": 0.0, "F": 0.0},
}

NI_ER_RATES = {
    "A": {"BCD": 0.15, "E": 0.15, "F": 0.15},
    "J": {"BCD": 0.15, "E": 0.15, "F": 0.15},
    "H": {"BCD": 0.0, "E": 0.0, "F": 0.15},
    "M": {"BCD": 0.0, "E": 0.0, "F": 0.15},
    "B": {"BCD": 0.15, "E": 0.15, "F": 0.15},
    "C": {"BCD": 0.15, "E": 0.15, "F": 0.15},
    "V": {"BCD": 0.0, "E": 0.0, "F": 0.15},
}

# ============================================================
# Student Loan Parameters for 2026-27
# ============================================================

SL_PARAMS = {
    "plan_1": {"threshold": 26900, "rate": 0.09},
    "plan_2": {"threshold": 29385, "rate": 0.09},
    "plan_4": {"threshold": 33795, "rate": 0.09},
    "plan_5": {"threshold": 25000, "rate": 0.09},
    "postgraduate": {"threshold": 21000, "rate": 0.06},
}

PERIODS_PER_YEAR = {"weekly": 52, "monthly": 12}


# ============================================================
# NIC Rounding (HMRC specific)
# ============================================================

def nic_round_final(value):
    """HMRC NIC rounding - 3rd decimal: <=5 down, >=6 up."""
    if value < 1e-9:
        return 0.0
    mills = value * 1000
    mills_rounded = round(mills, 4)
    mills_truncated = math.floor(mills_rounded + 1e-8)
    third_digit = mills_truncated % 10
    pence_truncated = mills_truncated // 10
    if third_digit >= 6:
        return round((pence_truncated + 1) / 100.0, 2)
    else:
        return round(pence_truncated / 100.0, 2)


# ============================================================
# PAYE Tax Code Parsing
# ============================================================

def parse_tax_code(code_str):
    code = code_str.strip().upper()
    result = {"regime": "UK", "code_type": None, "numeric": 0, "suffix": None, "d_number": 0}

    if code.startswith("S") and not code.startswith("SBR") and not code.startswith("SD") and not code.startswith("SK"):
        rest = code[1:]
        if rest and rest[0].isdigit():
            result["regime"] = "S"
            code = rest
        elif code.startswith("SK"):
            result["regime"] = "S"
            code = "K" + code[2:]
    elif code.startswith("C") and not code.startswith("CBR") and not code.startswith("CD") and not code.startswith("CK"):
        rest = code[1:]
        if rest and rest[0].isdigit():
            result["regime"] = "C"
            code = rest
        elif code.startswith("CK"):
            result["regime"] = "C"
            code = "K" + code[2:]

    if code_str.strip().upper().startswith("SBR"):
        result["regime"] = "S"
        code = "BR"
    elif code_str.strip().upper().startswith("CBR"):
        result["regime"] = "C"
        code = "BR"
    elif code_str.strip().upper().startswith("SD"):
        result["regime"] = "S"
        code = code_str.strip().upper()[1:]
    elif code_str.strip().upper().startswith("CD"):
        result["regime"] = "C"
        code = code_str.strip().upper()[1:]
    elif code_str.strip().upper().startswith("SK"):
        result["regime"] = "S"
        code = "K" + code_str.strip().upper()[2:]
    elif code_str.strip().upper().startswith("CK"):
        result["regime"] = "C"
        code = "K" + code_str.strip().upper()[2:]

    if code == "BR":
        result["code_type"] = "BR"
        return result
    elif code == "NT":
        result["code_type"] = "NT"
        result["regime"] = "UK"
        return result
    elif code.startswith("D") and len(code) >= 2 and code[1:].isdigit():
        result["code_type"] = "D"
        result["d_number"] = int(code[1:])
        return result
    elif code.startswith("K"):
        result["code_type"] = "K"
        num_str = ""
        suffix = ""
        rest = code[1:]
        for ch in rest:
            if ch.isdigit():
                num_str += ch
            else:
                suffix += ch
        result["numeric"] = int(num_str) if num_str else 0
        result["suffix"] = suffix if suffix else "T"
        return result
    else:
        result["code_type"] = "suffix"
        num_str = ""
        suffix = ""
        for ch in code:
            if ch.isdigit():
                num_str += ch
            else:
                suffix += ch
        result["numeric"] = int(num_str) if num_str else 0
        result["suffix"] = suffix if suffix else "T"
        return result


def compute_free_pay_week1(numeric_part, periods_per_year):
    if numeric_part == 0:
        return 0.0
    ppy = periods_per_year
    if numeric_part <= 500:
        annual = numeric_part * 10 + 9
        raw = annual / ppy
        return math.ceil(round(raw, 4) * 100) / 100
    else:
        adjusted = numeric_part - 1
        quotient = adjusted // 500
        remainder = (adjusted % 500) + 1
        annual_rem = remainder * 10 + 9
        raw_rem = annual_rem / ppy
        fp_remainder = math.ceil(round(raw_rem, 4) * 100) / 100
        if ppy == 52:
            fp_balance = quotient * 96.16
        elif ppy == 12:
            fp_balance = quotient * 416.67
        else:
            base = 500 * 10 / ppy
            fp_balance = quotient * math.ceil(round(base, 4) * 100) / 100
        return round(fp_remainder + fp_balance, 2)


def get_regime_params(regime):
    if regime == "S":
        return SCOT_RATES, SCOT_CUM_BANDWIDTHS, SCOT_CUM_TAX, SCOT_G1, SCOT_M
    elif regime == "C":
        return WELSH_RATES, WELSH_CUM_BANDWIDTHS, WELSH_CUM_TAX, WELSH_G2, WELSH_M
    else:
        return UK_RATES, UK_CUM_BANDWIDTHS, UK_CUM_TAX, UK_G, UK_M


def compute_tax_on_taxable_pay(taxable_pay_rounded, regime, n, periods_per_year):
    rates, cum_bw, cum_tax, g_ptr, maxrate = get_regime_params(regime)
    Tn = taxable_pay_rounded

    if Tn <= 0:
        return 0.0

    num_bands = len(cum_bw)
    cvalues = []
    thresholds = []
    threshold_taxes = []

    for i in range(num_bands):
        raw_threshold = cum_bw[i] * n / periods_per_year
        threshold_4dp = math.floor(raw_threshold * 10000 + 1e-8) / 10000
        thresholds.append(threshold_4dp)
        if raw_threshold == 0:
            cvalues.append(0)
        else:
            cvalues.append(math.ceil(raw_threshold - 1e-9))
        raw_ttax = cum_tax[i] * n / periods_per_year
        ttax_4dp = math.floor(raw_ttax * 10000 + 1e-8) / 10000
        threshold_taxes.append(ttax_4dp)

    formula_idx = num_bands
    for i in range(num_bands):
        if Tn <= cvalues[i]:
            formula_idx = i
            break

    if formula_idx == 0:
        Ln = Tn * rates[0]
    else:
        prev_idx = formula_idx - 1
        k_prev = threshold_taxes[prev_idx]
        c_prev = thresholds[prev_idx]
        rate = rates[formula_idx]
        Ln = k_prev + (Tn - c_prev) * rate

    Ln_4dp = math.floor(round(Ln, 8) * 10000) / 10000
    Ln_final = math.floor(Ln_4dp * 100 + 1e-9) / 100

    return Ln_final


def process_paye(employee, periods_per_year):
    cum_pay = 0.0
    tax_to_date = 0.0
    results = []

    for period in employee["periods"]:
        n = period["period_number"]
        gross = period["gross_pay"]
        code_str = period["tax_code"]
        w1m1 = period.get("w1m1", False)

        parsed = parse_tax_code(code_str)
        regime = parsed["regime"]
        code_type = parsed["code_type"]
        _, _, _, g_ptr, maxrate = get_regime_params(regime)

        if code_type == "NT":
            cum_pay += gross
            if not w1m1:
                Ln = 0.0
                tax_due = Ln - tax_to_date
                tax_to_date = Ln
            else:
                tax_due = 0.0
            results.append((round(tax_due, 2), round(tax_to_date, 2)))
            continue

        if code_type == "BR":
            rates, _, _, g_ptr, _ = get_regime_params(regime)
            rate = rates[g_ptr - 1]
            if w1m1:
                Tn = math.floor(gross + 1e-9)
                Ln = math.floor(round(Tn * rate, 8) * 100 + 1e-9) / 100
                tax_due = Ln
                results.append((round(tax_due, 2), round(tax_due, 2)))
            else:
                cum_pay += gross
                Tn = math.floor(cum_pay + 1e-9)
                Ln = math.floor(round(Tn * rate, 8) * 100 + 1e-9) / 100
                tax_due = round(Ln - tax_to_date, 2)
                tax_to_date = Ln
                results.append((round(tax_due, 2), round(tax_to_date, 2)))
            continue

        if code_type == "D":
            rates, _, _, g_ptr, _ = get_regime_params(regime)
            rate_idx = g_ptr + 1 + parsed["d_number"]
            rate = rates[rate_idx - 1]
            if w1m1:
                Tn = math.floor(gross + 1e-9)
                Ln = math.floor(round(Tn * rate, 8) * 100 + 1e-9) / 100
                tax_due = Ln
                results.append((round(tax_due, 2), round(tax_due, 2)))
            else:
                cum_pay += gross
                Tn = math.floor(cum_pay + 1e-9)
                Ln = math.floor(round(Tn * rate, 8) * 100 + 1e-9) / 100
                tax_due = round(Ln - tax_to_date, 2)
                tax_to_date = Ln
                results.append((round(tax_due, 2), round(tax_to_date, 2)))
            continue

        numeric = parsed["numeric"]
        is_k_code = (code_type == "K")
        fp1 = compute_free_pay_week1(numeric, periods_per_year)

        if w1m1:
            if is_k_code:
                Un = gross + fp1
            else:
                Un = gross - fp1
            if not is_k_code and Un <= 0:
                Ln = 0.0
            else:
                Tn = math.floor(Un + 1e-9) if Un > 0 else 0
                Ln = compute_tax_on_taxable_pay(Tn, regime, 1, periods_per_year)
            if Ln > 0 and gross > 0:
                max_tax = math.floor(round(maxrate * gross, 8) * 10000) / 10000
                max_tax = math.floor(max_tax * 100 + 1e-9) / 100
                if Ln > max_tax:
                    Ln = max_tax
            tax_due = round(Ln, 2)
            results.append((tax_due, tax_due))
        else:
            cum_pay += gross
            free_pay_n = round(n * fp1, 2)
            if is_k_code:
                Un = cum_pay + free_pay_n
            else:
                Un = cum_pay - free_pay_n
            if not is_k_code and Un <= 0:
                Ln = 0.0
            else:
                Tn = math.floor(Un + 1e-9) if Un > 0 else 0
                Ln = compute_tax_on_taxable_pay(Tn, regime, n, periods_per_year)
            tax_due_raw = Ln - tax_to_date
            if tax_due_raw > 0 and gross > 0:
                max_tax = math.floor(round(maxrate * gross, 8) * 10000) / 10000
                max_tax = math.floor(max_tax * 100 + 1e-9) / 100
                if tax_due_raw > max_tax:
                    tax_due_raw = max_tax
                    Ln = tax_to_date + max_tax
            tax_due = round(tax_due_raw, 2)
            tax_to_date = round(Ln, 2)
            results.append((tax_due, tax_to_date))

    return results


def process_nic(gross_pay, ni_category, pay_frequency):
    thresholds = NI_THRESHOLDS.get(pay_frequency)
    if not thresholds:
        return (0.0, 0.0, 0.0)

    ST = thresholds["ST"]
    GP = gross_pay

    if GP <= ST:
        return (0.0, 0.0, 0.0)

    LEL = thresholds["LEL"]
    PT = thresholds["PT"]
    FUST = thresholds["FUST"]
    UEL = thresholds["UEL"]

    earnings_st_to_lel = max(0, min(GP, LEL) - ST)
    earnings_lel_to_pt = max(0, min(GP, PT) - LEL)
    earnings_pt_to_fust = max(0, min(GP, FUST) - PT)
    earnings_fust_to_uel = max(0, min(GP, UEL) - FUST)
    earnings_above_uel = max(0, GP - UEL)

    ee_rates = NI_EE_RATES.get(ni_category, NI_EE_RATES["A"])
    er_rates = NI_ER_RATES.get(ni_category, NI_ER_RATES["A"])

    ee_de_earnings = earnings_pt_to_fust + earnings_fust_to_uel
    ee_de_amount = ee_de_earnings * ee_rates["DE"]
    ee_de_rounded = nic_round_final(ee_de_amount)
    ee_f_amount = earnings_above_uel * ee_rates["F"]
    ee_f_rounded = nic_round_final(ee_f_amount)
    employee_nic = round(ee_de_rounded + ee_f_rounded, 2)

    er_bcd_earnings = earnings_st_to_lel + earnings_lel_to_pt + earnings_pt_to_fust
    a = er_bcd_earnings * er_rates["BCD"]
    b = earnings_fust_to_uel * er_rates["E"]
    ab = a + b
    ab_rounded = nic_round_final(ab)
    er_f_amount = earnings_above_uel * er_rates["F"]
    er_f_rounded = nic_round_final(er_f_amount)
    employer_nic = round(ab_rounded + er_f_rounded, 2)

    total_nic = round(employee_nic + employer_nic, 2)
    return (employee_nic, employer_nic, total_nic)


def process_student_loans(gross_pay, loan_types, pay_frequency):
    ppy = PERIODS_PER_YEAR[pay_frequency]
    results = {}
    for loan_type in loan_types:
        params = SL_PARAMS.get(loan_type)
        if not params:
            continue
        periodic_threshold = math.floor(params["threshold"] / ppy * 100) / 100
        if gross_pay > periodic_threshold:
            excess = gross_pay - periodic_threshold
            deduction = excess * params["rate"]
            deduction = math.floor(deduction + 1e-9)
            results[loan_type] = float(deduction)
        else:
            results[loan_type] = 0.0
    return results


def process_employee(employee):
    pay_freq = employee["pay_frequency"]
    ppy = PERIODS_PER_YEAR[pay_freq]
    ni_cat = employee["ni_category"]
    student_loans = employee.get("student_loans", [])

    paye_results = process_paye(employee, ppy)

    results = []
    for i, period in enumerate(employee["periods"]):
        tax_due, tax_td = paye_results[i]
        ee_nic, er_nic, tot_nic = process_nic(period["gross_pay"], ni_cat, pay_freq)
        sl_results = process_student_loans(period["gross_pay"], student_loans, pay_freq)

        result = {
            "period_number": period["period_number"],
            "gross_pay": period["gross_pay"],
            "paye": {
                "tax_due": tax_due,
                "tax_due_to_date": tax_td,
            },
            "nic": {
                "employee_nic": ee_nic,
                "employer_nic": er_nic,
                "total_nic": tot_nic,
            },
        }
        if student_loans:
            result["student_loans"] = sl_results
        results.append(result)

    return results


# ============================================================
# CSV Input Parsing
# ============================================================

def parse_csv_input(csv_path):
    """Parse CSV input into employee list format."""
    employees = {}
    employee_order = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            eid = row['employee_id']
            if eid not in employees:
                employees[eid] = {
                    'id': eid,
                    'pay_frequency': row['pay_frequency'],
                    'ni_category': row['ni_category'],
                    'student_loans': [],
                    'periods': []
                }
                sl = row.get('student_loans', '').strip()
                if sl:
                    employees[eid]['student_loans'] = sl.split('|')
                employee_order.append(eid)

            employees[eid]['periods'].append({
                'period_number': int(row['period_number']),
                'gross_pay': float(row['gross_pay']),
                'tax_code': row['tax_code'],
                'w1m1': row.get('w1m1', 'false').lower() == 'true'
            })

    # Sort periods within each employee and return in input order
    result = []
    for eid in employee_order:
        emp = employees[eid]
        emp['periods'].sort(key=lambda p: p['period_number'])
        result.append(emp)
    return result


# ============================================================
# SQLite Output
# ============================================================

def write_sqlite(output, input_data, db_path='/app/payroll.db'):
    """Write payroll results to SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('DROP TABLE IF EXISTS student_loan_deductions')
    c.execute('DROP TABLE IF EXISTS payroll_results')

    c.execute('''CREATE TABLE payroll_results (
        employee_id TEXT NOT NULL,
        period_number INTEGER NOT NULL,
        gross_pay REAL NOT NULL,
        tax_due REAL NOT NULL,
        tax_due_to_date REAL NOT NULL,
        employee_nic REAL NOT NULL,
        employer_nic REAL NOT NULL,
        total_nic REAL NOT NULL,
        PRIMARY KEY (employee_id, period_number)
    )''')

    c.execute('''CREATE TABLE student_loan_deductions (
        employee_id TEXT NOT NULL,
        period_number INTEGER NOT NULL,
        loan_type TEXT NOT NULL,
        deduction REAL NOT NULL,
        PRIMARY KEY (employee_id, period_number, loan_type)
    )''')

    for emp in output['employees']:
        for r in emp['results']:
            c.execute(
                'INSERT INTO payroll_results VALUES (?,?,?,?,?,?,?,?)',
                (emp['id'], r['period_number'], r['gross_pay'],
                 r['paye']['tax_due'], r['paye']['tax_due_to_date'],
                 r['nic']['employee_nic'], r['nic']['employer_nic'],
                 r['nic']['total_nic']))

            if 'student_loans' in r:
                for lt, ded in r['student_loans'].items():
                    c.execute(
                        'INSERT INTO student_loan_deductions VALUES (?,?,?,?)',
                        (emp['id'], r['period_number'], lt, ded))

    conn.commit()
    conn.close()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='UK Payroll Deduction Engine 2026-27')
    parser.add_argument('--format', choices=['json', 'csv'], default='json',
                        help='Input format: json or csv')
    parser.add_argument('input_file', help='Path to input file')
    args = parser.parse_args()

    if args.format == 'csv':
        employees = parse_csv_input(args.input_file)
    else:
        with open(args.input_file) as f:
            data = json.load(f)
        employees = data['employees']

    output = {"employees": []}
    for emp in employees:
        emp_results = process_employee(emp)
        output["employees"].append({
            "id": emp["id"],
            "results": emp_results,
        })

    # JSON to stdout
    print(json.dumps(output, indent=2))

    # SQLite output
    write_sqlite(output, employees)


if __name__ == "__main__":
    main()
