A robotics lab's simulation and real-world manipulation policy evaluation data is stored in a normalized SQLite database at `/app/eval.db`. No schema documentation is provided.

`/app/context/methodology.md` describes the evaluation framework and the statistical metrics used to assess sim-to-real transfer quality. `/app/context/output_format.md` specifies the required JSON output structure and visualization requirements.

Produce:

1. `/app/results.json` — Complete statistical comparison of two simulation evaluation approaches against real-world performance, following the output specification.
2. `/app/plots/sim_vs_real.png` — Scatter plot generated with `gnuplot` showing simulated vs. real-world success rates for both approaches, with a diagonal reference line, axis labels, and a legend distinguishing the two approaches.

Not all data in the database is suitable for analysis — inspect experiment metadata and researcher annotations to determine which records to include.