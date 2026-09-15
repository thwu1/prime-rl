A REST API server is available at `/app/api/server.pyc` (compiled bytecode — no readable source code) with its OpenAPI 3.0 specification at `/app/spec/openapi.json`. The API manages users, projects, tasks, and webhooks with API key authentication. Start it with `python3 /app/start_server.py &`.

Schemathesis is pre-installed. Use it with custom authentication handling and stateful link-based testing as your primary discovery engine, supplemented by targeted edge-case analysis to find server faults that property-based testing alone may miss. Authentication requires calling `POST /api/v1/auth/register` to obtain an API key for the `X-API-Key` header.

Create `/app/run_fuzzer.sh` (accepts base URL as `$1`, default `http://localhost:5000`) that produces:

- `/app/results/schemathesis_output/` — Schemathesis test artifacts (output logs, cassettes, or reports)
- `/app/results/report.json` — structured fault analysis report

Report schema (`/app/results/report.json`):
```json
{
  "operations_covered": [{"method": "GET", "path": "/api/v1/users/{user_id}"}],
  "faults": [
    {
      "method": "GET",
      "path": "/api/v1/users/{user_id}",
      "status_code": 500,
      "exception_type": "ZeroDivisionError",
      "exception_message": "division by zero"
    }
  ],
  "summary": {
    "total_ops": 21,
    "covered_ops": 18,
    "coverage_pct": 85.71,
    "unique_faults": 7
  }
}
```

Achieve ≥80% operation coverage (≥17/21 returning 2XX), discover ≥6 unique server-side faults (distinct operations returning 5XX) with correct `exception_type` classification from error response bodies. At least 3 distinct Python exception types must appear across discovered faults. Paths must use OpenAPI template placeholders (e.g., `/api/v1/users/{user_id}`).