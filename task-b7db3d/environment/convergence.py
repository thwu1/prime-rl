"""Convergence analysis for DFG sampling strategies.

Evaluates three importance sampling strategies (ggx_is, cosine, uniform)
across roughness bands [0.1, 0.3, 0.5, 0.7, 0.9] to determine which
strategy converges fastest at each roughness level.

Evaluation methodology:
1. Compute reference DFG at high sample count (REFERENCE_SAMPLES) using GGX IS
2. For each strategy, compute DFG at EVAL_SAMPLES samples
3. Compute RMSE = sqrt((dx^2 + dy^2) / 2) against reference
4. Rank strategies by RMSE (lowest = best)

Output format (convergence_report.json):
{
    "roughness_bands": {
        "0.1": {
            "ranking": ["ggx_is", "cosine", "uniform"],
            "rmse": {"ggx_is": <float>, "cosine": <float>, "uniform": <float>}
        },
        ...
    }
}
"""
import json
import math

ROUGHNESS_BANDS = [0.1, 0.3, 0.5, 0.7, 0.9]
REFERENCE_SAMPLES = 8192
EVAL_SAMPLES = 1024
TEST_NOV = 0.5


def rank_strategies_for_roughness(roughness):
    """Evaluate and rank strategies for a given roughness.

    Returns dict with 'ranking' (list) and 'rmse' (dict).
    """
    raise NotImplementedError

def generate_report():
    """Generate complete convergence report for all roughness bands.

    Returns the report dict.
    """
    raise NotImplementedError
