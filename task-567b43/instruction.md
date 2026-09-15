A simplified C2 teamserver at `/app/teamserver/` implements operator and service-account authentication, agent binary compilation, beacon loot handling, and post-exploitation module compilation. Perform a comprehensive security assessment that combines automated SAST with manual expert review, evaluates coverage gaps in automated tooling, and fills those gaps with a custom analysis tool.

## Deliverables

**`/app/bandit_baseline.json`** — Raw JSON output from running `bandit` against `/app/teamserver/` (bandit is pre-installed). This establishes the automated analysis baseline.

**`/app/scanner/vuln_scanner.py`** — Custom Python vulnerability scanner built on the `ast` module that detects vulnerability patterns bandit misses (logic bugs, incomplete sanitization, unsafe fallback patterns). Must accept a directory path as its sole CLI argument and output JSON to stdout conforming to this schema:

```json
{
  "findings": [
    {
      "file": "<string: filename>",
      "line": "<int: line number>",
      "rule_id": "<string: unique rule identifier>",
      "severity": "<string: one of critical|high|medium|low>",
      "message": "<string: description of the finding>"
    }
  ]
}
```

The scanner must produce findings when run against the vulnerable code and zero findings when run against correctly patched code.

**`/app/assessment.json`** — Structured security assessment conforming to this schema (all fields required):

```json
{
  "automated_baseline": {
    "tool": "<string: tool name>",
    "total_findings": "<int: total findings from automated scan>",
    "high_severity_count": "<int: high/medium severity findings>",
    "coverage_gaps": "<string: analysis of what automated scanning missed and why>"
  },
  "vulnerabilities": [
    {
      "id": "<int: sequential starting from 1>",
      "cwe_id": "<string: format CWE-NNN, e.g. CWE-78>",
      "title": "<string: descriptive title>",
      "affected_file": "<string: relative path from /app/, e.g. teamserver/auth.py>",
      "affected_function": "<string: ClassName.method_name>",
      "cvss_vector": "<string: CVSS:3.1/AV:_/AC:_/PR:_/UI:_/S:_/C:_/I:_/A:_>",
      "cvss_score": "<float: CVSS 3.1 base score computed from the vector, 0.0-10.0>",
      "severity_rating": "<string: one of critical|high|medium|low>",
      "description": "<string: detailed description of the vulnerability>",
      "root_cause": "<string: the fundamental programming error>",
      "detection_method": "<string: one of automated|manual|both>"
    }
  ],
  "attack_chains": [
    {
      "chain_id": "<int: sequential>",
      "name": "<string: descriptive chain name>",
      "vulnerability_sequence": ["<int: vulnerability id references>"],
      "combined_impact": "<string: impact of the chained exploitation>",
      "likelihood": "<string: one of high|medium|low>"
    }
  ],
  "remediation_priority": ["<int: vulnerability ids in recommended fix order>"]
}
```

CVSS severity thresholds: critical >= 9.0, high 7.0-8.9, medium 4.0-6.9, low 0.1-3.9. Scores must be computed from the vector using the CVSS v3.1 base score formula. Attack chains must describe how individual vulnerabilities combine for amplified impact.

**`/app/exploits/`** — At least four Python exploit scripts (one per vulnerability). Each must demonstrate the vulnerability by exercising the original code at `/app/teamserver/` and exit with code 0 on successful exploitation.

**`/app/patched/`** — Fixed copies of each vulnerable module (`auth.py`, `builder.py`, `handlers.py`, `modules.py`). Patches must eliminate vulnerabilities while preserving all legitimate functionality.

## Context

- `/app/teamserver/app.py` shows how modules integrate; read it to understand data flow and caller assumptions.
- `/app/config.json` has the teamserver configuration.
- Agent templates are in `/app/templates/`, module build files in `/app/modules/`.