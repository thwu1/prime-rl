#!/usr/bin/env python3
"""Apply the refactored solution: decompose monolith into modules.

"""

import json
import shutil
import subprocess
import sys

try:
    from glob import glob
except ImportError:
    import glob as _g
    glob = _g.glob


def validate_complexity(max_cc=5):
    """Run radon and verify all functions are within CC threshold."""
    py_files = glob("/app/*.py")
    excluded = {"__init__.py", "run_scenario.py"}
    ok = True
    for fpath in py_files:
        fname = fpath.rsplit("/", 1)[-1]
        if fname in excluded:
            continue
        result = subprocess.run(
            ["radon", "cc", "-s", "-j", fpath],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("radon failed on {}: {}".format(fname, result.stderr))
            ok = False
            continue
        data = json.loads(result.stdout)
        for filepath, blocks in data.items():
            for block in blocks:
                if block["complexity"] > max_cc:
                    print("VIOLATION: {} {}.{}: CC={}".format(
                        fname, block["type"], block["name"],
                        block["complexity"]))
                    ok = False
                if "methods" in block:
                    for method in block["methods"]:
                        if method["complexity"] > max_cc:
                            print("VIOLATION: {} {}.{}: CC={}".format(
                                fname, block["name"],
                                method["name"],
                                method["complexity"]))
                            ok = False
    return ok


def main():
    modules = {
        "inventory.py": "/app/inventory.py",
        "pricing.py": "/app/pricing.py",
        "persistence.py": "/app/persistence.py",
        "legacy_system_facade.py": "/app/legacy_system.py",
    }
    for src_name, dst in modules.items():
        src = "/solution/{}".format(src_name)
        shutil.copy(src, dst)
        print("Wrote {}".format(dst))

    if not validate_complexity():
        print("ERROR: Cyclomatic complexity exceeds threshold")
        sys.exit(1)

    print("All functions within CC <= 5")


if __name__ == "__main__":
    main()
