"""Runner for external SAT solvers.

Wraps invocation of a DIMACS CNF solver and parses its output.
"""

import subprocess
import os

# Default solver binary — must be installed in PATH
SOLVER_CMD = "minisat"


def run_solver(dimacs_path, output_path):
    """Run the SAT solver on a DIMACS CNF file.

    Args:
        dimacs_path: Path to the .cnf input file
        output_path: Path where the solver writes its assignment

    Returns:
        (satisfiable, positive_vars): bool and set of positive variable indices
    """
    subprocess.run(
        [SOLVER_CMD, dimacs_path, output_path],
        capture_output=True,
        text=True,
    )

    with open(output_path) as f:
        lines = f.readlines()

    if not lines:
        return False, set()

    if lines[0].strip() == "SAT":
        if len(lines) > 1:
            vals = list(map(int, lines[1].strip().split()))
            positive = {v for v in vals if v > 0}
            return True, positive
        return True, set()
    return False, set()


def check_solver_available():
    """Check if the SAT solver binary is available in PATH."""
    try:
        subprocess.run(
            [SOLVER_CMD, "--help"],
            capture_output=True,
            text=True,
        )
        return True
    except FileNotFoundError:
        return False
