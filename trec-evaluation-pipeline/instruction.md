`/app/campaign/` contains relevance judgments (`qrels`) and system submissions (`sys_*.txt`) from a TREC-style shared retrieval evaluation in standard TREC format. The `trec_eval` tool source code is at `/app/trec_eval/` (uncompiled).

Not all submissions are suitable for fair comparative evaluation. Audit the campaign, identify and exclude every problematic submission, then evaluate and rank the remaining trustworthy systems.

Write `/app/output/audit.json`:

```json
{
  "disqualified": {},
  "valid_runs": [],
  "metrics": {},
  "ranking": []
}
```

- `disqualified` -- `{<run_id>: "<concise reason>"}` for each excluded submission.
- `valid_runs` -- alphabetically sorted IDs of all trustworthy submissions.
- `metrics` -- `{"map": <float>, "ndcg_cut_10": <float>, "P_5": <float>}` per valid run.
- `ranking` -- valid runs ordered best-to-worst by MAP.