
"""
Deterministic circuit simulator for MIB evaluation.
DO NOT MODIFY this file.
"""

import json
import math
import hashlib


def _det_hash(s: str) -> int:
    """Deterministic hash using SHA-256."""
    return int(hashlib.sha256(s.encode('utf-8')).hexdigest(), 16)


class CircuitSimulator:
    """Simulates model behavior for a given set of active circuit edges.

    Uses ground-truth edge weights to compute a deterministic score
    that approximates what a real model would produce.
    """

    def __init__(self, config_path: str):
        with open(config_path, 'r') as f:
            self.config = json.load(f)

    def evaluate(self, active_edge_names: list, task_name: str) -> float:
        """Compute the raw model score for a circuit defined by active edges.

        Args:
            active_edge_names: List of edge name strings (e.g., ["embed->L0.H0", ...])
            task_name: Task identifier (e.g., "ioi", "mcqa")

        Returns:
            Raw (unnormalized) model score as a float.
        """
        task_cfg = self.config[task_name]
        gt_weights = task_cfg["ground_truth_weights"]
        total_gt_weight = sum(gt_weights.values())
        baseline = task_cfg["baseline_score"]
        corrupted = task_cfg["corrupted_score"]

        # Contribution from ground-truth edges
        gt_contribution = sum(gt_weights.get(e, 0.0) for e in active_edge_names)

        # Small deterministic perturbation from non-ground-truth edges
        noise = 0.0
        for e in active_edge_names:
            if e not in gt_weights:
                h = _det_hash(f"noise_{task_name}_{e}")
                noise += 0.003 * math.sin(h * 0.0001)

        frac = gt_contribution / total_gt_weight
        raw_score = corrupted + frac * (baseline - corrupted) + noise
        return raw_score
