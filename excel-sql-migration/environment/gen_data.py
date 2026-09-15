#!/usr/bin/env python3
"""Generate deterministic financial dataset for the workbook formula audit task."""
import csv
import random
import os
from datetime import date, timedelta

random.seed(42)
os.makedirs('/app/data', exist_ok=True)

# === Products (20 items, 4 categories) ===
products_header = ['product_id', 'product_name', 'category', 'subcategory',
                   'cost_price', 'list_price', 'reorder_level', 'units_in_stock']
products_data = [
    ['P001', 'Laptop Pro 15',       'Electronics',     'Computers',      800.00, 1299.99, 10,  45],
    ['P002', 'Wireless Mouse',      'Electronics',     'Peripherals',     12.00,   29.99, 50, 200],
    ['P003', 'USB-C Hub',           'Electronics',     'Peripherals',     25.00,   59.99, 30, 120],
    ['P004', '4K Monitor',          'Electronics',     'Displays',       350.00,  699.99,  8,  30],
    ['P005', 'Mechanical Keyboard', 'Electronics',     'Peripherals',     45.00,  109.99, 20,  85],
    ['P006', 'Copy Paper A4',       'Office Supplies', 'Paper',            2.50,    8.99,100, 500],
    ['P007', 'Ink Cartridge Black', 'Office Supplies', 'Printing',        15.00,   34.99, 40, 180],
    ['P008', 'Sticky Notes',        'Office Supplies', 'Stationery',       1.00,    4.99,200, 800],
    ['P009', 'Binder Clips Asst',   'Office Supplies', 'Stationery',       3.00,    7.99,100, 350],
    ['P010', 'Whiteboard Markers',  'Office Supplies', 'Stationery',       5.00,   12.99, 60, 220],
    ['P011', 'Executive Desk',      'Furniture',       'Desks',          250.00,  599.99,  3,  12],
    ['P012', 'Ergonomic Chair',     'Furniture',       'Chairs',         180.00,  449.99,  5,  25],
    ['P013', 'Filing Cabinet',      'Furniture',       'Storage',        120.00,  279.99,  4,  18],
    ['P014', 'Bookshelf Unit',      'Furniture',       'Storage',         90.00,  199.99,  6,  22],
    ['P015', 'Conference Table',    'Furniture',       'Tables',         400.00,  899.99,  2,   8],
    ['P016', 'Office Suite Pro',    'Software',        'Productivity',    50.00,  149.99,  0, 999],
    ['P017', 'Antivirus Premium',   'Software',        'Security',        20.00,   59.99,  0, 999],
    ['P018', 'Project Manager',     'Software',        'Productivity',    75.00,  199.99,  0, 999],
    ['P019', 'Design Studio',       'Software',        'Creative',       100.00,  299.99,  0, 999],
    ['P020', 'Database Server',     'Software',        'Infrastructure', 200.00,  499.99,  0, 999],
]

# === Employees (10, various departments/hire dates/commission rates) ===
employees_header = ['employee_id', 'first_name', 'last_name', 'department',
                    'hire_date', 'base_salary', 'commission_rate', 'manager_id']
employees_data = [
    ['E001', 'James',    'Wilson',   'Sales',      '2020-03-15', 65000, 0.05,  'E010'],
    ['E002', 'Sarah',    'Chen',     'Sales',      '2021-07-01', 58000, 0.04,  'E010'],
    ['E003', 'Michael',  'Brown',    'Sales',      '2019-01-10', 72000, 0.06,  'E010'],
    ['E004', 'Emily',    'Davis',    'Sales',      '2022-06-20', 52000, 0.035, 'E010'],
    ['E005', 'Robert',   'Martinez', 'Sales',      '2023-02-14', 48000, 0.03,  'E010'],
    ['E006', 'Lisa',     'Anderson', 'Marketing',  '2020-11-01', 62000, 0.02,  'E010'],
    ['E007', 'David',    'Taylor',   'Marketing',  '2021-09-15', 55000, 0.02,  'E010'],
    ['E008', 'Jennifer', 'Thomas',   'Support',    '2018-05-20', 60000, 0.01,  'E010'],
    ['E009', 'William',  'Jackson',  'Support',    '2022-03-01', 50000, 0.01,  'E010'],
    ['E010', 'Patricia', 'White',    'Management', '2017-01-05', 95000, 0.08,  ''],
]

with open('/app/data/employees.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(employees_header)
    w.writerows(employees_data)

# === Regions (6) ===
regions_header = ['region_id', 'region_name', 'country', 'sales_target', 'tax_rate']
regions_data = [
    ['R001', 'Northeast',      'United States',  500000, 0.08],
    ['R002', 'Southeast',      'United States',  400000, 0.07],
    ['R003', 'West Coast',     'United States',  600000, 0.095],
    ['R004', 'Central Europe', 'Germany',        450000, 0.19],
    ['R005', 'United Kingdom', 'United Kingdom', 350000, 0.20],
    ['R006', 'Asia Pacific',   'Japan',          300000, 0.10],
]

with open('/app/data/regions.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(regions_header)
    w.writerows(regions_data)

# === Transactions (500, spanning Jan 2023 - Dec 2024) ===
transactions_header = ['transaction_id', 'date', 'employee_id', 'product_id',
                       'region_id', 'quantity', 'unit_price', 'discount_pct']

start_date = date(2023, 1, 1)
end_date = date(2024, 12, 31)
date_range = (end_date - start_date).days

product_prices = {p[0]: p[5] for p in products_data}
employee_ids = [e[0] for e in employees_data]
product_ids = [p[0] for p in products_data]
region_ids = [r[0] for r in regions_data]
discount_options = [0.0, 0.0, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25]

transactions = []
for i in range(1, 501):
    tid = 'T{:04d}'.format(i)
    d = start_date + timedelta(days=random.randint(0, date_range))
    emp = random.choice(employee_ids)
    prod = random.choice(product_ids)
    reg = random.choice(region_ids)
    qty = random.randint(1, 20)
    unit_price = product_prices[prod]
    discount = random.choice(discount_options)
    transactions.append([tid, d.isoformat(), emp, prod, reg, qty,
                         unit_price, discount])

# === Post-processing: adjust product stocks for boundary condition testing ===
product_sold = {}
for t in transactions:
    pid = t[3]
    qty = t[5]
    product_sold[pid] = product_sold.get(pid, 0) + qty

# P005 (index 4, reorder_level=20): set stock so remaining == reorder_level
# Ensures the <= vs < boundary in needs_reorder is testable
idx_p005 = 4
reorder_p005 = products_data[idx_p005][6]
sold_p005 = product_sold.get(products_data[idx_p005][0], 0)
products_data[idx_p005][7] = sold_p005 + reorder_p005

# P002 (index 1, reorder_level=50): set stock so remaining == 2 * reorder_level
# Ensures the *2 vs *3 boundary in stock_status is testable
idx_p002 = 1
reorder_p002 = products_data[idx_p002][6]
sold_p002 = product_sold.get(products_data[idx_p002][0], 0)
products_data[idx_p002][7] = sold_p002 + 2 * reorder_p002

# Write products CSV (after stock adjustments)
with open('/app/data/products.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(products_header)
    w.writerows(products_data)

# Write transactions CSV
with open('/app/data/transactions.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(transactions_header)
    w.writerows(transactions)

print('Generated {} transactions, {} products, {} employees, {} regions'.format(
    len(transactions), len(products_data), len(employees_data), len(regions_data)))
