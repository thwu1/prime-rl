The directory `/app/` contains an evaluation pipeline for a code optimization benchmark. It should extract data from a SQLite database, compute performance metrics, detect reward-hacking patches, and produce a ranked leaderboard with bootstrap confidence intervals.

The pipeline spans two layers:

- **Data extraction layer** (`/app/extract_data.sh`): queries `/app/data/benchmark.db` using `sqlite3`, transforms the output with `jq`, and produces `/app/data/results.json`
- **Computation layer** (`/app/pipeline/`): Python modules that process `results.json` to compute speedups, evaluate OPT@K metrics, detect hacks, and rank models

Running `bash /app/run.sh` produces incorrect results due to bugs in both layers. The correct final ranking by hack-adjusted OPT@2 is:

```
1. Gamma
2. Alpha
3. Delta
4. Beta
```

The benchmark database can be inspected directly:
```
sqlite3 /app/data/benchmark.db ".schema"
sqlite3 /app/data/benchmark.db ".tables"
sqlite3 /app/data/benchmark.db "SELECT * FROM tasks"
```

Reference materials:
- `/app/docs/metric_analysis.md` -- analysis of speedup aggregation method tradeoffs
- `/app/data/labeled_patches.json` -- labeled examples of hack vs. legitimate optimization patches with category explanations
- `/app/docs/output_schema.json` -- required output format including confidence interval fields

The hack detection module (`/app/pipeline/hack_detector.py`) is a stub returning `False` for all patches. Implement detection rules that generalize from the labeled examples to the unlabeled benchmark patches. Bootstrap confidence intervals for hack-adjusted OPT@2 are also unimplemented.

Fix all bugs across both layers and implement all missing functionality so that `bash /app/run.sh` writes a correct leaderboard to `/app/output/leaderboard.json`.