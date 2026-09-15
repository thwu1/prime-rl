A numerical experiments workspace at `/app/lab/` was used to generate calibration constants for a simulation pipeline. The pipeline has been producing incorrect results, traced to errors in some of the computed constants.

Audit the workspace: determine which experiments produce correct values and which contain numerical errors. For experiments with errors, compute the correct value independently.

Write your findings to `/app/audit_report.json`:

```json
{
  "<experiment_name>": {
    "value": <correct_numerical_value>,
    "original_is_correct": <boolean>
  },
  ...
}
```

All floating-point values must be accurate to at least 10 significant digits. Integer values must be exact. The `original_is_correct` field must accurately indicate whether the experiment's original output was correct (`true`) or contained a numerical error (`false`).