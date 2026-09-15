Three candidate Coherent Ising Machine (CIM) solver implementations for combinatorial optimization are in `/app/solvers/` (`alpha.py`, `beta.py`, `gamma.py`). Each reads problem instances from `/app/instances/` and solver parameters from `/app/config.toml`. Each candidate has defects affecting correctness or solution quality.

Six optimization instances span Ising spin-glass and QUBO (Quadratic Unconstrained Binary Optimization) models. Four are in JSON format in `/app/instances/`. Two additional instances in `/app/instances/raw/` require conversion from a text format — a Rust-based converter is in `/app/converter/`.

Evaluate each solver candidate by analyzing its code, running it against the instances, and comparing outputs. Identify the specific defects in each.

Produce:

1. `/app/verdict.json` — evaluation of each solver using this schema:
   ```json
   {
     "<solver_name>": {
       "has_defects": <bool>,
       "defect_categories": ["<category>", ...],
       "impact": "<description of how defects affect results>"
     }
   }
   ```
   Valid defect categories: `energy_computation`, `local_search`, `qubo_conversion`, `dynamics_parameters`, `numerical_stability`

2. `/app/solver.py` — a correct solver that combines the working components from the three candidates, free of all identified defects

3. `/app/results/<instance_name>.json` — near-optimal solutions for all 6 instances:
   - Ising: `{"spins": [s_0, ...], "energy": <float>}` where s_i ∈ {-1, +1}
   - QUBO: `{"bits": [x_0, ...], "energy": <float>}` where x_i ∈ {0, 1}

Energy formulas:
- Ising: H = Σ_{i<j} J_ij s_i s_j + Σ_i h_i s_i
- QUBO: E = Σ_i Q_ii x_i + Σ_{i<j} Q_ij x_i x_j

Reported energies must be self-consistent (exactly match the energy recomputed from the solution vector and instance data). Solutions must be near-optimal (within ~10–15% of the global minimum).