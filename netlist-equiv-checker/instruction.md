Four teams submitted optimized netlists for two ASAP7 designs (`aes_cipher_top` and `jpeg_encoder`) in the ISPD 2026 Post-Placement Buffering and Sizing Contest.

Evaluation data is organized under `/app/`:
- `/app/logs/` — OpenROAD evaluation log files for baseline and team submissions
- `/app/netlists/` — Pre- and post-optimization netlists for each submission
- `/app/tools/` — Contest evaluation utilities
- `/app/data/` — Cell library data and scoring configuration
- `/app/docs/` — Scoring methodology documentation

Determine the correct Design Score for each team submission across both designs and produce the contest leaderboard at `/app/leaderboard.json`:

```json
{
  "rankings": [
    {"rank": 1, "team": "<name>", "total_score": <float>, "aes_cipher_top": <float>, "jpeg_encoder": <float>},
    ...
  ]
}
```

Per-design and total scores should be rounded to 2 decimal places. Teams are ranked by descending total score.