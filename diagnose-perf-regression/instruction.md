A production data pipeline ("dataflow") suffered a throughput regression from 10K to 2K req/s after deploying v2.3.1. A junior SRE performed a differential flame graph analysis and filed a report at `/app/analysis/engineer_report.md`. Two hotfixes were subsequently applied. Throughput only recovered to ~2.5K req/s. The team suspects the analysis may contain errors.

Available at `/app/`:
- `src/` — v2.3.1 source code (6 C files, pre-hotfix state)
- `profiles/baseline.folded` — CPU profile from healthy v2.3.0 (folded stack format)
- `profiles/incident.folded` — CPU profile after v2.3.1 deployment
- `profiles/after_hotfix.folded` — CPU profile after both hotfixes applied
- `analysis/` — Engineer's report, pre-generated differential data, methodology notes
- `hotfixes/hotfix_a.patch`, `hotfixes/hotfix_b.patch` — Applied patches
- `FlameGraph/` — Brendan Gregg's FlameGraph tools (`difffolded.pl`, `flamegraph.pl`)

Perform an independent forensic analysis. Evaluate the engineer's methodology and conclusions, verify whether the pre-generated differential analysis is correct, classify each significant code change between v2.3.0 and v2.3.1 as a genuine performance bug or an intentional modification, determine whether each hotfix was effective, and identify any performance issues that are not visible in CPU-sampled profiles.

Write your findings to `/app/forensic_report.json`:

    {
      "flamegraph_correction": {
        "error_description": "<what was wrong with the pre-generated differential analysis>",
        "corrected_diff_path": "<absolute path to a corrected differential flame graph SVG you generated>"
      },
      "issues": [
        {
          "function": "<leaf function name>",
          "classification": "bug" or "intentional",
          "bug_type": "<type if classification is bug, else null>",
          "source_file": "<C source filename from src/>",
          "cpu_profile_visibility": "visible" or "hidden",
          "baseline_cpu_samples": <int from baseline profile>,
          "incident_cpu_samples": <int from incident profile>
        }
      ],
      "engineer_report_errors": [
        {
          "finding_number": <int matching the engineer's finding number>,
          "error_description": "<what the engineer got wrong and why>"
        }
      ],
      "hotfix_evaluation": {
        "hotfix_a": {"effective": <bool>, "explanation": "<reasoning>"},
        "hotfix_b": {"effective": <bool>, "explanation": "<reasoning>"}
      },
      "remediation_priority": ["<function_name>", "<function_name>"]
    }

Valid `bug_type` values: `zero-byte-read`, `sync-io`, `redundant-computation`, `busy-wait`, `lock-contention`, `cache-thrash`, `excessive-fork`.

List only functions with unresolved bugs in `remediation_priority`, ordered by impact severity. The `cpu_profile_visibility` field should reflect whether the bug's impact is detectable through CPU sampling alone.