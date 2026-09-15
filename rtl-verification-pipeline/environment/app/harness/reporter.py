"""Generates the mutation adequacy report."""
import json
import os
from harness.config import RESULTS_DIR


def generate_report(mutation_results, adequacy):
    """Generate the final report JSON."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    report = {"mutations": mutation_results}

    report_path = os.path.join(RESULTS_DIR, "report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    return report_path
