"""Runs compiled simulations."""
import subprocess
import os
from harness.config import RESULTS_DIR


def run_simulation(mutation_id, binary_path):
    """Run the compiled simulation binary."""
    log_dir = os.path.join(RESULTS_DIR, mutation_id)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "simulation.log")

    result = subprocess.run([binary_path])

    with open(log_path, "w") as f:
        f.write(getattr(result, "stdout", "") or "")

    return {"returncode": result.returncode, "log_path": log_path}
