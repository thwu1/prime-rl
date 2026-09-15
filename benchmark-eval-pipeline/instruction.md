The image benchmark evaluation system at `/app/` is incomplete. It must evaluate candidate image edits against ground-truth renders across multiple camera views, rank candidates, and produce structured JSON evaluation reports with statistical confidence intervals.

The interface stub is at `/app/evaluator.py`. Behavioral requirements and constraints are documented in `/app/SPEC.md`. Default evaluation parameters are in `/app/config.toml`.

Complete the implementation so that the full test suite passes.