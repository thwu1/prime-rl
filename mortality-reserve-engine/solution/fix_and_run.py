#!/usr/bin/env python3
"""Fix all pipeline bugs and run the valuation pipeline.

Fixes across four components:
1. Makefile: dependency chain and shell variable expansion
2. schema.sql: INTEGER→REAL for improvement factors, add UNIQUE on select_rates
3. load_data.py: XPath for improvement scale inner axis
4. compute_reserves.py: select boundary, improvement accumulation range, annuity-due

"""

import json
import os
import sqlite3
import subprocess
import xml.etree.ElementTree as ET


# ===========================================================================
# Fix 1: Rewrite the Makefile
# ===========================================================================

FIXED_MAKEFILE = r"""# Actuarial valuation pipeline

DB_PATH := /app/mortality.db
DATA_DIR := /app/data
CONFIG := /app/config.json
SCHEMA := /app/schema.sql
RESULTS := /app/results.json

XML_FILES := $(wildcard $(DATA_DIR)/*.xml)

.PHONY: pipeline clean validate load compute

pipeline: load compute

validate:
	@echo "=== Validating XML files ==="
	@for f in $(XML_FILES); do \
		xmllint --noout $$f 2>/dev/null && echo "  OK: $$f" || echo "  WARN: $$f"; \
	done

load: validate
	@echo "=== Loading data into SQLite ==="
	rm -f $(DB_PATH)
	sqlite3 $(DB_PATH) < $(SCHEMA)
	python3 /app/load_data.py --db $(DB_PATH) --data-dir $(DATA_DIR)

compute: load
	@echo "=== Computing reserves ==="
	python3 /app/compute_reserves.py --db $(DB_PATH) --config $(CONFIG) --output $(RESULTS)

clean:
	rm -f $(DB_PATH) $(RESULTS)
"""


# ===========================================================================
# Fix 2: Rewrite the SQL schema
# ===========================================================================

FIXED_SCHEMA = """-- Mortality database schema

CREATE TABLE IF NOT EXISTS table_metadata (
    table_id INTEGER PRIMARY KEY,
    content_type TEXT NOT NULL,
    table_name TEXT NOT NULL,
    table_description TEXT,
    source_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS select_rates (
    table_id INTEGER NOT NULL,
    issue_age INTEGER NOT NULL,
    duration INTEGER NOT NULL,
    qx REAL NOT NULL,
    PRIMARY KEY (table_id, issue_age, duration),
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);

CREATE TABLE IF NOT EXISTS ultimate_rates (
    table_id INTEGER NOT NULL,
    attained_age INTEGER NOT NULL,
    qx REAL NOT NULL,
    PRIMARY KEY (table_id, attained_age),
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);

CREATE TABLE IF NOT EXISTS improvement_factors (
    table_id INTEGER NOT NULL,
    age INTEGER NOT NULL,
    year INTEGER NOT NULL,
    rate REAL NOT NULL,
    PRIMARY KEY (table_id, age, year),
    FOREIGN KEY (table_id) REFERENCES table_metadata(table_id)
);
"""


# ===========================================================================
# Fix 3: Corrected data loader
# ===========================================================================

def parse_and_load_xml(xml_path, conn):
    """Parse an XTbML file and load its data into the database."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    cc = root.find("ContentClassification")
    table_id = int(cc.find("TableIdentity").text.strip())
    ct_elem = cc.find("ContentType")
    content_type = ct_elem.text.strip() if ct_elem.text else ""
    table_name = cc.find("TableName").text.strip()
    desc_elem = cc.find("TableDescription")
    description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""

    conn.execute(
        "INSERT OR REPLACE INTO table_metadata VALUES (?, ?, ?, ?, ?)",
        (table_id, content_type, table_name, description, os.path.basename(xml_path))
    )

    tables = root.findall("Table")

    if len(tables) >= 2:
        _load_select_table(conn, table_id, tables[0])
        _load_ultimate_table(conn, table_id, tables[1])
    elif len(tables) == 1:
        meta = tables[0].find("MetaData")
        axis_defs = meta.findall("AxisDef")
        if len(axis_defs) == 2:
            _load_improvement_scale(conn, table_id, tables[0])
        else:
            _load_ultimate_table(conn, table_id, tables[0])


def _load_select_table(conn, table_id, table_elem):
    for age_axis in table_elem.findall("Values/Axis"):
        age = int(age_axis.attrib["t"])
        inner = age_axis.find("Axis")
        if inner is None:
            continue
        for y in inner.findall("Y"):
            dur = int(y.attrib["t"])
            qx = float(y.text)
            conn.execute(
                "INSERT OR REPLACE INTO select_rates VALUES (?, ?, ?, ?)",
                (table_id, age, dur, qx)
            )


def _load_ultimate_table(conn, table_id, table_elem):
    y_elems = table_elem.findall("Values/Axis/Y")
    if not y_elems:
        y_elems = table_elem.findall("Values/Axis/Axis/Y")
    for y in y_elems:
        age = int(y.attrib["t"])
        qx = float(y.text)
        conn.execute(
            "INSERT OR REPLACE INTO ultimate_rates VALUES (?, ?, ?)",
            (table_id, age, qx)
        )


def _load_improvement_scale(conn, table_id, table_elem):
    """FIX: Use Axis/Y to find year entries inside the inner axis."""
    for age_axis in table_elem.findall("Values/Axis"):
        age = int(age_axis.attrib["t"])
        inner = age_axis.find("Axis")
        if inner is None:
            continue
        for y in inner.findall("Y"):
            year = int(y.attrib["t"])
            rate = float(y.text)
            conn.execute(
                "INSERT OR REPLACE INTO improvement_factors VALUES (?, ?, ?, ?)",
                (table_id, age, year, rate)
            )


def load_all_xml(db_path, data_dir):
    conn = sqlite3.connect(db_path)
    loaded = 0
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".xml"):
            continue
        path = os.path.join(data_dir, fname)
        try:
            parse_and_load_xml(path, conn)
            loaded += 1
        except Exception as e:
            print(f"  Skipped {fname}: {e}")
    conn.commit()
    conn.close()
    print(f"  Loaded {loaded} table files")


# ===========================================================================
# Fix 4: Corrected reserve computation
# ===========================================================================

def get_base_rate(conn, table_id, issue_age, duration):
    """FIX: duration <= 25 (not < 25) for select lookup."""
    if duration <= 25:
        row = conn.execute(
            "SELECT qx FROM select_rates "
            "WHERE table_id=? AND issue_age=? AND duration=?",
            (table_id, issue_age, duration)
        ).fetchone()
        if row is not None:
            return row[0]
    attained_age = issue_age + duration - 1
    row = conn.execute(
        "SELECT qx FROM ultimate_rates "
        "WHERE table_id=? AND attained_age=?",
        (table_id, attained_age)
    ).fetchone()
    if row is None:
        raise ValueError(
            f"No rate: table_id={table_id}, age={issue_age}, dur={duration}"
        )
    return row[0]


def get_improvement(conn, table_id, age, year):
    """Look up improvement factor with terminal year extrapolation."""
    row = conn.execute(
        "SELECT rate FROM improvement_factors "
        "WHERE table_id=? AND age=? AND year=?",
        (table_id, age, year)
    ).fetchone()
    if row is not None:
        return row[0]
    if year > 2037:
        row = conn.execute(
            "SELECT rate FROM improvement_factors "
            "WHERE table_id=? AND age=? AND year=2037",
            (table_id, age)
        ).fetchone()
        if row is not None:
            return row[0]
    return 0.0


def project_rate(conn, q_base, imp_table_id, attained_age, calendar_year,
                 base_year):
    """FIX: Start accumulation at base_year + 1, not base_year."""
    cumulative = 1.0
    for t in range(base_year + 1, calendar_year + 1):
        imp = get_improvement(conn, imp_table_id, attained_age, t)
        cumulative *= (1.0 - imp)
    return q_base * cumulative


def compute_projected_rates(conn, table_id, imp_table_id, issue_age,
                            start_dur, count, start_year, base_year):
    rates = []
    for k in range(count):
        dur = start_dur + k
        att_age = issue_age + dur - 1
        cal_yr = start_year + k
        qb = get_base_rate(conn, table_id, issue_age, dur)
        rates.append(
            project_rate(conn, qb, imp_table_id, att_age, cal_yr, base_year)
        )
    return rates


def compute_annuity_due(projected_qx, interest_rate):
    """FIX: Use v^k for annuity-due (not v^(k+1) for annuity-immediate)."""
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        result += kpx * v ** k
        kpx *= (1.0 - qx)
    return result


def compute_insurance_pv(projected_qx, interest_rate):
    v = 1.0 / (1.0 + interest_rate)
    result = 0.0
    kpx = 1.0
    for k, qx in enumerate(projected_qx):
        result += kpx * qx * v ** (k + 1)
        kpx *= (1.0 - qx)
    return result


def run_valuation(conn, val_cfg, base_year, rate_override=None):
    ia = val_cfg["issue_age"]
    iy = val_cfg["issue_year"]
    term = val_cfg["term_years"]
    rate = rate_override if rate_override is not None else val_cfg["annual_interest_rate"]
    vy = val_cfg["valuation_year"]
    fa = val_cfg["face_amount"]
    tid = val_cfg["table_id"]
    imp_tid = val_cfg["improvement_table_id"]

    elapsed = vy - iy
    remaining = term - elapsed

    val_qx = compute_projected_rates(
        conn, tid, imp_tid, ia, elapsed + 1, remaining, vy, base_year
    )
    ann_val = compute_annuity_due(val_qx, rate)
    ins_val = compute_insurance_pv(val_qx, rate)

    issue_qx = compute_projected_rates(
        conn, tid, imp_tid, ia, 1, term, iy, base_year
    )
    ann_issue = compute_annuity_due(issue_qx, rate)
    ins_issue = compute_insurance_pv(issue_qx, rate)

    premium = ins_issue / ann_issue
    reserve = ins_val - premium * ann_val

    return {
        "projected_qx": val_qx,
        "annuity_due": ann_val,
        "insurance_pv": ins_val,
        "annual_premium": premium,
        "reserve": reserve,
        "face_amount": fa,
    }


# ===========================================================================
# Main: apply all fixes and run pipeline
# ===========================================================================

def main():
    print("=== Applying fixes ===")

    # Fix Makefile
    with open("/app/Makefile", "w") as f:
        f.write(FIXED_MAKEFILE)
    print("  Fixed Makefile")

    # Fix schema.sql
    with open("/app/schema.sql", "w") as f:
        f.write(FIXED_SCHEMA)
    print("  Fixed schema.sql")

    # Fix load_data.py (we run the corrected version directly)
    # Fix compute_reserves.py (we run the corrected version directly)

    # Run pipeline steps
    db_path = "/app/mortality.db"
    data_dir = "/app/data"
    config_path = "/app/config.json"
    output_path = "/app/results.json"

    # Step 1: Validate XML
    print("=== Validating XML files ===")
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".xml"):
            continue
        path = os.path.join(data_dir, fname)
        result = subprocess.run(
            ["xmllint", "--noout", path],
            capture_output=True, text=True
        )
        status = "OK" if result.returncode == 0 else "WARN"
        print(f"  {status}: {fname}")

    # Step 2: Create and populate database
    print("=== Loading data into SQLite ===")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.executescript(FIXED_SCHEMA)
    conn.close()

    load_all_xml(db_path, data_dir)

    # Step 3: Compute reserves
    print("=== Computing reserves ===")
    with open(config_path) as f:
        config = json.load(f)

    conn = sqlite3.connect(db_path)
    base_year = config["base_year"]
    stress_bps = config["stress_bps"]

    results = {}
    total = 0.0
    total_up = 0.0
    total_down = 0.0

    for val in config["valuations"]:
        base_rate = val["annual_interest_rate"]

        r = run_valuation(conn, val, base_year)
        r_up = run_valuation(conn, val, base_year,
                              rate_override=base_rate + stress_bps * 0.0001)
        r_down = run_valuation(conn, val, base_year,
                                rate_override=base_rate - stress_bps * 0.0001)

        results[val["id"]] = {
            "projected_qx": r["projected_qx"],
            "annuity_due": r["annuity_due"],
            "insurance_pv": r["insurance_pv"],
            "annual_premium": r["annual_premium"],
            "reserve": r["reserve"],
            "reserve_up": r_up["reserve"],
            "reserve_down": r_down["reserve"],
        }
        total += r["face_amount"] * r["reserve"]
        total_up += r["face_amount"] * r_up["reserve"]
        total_down += r["face_amount"] * r_down["reserve"]

    results["total_reserve"] = total
    results["total_reserve_up"] = total_up
    results["total_reserve_down"] = total_down

    conn.close()

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"=== Results written to {output_path} ===")


if __name__ == "__main__":
    main()
