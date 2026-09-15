A predictive maintenance system at `/app/` has a registered baseline model showing degraded production performance. The environment contains:

- `/app/data/` — Reference and production sensor datasets
- `/app/config.yaml` — Full pipeline configuration
- `/app/mlruns/` — MLflow tracking directory (URI `file:///app/mlruns`) with registered model `predictive_maintenance_model` under experiment `predictive_maintenance`
- `/app/baseline_run_id.txt` — Run ID of the baseline model

Build `/app/pipeline/run_pipeline.py` that reads `/app/config.yaml`, analyzes the data and model state, and produces three JSON reports in `/app/output/` conforming to the schemas below.

## `/app/output/drift_report.json`

```json
{
  "features": {
    "<feature_name>": {
      "ks_statistic": "<float [0,1]>",
      "ks_pvalue": "<float [0,1]>",
      "psi": "<float [0,inf)>",
      "kde_overlap": "<float [0,1]>",
      "is_drifted": "<bool>"
    }
  },
  "drifted_features": ["<str>"],
  "n_drifted": "<int>"
}
```

Must cover every feature listed in `config.yaml`. `n_drifted` equals the length of `drifted_features`.

## `/app/output/evaluation_report.json`

Produced when drift is detected.

```json
{
  "baseline": {
    "run_id": "<str>",
    "metrics": {"f1_score": "<float>", "precision": "<float>", "recall": "<float>", "accuracy": "<float>"},
    "fairness": {
      "equalized_odds_gap": "<float [0,1]>",
      "tpr_gap": "<float>", "fpr_gap": "<float>",
      "group_metrics": {"<group_value>": {"tpr": "<float>", "fpr": "<float>"}}
    }
  },
  "candidate": {
    "run_id": "<str>",
    "params": {},
    "metrics": {"f1_score": "<float>", "precision": "<float>", "recall": "<float>", "accuracy": "<float>"},
    "fairness": {
      "equalized_odds_gap": "<float [0,1]>",
      "tpr_gap": "<float>", "fpr_gap": "<float>",
      "group_metrics": {"<group_value>": {"tpr": "<float>", "fpr": "<float>"}}
    }
  },
  "comparison": {
    "f1_improvement_pct": "<float>",
    "f1_improvement_abs": "<float>"
  }
}
```

Retraining and evaluation parameters are defined in `config.yaml`. The MLflow experiment should contain logged runs for the hyperparameter sweep with their parameters and metrics.

## `/app/output/deployment_plan.json`

```json
{
  "decision": "<immediate|gradual|no_rollout|blocked|no_action>",
  "reason": "<str>",
  "rollout_schedule": "<array of {stage: int, traffic_pct: int, delay_hours: int} | null>"
}
```

Deployment rules are defined in `config.yaml` under `deployment.rollout_rules`. `rollout_schedule` is `null` when not deploying. `no_action` applies when no drift was detected.