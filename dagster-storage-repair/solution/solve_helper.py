#!/usr/bin/env python3
"""
Deploy and execute all fix scripts.

"""
import shutil
import subprocess
import sys

DEPLOYMENTS = [
    ("/solution/repair_db.py", "/app/repair_db.py"),
    ("/solution/optimize_db.py", "/app/optimize_db.py"),
    ("/solution/retention.py", "/app/retention.py"),
    ("/solution/reconciliation_fixed.py", "/app/pipeline/reconciliation.py"),
]

SCRIPTS_TO_RUN = [
    "/app/repair_db.py",
    "/app/optimize_db.py",
    "/app/retention.py",
]


def main():
    for src, dst in DEPLOYMENTS:
        shutil.copy2(src, dst)
        print("Deployed {} -> {}".format(src, dst))

    for script in SCRIPTS_TO_RUN:
        print("Running {} ...".format(script))
        result = subprocess.run(
            [sys.executable, script], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("FAILED: {}".format(result.stderr))
            sys.exit(1)
        print("  OK")


if __name__ == "__main__":
    main()
