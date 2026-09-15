#!/usr/bin/env python3
"""Solution for actuarial reserve valuation pipeline.

Extracts compressed assumptions archive, parses YAML mortality config and
TOML valuation config, queries SQLite for policy/expense/reinsurance data,
computes actuarial values from scratch, and outputs JSON + CSV.

"""
import csv
import json
import math
import os
import sqlite3
import tarfile
import tomllib
import yaml


# ── Extract compressed assumptions archive ──────────────────────────────────
EXTRACT_DIR = "/tmp/_solution_assumptions"
os.makedirs(EXTRACT_DIR, exist_ok=True)
with tarfile.open("/data/assumptions.tar.gz", "r:gz") as tar:
    tar.extractall(EXTRACT_DIR)

# ── Load YAML mortality configuration ───────────────────────────────────────
with open(os.path.join(EXTRACT_DIR, "mortality.yaml")) as f:
    mort_config = yaml.safe_load(f)

A_param = mort_config["basis"]["parameters"]["A"]
B_param = mort_config["basis"]["parameters"]["B"]
c_param = mort_config["basis"]["parameters"]["c"]
bands = mort_config["adjustments"]["bands"]

# ── Load TOML valuation configuration ──────────────────────────────────────
with open(os.path.join(EXTRACT_DIR, "valuation.toml"), "rb") as f:
    val_config = tomllib.load(f)

maxage = val_config["valuation"]["maxage"]
i_rate = val_config["interest"]["annual_effective_rate"]
val_t = val_config["valuation"]["duration"]

# ── Load data from SQLite ────────────────────────────────────────────────────
conn = sqlite3.connect("/data/portfolio.db")
conn.row_factory = sqlite3.Row

policies = [dict(r) for r in conn.execute(
    "SELECT * FROM policy_groups ORDER BY group_code"
).fetchall()]

# Pivot expense_loadings into dictionary keyed by timing_loadingtype
expenses = {}
for row in conn.execute("SELECT loading_type, timing, rate FROM expense_loadings"):
    key = f"{row['timing']}_{row['loading_type']}"
    expenses[key] = row["rate"]

settlement = conn.execute(
    "SELECT amount FROM settlement_expenses WHERE expense_type = 'death_claim'"
).fetchone()["amount"]

reinsurance = {}
for row in conn.execute("SELECT * FROM reinsurance"):
    reinsurance[row["group_code"]] = dict(row)

conn.close()

# ── Build adjusted mortality table ───────────────────────────────────────────
def get_select_factor(age):
    for band in bands:
        lower, upper = band["range"]
        if lower <= age <= upper:
            return band["factor"]
    return 1.0

v = 1.0 / (1.0 + i_rate)

q = {}
for age in range(maxage):
    surv = math.exp(
        -A_param - B_param * c_param**age * (c_param - 1) / math.log(c_param)
    )
    base_q = 1.0 - surv
    q[age] = min(1.0, base_q * get_select_factor(age))
q[maxage] = 1.0

# ── Actuarial functions ──────────────────────────────────────────────────────
def wl_insurance(x):
    """Whole life insurance: A_x = sum v^{k+1} * k_p_x * q_{x+k}"""
    total = 0.0
    k_p_x = 1.0
    for k in range(maxage - x):
        total += v ** (k + 1) * k_p_x * q[x + k]
        k_p_x *= 1 - q[x + k]
    return total

def wl_annuity(x):
    """Whole life annuity-due: a-double-dot_x = sum v^k * k_p_x"""
    total = 0.0
    k_p_x = 1.0
    for k in range(maxage - x + 1):
        total += v ** k * k_p_x
        if x + k < maxage:
            k_p_x *= 1 - q[x + k]
        else:
            break
    return total

def net_premium_fn(x, b):
    return b * wl_insurance(x) / wl_annuity(x)

def gross_premium_fn(x, b):
    Ax = wl_insurance(x)
    ax = wl_annuity(x)
    numerator = (b + settlement) * Ax + expenses["renewal_policy"] * ax + (expenses["initial_policy"] - expenses["renewal_policy"])
    denominator = ax - expenses["renewal_premium"] * ax - (expenses["initial_premium"] - expenses["renewal_premium"])
    return numerator / denominator

def net_policy_value_fn(x, t, b):
    return b * wl_insurance(x + t) - net_premium_fn(x, b) * wl_annuity(x + t)

def gross_policy_value_fn(x, t, b, gp):
    Axt = wl_insurance(x + t)
    axt = wl_annuity(x + t)
    return (b + settlement) * Axt + expenses["renewal_policy"] * axt - gp * (1 - expenses["renewal_premium"]) * axt

def fpt_policy_value_fn(x, t, b):
    if t <= 1:
        return 0.0
    return net_policy_value_fn(x + 1, t - 1, b)

# ── Compute results ──────────────────────────────────────────────────────────
output = {}
csv_rows = []
total_retained = 0.0
total_ceded = 0.0

for pol in policies:
    pid = pol["group_code"]
    x = pol["issue_age"]
    b = pol["benefit_amount"]
    count = pol["in_force_count"]

    np_ = net_premium_fn(x, b)
    gp_ = gross_premium_fn(x, b)
    npv = net_policy_value_fn(x, val_t, b)
    gpv = gross_policy_value_fn(x, val_t, b, gp_)
    fpt = fpt_policy_value_fn(x, val_t, b)
    exp_res = gpv - npv

    # Reinsurance
    ri = reinsurance[pid]
    ret_benefit = min(b, ri["retention"]) * (1 - ri["quota_share_ceded_pct"])
    ced_benefit = b - ret_benefit
    ret_res_pp = npv * (ret_benefit / b)
    ced_res_pp = npv * (ced_benefit / b)

    output[pid] = {
        "net_premium": np_,
        "gross_premium": gp_,
        "net_policy_value_10": npv,
        "gross_policy_value_10": gpv,
        "fpt_reserve_10": fpt,
        "expense_reserve_10": exp_res,
        "retained_benefit": ret_benefit,
        "ceded_benefit": ced_benefit,
        "retained_reserve_per_policy": ret_res_pp,
        "ceded_reserve_per_policy": ced_res_pp,
    }

    total_retained += count * ret_res_pp
    total_ceded += count * ced_res_pp

    csv_rows.append({
        "group_code": pid,
        "issue_age": x,
        "benefit": b,
        "count": count,
        "net_premium": np_,
        "net_pv_10": npv,
        "retained_reserve": count * ret_res_pp,
        "ceded_reserve": count * ced_res_pp,
    })

output["portfolio_retained_reserve"] = total_retained
output["portfolio_ceded_reserve"] = total_ceded
output["portfolio_total_reserve"] = total_retained + total_ceded

# ── Write JSON ───────────────────────────────────────────────────────────────
with open("/app/results.json", "w") as f:
    json.dump(output, f, indent=2)

# ── Write CSV ────────────────────────────────────────────────────────────────
with open("/app/summary.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "group_code", "issue_age", "benefit", "count",
        "net_premium", "net_pv_10", "retained_reserve", "ceded_reserve"
    ])
    writer.writeheader()
    writer.writerows(csv_rows)

print("Results written to /app/results.json and /app/summary.csv")
