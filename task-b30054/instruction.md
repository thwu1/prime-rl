An ecommerce platform consisting of three microservices (frontend, api-server, worker) and supporting Kubernetes infrastructure has its complete manifest set in `/app/manifests/`. The manifests were prepared by a junior engineer and have never deployed successfully — cross-resource dependencies are broken in multiple ways that would prevent correct deployment and operation of the application.

Perform a comprehensive audit, remediate all defects, and build a reusable validation tool.

Produce:

1. **`/app/fixed/`** — Corrected copies of every manifest file. Preserve original filenames, resource kinds, and resource names. All namespace-scoped resources must remain in the `ecommerce` namespace.

2. **`/app/audit.json`** — Structured report of every defect found and remediated:

```json
{
  "findings": [
    {
      "file": "<filename>",
      "resource": "<Kind>/<name>",
      "severity": "critical|high|medium",
      "category": "<free-text category>",
      "description": "<what is wrong and what you changed>"
    }
  ],
  "total_issues": <int>
}
```

3. **`/app/validate.py`** — A general-purpose Kubernetes manifest consistency checker that works on any manifest directory, not just this application's manifests.

   - Invocation: `python3 /app/validate.py <manifest-directory>`
   - Parses all `.yaml`/`.yml` files in the target directory (multi-document YAML supported)
   - Stdout JSON: `{"issues": [{"resource": "Kind/name", "check": "<check-name>", "message": "<desc>"}], "total": <int>}`
   - Exit 0 if no issues found, non-zero otherwise
   - Must detect defects when run against `/app/manifests/` and report clean for `/app/fixed/`