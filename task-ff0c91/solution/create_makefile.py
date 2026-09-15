#!/usr/bin/env python3
"""Generate the pipeline Makefile with proper tab indentation."""

lines = [
    ".PHONY: pipeline clean",
    "",
    "CONFIG = /app/config.json",
    "SCHEMA = /app/schema.sql",
    "DB = /app/results.db",
    "REPORT = /app/report.json",
    "",
    "pipeline:",
    "\tjq -e '.' $(CONFIG) > /dev/null",
    "\tjq -e '.data.returns_path, .data.orderbook_path, .output.database' $(CONFIG) > /dev/null",
    "\tsqlite3 $(DB) < $(SCHEMA)",
    "\tpython3 /app/pipeline_runner.py",
    "\tVFC=$$(sqlite3 $(DB) \"SELECT COUNT(*) FROM volatility_forecast\") && \\",
    "\tAQC=$$(sqlite3 $(DB) \"SELECT COUNT(*) FROM quoting_decision WHERE active=1\") && \\",
    "\tHQC=$$(sqlite3 $(DB) \"SELECT COUNT(*) FROM quoting_decision WHERE active=0\") && \\",
    "\tVAR99=$$(sqlite3 $(DB) \"SELECT var_99_1d FROM risk_metrics WHERE method='historical'\") && \\",
    "\tCVAR=$$(sqlite3 $(DB) \"SELECT cvar_95 FROM risk_metrics WHERE method='historical'\") && \\",
    "\tRD=$$(sqlite3 $(DB) \"SELECT json_group_object(regime, cnt) FROM (SELECT regime, COUNT(*) as cnt FROM regime_state GROUP BY regime)\") && \\",
    "\tjq -n \\",
    "\t\t--argjson vfc \"$$VFC\" \\",
    "\t\t--argjson aqc \"$$AQC\" \\",
    "\t\t--argjson hqc \"$$HQC\" \\",
    "\t\t--argjson var99 \"$$VAR99\" \\",
    "\t\t--argjson cvar \"$$CVAR\" \\",
    "\t\t--argjson rd \"$$RD\" \\",
    "\t\t'{volatility_forecast_count: $$vfc, regime_distribution: $$rd, active_quotes_count: $$aqc, halted_quotes_count: $$hqc, var_99_1d: $$var99, cvar_95: $$cvar}' > $(REPORT)",
    "",
    "clean:",
    "\trm -f $(DB) $(REPORT)",
    "",
]

with open('/app/Makefile', 'w') as f:
    f.write('\n'.join(lines))

print("Created /app/Makefile")
