#!/usr/bin/env python3
"""Generate consolidated board report workbook from CSV data."""

import csv
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName


def read_csv(filepath):
    with open(filepath, newline='') as f:
        reader = csv.reader(f)
        headers = next(reader)
        data = [row for row in reader]
    return headers, data


txn_h, txn_data = read_csv('/data/transactions.csv')
prod_h, prod_data = read_csv('/data/products.csv')
emp_h, emp_data = read_csv('/data/employees.csv')
bud_h, bud_data = read_csv('/data/budgets.csv')

wb = Workbook()

# ── Transactions ──────────────────────────────────────────────────────────

ws_txn = wb.active
ws_txn.title = "Transactions"

headers = ['Date', 'ProductID', 'Region', 'Quantity', 'UnitPrice',
           'SalespersonID', 'Revenue', 'Cost', 'Profit', 'Quarter']
for c, h in enumerate(headers, 1):
    ws_txn.cell(row=1, column=c, value=h).font = Font(bold=True)

for i, row in enumerate(txn_data, 2):
    ws_txn.cell(row=i, column=1, value=datetime.strptime(row[0], '%Y-%m-%d'))
    ws_txn.cell(row=i, column=2, value=row[1])
    ws_txn.cell(row=i, column=3, value=row[2])
    ws_txn.cell(row=i, column=4, value=int(row[3]))
    ws_txn.cell(row=i, column=5, value=float(row[4]))
    ws_txn.cell(row=i, column=6, value=row[5])
    ws_txn.cell(row=i, column=7, value=f'=D{i}+E{i}')
    ws_txn.cell(row=i, column=8, value=f'=D{i}*VLOOKUP(B{i},Products!A:D,4,FALSE)')
    ws_txn.cell(row=i, column=9, value=f'=G{i}-H{i}')
    ws_txn.cell(row=i, column=10, value=f'=MONTH(A{i})')

# ── Products ──────────────────────────────────────────────────────────────

ws_prod = wb.create_sheet("Products")

prod_headers = ['ProductID', 'Name', 'Category', 'Cost', 'ListPrice',
                'TotalUnitsSold', 'TotalRevenue', 'TransactionCount',
                'AvgOrderSize', 'ProfitabilityTier']
for c, h in enumerate(prod_headers, 1):
    ws_prod.cell(row=1, column=c, value=h).font = Font(bold=True)

for i, row in enumerate(prod_data, 2):
    ws_prod.cell(row=i, column=1, value=row[0])
    ws_prod.cell(row=i, column=2, value=row[1])
    ws_prod.cell(row=i, column=3, value=row[2])
    ws_prod.cell(row=i, column=4, value=float(row[3]))
    ws_prod.cell(row=i, column=5, value=float(row[4]))
    ws_prod.cell(row=i, column=6, value=f'=SUMIF(Transactions!B:B,A{i},Transactions!D:D)')
    ws_prod.cell(row=i, column=7, value=f'=SUMIF(Transactions!B:B,A{i},Transactions!G:G)')
    ws_prod.cell(row=i, column=8, value=f'=COUNTIF(Transactions!B:B,A{i})')
    ws_prod.cell(row=i, column=9, value=f'=IF(H{i}>0,G{i}/H{i},0)')
    ws_prod.cell(row=i, column=10,
                 value=f'=IFS((E{i}-D{i})/E{i}>0.4,"High",(E{i}-D{i})/E{i}>0.2,"Medium",TRUE,"Low")')

# ── Employees ─────────────────────────────────────────────────────────────

ws_emp = wb.create_sheet("Employees")

emp_headers = ['EmployeeID', 'Name', 'Department', 'Region', 'HireDate',
               'Salary', 'TenureYears', 'SalaryBand', 'AnnualBonus']
for c, h in enumerate(emp_headers, 1):
    ws_emp.cell(row=1, column=c, value=h).font = Font(bold=True)

for i, row in enumerate(emp_data, 2):
    ws_emp.cell(row=i, column=1, value=row[0])
    ws_emp.cell(row=i, column=2, value=row[1])
    ws_emp.cell(row=i, column=3, value=row[2])
    ws_emp.cell(row=i, column=4, value=row[3])
    ws_emp.cell(row=i, column=5, value=datetime.strptime(row[4], '%Y-%m-%d'))
    ws_emp.cell(row=i, column=6, value=float(row[5]))
    ws_emp.cell(row=i, column=7, value=f'=(TODAY()-E{i})/365.25')
    ws_emp.cell(row=i, column=8,
                value=f'=IFS(F{i}>=100000,"Executive",F{i}>=75000,"Senior",F{i}>=50000,"Mid",TRUE,"Junior")')
    ws_emp.cell(row=i, column=9, value=f'=F{i}*0.05')

# ── RegionalSummary ───────────────────────────────────────────────────────

ws_reg = wb.create_sheet("RegionalSummary")

ws_reg.cell(row=1, column=1, value="Region").font = Font(bold=True)
for q in range(1, 5):
    ws_reg.cell(row=1, column=q + 1, value=q).font = Font(bold=True)
ws_reg.cell(row=1, column=6, value="Total").font = Font(bold=True)

regions = ["North", "South", "East", "West", "Central"]
for i, region in enumerate(regions, 2):
    ws_reg.cell(row=i, column=1, value=region)
    for q in range(1, 5):
        col = q + 1
        cl = get_column_letter(col)
        ws_reg.cell(row=i, column=col,
                    value=f'=SUMIFS(Transactions!G:G,Transactions!C:C,$A{i},Transactions!K:K,{cl}$1)')
    ws_reg.cell(row=i, column=6, value=f'=SUM(B{i}:E{i})')

# ── FinancialModel ────────────────────────────────────────────────────────

ws_fin = wb.create_sheet("FinancialModel")

ws_fin.cell(row=1, column=1, value="Parameter").font = Font(bold=True)
ws_fin.cell(row=1, column=2, value="Value").font = Font(bold=True)

params = [
    ("Initial Investment", 500000),
    ("Discount Rate", 0.08),
    ("Loan Amount", 300000),
    ("Annual Interest Rate", 0.06),
    ("Loan Term Years", 10),
]
for idx, (name, val) in enumerate(params, 2):
    ws_fin.cell(row=idx, column=1, value=name)
    ws_fin.cell(row=idx, column=2, value=val)

ws_fin.cell(row=8, column=1, value="Year").font = Font(bold=True)
ws_fin.cell(row=8, column=2, value="Cash Flow").font = Font(bold=True)

ws_fin.cell(row=9, column=1, value=0)
ws_fin.cell(row=9, column=2, value='=-B2')

cash_flows = [120000, 135000, 150000, 140000, 160000]
for idx, cf in enumerate(cash_flows):
    ws_fin.cell(row=10 + idx, column=1, value=idx + 1)
    ws_fin.cell(row=10 + idx, column=2, value=cf)

ws_fin.cell(row=16, column=1, value="Metric").font = Font(bold=True)
ws_fin.cell(row=16, column=2, value="Result").font = Font(bold=True)

ws_fin.cell(row=17, column=1, value="NPV")
ws_fin.cell(row=17, column=2, value='=NPV(B3,B10:B14)+B9')

ws_fin.cell(row=18, column=1, value="IRR")
ws_fin.cell(row=18, column=2, value=0)

ws_fin.cell(row=19, column=1, value="Monthly Payment")
ws_fin.cell(row=19, column=2, value='=PMT(B5/12,B6*12,-B4)')

ws_fin.cell(row=20, column=1, value="Total Loan Cost")
ws_fin.cell(row=20, column=2, value='=B19*B6*12')

ws_fin.cell(row=21, column=1, value="Total Interest")
ws_fin.cell(row=21, column=2, value='=B20-B4')

ws_fin.cell(row=22, column=1, value="Future Value 5yr")
ws_fin.cell(row=22, column=2, value=0)

# ── Dashboard ─────────────────────────────────────────────────────────────

ws_dash = wb.create_sheet("Dashboard")

ws_dash.cell(row=1, column=1, value="Dashboard Summary").font = Font(bold=True, size=14)

ws_dash.cell(row=3, column=1, value="Top Product by Revenue")
ws_dash.cell(row=3, column=2, value="Widget Alpha")
ws_dash.cell(row=4, column=1, value="Top Product Revenue")
ws_dash.cell(row=4, column=2, value=50000)
ws_dash.cell(row=5, column=1, value="Lowest Product by Revenue")
ws_dash.cell(row=5, column=2, value="Component X")
ws_dash.cell(row=6, column=1, value="Lowest Product Revenue")
ws_dash.cell(row=6, column=2, value=5000)
ws_dash.cell(row=8, column=1, value="Total Company Revenue")
ws_dash.cell(row=8, column=2, value=500000)
ws_dash.cell(row=9, column=1, value="Total Transactions")
ws_dash.cell(row=9, column=2, value=50)
ws_dash.cell(row=10, column=1, value="Average Transaction Value")
ws_dash.cell(row=10, column=2, value=10000)

# ── Named Ranges ──────────────────────────────────────────────────────────

dn = DefinedName('DiscountRate', attr_text="FinancialModel!$B$3")
wb.defined_names.add(dn)

# ── Save ──────────────────────────────────────────────────────────────────

os.makedirs('/app/output', exist_ok=True)
wb.save('/app/output/consolidated_report.xlsx')
print("Workbook generated successfully")
