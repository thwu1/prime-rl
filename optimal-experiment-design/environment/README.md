# Experiment Design Optimizer

Computes D-optimal, A-optimal, and E-optimal designs for a linear
measurement model y = v^T theta + epsilon.

The Fisher Information Matrix for design weights w is:

    FIM(w) = sum_i w_i * v_i v_i^T

Design weights must satisfy: w_i >= 0, sum w_i = 1,
w_i <= max_per_experiment / budget.

## Files
- experiments.npy: candidate experiment vectors (m x d)
- config.json: problem parameters (dimension, budget, caps)
- optimizer.py: optimization pipeline

## Usage
    python3 /app/optimizer.py

## Output
results.json with relaxed designs, integer allocations,
cross-efficiency matrix, and robust experiment indices.
