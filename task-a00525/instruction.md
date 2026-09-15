The research project at `/app/` studies the computational hardness of n-Queens variants, including n-Queens Completion (QC) and the Excluded Diagonals Problem (EDP). The codebase in `/app/src/` includes a SAT encoder that produces incorrect results on some instances.

Complete the research pipeline:

- Fix the SAT encoder so it correctly handles all QC instances in `/app/data/qc_instances/`
- Extend the solver to handle EDP instances in `/app/data/edp_instances/`
- Run the phase transition experiment using parameters from `/app/experiments/config.json`
- Write all results to `/app/results/`

Known correct satisfiability values for all instances are in `/app/data/validation.json`. Output format conventions and available tools can be found by examining the existing codebase.