`/app/scorer.py` evaluates temporal activity detection system output against ground-truth reference annotations, producing per-activity and aggregated metric CSVs. The scorer contains defects that cause incorrect numerical results.

Run the scorer with:

```
python3 /app/scorer.py \
    --reference /app/data/reference.json \
    --system-output /app/data/system_output.json \
    --activity-index /app/data/activity_index.json \
    --file-index /app/data/file_index.json \
    --scoring-parameters /app/data/scoring_parameters.json \
    --output-dir /app/output
```

Verified reference outputs are in `/app/expected/`. Diagnose and fix all defects so that the output CSVs match the expected files within absolute tolerance 0.002. The corrections must generalize to arbitrary valid inputs and scoring parameter configurations.