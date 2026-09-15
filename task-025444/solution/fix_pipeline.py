#!/usr/bin/env python3
"""Fix all 6 bugs in the OWASP Benchmark scoring pipeline.

Bug 1 (ingest.py — schema bypass): Pipeline creates inline schema instead of
    using /app/schema.sql. The inline findings table has UNIQUE(tool_name,
    test_name) which is absent from the authoritative schema. Each module
    independently drops and recreates tables, losing CHECK constraints,
    FOREIGN KEYs, and the AUTOINCREMENT column.
    Fix: Remove inline schema creation; tables already exist from schema.sql.
         Use DELETE FROM for idempotent re-runs.

Bug 2 (ingest.py — duplicate finding loss): UNIQUE(tool_name, test_name)
    combined with INSERT OR REPLACE silently drops all but the last finding
    per (tool, test) pair. ToolGamma has multi-CWE findings per test case.
    Fix: Use plain INSERT (schema.sql has no UNIQUE on findings).

Bug 3 (analyze.py — CWE prefix matching): Uses exact string equality
    (tool_name == prefix) instead of tool_name.startswith(prefix). This
    breaks the CWE 327→328 exception for "AppScanLike" because
    "AppScanLike" != "AppScan" but "AppScanLike".startswith("AppScan").
    Fix: Use startswith() for prefix-based CWE exceptions.

Bug 4 (metrics.py — micro-averaging): Overall TPR/FPR computed from
    aggregate TP/FN/FP/TN counts (micro-averaging) instead of the mean of
    per-category rates (macro-averaging). With imbalanced category sizes,
    these diverge — the OWASP methodology uses macro-averaging so each
    vulnerability category contributes equally.
    Fix: Average per-category TPR/FPR values.

Bug 5 (export.py — sort order): Ranking sorted ascending by Youden's J
    instead of descending (best tools should rank first).
    Fix: Add reverse=True.

Bug 6 (run_pipeline.sh — missing steps): Does not initialize the database
    from /app/schema.sql before running modules. Does not generate
    /app/output/audit.csv from /app/audit_query.sql. Does not validate JSON.
    Fix: Add schema initialization, audit CSV generation, and JSON validation.
"""

import os
import stat


def fix_run_pipeline():
    """Fix Bug 6: Initialize DB from schema.sql, generate audit.csv."""
    with open("/app/run_pipeline.sh", "w") as f:
        f.write("#!/bin/bash\n")
        f.write("set -e\n")
        f.write("cd /app\n")
        f.write("rm -f /app/benchmark.db\n")
        f.write("sqlite3 /app/benchmark.db < /app/schema.sql\n")
        f.write("python3 -m pipeline.ingest\n")
        f.write("python3 -m pipeline.analyze\n")
        f.write("python3 -m pipeline.metrics\n")
        f.write("python3 -m pipeline.export\n")
        f.write("mkdir -p /app/output\n")
        f.write("sqlite3 -header -csv /app/benchmark.db < /app/audit_query.sql > /app/output/audit.csv\n")
        f.write('jq -e "." /app/output/scorecard.json > /dev/null\n')
        f.write('echo "Pipeline complete"\n')
    os.chmod("/app/run_pipeline.sh", stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)


def fix_ingest():
    """Fix Bugs 1 & 2: Remove inline schema, use plain INSERT."""
    with open("/app/pipeline/ingest.py", "w") as f:
        f.write('#!/usr/bin/env python3\n')
        f.write('"""Ingest expected results, tool configurations, and scan findings into SQLite."""\n')
        f.write('import json\n')
        f.write('import os\n')
        f.write('import sqlite3\n')
        f.write('\n')
        f.write('import yaml\n')
        f.write('\n')
        f.write('DB_PATH = "/app/benchmark.db"\n')
        f.write('\n')
        f.write('\n')
        f.write('def load_expected_results(conn, filepath):\n')
        f.write('    """Load expected results CSV into the database."""\n')
        f.write('    with open(filepath) as f:\n')
        f.write('        for line in f:\n')
        f.write('            line = line.strip()\n')
        f.write('            if not line or line.startswith("#"):\n')
        f.write('                continue\n')
        f.write('            parts = line.split(",")\n')
        f.write('            conn.execute(\n')
        f.write('                "INSERT INTO expected_results (test_name, category, is_true_positive, cwe) "\n')
        f.write('                "VALUES (?, ?, ?, ?)",\n')
        f.write('                (parts[0].strip(), parts[1].strip(),\n')
        f.write('                 1 if parts[2].strip().lower() == "true" else 0,\n')
        f.write('                 int(parts[3].strip()))\n')
        f.write('            )\n')
        f.write('\n')
        f.write('\n')
        f.write('def load_tool_results(conn, tool_name, filepath):\n')
        f.write('    """Load a tool\'s JSONL scan results into the findings table."""\n')
        f.write('    with open(filepath) as f:\n')
        f.write('        for line in f:\n')
        f.write('            line = line.strip()\n')
        f.write('            if not line:\n')
        f.write('                continue\n')
        f.write('            entry = json.loads(line)\n')
        f.write('            conn.execute(\n')
        f.write('                "INSERT INTO findings (tool_name, test_name, cwe) "\n')
        f.write('                "VALUES (?, ?, ?)",\n')
        f.write('                (tool_name, entry["test_name"], entry["cwe"])\n')
        f.write('            )\n')
        f.write('\n')
        f.write('\n')
        f.write('def ingest(config_path):\n')
        f.write('    """Main ingestion entry point."""\n')
        f.write('    with open(config_path) as f:\n')
        f.write('        config = yaml.safe_load(f)\n')
        f.write('\n')
        f.write('    data_dir = os.path.dirname(config_path)\n')
        f.write('    conn = sqlite3.connect(DB_PATH)\n')
        f.write('\n')
        f.write('    expected_path = os.path.join(data_dir, config["expected_results_file"])\n')
        f.write('    load_expected_results(conn, expected_path)\n')
        f.write('\n')
        f.write('    for tool in config["tools"]:\n')
        f.write('        conn.execute(\n')
        f.write('            "INSERT INTO tools (name, results_file, commercial) VALUES (?, ?, ?)",\n')
        f.write('            (tool["name"], tool["results_file"], 1 if tool["commercial"] else 0)\n')
        f.write('        )\n')
        f.write('        results_path = os.path.join(data_dir, tool["results_file"])\n')
        f.write('        load_tool_results(conn, tool["name"], results_path)\n')
        f.write('\n')
        f.write('    conn.commit()\n')
        f.write('    conn.close()\n')
        f.write('    print(f"Ingested data into {DB_PATH}")\n')
        f.write('\n')
        f.write('\n')
        f.write('if __name__ == "__main__":\n')
        f.write('    ingest("/app/data/config.yaml")\n')


def fix_analyze():
    """Fix Bugs 1 & 3: Use DELETE FROM, fix prefix matching."""
    with open("/app/pipeline/analyze.py") as f:
        content = f.read()

    # Fix schema bypass: replace DROP+CREATE with DELETE FROM
    content = content.replace(
        'conn.execute("DROP TABLE IF EXISTS classifications")',
        'conn.execute("DELETE FROM classifications")'
    )

    # Remove the inline CREATE TABLE block for classifications
    import re
    content = re.sub(
        r'\s+conn\.execute\("""\s+CREATE TABLE classifications\s.*?"""\)',
        '',
        content,
        flags=re.DOTALL
    )

    # Fix CWE prefix matching: exact equality -> startsWith
    content = content.replace(
        'tool_name == prefix',
        'tool_name.startswith(prefix)'
    )

    with open("/app/pipeline/analyze.py", "w") as f:
        f.write(content)


def fix_metrics():
    """Fix Bugs 1 & 4: Use DELETE FROM, fix macro-averaging."""
    with open("/app/pipeline/metrics.py") as f:
        content = f.read()

    # Fix schema bypass: replace DROP+CREATE with DELETE FROM
    content = content.replace(
        'conn.execute("DROP TABLE IF EXISTS category_metrics")',
        'conn.execute("DELETE FROM category_metrics")'
    )
    content = content.replace(
        'conn.execute("DROP TABLE IF EXISTS overall_metrics")',
        'conn.execute("DELETE FROM overall_metrics")'
    )

    # Remove inline CREATE TABLE blocks
    import re
    content = re.sub(
        r'\s+conn\.execute\("""\s+CREATE TABLE category_metrics\s.*?"""\)',
        '',
        content,
        flags=re.DOTALL
    )
    content = re.sub(
        r'\s+conn\.execute\("""\s+CREATE TABLE overall_metrics\s.*?"""\)',
        '',
        content,
        flags=re.DOTALL
    )

    # Fix micro-averaging -> macro-averaging
    # Replace total count accumulators with rate accumulators
    content = content.replace(
        "        total_tp = total_fn = total_fp = total_tn = 0",
        "        tpr_sum = 0.0\n        fpr_sum = 0.0\n        n_categories = 0"
    )
    content = content.replace(
        "            total_tp += tp\n"
        "            total_fn += fn\n"
        "            total_fp += fp\n"
        "            total_tn += tn",
        "            tpr_sum += tpr\n"
        "            fpr_sum += fpr\n"
        "            n_categories += 1"
    )
    # Replace micro-averaged computation with macro-averaged
    content = content.replace(
        "        # Compute overall metrics from aggregate counts\n"
        "        overall_tpr = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0\n"
        "        overall_fpr = total_fp / (total_fp + total_tn) if (total_fp + total_tn) > 0 else 0.0\n"
        "        youdens_j = overall_tpr - overall_fpr",
        "        # Macro-average: mean of per-category rates\n"
        "        overall_tpr = tpr_sum / n_categories if n_categories > 0 else 0.0\n"
        "        overall_fpr = fpr_sum / n_categories if n_categories > 0 else 0.0\n"
        "        youdens_j = overall_tpr - overall_fpr"
    )

    with open("/app/pipeline/metrics.py", "w") as f:
        f.write(content)


def fix_export():
    """Fix Bug 5: Sort ranking descending by Youden's J."""
    with open("/app/pipeline/export.py") as f:
        content = f.read()

    content = content.replace(
        'sorted(tools_output, key=lambda t: t["overall"]["youdens_j"])',
        'sorted(tools_output, key=lambda t: t["overall"]["youdens_j"], reverse=True)'
    )

    with open("/app/pipeline/export.py", "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_run_pipeline()
    fix_ingest()
    fix_analyze()
    fix_metrics()
    fix_export()
    print("All 6 pipeline bugs fixed")
