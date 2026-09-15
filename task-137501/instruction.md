Raw user conversion event data is at `/app/data/conversions.csv` with columns: `user_id`, `cohort_week`, `channel`, `converted` (1=yes, 0=not observed), `days_to_event`. The dataset covers three acquisition channels (A, B, C) across 26 weekly cohorts.

The marketing team currently computes conversion rates as `sum(converted) / count(*)` per channel, but these numbers are unreliable — they shift whenever the analysis window changes and contradict the team's qualitative understanding of channel performance. Leadership needs statistically sound estimates of each channel's true long-term conversion probability, with uncertainty quantification, to inform budget allocation.

Build a Python package at `/app/conversion_model/` invocable as:

```
python3 -m conversion_model <input_csv> <output_json>
```

Run it on the provided dataset and write results to `/app/results.json`:

```json
{
  "<channel>": {
    "estimated_long_term_rate": <float in (0,1)>,
    "ci_lower": <float>,
    "ci_upper": <float>,
    "model_type": "<string identifying the model>"
  }
}
```

`estimated_long_term_rate` is the probability that a user from that channel will eventually convert given sufficient observation time. `ci_lower`/`ci_upper` define a 95% confidence interval for that estimate. The model must generalize — it should produce valid estimates on any dataset following the same CSV schema, not just the provided one.