`/app/audit.py` scans HTML files and produces a JSON conformance report based on ICT Testing Baseline checks against WCAG 2.1 Level AA. The tool has defects that cause incorrect PASS/FAIL classifications.

Diagnose and fix all defects in `/app/audit.py`. The corrected tool must produce accurate results for every page in `/app/pages/` and generalize correctly to arbitrary HTML.

## Environment

- `/app/audit.py` — the audit tool (defective)
- `/app/pages/` — HTML pages with various accessibility patterns
- `/app/baseline_wcag_map.json` — baseline test ID to WCAG success criteria mapping

## Deliverable

A corrected `/app/audit.py` and the report it generates:

    python3 /app/audit.py /app/pages/ /app/report.json

Report schema:

    {
      "pages": {
        "<filename>": {
          "findings": [
            {"test_id": "...", "result": "PASS|FAIL", "wcag_sc": "...", "element": "...", "message": "..."}
          ]
        }
      }
    }