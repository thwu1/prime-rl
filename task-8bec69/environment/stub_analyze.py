#!/usr/bin/env python3
"""SGLang SLO analyzer — reads interval delta data and SLO configuration,
produces compliance and burn-rate alert report.

This is a stub. Implement the full analysis pipeline.
See /app/slo_config.json for SLO definitions, severity classification rules,
and error-budget parameters.
Output: /app/report.json
"""
import json
import sys

json.dump({"error": "analyzer not implemented"}, open("/app/report.json", "w"))
print("ERROR: Analyzer not yet implemented", file=sys.stderr)
sys.exit(1)
