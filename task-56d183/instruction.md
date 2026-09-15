Implement the complete SMT-COMP 2026 Single Query Track scoring engine.

The scoring specification is at `/app/scoring_spec.md`. The competition input data is at `/app/competition_data.json`. The required output schema is at `/app/output_schema.md`.

Your program must read the competition data, apply every scoring rule from the specification (benchmark scoring, disagreement removal, parallel and sequential division scoring, PAR-2 scores, all three competition-wide rankings, and derived solver eligibility), and write the results to `/app/output.json` conforming exactly to the output schema.

Key requirements:
- Correctly identify and remove benchmarks with unknown status where sound solvers disagree (Section 5)
- Compute per-benchmark parallel score tuples (e, n, w, c) per Section 3
- Derive sequential scores by imposing virtual CPU time limit equal to wall-clock time limit T (Section 4)
- Sum benchmark scores to division scores and rank solvers using the lexicographic ordering (Section 5)
- Compute PAR-2 division scores with 2T / 2mT penalties for unsolved benchmarks (Section 6)
- Compute Best Overall ranking with squared normalized correctness scores and log10 scaling (Section 7.1)
- Compute Biggest Lead ranking using correctness and time ratios (Section 7.2)
- Compute Largest Contribution ranking via Virtual Best Solver contribution analysis (Section 7.3)
- Determine derived solver eligibility: 10% PAR-2 wallclock improvement threshold per division and competition-wide (Section 8)