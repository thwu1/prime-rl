"""
Validate solver output, convergence study, plot, and database.
"""
import json
import sys
import os
import sqlite3 as sql


def main():
    ok = True
    results_dir = '/app/results'

    # Check CSV result files exist and have content
    for name in ['sod', 'einfeldt', 'blast']:
        path = os.path.join(results_dir, f'{name}.csv')
        if not os.path.exists(path):
            print(f"FAIL: {path} not found")
            ok = False
            continue
        with open(path) as f:
            lines = f.readlines()
        if len(lines) < 50:
            print(f"FAIL: {path} has too few data points ({len(lines)} lines)")
            ok = False

    # Check convergence study results
    conv_path = os.path.join(results_dir, 'convergence.json')
    if not os.path.exists(conv_path):
        print(f"FAIL: {conv_path} not found")
        ok = False
    else:
        with open(conv_path) as f:
            conv = json.load(f)
        if not conv.get('pass', False):
            print(f"FAIL: convergence study did not pass")
            print(f"  rate = {conv.get('convergence_rate', 'N/A')}")
            print(f"  checks = {conv.get('checks', {})}")
            ok = False
        else:
            print(f"Convergence rate: {conv.get('convergence_rate')}")

    # Check convergence plot
    plot_path = os.path.join(results_dir, 'convergence.png')
    if not os.path.exists(plot_path):
        print(f"FAIL: {plot_path} not found")
        ok = False
    elif os.path.getsize(plot_path) < 1000:
        print(f"FAIL: {plot_path} appears empty or corrupt")
        ok = False
    else:
        print("Convergence plot: OK")

    # Check results database
    db_path = os.path.join(results_dir, 'results.db')
    if not os.path.exists(db_path):
        print(f"FAIL: {db_path} not found")
        ok = False
    else:
        try:
            conn = sql.connect(db_path)
            for table in ['sod', 'einfeldt', 'blast', 'convergence']:
                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                if count < 4:
                    print(f"FAIL: table {table} has only {count} rows")
                    ok = False
            conn.close()
            if ok:
                print("Results database: OK")
        except Exception as e:
            print(f"FAIL: database error: {e}")
            ok = False

    if ok:
        print("=== ALL VALIDATION CHECKS PASSED ===")
    else:
        print("=== VALIDATION FAILED ===")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
