`/app/target.py` is a MiniCalc interpreter containing multiple correctness bugs. `/app/reference.py` is the correct implementation of the same language. `/app/seeds.json` has example MiniCalc programs. An input exposes a bug when `target.execute(input)` and `reference.execute(input)` produce different outputs.

Build an automated system at `/app/pipeline.py` that:

1. **Discovers failure-inducing inputs**: Automatically generate MiniCalc programs that trigger behavioral differences between the target and reference. Find at least 5 distinct failure-inducing inputs spanning at least 2 different categories of output difference (e.g., numeric vs boolean vs string).

2. **Ranks suspicious lines**: For each executable line of `/app/target.py`, compute a suspiciousness score in [0.0, 1.0] indicating the likelihood that line contributes to observed failures.

3. **Minimizes test cases**: For each discovered failure, produce the shortest input that still triggers the same behavioral difference. In a properly minimized input, removing any single character should cause the difference to disappear.

Write results to `/app/results/`:
- `crashes.json`: `[{"input": str, "target_output": str, "reference_output": str}, ...]`
- `rankings.json`: `[{"location": [filepath, lineno], "score": float}, ...]` sorted descending by score
- `minimized.json`: `[{"original": str, "minimized": str, "target_output": str, "reference_output": str}, ...]`

Entry point: `python3 /app/pipeline.py`