A platform team needs to audit configuration drift between their Kustomize-managed desired state and live cluster state. The scoring specification is at `/app/SPEC.md`. Environment configurations are listed in `/app/audit.yaml`, Kustomize overlays are under `/app/kustomize/`, and live state YAML files are under `/app/live/`.

Build `/app/audit.py` that renders each environment's Kustomize overlay, matches resources against the corresponding live state, computes per-resource drift scores according to the SPEC, and writes results to `/app/output/drift_report.json`:

```json
{
  "environments": {
    "<env_name>": {
      "resources": {
        "<apiVersion>/<kind>/<name>": 0.xyz,
        ...
      },
      "mean": 0.xyz
    },
    ...
  },
  "aggregate_mean": 0.xyz
}
```

Resource keys use `apiVersion/kind/name` format (e.g., `apps/v1/Deployment/alpha-webapp`). Environment `mean` is the arithmetic mean of that environment's resource scores. `aggregate_mean` is the arithmetic mean of all individual resource scores across all environments.

Run: `cd /app && python3 audit.py`