#!/usr/bin/env python3
"""HMDA Filing Validation Engine — reference solution.

"""
import json
import sys
from datetime import datetime


def parse_filing(filepath):
    """Parse a pipe-delimited HMDA filing into TS fields and LAR field lists."""
    with open(filepath) as f:
        lines = [line.strip() for line in f if line.strip()]

    ts_fields = lines[0].split("|")
    lar_records = [line.split("|") for line in lines[1:]]
    return ts_fields, lar_records


def is_valid_date(s):
    """Return True if s is exactly 8 digits representing a real calendar date."""
    if len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
        return True
    except ValueError:
        return False


def validate(ts, lars):
    """Run all edit rules and return violations + quality flags."""
    violations = []
    quality_flags = []

    # ===================== TS RULES =====================

    # S300 (TS): Record Identifier must be 1
    if ts[0] != "1":
        violations.append({
            "rule": "S300", "scope": "ts", "lar_index": None,
            "message": f"TS Record Identifier is '{ts[0]}', expected '1'"
        })

    # V600: LEI length must be exactly 20
    if len(ts[14]) != 20:
        violations.append({
            "rule": "V600", "scope": "ts", "lar_index": None,
            "message": f"TS LEI length is {len(ts[14])}, expected 20"
        })

    # V601: Institution Name must not be empty
    if not ts[1].strip():
        violations.append({
            "rule": "V601", "scope": "ts", "lar_index": None,
            "message": "TS Financial Institution Name is empty"
        })

    # V602: Calendar Year must be 4-digit numeric
    if not (ts[2].isdigit() and len(ts[2]) == 4):
        violations.append({
            "rule": "V602", "scope": "ts", "lar_index": None,
            "message": f"TS Calendar Year '{ts[2]}' is not a 4-digit number"
        })

    # V603: Quarter must be 4
    if ts[3] != "4":
        violations.append({
            "rule": "V603", "scope": "ts", "lar_index": None,
            "message": f"TS Calendar Quarter is '{ts[3]}', expected '4'"
        })

    # V604: Contact name not empty
    if not ts[4].strip():
        violations.append({
            "rule": "V604", "scope": "ts", "lar_index": None,
            "message": "TS Contact Person's Name is empty"
        })

    # V605: Contact phone not empty
    if not ts[5].strip():
        violations.append({
            "rule": "V605", "scope": "ts", "lar_index": None,
            "message": "TS Contact Person's Phone is empty"
        })

    # V606: Contact email not empty
    if not ts[6].strip():
        violations.append({
            "rule": "V606", "scope": "ts", "lar_index": None,
            "message": "TS Contact Person's E-mail is empty"
        })

    # V607: Agency code must be one of {1,2,3,5,7,9}
    if ts[11] not in ("1", "2", "3", "5", "7", "9"):
        violations.append({
            "rule": "V607", "scope": "ts", "lar_index": None,
            "message": f"TS Federal Agency '{ts[11]}' is not a valid code"
        })

    # =================== FILING-LEVEL RULES ===================

    # S304: Total number of LAR entries must match actual count
    try:
        ts_total = int(ts[12])
    except ValueError:
        ts_total = -1
    if ts_total != len(lars):
        violations.append({
            "rule": "S304", "scope": "filing", "lar_index": None,
            "message": f"TS reports {ts_total} LAR entries but filing contains {len(lars)}"
        })

    # S305: All ULIs must be unique
    uli_map = {}
    for i, lar in enumerate(lars):
        uli = lar[2]
        uli_map.setdefault(uli, []).append(i + 1)
    for uli, indices in uli_map.items():
        if len(indices) > 1:
            violations.append({
                "rule": "S305", "scope": "filing", "lar_index": None,
                "message": f"Duplicate ULI '{uli}' found in LAR records {indices}"
            })

    ts_lei = ts[14]

    # =================== PER-LAR RULES ===================

    for i, lar in enumerate(lars):
        idx = i + 1  # 1-indexed

        # S300 (LAR): Record Identifier must be 2
        if lar[0] != "2":
            violations.append({
                "rule": "S300", "scope": "lar", "lar_index": idx,
                "message": f"LAR Record Identifier is '{lar[0]}', expected '2'"
            })

        # S301: LAR LEI must match TS LEI
        if lar[1] != ts_lei:
            violations.append({
                "rule": "S301", "scope": "lar", "lar_index": idx,
                "message": f"LAR LEI '{lar[1]}' does not match TS LEI '{ts_lei}'"
            })

        uli = lar[2]
        lei = lar[1]

        # V608_1: ULI must begin with the record's own LEI
        if not uli.startswith(lei):
            violations.append({
                "rule": "V608_1", "scope": "lar", "lar_index": idx,
                "message": "ULI does not begin with the record's LEI"
            })

        # V609: ULI must be 23-45 chars, alphanumeric
        if not (23 <= len(uli) <= 45 and uli.isalnum()):
            violations.append({
                "rule": "V609", "scope": "lar", "lar_index": idx,
                "message": f"ULI length {len(uli)} outside [23,45] or not alphanumeric"
            })

        # V610_1: Application Date must be "NA" or valid YYYYMMDD
        app_date = lar[3]
        if app_date != "NA" and not is_valid_date(app_date):
            violations.append({
                "rule": "V610_1", "scope": "lar", "lar_index": idx,
                "message": f"Application Date '{app_date}' is not 'NA' or valid YYYYMMDD"
            })

        # V611: Loan Type in {1,2,3,4}
        if lar[4] not in ("1", "2", "3", "4"):
            violations.append({
                "rule": "V611", "scope": "lar", "lar_index": idx,
                "message": f"Loan Type '{lar[4]}' not in {{1,2,3,4}}"
            })

        # V612_1: Loan Purpose in {1,2,31,32,4,5}
        if lar[5] not in ("1", "2", "31", "32", "4", "5"):
            violations.append({
                "rule": "V612_1", "scope": "lar", "lar_index": idx,
                "message": f"Loan Purpose '{lar[5]}' not in {{1,2,31,32,4,5}}"
            })

        # V613_1: Preapproval in {1,2}
        if lar[6] not in ("1", "2"):
            violations.append({
                "rule": "V613_1", "scope": "lar", "lar_index": idx,
                "message": f"Preapproval '{lar[6]}' not in {{1,2}}"
            })

        # V614_1: Construction Method in {1,2}
        if lar[7] not in ("1", "2"):
            violations.append({
                "rule": "V614_1", "scope": "lar", "lar_index": idx,
                "message": f"Construction Method '{lar[7]}' not in {{1,2}}"
            })

        # V615_1: Occupancy Type in {1,2,3}
        if lar[8] not in ("1", "2", "3"):
            violations.append({
                "rule": "V615_1", "scope": "lar", "lar_index": idx,
                "message": f"Occupancy Type '{lar[8]}' not in {{1,2,3}}"
            })

        # V616: Loan Amount must be numeric and > 0
        try:
            amount = float(lar[9])
            if amount <= 0:
                violations.append({
                    "rule": "V616", "scope": "lar", "lar_index": idx,
                    "message": f"Loan Amount {amount} is not greater than 0"
                })
        except ValueError:
            violations.append({
                "rule": "V616", "scope": "lar", "lar_index": idx,
                "message": f"Loan Amount '{lar[9]}' is not numeric"
            })

        # V617: Action Taken in {1..8}
        if lar[10] not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            violations.append({
                "rule": "V617", "scope": "lar", "lar_index": idx,
                "message": f"Action Taken '{lar[10]}' not in {{1-8}}"
            })

        # V618: Action Taken Date must be valid YYYYMMDD
        if not is_valid_date(lar[11]):
            violations.append({
                "rule": "V618", "scope": "lar", "lar_index": idx,
                "message": f"Action Taken Date '{lar[11]}' is not valid YYYYMMDD"
            })

        # V619_1: If Preapproval=1, Action Taken must be in {1,2,3,4,5,7,8}
        if lar[6] == "1" and lar[10] not in ("1", "2", "3", "4", "5", "7", "8"):
            violations.append({
                "rule": "V619_1", "scope": "lar", "lar_index": idx,
                "message": f"Preapproval=1 but Action Taken '{lar[10]}' not in {{1,2,3,4,5,7,8}}"
            })

        # V620: If Action Taken in {7,8}, Preapproval must be 1
        if lar[10] in ("7", "8") and lar[6] != "1":
            violations.append({
                "rule": "V620", "scope": "lar", "lar_index": idx,
                "message": f"Action Taken='{lar[10]}' but Preapproval='{lar[6]}', expected '1'"
            })

        # V636_1: Sex of Applicant (field 51 = index 50) in {1,2,3,4,6}
        if lar[50] not in ("1", "2", "3", "4", "6"):
            violations.append({
                "rule": "V636_1", "scope": "lar", "lar_index": idx,
                "message": f"Sex of Applicant '{lar[50]}' not in {{1,2,3,4,6}}"
            })

        # V661: Lien Status (field 61 = index 60) in {1,2}
        if lar[60] not in ("1", "2"):
            violations.append({
                "rule": "V661", "scope": "lar", "lar_index": idx,
                "message": f"Lien Status '{lar[60]}' not in {{1,2}}"
            })

        # ---- Quality rules ----

        # Q601: Loan amount > 10,000,000
        try:
            amt = float(lar[9])
            if amt > 10_000_000:
                quality_flags.append({
                    "rule": "Q601", "lar_index": idx,
                    "message": f"Loan Amount {amt} exceeds 10,000,000"
                })
        except ValueError:
            pass

        # Q617: Action date earlier than application date
        if app_date != "NA" and is_valid_date(app_date) and is_valid_date(lar[11]):
            ad = datetime.strptime(app_date, "%Y%m%d")
            atd = datetime.strptime(lar[11], "%Y%m%d")
            if atd < ad:
                quality_flags.append({
                    "rule": "Q617", "lar_index": idx,
                    "message": f"Action Taken Date {lar[11]} is before Application Date {app_date}"
                })

    # =================== BUILD SUMMARY ===================

    all_rules = set()
    for v in violations:
        all_rules.add(v["rule"])
    for q in quality_flags:
        all_rules.add(q["rule"])

    summary = {
        "total_lars": len(lars),
        "violations_count": len(violations),
        "quality_flags_count": len(quality_flags),
        "rules_triggered": sorted(all_rules),
    }

    return {
        "violations": violations,
        "quality_flags": quality_flags,
        "summary": summary,
    }


def main():
    ts, lars = parse_filing("/app/filing.txt")
    report = validate(ts, lars)

    with open("/app/validation_report.json", "w") as f:
        json.dump(report, f, indent=2)

    s = report["summary"]
    print(f"Validation complete: {s['violations_count']} violations, "
          f"{s['quality_flags_count']} quality flags, "
          f"{s['total_lars']} LAR records")
    print(f"Rules triggered: {', '.join(s['rules_triggered'])}")


if __name__ == "__main__":
    main()
