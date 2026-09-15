"""Tests for actuarial reserve valuation pipeline.

Verifies agent-computed results against an independent oracle that reads the
same data sources (tar.gz archive + SQLite database) and uses the actuarialmath
library to compute insurance, annuity, premium, reserve, and reinsurance values.

"""
import csv
import json
import math
import os
import sqlite3
import tarfile
import tomllib
import yaml
import pytest
from actuarialmath import LifeTable, Contract


# ---------------------------------------------------------------------------
# Extract compressed assumptions archive
# ---------------------------------------------------------------------------
EXTRACT_DIR = "/tmp/_test_assumptions"
os.makedirs(EXTRACT_DIR, exist_ok=True)
with tarfile.open("/data/assumptions.tar.gz", "r:gz") as tar:
    tar.extractall(EXTRACT_DIR)

# ---------------------------------------------------------------------------
# Load YAML mortality configuration
# ---------------------------------------------------------------------------
with open(os.path.join(EXTRACT_DIR, "mortality.yaml")) as f:
    mort_config = yaml.safe_load(f)

A_m = mort_config["basis"]["parameters"]["A"]
B_m = mort_config["basis"]["parameters"]["B"]
c_m = mort_config["basis"]["parameters"]["c"]
bands = mort_config["adjustments"]["bands"]

# ---------------------------------------------------------------------------
# Load TOML valuation configuration
# ---------------------------------------------------------------------------
with open(os.path.join(EXTRACT_DIR, "valuation.toml"), "rb") as f:
    val_config = tomllib.load(f)

maxage = val_config["valuation"]["maxage"]
i_rate = val_config["interest"]["annual_effective_rate"]
val_t = val_config["valuation"]["duration"]

# ---------------------------------------------------------------------------
# Load data from SQLite
# ---------------------------------------------------------------------------
conn = sqlite3.connect("/data/portfolio.db")
conn.row_factory = sqlite3.Row

policies = [dict(r) for r in conn.execute(
    "SELECT * FROM policy_groups ORDER BY group_code"
).fetchall()]

expenses = {}
for row in conn.execute("SELECT loading_type, timing, rate FROM expense_loadings"):
    key = f"{row['timing']}_{row['loading_type']}"
    expenses[key] = row["rate"]

settlement = conn.execute(
    "SELECT amount FROM settlement_expenses WHERE expense_type = 'death_claim'"
).fetchone()["amount"]

reinsurance_data = {}
for row in conn.execute("SELECT * FROM reinsurance"):
    reinsurance_data[row["group_code"]] = dict(row)

conn.close()

# ---------------------------------------------------------------------------
# Build adjusted mortality table
# ---------------------------------------------------------------------------
def get_select_factor(age):
    for band in bands:
        lower, upper = band["range"]
        if lower <= age <= upper:
            return band["factor"]
    return 1.0

q_table = {}
for age in range(maxage):
    surv = math.exp(
        -A_m - B_m * c_m**age * (c_m - 1) / math.log(c_m)
    )
    base_q = 1.0 - surv
    q_table[age] = min(1.0, base_q * get_select_factor(age))
q_table[maxage] = 1.0

# Build actuarialmath LifeTable with adjusted q values
life = LifeTable(udd=True)
life.set_table(q=q_table, minage=0, maxage=maxage)
life.set_interest(i=i_rate)

# ---------------------------------------------------------------------------
# Load agent results
# ---------------------------------------------------------------------------
with open("/app/results.json") as f:
    results = json.load(f)

REL_TOL = 0.005   # 0.5% relative tolerance
ABS_TOL = 5.0     # absolute tolerance for values near zero


def _close(agent_val, expected_val):
    """Return True when agent_val is acceptably close to expected_val."""
    if abs(expected_val) < 10:
        return abs(agent_val - expected_val) < ABS_TOL
    return math.isclose(agent_val, expected_val, rel_tol=REL_TOL)


# ---------------------------------------------------------------------------
# Pre-compute expected values from the library
# ---------------------------------------------------------------------------
expected = {}
total_retained = 0.0
total_ceded = 0.0

for pol in policies:
    pid = pol["group_code"]
    x = pol["issue_age"]
    b = pol["benefit_amount"]
    count = pol["in_force_count"]

    A_x = life.whole_life_insurance(x)

    net_prem = life.premium_equivalence(A=A_x, b=b)

    gross_prem = life.gross_premium(
        A=A_x,
        benefit=b,
        initial_premium=expenses["initial_premium"],
        renewal_premium=expenses["renewal_premium"],
        initial_policy=expenses["initial_policy"],
        renewal_policy=expenses["renewal_policy"],
        settlement_policy=settlement,
    )

    net_pv = life.net_policy_value(x, t=val_t, b=b)

    contract = Contract(
        benefit=b,
        premium=gross_prem,
        initial_premium=expenses["initial_premium"],
        renewal_premium=expenses["renewal_premium"],
        initial_policy=expenses["initial_policy"],
        renewal_policy=expenses["renewal_policy"],
        settlement_policy=settlement,
    )
    gross_pv = life.gross_policy_value(x, t=val_t, contract=contract)

    fpt_res = life.FPT_policy_value(x, t=val_t, b=b)
    expense_res = gross_pv - net_pv

    # Reinsurance
    ri = reinsurance_data[pid]
    retained_benefit = min(b, ri["retention"]) * (1 - ri["quota_share_ceded_pct"])
    ceded_benefit = b - retained_benefit
    retained_res_pp = net_pv * (retained_benefit / b)
    ceded_res_pp = net_pv * (ceded_benefit / b)

    expected[pid] = {
        "net_premium": net_prem,
        "gross_premium": gross_prem,
        "net_policy_value_10": net_pv,
        "gross_policy_value_10": gross_pv,
        "fpt_reserve_10": fpt_res,
        "expense_reserve_10": expense_res,
        "retained_benefit": retained_benefit,
        "ceded_benefit": ceded_benefit,
        "retained_reserve_per_policy": retained_res_pp,
        "ceded_reserve_per_policy": ceded_res_pp,
    }

    total_retained += count * retained_res_pp
    total_ceded += count * ceded_res_pp

expected["portfolio_retained_reserve"] = total_retained
expected["portfolio_ceded_reserve"] = total_ceded
expected["portfolio_total_reserve"] = total_retained + total_ceded


# ---------------------------------------------------------------------------
# Parametrised tests — policy group fields
# ---------------------------------------------------------------------------
GROUPS = ["G1", "G2", "G3", "G4"]
FIELDS = [
    "net_premium", "gross_premium",
    "net_policy_value_10", "gross_policy_value_10",
    "fpt_reserve_10", "expense_reserve_10",
    "retained_benefit", "ceded_benefit",
    "retained_reserve_per_policy", "ceded_reserve_per_policy",
]


@pytest.mark.parametrize("pid", GROUPS)
@pytest.mark.parametrize("field", FIELDS)
def test_policy_field(pid, field):
    agent_val = float(results[pid][field])
    exp_val = expected[pid][field]
    assert _close(agent_val, exp_val), (
        f"{pid}.{field}: agent={agent_val}, expected={exp_val}"
    )


@pytest.mark.parametrize("agg", [
    "portfolio_retained_reserve",
    "portfolio_ceded_reserve",
    "portfolio_total_reserve",
])
def test_portfolio_aggregates(agg):
    agent_val = float(results[agg])
    exp_val = expected[agg]
    assert _close(agent_val, exp_val), (
        f"{agg}: agent={agent_val}, expected={exp_val}"
    )


# ---------------------------------------------------------------------------
# CSV output tests
# ---------------------------------------------------------------------------
def test_csv_structure():
    """Verify summary.csv exists with correct headers and row count."""
    with open("/app/summary.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 4, f"Expected 4 rows, got {len(rows)}"
    expected_headers = {
        "group_code", "issue_age", "benefit", "count",
        "net_premium", "net_pv_10", "retained_reserve", "ceded_reserve"
    }
    assert set(reader.fieldnames) == expected_headers, (
        f"CSV headers mismatch: got {reader.fieldnames}, expected {expected_headers}"
    )


def test_csv_group_codes():
    """Verify CSV contains all four groups in order."""
    with open("/app/summary.csv") as f:
        reader = csv.DictReader(f)
        codes = [r["group_code"] for r in reader]
    assert codes == ["G1", "G2", "G3", "G4"], f"Group codes: {codes}"


def test_csv_values_match_json():
    """Verify CSV numeric values are consistent with JSON output."""
    with open("/app/summary.csv") as f:
        reader = csv.DictReader(f)
        csv_rows = {r["group_code"]: r for r in reader}

    for pid in GROUPS:
        csv_net_prem = float(csv_rows[pid]["net_premium"])
        json_net_prem = float(results[pid]["net_premium"])
        assert _close(csv_net_prem, json_net_prem), (
            f"CSV/JSON net_premium mismatch for {pid}: csv={csv_net_prem}, json={json_net_prem}"
        )

        csv_net_pv = float(csv_rows[pid]["net_pv_10"])
        json_net_pv = float(results[pid]["net_policy_value_10"])
        assert _close(csv_net_pv, json_net_pv), (
            f"CSV/JSON net_pv_10 mismatch for {pid}: csv={csv_net_pv}, json={json_net_pv}"
        )


def test_csv_reserve_consistency():
    """Verify CSV retained/ceded reserves match per-policy values times count."""
    with open("/app/summary.csv") as f:
        reader = csv.DictReader(f)
        csv_rows = {r["group_code"]: r for r in reader}

    for pid in GROUPS:
        count = int(csv_rows[pid]["count"])
        ret_pp = float(results[pid]["retained_reserve_per_policy"])
        ced_pp = float(results[pid]["ceded_reserve_per_policy"])

        csv_ret = float(csv_rows[pid]["retained_reserve"])
        csv_ced = float(csv_rows[pid]["ceded_reserve"])

        assert _close(csv_ret, count * ret_pp), (
            f"CSV retained_reserve mismatch for {pid}"
        )
        assert _close(csv_ced, count * ced_pp), (
            f"CSV ceded_reserve mismatch for {pid}"
        )
