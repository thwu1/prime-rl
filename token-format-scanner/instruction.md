A security team has reported a potential credential leak affecting a company's infrastructure. Authentication tokens conforming to a documented format may have been exposed across multiple systems. Conduct a comprehensive forensic investigation of all provided data sources, identify every token instance that matches the format specification, verify each token's integrity, and produce a consolidated incident report.

## Environment

- `/app/spec.md` — Token format reference documentation
- `/app/known_valid.json` — Calibration set of tokens with verified integrity
- `/app/corpus/` — Files recovered from the company's infrastructure in heterogeneous formats. Tokens may be plaintext, encoded, or encrypted. Not all apparent credentials belong to the format under investigation. The directory also contains credentials from unrelated services that must not be reported.
- `/app/repo/` — A git repository from the development team. The current state of the working tree does not necessarily reflect everything that has passed through this repository. Examine the full object store — including objects not reachable from any branch tip.
- `/app/audit/http_requests.db` — A SQLite database of HTTP request/response audit logs captured by an API gateway. Multiple tables may contain relevant data. Token values may appear in encoded form within headers, cookies, request bodies, or URL parameters.

## Deliverable

Produce `/app/incident_report.json` with the following structure:

```json
{
  "findings": [
    {
      "token": "<full token string>",
      "token_type": "<3-letter prefix>",
      "checksum_valid": true | false,
      "source": "<description of where the token was found>",
      "vector": "file | git_history | audit_db"
    }
  ],
  "summary": {
    "total_findings": <int>,
    "valid_tokens": <int>,
    "invalid_checksums": <int>,
    "by_type": {"ghp": <int>, "gho": <int>, ...},
    "by_vector": {"file": <int>, "git_history": <int>, "audit_db": <int>}
  }
}
```

Findings must be deduplicated by token value — report each unique token exactly once. Include every token that matches the documented prefix pattern, whether or not its integrity check passes.