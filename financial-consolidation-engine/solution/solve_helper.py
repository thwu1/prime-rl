#!/usr/bin/env python3
"""
Solution: Financial Consolidation Engine for Nexus Global Holdings.
"""

import sys
from openpyxl import Workbook, load_workbook


def compute_pmt(pv, rate_monthly, nper):
    if rate_monthly == 0:
        return pv / nper
    return pv * rate_monthly / (1 - (1 + rate_monthly) ** (-nper))


def compute_remaining_balance(pv, rate_monthly, pmt, k):
    if rate_monthly == 0:
        return pv - pmt * k
    return (pv * (1 + rate_monthly) ** k
            - pmt * ((1 + rate_monthly) ** k - 1) / rate_monthly)


def find_sheet(wb, name):
    """Find a sheet by name, case-insensitive with fallbacks."""
    if name in wb.sheetnames:
        return wb[name]
    lower = name.lower()
    for sn in wb.sheetnames:
        if sn.lower() == lower:
            return wb[sn]
    print(f"ERROR: Sheet '{name}' not found. Available: {wb.sheetnames}", file=sys.stderr)
    sys.exit(1)


def main():
    src_path = "/app/group_financials.xlsx"
    src = load_workbook(src_path, data_only=True)
    print(f"Source workbook sheets: {src.sheetnames}")

    # ---- Parse exchange rates ----
    fx = {}
    ws = find_sheet(src, "ExchangeRates")
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and row[1] is not None:
            fx[str(row[0])] = float(row[1])

    # ---- Parse ownership stakes ----
    ownership = {}
    ws = find_sheet(src, "Ownership")
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            ownership[str(row[0])] = float(row[1])

    # ---- Parse and convert subsidiary financials ----
    revenue_by_cat = {}
    expense_by_cat = {}
    sub_ni = {}

    for name in ["SubA", "SubB", "SubC", "SubD"]:
        ws = find_sheet(src, name)
        s_rev = 0
        s_exp = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row[0]:
                continue
            type_ = str(row[0])
            cat = str(row[1])
            amt = float(row[2])
            cur = str(row[3])
            usd = amt * fx[cur]
            if type_ == "Revenue":
                revenue_by_cat[cat] = revenue_by_cat.get(cat, 0) + usd
                s_rev += usd
            else:
                expense_by_cat[cat] = expense_by_cat.get(cat, 0) + usd
                s_exp += usd
        sub_ni[name] = s_rev - s_exp

    total_gross_rev = sum(revenue_by_cat.values())
    total_gross_exp = sum(expense_by_cat.values())

    # ---- Parse intercompany transactions ----
    ic_rev_elim = {}
    ic_exp_elim = {}
    total_ic = 0.0
    ws = find_sheet(src, "Intercompany")
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        amt_usd = float(row[2]) * fx[str(row[3])]
        rev_cat = str(row[4])
        exp_cat = str(row[5])
        ic_rev_elim[rev_cat] = ic_rev_elim.get(rev_cat, 0) + amt_usd
        ic_exp_elim[exp_cat] = ic_exp_elim.get(exp_cat, 0) + amt_usd
        total_ic += amt_usd

    net_rev = total_gross_rev - total_ic
    net_exp = total_gross_exp - total_ic
    net_income = net_rev - net_exp

    # ---- NCI calculation ----
    total_nci = sum(sub_ni[n] * (1 - ownership[n])
                    for n in sub_ni if ownership[n] < 1.0)
    parent_ni = net_income - total_nci

    # ---- Build output workbook ----
    out = Workbook()

    # ==== ConsolidatedPL ====
    ws = out.active
    ws.title = "ConsolidatedPL"
    ws.append(["Category", "Gross_USD", "IC_Elimination", "Net_USD"])

    rev_cats = sorted(revenue_by_cat.keys())
    for cat in rev_cats:
        gross = revenue_by_cat[cat]
        elim = ic_rev_elim.get(cat, 0)
        ws.append([cat, gross, -elim, gross - elim])
    ws.append(["Total Revenue", total_gross_rev, -total_ic, net_rev])
    ws.append([])

    exp_cats = sorted(expense_by_cat.keys())
    for cat in exp_cats:
        gross = expense_by_cat[cat]
        elim = ic_exp_elim.get(cat, 0)
        ws.append([cat, gross, -elim, gross - elim])
    ws.append(["Total Expenses", total_gross_exp, -total_ic, net_exp])
    ws.append([])

    gross_ni = total_gross_rev - total_gross_exp
    ws.append(["Net Income", gross_ni, 0, net_income])
    ws.append(["Non-Controlling Interest", "", "", total_nci])
    ws.append(["Net Income Attributable to Parent", "", "", parent_ni])

    # ==== Amortization ====
    ws = out.create_sheet("Amortization")
    ws.append(["Loan_ID", "Principal", "Annual_Rate", "Term_Months",
               "Payments_Made", "Monthly_Payment", "Remaining_Balance",
               "Interest_Paid", "Principal_Paid", "Remaining_Interest"])

    loans_ws = find_sheet(src, "Loans")
    for row in loans_ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        lid = str(row[0])
        pv = float(row[1])
        annual_rate = float(row[2])
        term = int(row[3])
        paid = int(row[4])
        r = annual_rate / 12
        pmt = compute_pmt(pv, r, term)
        remaining = compute_remaining_balance(pv, r, pmt, paid)
        principal_paid = pv - remaining
        interest_paid = pmt * paid - principal_paid
        remaining_interest = pmt * (term - paid) - remaining
        ws.append([lid, pv, annual_rate, term, paid,
                   pmt, remaining, interest_paid, principal_paid,
                   remaining_interest])

    # ==== Ratios ====
    ws = out.create_sheet("Ratios")
    ws.append(["Ratio", "Value"])

    net_cogs = expense_by_cat.get("COGS", 0) - ic_exp_elim.get("COGS", 0)
    gross_margin = (net_rev - net_cogs) / net_rev
    operating_margin = net_income / net_rev
    ic_pct = total_ic / total_gross_rev
    expense_ratio = net_exp / net_rev
    cogs_ratio = net_cogs / net_rev

    ws.append(["Gross Margin", gross_margin])
    ws.append(["Operating Margin", operating_margin])
    ws.append(["IC Revenue Pct", ic_pct])
    ws.append(["Expense Ratio", expense_ratio])
    ws.append(["COGS Ratio", cogs_ratio])

    # ==== BreakEven ====
    ws = out.create_sheet("BreakEven")
    ws.append(["Metric", "Value"])

    fixed_costs = sum(expense_by_cat.get(c, 0)
                      for c in ["Salaries", "R&D", "Depreciation"])
    variable_costs = net_cogs + expense_by_cat.get("Marketing", 0)
    var_cost_ratio = variable_costs / net_rev
    contribution_margin = 1 - var_cost_ratio
    breakeven_rev = fixed_costs / contribution_margin

    ws.append(["Fixed Costs", fixed_costs])
    ws.append(["Variable Costs", variable_costs])
    ws.append(["Variable Cost Ratio", var_cost_ratio])
    ws.append(["Contribution Margin Ratio", contribution_margin])
    ws.append(["Break-Even Revenue", breakeven_rev])

    # ==== Sensitivity ====
    ws = out.create_sheet("Sensitivity")
    ws.append(["Scenario", "FX_Factor", "Net_Income"])

    for label, factor in [("-20%", 0.8), ("-10%", 0.9), ("Base", 1.0),
                          ("+10%", 1.1), ("+20%", 1.2)]:
        adj_fx = {cur: (rate if cur == "USD" else rate * factor)
                  for cur, rate in fx.items()}
        adj_rev = 0
        adj_exp = 0
        for sname in ["SubA", "SubB", "SubC", "SubD"]:
            sub_ws = find_sheet(src, sname)
            for row in sub_ws.iter_rows(min_row=2, values_only=True):
                if not row[0]:
                    continue
                amt_usd = float(row[2]) * adj_fx[str(row[3])]
                if str(row[0]) == "Revenue":
                    adj_rev += amt_usd
                else:
                    adj_exp += amt_usd
        adj_ni = adj_rev - adj_exp
        ws.append([label, factor, adj_ni])

    out.save("/app/consolidated.xlsx")
    print("Output saved to /app/consolidated.xlsx")


if __name__ == "__main__":
    main()
