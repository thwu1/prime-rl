A multi-container Discourse Docker deployment at `/app/` is misconfigured: PostgreSQL crashes under concurrent load, outbound emails silently drop, and TLS handshake errors appear on the web frontend. Three container definitions live in `/app/containers/` (`app.yml`, `web.yml`, `data.yml`). Pristine copies of these (broken) configs are preserved at `/app/containers_backup/`.

An existing bash precheck script (`/app/launcher`) was meant to validate the deployment but is itself buggy — it reports zero issues against the broken configs. System metadata (`/app/system_info.json`), deployment constraints (`/app/constraints.json`), a bundled-plugins manifest (`/app/bundled_plugins.txt`), and a reference standalone config (`/app/samples/standalone.yml`) document the deployment requirements.

Design and implement a Python-based configuration auditor at `/app/auditor.py` that replaces the broken precheck. The auditor must:

- Accept a config directory path as its sole CLI argument
- Validate all `.yml` container definitions against system constraints, the bundled-plugins manifest, and Discourse deployment conventions
- Detect and categorize all configuration defects including cross-container issues
- Write a structured JSON report to `/app/audit_report.json` with this schema:

```json
{
  "issues": [{"file": "...", "category": "...", "severity": "error|warning", "description": "..."}],
  "summary": {"total": N, "errors": N, "warnings": N, "files_scanned": N}
}
```

- Exit non-zero when any issues are found, exit 0 when clean

Also fix all configuration defects in `/app/containers/`.

When complete:
- `python3 /app/auditor.py /app/containers_backup/` must identify ≥10 distinct issues across multiple categories and exit non-zero
- `python3 /app/auditor.py /app/containers/` must report zero issues and exit 0