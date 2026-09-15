#!/usr/bin/env python3
"""Completed run_calibration.py — adds valve test processing."""

import json
import os
import sqlite3
import sys

sys.path.insert(0, '/app')

try:
    import tomllib
except ImportError:
    import tomli as tomllib

import flowcal


def init_db(sql_path, db_path):
    if os.path.exists(db_path):
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    with open(sql_path, 'r') as f:
        conn.executescript(f.read())
    conn.close()


def load_config(path='/app/config.toml'):
    with open(path, 'rb') as f:
        return tomllib.load(f)


def process_orifice_C(conn, tolerance):
    results = []
    cursor = conn.execute(
        "SELECT id, D, Do, rho, mu, m, taps, expected_C FROM orifice_C_tests"
    )
    for row in cursor.fetchall():
        test_id, D, Do, rho, mu, m, taps, expected = row
        computed = flowcal.orifice_discharge_coefficient(D, Do, rho, mu, m, taps)
        error_pct = 100.0 * abs(computed - expected) / abs(expected)
        results.append({
            "id": test_id,
            "category": "orifice_C",
            "computed": computed,
            "expected": expected,
            "error_pct": error_pct,
            "status": "pass" if error_pct < tolerance else "fail"
        })
    return results


def process_orifice_eps(conn, tolerance):
    results = []
    cursor = conn.execute(
        "SELECT id, D, Do, P1, P2, k, expected_eps FROM orifice_eps_tests"
    )
    for row in cursor.fetchall():
        test_id, D, Do, P1, P2, k, expected = row
        computed = flowcal.orifice_expansibility(D, Do, P1, P2, k)
        error_pct = 100.0 * abs(computed - expected) / abs(expected)
        results.append({
            "id": test_id,
            "category": "orifice_eps",
            "computed": computed,
            "expected": expected,
            "error_pct": error_pct,
            "status": "pass" if error_pct < tolerance else "fail"
        })
    return results


def process_orifice_flow(conn, tolerance):
    results = []
    cursor = conn.execute(
        "SELECT id, D, Do, P1, P2, rho, mu, k, taps, expected_m "
        "FROM orifice_flow_tests"
    )
    for row in cursor.fetchall():
        test_id, D, Do, P1, P2, rho, mu, k, taps, expected = row
        computed = flowcal.solve_orifice_flow_rate(D, Do, P1, P2, rho, mu, k, taps)
        error_pct = 100.0 * abs(computed - expected) / abs(expected)
        results.append({
            "id": test_id,
            "category": "orifice_flow",
            "computed": computed,
            "expected": expected,
            "error_pct": error_pct,
            "status": "pass" if error_pct < tolerance else "fail"
        })
    return results


def process_valve_liquid(conn, tolerance):
    results = []
    cursor = conn.execute(
        "SELECT id, rho, Psat, Pc, mu, P1, P2, Q, D1, D2, d, FL, Fd, expected_Kv "
        "FROM valve_liquid_tests"
    )
    for row in cursor.fetchall():
        test_id, rho, Psat, Pc, mu, P1, P2, Q, D1, D2, d, FL, Fd, expected = row
        computed = flowcal.size_liquid_valve(
            rho, Psat, Pc, mu, P1, P2, Q,
            D1=D1, D2=D2, d=d, FL=FL, Fd=Fd
        )
        error_pct = 100.0 * abs(computed - expected) / abs(expected)
        results.append({
            "id": test_id,
            "category": "valve_liquid",
            "computed": computed,
            "expected": expected,
            "error_pct": error_pct,
            "status": "pass" if error_pct < tolerance else "fail"
        })
    return results


def process_valve_gas(conn, tolerance):
    results = []
    cursor = conn.execute(
        "SELECT id, T, MW, mu, gamma, Z, P1, P2, Q, D1, D2, d, FL, Fd, xT, expected_Kv "
        "FROM valve_gas_tests"
    )
    for row in cursor.fetchall():
        test_id, T, MW, mu, gamma, Z, P1, P2, Q, D1, D2, d, FL, Fd, xT, expected = row
        computed = flowcal.size_gas_valve(
            T, MW, mu, gamma, Z, P1, P2, Q,
            D1=D1, D2=D2, d=d, FL=FL, Fd=Fd, xT=xT
        )
        error_pct = 100.0 * abs(computed - expected) / abs(expected)
        results.append({
            "id": test_id,
            "category": "valve_gas",
            "computed": computed,
            "expected": expected,
            "error_pct": error_pct,
            "status": "pass" if error_pct < tolerance else "fail"
        })
    return results


PROCESSORS = {
    "orifice_C": process_orifice_C,
    "orifice_eps": process_orifice_eps,
    "orifice_flow": process_orifice_flow,
    "valve_liquid": process_valve_liquid,
    "valve_gas": process_valve_gas,
}


def main():
    config = load_config()
    tolerance = config['calibration']['tolerance_pct']
    output_path = config['calibration']['output_path']
    groups = config['tests']['groups']

    sql_path = '/app/data/reference_data.sql'
    db_path = '/app/data/calibration.db'
    init_db(sql_path, db_path)

    conn = sqlite3.connect(db_path)
    all_results = []

    for group in groups:
        processor = PROCESSORS.get(group)
        if processor:
            all_results.extend(processor(conn, tolerance))

    conn.close()

    passed = sum(1 for r in all_results if r['status'] == 'pass')
    failed = sum(1 for r in all_results if r['status'] == 'fail')

    report = {
        "test_results": all_results,
        "summary": {
            "total": len(all_results),
            "passed": passed,
            "failed": failed
        }
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {output_path}")
    print(f"Total: {len(all_results)}, Passed: {passed}, Failed: {failed}")


if __name__ == '__main__':
    main()
