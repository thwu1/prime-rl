
import subprocess
import os
import csv
import sqlite3
import shutil
import math
import pytest

CRIF_DIR = "/app/crif"
CALC_SCRIPT = "/app/simm_calc.py"
PARAMS_DB = "/app/simm_params.db"
RESULTS_DB = "/app/simm_results.db"

# Full expected values: (test_id, delta, vega, curvature, base_corr, addon, benchmark)
EXPECTED = [
    ("C1",   460000000, None, None, None, None, 460000000),
    ("C20",  27000000, None, None, None, None, 27000000),
    ("C50",  5989197781, None, None, None, None, 5989197781),
    ("C55",  5123511762, None, None, None, None, 5123511762),
    ("C65",  304401380, None, None, None, None, 304401380),
    ("C70",  6697306623, None, None, None, None, 6697306623),
    ("C80",  45609126471, None, None, None, None, 45609126471),
    ("C90",  12060000, None, None, None, None, 12060000),
    ("C100", 66500000, None, None, None, None, 66500000),
    ("C115", 11066161, None, None, None, None, 11066161),
    ("C128", 128959054, None, None, None, None, 128959054),
    ("C132", None, None, None, 5546170, None, 5546170),
    ("C133", 345351405, None, None, 5546170, None, 350897575),
    ("C134", 1680000000, None, None, None, None, 1680000000),
    ("C150", 3602373954, None, None, None, None, 3602373954),
    ("C170", 34000000, None, None, None, None, 34000000),
    ("C200", 56557228, None, None, None, None, 56557228),
    ("C220", 18048203818, None, None, None, None, 18048203818),
    ("C250", 16000000, None, None, None, None, 16000000),
    ("C260", 222334207894, None, None, None, None, 222334207894),
    ("C280", 157906301, None, None, None, None, 157906301),
    ("C299", None, 126000000, 15335953, None, None, 141335953),
    ("C350", None, 492223521, 405074479, None, None, 897298000),
    ("C390", None, 11100000, 1908669, None, None, 13008669),
    ("C400", None, 76054528, 13838831, None, None, 89893359),
]

COMPONENT_KEYS = ["SIMM Delta", "SIMM Vega", "SIMM Curvature", "SIMM Base Corr", "SIMM AddOn"]
ALL_KEYS = COMPONENT_KEYS + ["SIMM Benchmark"]


def run_calc(crif_path):
    """Run the SIMM calculator and parse CSV output."""
    result = subprocess.run(
        ["python3", CALC_SCRIPT, crif_path],
        capture_output=True, text=True, timeout=120, cwd="/app"
    )
    assert result.returncode == 0, f"Calculator failed: stderr={result.stderr}"
    lines = result.stdout.strip().split("\n")
    header_line = None
    data_line = None
    for i, line in enumerate(lines):
        if "SIMM Delta" in line and "SIMM Benchmark" in line:
            header_line = line
            if i + 1 < len(lines):
                data_line = lines[i + 1]
            break
    assert header_line is not None, f"No CSV header in output: {result.stdout}"
    assert data_line is not None, f"No data line in output: {result.stdout}"
    reader = csv.DictReader([header_line, data_line])
    row = next(reader)
    parsed = {}
    for key in ALL_KEYS:
        val = row[key].strip()
        parsed[key] = None if val == "-" else int(round(float(val)))
    return parsed


def values_match(actual, expected):
    """Check if two values match within tolerance."""
    if expected is None:
        return actual is None or actual == 0
    if actual is None:
        return expected == 0
    if abs(expected) > 1_000_000_000:
        if expected == 0:
            return actual == 0
        return abs(actual - expected) / abs(expected) < 0.005
    else:
        return abs(actual - expected) <= 1


# --- Core correctness tests ------------------------------------------

@pytest.mark.parametrize("test_id,exp_d,exp_v,exp_c,exp_bc,exp_a,exp_bench", EXPECTED)
def test_benchmark(test_id, exp_d, exp_v, exp_c, exp_bc, exp_a, exp_bench):
    """Verify SIMM Benchmark matches expected value."""
    crif_path = os.path.join(CRIF_DIR, f"{test_id}_crif.csv")
    out = run_calc(crif_path)
    actual = out["SIMM Benchmark"]
    assert values_match(actual, exp_bench), (
        f"{test_id}: Benchmark mismatch: got {actual}, expected {exp_bench}"
    )


@pytest.mark.parametrize("test_id,exp_d,exp_v,exp_c,exp_bc,exp_a,exp_bench", EXPECTED)
def test_components(test_id, exp_d, exp_v, exp_c, exp_bc, exp_a, exp_bench):
    """Verify individual margin components match expected values."""
    crif_path = os.path.join(CRIF_DIR, f"{test_id}_crif.csv")
    out = run_calc(crif_path)
    expected_vals = {
        "SIMM Delta": exp_d, "SIMM Vega": exp_v,
        "SIMM Curvature": exp_c, "SIMM Base Corr": exp_bc, "SIMM AddOn": exp_a,
    }
    for comp, exp_val in expected_vals.items():
        act_val = out[comp]
        assert values_match(act_val, exp_val), (
            f"{test_id} {comp}: got {act_val}, expected {exp_val}"
        )


# --- Structure and format tests ---------------------------------------

def test_calculator_exists():
    """Calculator script must exist."""
    assert os.path.isfile(CALC_SCRIPT), f"Calculator not found at {CALC_SCRIPT}"


def test_csv_output_format():
    """Output must have CSV header with all required columns."""
    crif_path = os.path.join(CRIF_DIR, "C1_crif.csv")
    result = subprocess.run(
        ["python3", CALC_SCRIPT, crif_path],
        capture_output=True, text=True, timeout=60, cwd="/app"
    )
    assert result.returncode == 0, f"Calculator failed: {result.stderr}"
    output = result.stdout.strip()
    for col in ALL_KEYS:
        assert col in output, f"Missing column '{col}' in output"


# --- SQLite results database tests ------------------------------------

def test_results_db_created():
    """Calculator must create /app/simm_results.db with margin_results table."""
    if os.path.exists(RESULTS_DB):
        os.remove(RESULTS_DB)
    crif_path = os.path.join(CRIF_DIR, "C1_crif.csv")
    result = subprocess.run(
        ["python3", CALC_SCRIPT, crif_path],
        capture_output=True, text=True, timeout=60, cwd="/app"
    )
    assert result.returncode == 0, f"Calculator failed: {result.stderr}"
    assert os.path.isfile(RESULTS_DB), "simm_results.db not created"
    conn = sqlite3.connect(RESULTS_DB)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "margin_results" in tables, "margin_results table not found"
    cols = [r[1] for r in conn.execute("PRAGMA table_info(margin_results)").fetchall()]
    for expected_col in ["id", "delta", "vega", "curvature", "base_corr", "addon", "benchmark"]:
        assert expected_col in cols, f"Column '{expected_col}' missing from margin_results"
    conn.close()


def test_results_db_values():
    """Results in SQLite must match CSV output for C1."""
    if os.path.exists(RESULTS_DB):
        os.remove(RESULTS_DB)
    crif_path = os.path.join(CRIF_DIR, "C1_crif.csv")
    csv_out = run_calc(crif_path)
    conn = sqlite3.connect(RESULTS_DB)
    row = conn.execute(
        "SELECT id, delta, vega, curvature, base_corr, addon, benchmark "
        "FROM margin_results WHERE id='C1'"
    ).fetchone()
    conn.close()
    assert row is not None, "C1 not found in margin_results"
    assert row[0] == "C1"
    db_bench = int(round(row[6]))
    assert values_match(db_bench, 460000000), f"DB benchmark: {db_bench} != 460000000"


def test_results_db_multiple():
    """Running calculator on multiple CRIFs accumulates results in the DB."""
    if os.path.exists(RESULTS_DB):
        os.remove(RESULTS_DB)
    for tid in ["C1", "C90", "C170"]:
        crif_path = os.path.join(CRIF_DIR, f"{tid}_crif.csv")
        result = subprocess.run(
            ["python3", CALC_SCRIPT, crif_path],
            capture_output=True, text=True, timeout=60, cwd="/app"
        )
        assert result.returncode == 0
    conn = sqlite3.connect(RESULTS_DB)
    ids = sorted([r[0] for r in conn.execute("SELECT id FROM margin_results").fetchall()])
    conn.close()
    assert "C1" in ids and "C90" in ids and "C170" in ids, (
        f"Expected C1, C90, C170 in DB, got {ids}"
    )


# --- Anti-cheat: parameter database dependency test -------------------

def test_reads_parameters_from_db():
    """Verify the calculator actually reads parameters from simm_params.db.

    Temporarily doubles the IR Regular/2w risk weight and checks the
    C1 benchmark (single IR delta, USD, 2w, amount=4000000) doubles too.
    """
    backup_path = "/tmp/simm_params_backup.db"
    shutil.copy(PARAMS_DB, backup_path)
    if os.path.exists(RESULTS_DB):
        os.remove(RESULTS_DB)
    try:
        conn = sqlite3.connect(PARAMS_DB)
        orig = conn.execute(
            "SELECT weight FROM ir_risk_weights WHERE tenor='2w' AND vol_regime='Regular'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE ir_risk_weights SET weight = ? WHERE tenor='2w' AND vol_regime='Regular'",
            (orig * 2,)
        )
        conn.commit()
        conn.close()

        crif_path = os.path.join(CRIF_DIR, "C1_crif.csv")
        out = run_calc(crif_path)
        actual = out["SIMM Benchmark"]
        # C1: single sensitivity, amount=4000000, below concentration threshold
        # Original: RW * 4000000 = 460000000 (RW=115)
        # Modified: 2*RW * 4000000 = 920000000
        expected_modified = int(round(orig * 2 * 4000000))
        assert values_match(actual, expected_modified), (
            f"With doubled RW, expected ~{expected_modified}, got {actual}. "
            "Calculator may not be reading parameters from simm_params.db."
        )
    finally:
        shutil.copy(backup_path, PARAMS_DB)
        os.remove(backup_path)


# --- Anti-cheat: synthetic CRIF test ----------------------------------

def test_synthetic_single_ir_sensitivity():
    """Generate a novel CRIF not in the test vectors and verify correct computation.

    Creates a single IR delta sensitivity with a unique amount and verifies
    the calculator produces the correct margin using parameters from the DB.
    """
    amount = 7654321.0
    crif_path = "/tmp/synthetic_test_crif.csv"
    with open(crif_path, "w") as f:
        f.write("ProductClass,RiskType,Qualifier,Bucket,Label1,Label2,Amount,AmountCurrency,AmountUSD\n")
        f.write(f"RatesFX,Risk_IRCurve,USD,1,2w,OIS,{amount},USD,{amount}\n")

    # Read the risk weight and concentration threshold from the parameter DB
    conn = sqlite3.connect(PARAMS_DB)
    rw = conn.execute(
        "SELECT weight FROM ir_risk_weights WHERE tenor='2w' AND vol_regime='Regular'"
    ).fetchone()[0]
    ct_millions = conn.execute(
        "SELECT threshold_millions FROM concentration_thresholds "
        "WHERE risk_class='IR' AND margin_type='delta' AND key='USD'"
    ).fetchone()[0]
    conn.close()

    ct = ct_millions * 1_000_000
    cr_val = max(1.0, math.sqrt(abs(amount) / ct))
    expected = int(round(rw * amount * cr_val))

    out = run_calc(crif_path)
    actual = out["SIMM Benchmark"]
    assert values_match(actual, expected), (
        f"Synthetic test: got {actual}, expected {expected}"
    )
    os.remove(crif_path)


def test_synthetic_creditq_sensitivity():
    """Generate a novel CreditQ CRIF and verify computation."""
    amount = 3141592.0
    crif_path = "/tmp/synthetic_creditq_crif.csv"
    with open(crif_path, "w") as f:
        f.write("ProductClass,RiskType,Qualifier,Bucket,Label1,Label2,Amount,AmountCurrency,AmountUSD\n")
        f.write(f"Credit,Risk_CreditQ,ISSUER_A,1,1y,SEC,{amount},USD,{amount}\n")

    conn = sqlite3.connect(PARAMS_DB)
    rw = conn.execute(
        "SELECT weight FROM creditq_bucket_weights WHERE bucket=1"
    ).fetchone()[0]
    ct_millions = conn.execute(
        "SELECT threshold_millions FROM concentration_thresholds "
        "WHERE risk_class='CreditQ' AND margin_type='delta' AND key='1'"
    ).fetchone()[0]
    conn.close()

    ct = ct_millions * 1_000_000
    cr_val = max(1.0, math.sqrt(abs(amount) / ct))
    expected = int(round(rw * amount * cr_val))

    out = run_calc(crif_path)
    actual = out["SIMM Benchmark"]
    assert values_match(actual, expected), (
        f"Synthetic CreditQ: got {actual}, expected {expected}"
    )
    os.remove(crif_path)
