Build `/app/plr_analyze.py` to process chromatic pupillometry recordings following the Kelbsch et al. (2019) pupillography standards. Invoke as:

```
python3 /app/plr_analyze.py --input /app/data --output /app/results
```

**Input:** The `--input` directory contains `protocol.json` (stimulus timing, analysis windows, detection thresholds) and CSV recordings named `{condition}_{trial:02d}.csv` (e.g., `blue_01.csv`, `red_02.csv`) plus bilateral Horner assessment files `horner_left.csv`, `horner_right.csv`. Each CSV has columns `time_s,diameter_mm,stimulus` where `stimulus` is 0 (off) or 1 (on). Recordings contain blink artifacts and tracking noise requiring preprocessing.

**Output:** Write `<output_dir>/report.json` with this schema:

```json
{
  "conditions": {
    "<name>": {
      "n_valid_trials": int,
      "average": {
        "baseline_mm": float, "max_constriction_mm": float,
        "max_constriction_pct": float, "latency_s": float,
        "time_to_max_constriction_s": float,
        "max_constriction_velocity_mm_s": float,
        "redilation_velocity_mm_s": float, "t75_s": float_or_null,
        "pipr_6s_pct": float, "pipr_plateau_pct": float,
        "pipr_early_auc": float, "pipr_late_auc": float
      }
    }
  },
  "net_pipr_6s_pct": float,
  "horner_assessment": {
    "dilation_lag_4s_mm": float,
    "affected_eye": "left|right|none",
    "t75_left_s": float, "t75_right_s": float
  },
  "artifact_summary": {
    "<filename>": {"blinks_detected": int, "artifact_pct": float}
  }
}
```

**Specifications:**

- Detect and exclude blink artifacts (sudden diameter drops, physiologically implausible velocity transients) before parameter computation. Trials exceeding the artifact threshold in `protocol.json` are invalid and excluded from averaging.
- Baseline: mean diameter from clean pre-stimulus period.
- Relative normalization: `(baseline - diameter) / baseline * 100`.
- Maximum constriction velocity (MCV): peak absolute rate of diameter decrease during constriction.
- Redilation velocity: peak rate of diameter increase after stimulus offset.
- T75: time from maximum constriction until 75% of the constriction amplitude is recovered; `null` if the sustained post-illumination constriction prevents reaching 75% recovery.
- PIPR metrics are computed from the post-stimulus-offset period. AUC units are %*s. Net PIPR: blue minus red PIPR amplitude at the configured time point.
- Horner assessment: dilation lag is the absolute diameter difference between eyes at the configured post-offset time. Identify the affected eye (slower redilation). Report T75 per eye.
- All timing parameters and analysis windows must be read from `protocol.json`.
