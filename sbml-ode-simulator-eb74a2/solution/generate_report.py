#!/usr/bin/env python3
"""
Generate conformance_report.json by comparing simulator output against expected results.

"""

import csv
import json
import os


CASES = ["case_001", "case_002", "case_003", "case_004"]
MODELS_DIR = "/app/models"
TESTS_DIR = "/tests"


def parse_settings(path):
    settings = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            settings[key.strip()] = val.strip()
    return settings


def parse_csv_file(path):
    with open(path) as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        rows = []
        for row in reader:
            if any(row):
                rows.append([float(v.strip()) for v in row])
    return header, rows


def check_case(case_name):
    settings = parse_settings(os.path.join(MODELS_DIR, case_name, "settings.txt"))
    abs_tol = float(settings.get("absolute", "1e-7"))
    rel_tol = float(settings.get("relative", "0.0001"))

    expected_path = os.path.join(TESTS_DIR, f"{case_name}_expected.csv")
    output_path = os.path.join("/app", f"output_{case_name}.csv")

    if not os.path.exists(output_path):
        return "fail"

    _, exp_rows = parse_csv_file(expected_path)
    _, act_rows = parse_csv_file(output_path)

    if len(exp_rows) != len(act_rows):
        return "fail"

    for exp_row, act_row in zip(exp_rows, act_rows):
        if len(exp_row) != len(act_row):
            return "fail"
        for c_ij, u_ij in zip(exp_row, act_row):
            tol = abs_tol + rel_tol * abs(c_ij)
            if abs(c_ij - u_ij) > tol:
                return "fail"

    return "pass"


def main():
    report = {}
    for case in CASES:
        report[case] = check_case(case)
    with open("/app/conformance_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
