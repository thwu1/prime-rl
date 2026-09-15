#!/usr/bin/env python3
"""Corrected HMDA Filing Validation Engine.


Extracts filing data from SQLite, reconciles Scala DSL reference vs buggy
Python pipeline, fixes all bugs, implements Q634 macro rule, writes reports.
"""
import json
import os
import re
import sqlite3
from datetime import datetime


def is_valid_date(s):
    if len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def parse_hocon_config(conf_path):
    """Parse rule thresholds from HOCON-style edits.conf."""
    config = {}
    try:
        with open(conf_path) as f:
            content = f.read()
        m = re.search(r'Q607\s*\{[^}]*amount\s*=\s*([\d.]+)', content)
        if m:
            config['Q607_amount'] = float(m.group(1))
        m = re.search(r'Q634\s*\{[^}]*threshold\s*=\s*(\d+)', content)
        if m:
            config['Q634_threshold'] = int(m.group(1))
        m = re.search(r'Q634\s*\{[^}]*ratio\s*=\s*([\d.]+)', content)
        if m:
            config['Q634_ratio'] = float(m.group(1))
    except FileNotFoundError:
        pass
    return config


def extract_filings_from_db(db_path):
    """Extract filing data from SQLite database.

    Returns list of (filing_id, ts_fields, lar_records) tuples.
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # JOIN institutions and filings to get full TS data
    c.execute('''
        SELECT f.filing_id,
               i.name, f.filing_year, f.quarter,
               f.contact_name, f.contact_phone, f.contact_email,
               f.contact_street, f.contact_city, f.contact_state, f.contact_zip,
               i.agency_code, f.reported_lar_count, i.tax_id, i.lei
        FROM filings f
        JOIN institutions i ON f.lei = i.lei
        ORDER BY f.filing_id
    ''')
    filing_rows = c.fetchall()

    results = []
    for row in filing_rows:
        filing_id = row[0]

        # Reconstruct TS record: 15 pipe-delimited fields
        # Order: id|name|year|quarter|contact_name|phone|email|street|city|state|zip|agency|total_lars|tax_id|lei
        ts_fields = [
            "1",            # index 0: Record ID
            str(row[1]),    # index 1: institution name
            str(row[2]),    # index 2: filing year
            str(row[3]),    # index 3: quarter
            str(row[4]),    # index 4: contact name
            str(row[5]),    # index 5: contact phone
            str(row[6]),    # index 6: contact email
            str(row[7]),    # index 7: street
            str(row[8]),    # index 8: city
            str(row[9]),    # index 9: state
            str(row[10]),   # index 10: zip
            str(row[11]),   # index 11: agency code
            str(row[12]),   # index 12: reported LAR count
            str(row[13]),   # index 13: tax ID
            str(row[14]),   # index 14: LEI
        ]

        # Get LAR records
        c.execute('''
            SELECT raw_fields FROM lar_records
            WHERE filing_id = ?
            ORDER BY lar_index
        ''', (filing_id,))
        lar_records = [r[0].split("|") for r in c.fetchall()]

        results.append((filing_id, ts_fields, lar_records))

    conn.close()
    return results


def validate(ts, lars, config):
    """Run all corrected edit rules and return violations + quality flags."""
    violations = []
    quality_flags = []

    q607_threshold = config.get('Q607_amount', 250000.0)
    q634_threshold = config.get('Q634_threshold', 4)
    q634_ratio = config.get('Q634_ratio', 0.80)

    # ======================== TS RULES ========================

    if ts[0] != "1":
        violations.append({"rule": "S300", "scope": "ts", "lar_index": None,
                           "message": "TS Record Identifier is not 1"})

    if len(ts[14]) != 20:
        violations.append({"rule": "V600", "scope": "ts", "lar_index": None,
                           "message": f"TS LEI length is {len(ts[14])}, expected 20"})

    if not ts[1].strip():
        violations.append({"rule": "V601", "scope": "ts", "lar_index": None,
                           "message": "TS Institution Name is empty"})

    if not (ts[2].isdigit() and len(ts[2]) == 4):
        violations.append({"rule": "V602", "scope": "ts", "lar_index": None,
                           "message": "TS Calendar Year is not a valid 4-digit year"})

    if ts[3] != "4":
        violations.append({"rule": "V603", "scope": "ts", "lar_index": None,
                           "message": "TS Calendar Quarter is not 4"})

    # FIX #1: V607 checks ts.taxId format (regex), NOT agency code
    # Scala: ts.taxId is validTaxId  (PredicateRegEx.validTaxId = ^\d{2}-\d{7}$)
    # Regulatory spec says agency code — spec is WRONG, Scala is authoritative
    if not re.match(r'^\d{2}-\d{7}$', ts[13]):
        violations.append({"rule": "V607", "scope": "ts", "lar_index": None,
                           "message": f"TS Tax ID '{ts[13]}' does not match XX-XXXXXXX format"})

    # ==================== FILING-LEVEL RULES ====================

    try:
        ts_total = int(ts[12])
    except ValueError:
        ts_total = -1
    if ts_total != len(lars):
        violations.append({"rule": "S304", "scope": "filing", "lar_index": None,
                           "message": f"TS reports {ts_total} LARs but filing has {len(lars)}"})

    uli_seen = {}
    for i, lar in enumerate(lars):
        uli = lar[2]
        uli_seen.setdefault(uli, []).append(i + 1)
    for uli, indices in uli_seen.items():
        if len(indices) > 1:
            violations.append({"rule": "S305", "scope": "filing", "lar_index": None,
                               "message": f"Duplicate ULI in LAR records {indices}"})

    ts_lei = ts[14]

    # ==================== PER-LAR RULES ====================

    for i, lar in enumerate(lars):
        idx = i + 1

        if lar[0] != "2":
            violations.append({"rule": "S300", "scope": "lar", "lar_index": idx,
                               "message": "LAR Record Identifier is not 2"})

        # FIX #2: S301 case-insensitive LEI comparison
        # Scala: lar.LEI.toLowerCase is equalTo(ts.LEI.toLowerCase)
        # Regulatory spec says byte-for-byte — spec is WRONG
        if lar[1].lower() != ts_lei.lower():
            violations.append({"rule": "S301", "scope": "lar", "lar_index": idx,
                               "message": "LAR LEI does not match TS LEI"})

        uli = lar[2]

        # FIX #3: V608_1 checks alphanumeric + length, not starts-with
        # Scala: when(ULI.length >= 23) { ULI is alphaNumeric and (ULI.length <= 45) }
        # Regulatory spec says starts-with-LEI — spec is WRONG for V608_1
        if len(uli) >= 23:
            if not uli.isalnum() or len(uli) > 45:
                violations.append({"rule": "V608_1", "scope": "lar", "lar_index": idx,
                                   "message": "ULI is not alphanumeric or exceeds 45 chars"})

        app_date = lar[3]
        if app_date != "NA" and not is_valid_date(app_date):
            violations.append({"rule": "V610_1", "scope": "lar", "lar_index": idx,
                               "message": f"Application Date '{app_date}' invalid"})

        if lar[4] not in ("1", "2", "3", "4"):
            violations.append({"rule": "V611", "scope": "lar", "lar_index": idx,
                               "message": f"Loan Type '{lar[4]}' invalid"})

        if lar[5] not in ("1", "2", "31", "32", "4", "5"):
            violations.append({"rule": "V612_1", "scope": "lar", "lar_index": idx,
                               "message": f"Loan Purpose '{lar[5]}' invalid"})

        if lar[6] not in ("1", "2"):
            violations.append({"rule": "V613_1", "scope": "lar", "lar_index": idx,
                               "message": f"Preapproval '{lar[6]}' invalid"})

        # FIX #6: V613_4 — when preapproval=1, action must be in {1,2,7,8}
        # Scala: when(preapproval is PreapprovalRequested) { action in {1,2,7,8} }
        if lar[6] == "1" and lar[10] not in ("1", "2", "7", "8"):
            violations.append({"rule": "V613_4", "scope": "lar", "lar_index": idx,
                               "message": f"Preapproval=1 but Action '{lar[10]}' not in {{1,2,7,8}}"})

        # FIX #4: V614_1 — when purpose in refinance/improvement set, preapproval must be 2
        # Scala: when(purpose in {2,31,32,4,5}) { preapproval is PreapprovalNotRequested }
        # Regulatory spec says construction method — spec is WRONG
        if lar[5] in ("2", "31", "32", "4", "5") and lar[6] != "2":
            violations.append({"rule": "V614_1", "scope": "lar", "lar_index": idx,
                               "message": f"Purpose '{lar[5]}' requires Preapproval=2"})

        if lar[8] not in ("1", "2", "3"):
            violations.append({"rule": "V615_1", "scope": "lar", "lar_index": idx,
                               "message": f"Occupancy Type '{lar[8]}' invalid"})

        try:
            amount = float(lar[9])
            if amount <= 0:
                violations.append({"rule": "V616", "scope": "lar", "lar_index": idx,
                                   "message": f"Loan Amount {amount} not > 0"})
        except ValueError:
            violations.append({"rule": "V616", "scope": "lar", "lar_index": idx,
                               "message": f"Loan Amount '{lar[9]}' not numeric"})

        if lar[10] not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            violations.append({"rule": "V617", "scope": "lar", "lar_index": idx,
                               "message": f"Action Taken '{lar[10]}' invalid"})

        if not is_valid_date(lar[11]):
            violations.append({"rule": "V618", "scope": "lar", "lar_index": idx,
                               "message": f"Action Taken Date '{lar[11]}' invalid"})

        if lar[6] == "1" and lar[10] not in ("1", "2", "3", "4", "5", "7", "8"):
            violations.append({"rule": "V619_1", "scope": "lar", "lar_index": idx,
                               "message": "Preapproval=1 but Action not in allowed set"})

        if lar[10] in ("7", "8") and lar[6] != "1":
            violations.append({"rule": "V620", "scope": "lar", "lar_index": idx,
                               "message": "Action 7/8 requires Preapproval=1"})

        if lar[50] not in ("1", "2", "3", "4", "6"):
            violations.append({"rule": "V636_1", "scope": "lar", "lar_index": idx,
                               "message": f"Sex of Applicant '{lar[50]}' invalid"})

        if lar[60] not in ("1", "2"):
            violations.append({"rule": "V661", "scope": "lar", "lar_index": idx,
                               "message": f"Lien Status '{lar[60]}' invalid"})

        # ---- Quality Rules ----

        # FIX #5: Q601 checks date recency, not amount
        # Scala: when(applicationDate is numeric) { appDate >= actionDate - 2 years }
        # Regulatory spec says amount > 10M — spec is WRONG
        if lar[3].isdigit() and len(lar[3]) == 8 and len(lar[11]) >= 8:
            try:
                min_year = int(lar[11][:4]) - 2
                min_date = int(f"{min_year}{lar[11][4:8]}")
                app_date_int = int(lar[3])
                if app_date_int < min_date:
                    quality_flags.append({"rule": "Q601", "lar_index": idx,
                                          "message": f"Application date {lar[3]} is more than 2 years before action date {lar[11]}"})
            except (ValueError, IndexError):
                pass

        # FIX #7: Q607 — subordinate lien amount threshold
        # Scala: when(lienStatus == SecuredBySubordinateLien) { amount <= configAmount }
        if lar[60] == "2":
            try:
                amt = float(lar[9])
                if amt > q607_threshold:
                    quality_flags.append({"rule": "Q607", "lar_index": idx,
                                          "message": f"Subordinate lien amount {amt} exceeds threshold {q607_threshold}"})
            except ValueError:
                pass

        # Q617: Action date earlier than application date
        if app_date != "NA" and is_valid_date(app_date) and is_valid_date(lar[11]):
            ad = datetime.strptime(app_date, "%Y%m%d")
            atd = datetime.strptime(lar[11], "%Y%m%d")
            if atd < ad:
                quality_flags.append({"rule": "Q617", "lar_index": idx,
                                      "message": "Action date before application date"})

    # ==================== Q634 MACRO QUALITY RULE ====================
    # Implemented from regulatory spec (no Scala source exists)
    # Count home purchase originations vs total home purchase applications

    home_purchase_originated = sum(
        1 for lar in lars if lar[5] == "1" and lar[10] == "1"
    )
    home_purchase_total = sum(
        1 for lar in lars if lar[5] == "1"
    )

    if home_purchase_originated > q634_threshold:
        if home_purchase_total > 0 and home_purchase_originated > q634_ratio * home_purchase_total:
            quality_flags.append({
                "rule": "Q634", "lar_index": None,
                "message": f"Home purchase origination concentration: {home_purchase_originated} "
                           f"originated out of {home_purchase_total} applications "
                           f"(ratio {home_purchase_originated/home_purchase_total:.2f} exceeds {q634_ratio})"
            })

    # ==================== BUILD SUMMARY ====================

    all_rules = set()
    for v in violations:
        all_rules.add(v["rule"])
    for q in quality_flags:
        all_rules.add(q["rule"])

    return {
        "violations": violations,
        "quality_flags": quality_flags,
        "summary": {
            "total_lars": len(lars),
            "violations_count": len(violations),
            "quality_flags_count": len(quality_flags),
            "rules_triggered": sorted(all_rules),
        }
    }


def main():
    db_path = "/app/hmda_filings.db"
    conf_paths = ["/app/pipeline/edits.conf", "/app/scala_rules/edits.conf"]
    results_dir = "/app/results"

    # Parse configuration
    config = {}
    for cp in conf_paths:
        if os.path.exists(cp):
            config = parse_hocon_config(cp)
            break

    # Extract filing data from SQLite
    filings = extract_filings_from_db(db_path)

    os.makedirs(results_dir, exist_ok=True)

    for filing_id, ts, lars in filings:
        report = validate(ts, lars, config)

        out_path = os.path.join(results_dir, f"{filing_id}_report.json")
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)

        s = report["summary"]
        print(f"{filing_id}: {s['violations_count']} violations, "
              f"{s['quality_flags_count']} quality flags, "
              f"rules: {s['rules_triggered']}")


if __name__ == "__main__":
    main()
