"""
n-Queens Completion solver pipeline.

Encodes an instance as DIMACS CNF, invokes minisat, and decodes/validates the solution.
"""

import os
import subprocess
import tempfile

from encoder import encode


def solve(instance):
    """Solve an n-Queens Completion instance via SAT.

    Args:
        instance: Dict with "n" and "queens".

    Returns:
        Dict with "satisfiable" (bool) and "solution" (list of [r,c] or None).
    """
    n = instance["n"]
    cnf = encode(instance)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', delete=False) as f:
        f.write(cnf)
        cnf_path = f.name

    out_path = cnf_path + '.out'

    try:
        subprocess.run(
            ['minisat', cnf_path, out_path],
            capture_output=True,
            timeout=60
        )

        with open(out_path, 'r') as f:
            content = f.read().strip()

        lines = content.split('\n')
        if lines[0].strip() == 'SAT':
            # Collect positive literals from solution assignment
            positive_lits = set()
            for line in lines[1:]:
                for token in line.strip().split():
                    v = int(token)
                    if v == 0:
                        break
                    if v > 0:
                        positive_lits.add(v)

            # Decode: find primary variables that are true
            solution = []
            for i in range(n):
                for j in range(n):
                    v = i * n + j + 1
                    if v in positive_lits:
                        solution.append([i, j])

            # Validate the solution
            if len(solution) != n:
                return {"satisfiable": False, "solution": None}

            rows = set()
            cols = set()
            diags = set()
            antis = set()
            valid = True
            for r, c in solution:
                if r in rows or c in cols or (r + c) in diags or (r - c) in antis:
                    valid = False
                    break
                rows.add(r)
                cols.add(c)
                diags.add(r + c)
                antis.add(r - c)

            if not valid:
                return {"satisfiable": False, "solution": None}

            # Verify pre-placed queens are in solution
            for q in instance["queens"]:
                if q not in solution:
                    valid = False
            if not valid:
                return {"satisfiable": False, "solution": None}

            return {"satisfiable": True, "solution": sorted(solution)}
        else:
            return {"satisfiable": False, "solution": None}
    finally:
        os.unlink(cnf_path)
        if os.path.exists(out_path):
            os.unlink(out_path)
