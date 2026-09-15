Six benchmark linear programming problems from the Netlib collection are stored at `/app/data/`. The files use the legacy Netlib distribution encoding — they are **not** standard MPS files and cannot be read directly by LP solvers.

Produce a full optimality and basis analysis for each problem and write results to `/app/results.json`.

Problems: `afiro`, `blend`, `sc50a`, `sc50b`, `adlittle`, `kb2` (all minimization).

Required schema for `/app/results.json`:

    {
      "problems": {
        "<name>": {
          "optimal_value": <float>,
          "num_constraints": <int>,
          "num_variables": <int>,
          "num_basic_variables": <int>,
          "max_primal_infeasibility": <float>,
          "max_dual_infeasibility": <float>,
          "max_complementary_slackness_violation": <float>,
          "num_degenerate_basics": <int>,
          "has_alternative_optima": <bool>,
          "basis_condition_number_log10": <float>
        }
      },
      "ranking_by_optimal_value": ["<name1>", "<name2>", ...]
    }

Conventions:
- Constraint and variable counts follow the Netlib PROBLEM SUMMARY TABLE conventions (constraint count excludes the objective row; variable count is structural columns only).
- `basis_condition_number_log10`: log base 10 of the 1-norm condition number of the optimal basis matrix.
- `ranking_by_optimal_value`: all six problems sorted ascending by optimal objective value.