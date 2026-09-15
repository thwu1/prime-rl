#!/usr/bin/env python3
"""Generate raw transaction-level data for CLV task.

Population parameters below are NOT the MLE answers -- fitted parameters
will differ from population parameters due to sampling variability.
"""

import random
import csv
import json
import os
from datetime import datetime, timedelta

random.seed(42)

# Population parameters for data generation
r, alpha = 0.243, 4.414
a, b = 0.793, 2.426
p_gg, q_gg, v_gg = 6.25, 3.74, 15.44

n_customers = 800
base_date = datetime(2023, 1, 1)
obs_end = datetime(2024, 6, 30)

transactions = []
txn_id = 1

for cust_id in range(1, n_customers + 1):
    # Random first appearance in first ~400 days of the window
    first_day = random.randint(0, 400)
    first_date = base_date + timedelta(days=first_day)

    T_weeks = (obs_end - first_date).days / 7.0
    if T_weeks < 2:
        continue

    # BG/NBD: customer-level purchase rate and churn probability
    lam = random.gammavariate(r, 1.0 / alpha)
    p_drop = random.betavariate(a, b)

    # Gamma-Gamma: customer-level spending rate
    nu = random.gammavariate(q_gg, 1.0 / v_gg)
    if nu < 1e-15:
        nu = 1e-15

    # First purchase (birth event)
    amount = max(0.01, random.gammavariate(p_gg, 1.0 / nu))
    transactions.append({
        'transaction_id': txn_id,
        'customer_id': cust_id,
        'date': first_date.strftime('%Y-%m-%d'),
        'amount': round(amount, 2),
    })
    txn_id += 1

    # Subsequent purchases (repeat events)
    t_weeks = 0.0
    alive = True
    while alive and lam > 1e-15:
        wait = random.expovariate(lam)
        t_weeks += wait
        if t_weeks >= T_weeks:
            break

        purchase_date = first_date + timedelta(days=t_weeks * 7)
        if purchase_date > obs_end:
            break

        amount = max(0.01, random.gammavariate(p_gg, 1.0 / nu))
        transactions.append({
            'transaction_id': txn_id,
            'customer_id': cust_id,
            'date': purchase_date.strftime('%Y-%m-%d'),
            'amount': round(amount, 2),
        })
        txn_id += 1

        if random.random() < p_drop:
            alive = False

    # ~8% chance of a refund transaction for this customer
    if random.random() < 0.08:
        refund_days = random.randint(1, max(1, int(T_weeks * 7) - 1))
        refund_date = first_date + timedelta(days=refund_days)
        if refund_date <= obs_end:
            transactions.append({
                'transaction_id': txn_id,
                'customer_id': cust_id,
                'date': refund_date.strftime('%Y-%m-%d'),
                'amount': -round(random.uniform(5.0, 50.0), 2),
            })
            txn_id += 1

# Add ~3% duplicate transactions (exact copies with same transaction_id)
max_orig = len(transactions)
n_dupes = int(max_orig * 0.03)
for _ in range(n_dupes):
    idx = random.randint(0, max_orig - 1)
    transactions.append(dict(transactions[idx]))

# Shuffle all rows
random.shuffle(transactions)

# Write CSV
output_dir = os.path.dirname(os.path.abspath(__file__))
csv_path = os.path.join(output_dir, 'transactions.csv')
with open(csv_path, 'w', newline='') as f:
    writer = csv.DictWriter(
        f, fieldnames=['transaction_id', 'customer_id', 'date', 'amount']
    )
    writer.writeheader()
    for t in transactions:
        writer.writerow(t)

# Write config
config = {
    "observation_end": obs_end.strftime('%Y-%m-%d'),
    "prediction_horizon_weeks": 39,
}
config_path = os.path.join(output_dir, 'config.json')
with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

# Stats
unique_cust = len(set(t['customer_id'] for t in transactions))
refund_count = sum(1 for t in transactions if t['amount'] < 0)
print(f"Generated {len(transactions)} rows, {unique_cust} customers, "
      f"{refund_count} refunds, ~{n_dupes} duplicates added")
