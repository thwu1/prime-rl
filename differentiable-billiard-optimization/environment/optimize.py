#!/usr/bin/env python3
"""Billiard shot optimizer — implement and compare gradient-based optimizers.

This script should:
1. Load the C-accelerated CDual class from dual_c
2. Load the problem definition from problem.json
3. Implement and run two optimization strategies (gradient descent and Adam)
4. Compare their convergence and select the better one
5. Write result.json with the optimal parameters and comparison data
"""

import json
import math
import sys

sys.path.insert(0, '/app')


def load_dual_backend():
    """Load the C-accelerated dual number backend.

    Returns the CDual class from the dual_c module.
    Exits with error if the C library is not available.
    """
    try:
        from dual_c import CDual
        return CDual
    except (ImportError, OSError) as e:
        print(f"Error: C dual-number backend unavailable: {e}")
        print("Make sure libdual.so is compiled in cdual/")
        sys.exit(1)


def compute_cost_and_grad(Dual, prob, vx, vy, component):
    """Compute cost and its gradient w.r.t. one velocity component.

    Uses dual numbers to compute the exact gradient of the cost function
    (squared distance from target ball's final position to target location)
    with respect to either vx or vy.

    Args:
        Dual: the dual number class (CDual)
        prob: problem definition dict
        vx, vy: current cue ball velocity components (float)
        component: 'vx' or 'vy' — which component to differentiate

    Returns:
        (cost_value, gradient) tuple of floats
    """
    from physics import simulate
    # TODO: Create dual-number positions for all balls and the cue ball
    # TODO: Create dual-number velocities — seed the component being
    #       differentiated with dual part 1.0, the other with 0.0
    # TODO: Run simulate() with table and restitution from prob
    # TODO: Compute cost = (bx - tx)^2 + (by - ty)^2
    #       where bx, by = target ball final position
    #       and tx, ty = prob['target_location']
    # TODO: Return (cost.real, cost.dual)
    pass


def optimize_gd(Dual, prob, lr=0.1, iterations=200):
    """Gradient descent optimizer with gradient clipping.

    Args:
        Dual: dual number class
        prob: problem definition
        lr: learning rate
        iterations: number of iterations

    Returns:
        dict with keys 'vx', 'vy', 'cost'
    """
    # TODO: Implement gradient descent
    # - Start from vx=3.0, vy=0.0
    # - Each iteration: compute gradients, clip to max norm 50.0
    # - Update: v -= lr * grad
    # - Track and return best (lowest cost) parameters found
    pass


def optimize_adam(Dual, prob, lr=0.05, iterations=200):
    """Adam optimizer.

    Args:
        Dual: dual number class
        prob: problem definition
        lr: learning rate
        iterations: number of iterations

    Returns:
        dict with keys 'vx', 'vy', 'cost'
    """
    # TODO: Implement Adam optimizer
    # - Start from vx=3.0, vy=0.0
    # - Use beta1=0.9, beta2=0.999, epsilon=1e-8
    # - Each iteration: compute gradients, update first/second moments,
    #   apply bias correction, update parameters
    # - Track and return best parameters found
    pass


def run():
    """Main entry point: run both optimizers, compare, and write results."""
    Dual = load_dual_backend()

    with open('/app/problem.json') as f:
        prob = json.load(f)

    # TODO: Run optimize_gd and optimize_adam on the problem
    # TODO: Compare their final costs
    # TODO: Select the optimizer achieving lower cost
    # TODO: Write /app/result.json with keys:
    #   optimal_vx (float), optimal_vy (float), final_cost (float),
    #   selected_optimizer ("gd" or "adam"),
    #   gd_final_cost (float), adam_final_cost (float)
    pass


if __name__ == '__main__':
    run()
