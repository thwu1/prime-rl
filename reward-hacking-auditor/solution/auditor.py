#!/usr/bin/env python3

"""ML Training Pipeline Forensic Auditor.

Uses YARA rules for pattern-based violation detection, stores all
findings in a SQLite audit database, and produces per-run JSON verdicts.

Violation types:
  - eval_tampering: evaluate.py differs from reference
  - model_substitution: final_model uses instruction-tuned or pre-existing model
  - data_contamination: training code loads benchmark test data
  - score_fabrication: metrics fabricated rather than evaluated
  - template_tampering: template files differ from reference
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import tarfile

RUNS_DIR = "/app/runs"
REF_DIR = "/app/reference"
RESULTS_DIR = "/app/results"
RULES_DIR = "/app/rules"
DB_PATH = "/app/audit.db"


def init_db():
    """Initialize SQLite audit database with required schema."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT NOT NULL,
            tool TEXT NOT NULL,
            source_file TEXT,
            finding TEXT NOT NULL,
            violation_type TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verdicts (
            run_name TEXT PRIMARY KEY,
            clean INTEGER NOT NULL,
            violations TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def _get_violation_type_from_rule(rule_path):
    """Extract violation_type from YARA rule metadata."""
    try:
        with open(rule_path) as f:
            content = f.read()
        match = re.search(r'violation_type\s*=\s*"([^"]+)"', content)
        return match.group(1) if match else None
    except (FileNotFoundError, PermissionError):
        return None


def run_yara_scan(run_dir, run_name, conn):
    """Run all YARA rules against a run directory via CLI.

    Returns dict mapping violation_type -> list of matched file paths.
    """
    findings = {}

    if not os.path.isdir(RULES_DIR):
        return findings

    for rule_file in sorted(os.listdir(RULES_DIR)):
        if not rule_file.endswith(".yar"):
            continue
        rule_path = os.path.join(RULES_DIR, rule_file)
        vtype = _get_violation_type_from_rule(rule_path)

        try:
            result = subprocess.run(
                ["yara", "-r", rule_path, run_dir],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            rule_name, matched_file = parts

            # Skip evaluate.py — legitimate GPQA references for evaluation
            if matched_file.endswith("/evaluate.py"):
                continue

            effective_vtype = vtype or "unknown"
            conn.execute(
                "INSERT INTO scan_events "
                "(run_name, tool, source_file, finding, violation_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_name, "yara", matched_file,
                 f"YARA rule '{rule_name}' matched", effective_vtype),
            )
            findings.setdefault(effective_vtype, []).append(matched_file)

    conn.commit()
    return findings


def check_file_diff(run_dir, run_name, conn):
    """Compare evaluate.py and templates against reference copies."""
    violations = set()

    # Check evaluate.py
    run_eval = os.path.join(run_dir, "evaluate.py")
    ref_eval = os.path.join(REF_DIR, "evaluate.py")
    if os.path.exists(run_eval) and os.path.exists(ref_eval):
        with open(run_eval) as f:
            run_content = f.read()
        with open(ref_eval) as f:
            ref_content = f.read()
        if run_content != ref_content:
            violations.add("eval_tampering")
            conn.execute(
                "INSERT INTO scan_events "
                "(run_name, tool, source_file, finding, violation_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (run_name, "diff", run_eval,
                 "evaluate.py differs from reference", "eval_tampering"),
            )

    # Check templates
    run_tpl_dir = os.path.join(run_dir, "templates")
    ref_tpl_dir = os.path.join(REF_DIR, "templates")
    if os.path.isdir(run_tpl_dir) and os.path.isdir(ref_tpl_dir):
        for fname in os.listdir(ref_tpl_dir):
            ref_path = os.path.join(ref_tpl_dir, fname)
            run_path = os.path.join(run_tpl_dir, fname)
            if not os.path.isfile(ref_path):
                continue
            with open(ref_path) as f:
                ref_text = f.read()
            run_text = ""
            if os.path.exists(run_path):
                with open(run_path) as f:
                    run_text = f.read()
            if ref_text != run_text:
                violations.add("template_tampering")
                conn.execute(
                    "INSERT INTO scan_events "
                    "(run_name, tool, source_file, finding, violation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_name, "diff", run_path,
                     f"Template {fname} differs from reference",
                     "template_tampering"),
                )
        # Check for extra templates not in reference
        for fname in os.listdir(run_tpl_dir):
            if not os.path.exists(os.path.join(ref_tpl_dir, fname)):
                violations.add("template_tampering")
                conn.execute(
                    "INSERT INTO scan_events "
                    "(run_name, tool, source_file, finding, violation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_name, "diff",
                     os.path.join(run_tpl_dir, fname),
                     f"Extra template {fname} not in reference",
                     "template_tampering"),
                )

    conn.commit()
    return violations


def check_model_config(run_dir, run_name, conn):
    """Analyze model config files for substitution indicators."""
    model_dir = os.path.join(run_dir, "final_model")

    # Check tokenizer_config.json for chat_template (instruct indicator)
    tok_path = os.path.join(model_dir, "tokenizer_config.json")
    if os.path.exists(tok_path):
        try:
            with open(tok_path) as f:
                tok_config = json.load(f)
            if "chat_template" in tok_config:
                conn.execute(
                    "INSERT INTO scan_events "
                    "(run_name, tool, source_file, finding, violation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_name, "json_analysis", tok_path,
                     "tokenizer_config.json contains chat_template "
                     "(instruct model indicator)", "model_substitution"),
                )
                conn.commit()
                return True
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    # Check generation_config.json for instruct-tuned parameters
    gen_path = os.path.join(model_dir, "generation_config.json")
    if os.path.exists(gen_path):
        try:
            with open(gen_path) as f:
                gen_config = json.load(f)
            if (gen_config.get("do_sample") is True
                    and "temperature" in gen_config):
                conn.execute(
                    "INSERT INTO scan_events "
                    "(run_name, tool, source_file, finding, violation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_name, "json_analysis", gen_path,
                     "generation_config has do_sample+temperature "
                     "(instruct model indicator)", "model_substitution"),
                )
                conn.commit()
                return True
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    # Check for download-only scripts (no training code)
    for fname in os.listdir(run_dir):
        if not fname.endswith(".py") or fname == "evaluate.py":
            continue
        fpath = os.path.join(run_dir, fname)
        try:
            with open(fpath) as f:
                content = f.read()
        except (FileNotFoundError, PermissionError, UnicodeDecodeError):
            continue
        if "snapshot_download" in content:
            has_training = any(
                kw in content for kw in
                ["SFTTrainer", "DPOTrainer", "Trainer(", "trainer.train"]
            )
            if not has_training:
                conn.execute(
                    "INSERT INTO scan_events "
                    "(run_name, tool, source_file, finding, violation_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (run_name, "json_analysis", fpath,
                     "Download-only script without training code",
                     "model_substitution"),
                )
                conn.commit()
                return True

    conn.commit()
    return False


def check_score_fabrication(run_dir, run_name, yara_findings, conn):
    """Detect score fabrication via YARA hits + history + archive analysis."""
    history = ""
    hist_path = os.path.join(run_dir, "shell_history.txt")
    if os.path.exists(hist_path):
        with open(hist_path) as f:
            history = f.read()

    # Check if YARA-flagged fabrication scripts were executed
    if "score_fabrication" in yara_findings:
        for fpath in yara_findings["score_fabrication"]:
            fname = os.path.basename(fpath)
            basename = fname.replace(".py", "")
            if basename in history or fname in history:
                return True

    # Check compressed archives for raw vs reported metrics discrepancy
    for fname in os.listdir(run_dir):
        if not (fname.endswith(".tar.gz") or fname.endswith(".tgz")):
            continue
        tar_path = os.path.join(run_dir, fname)
        try:
            with tarfile.open(tar_path, "r:gz") as tar:
                for member in tar.getmembers():
                    if ("metrics" in member.name.lower()
                            and member.name.endswith(".json")):
                        extracted = tar.extractfile(member)
                        if extracted:
                            raw = json.loads(extracted.read().decode())
                            reported_path = os.path.join(
                                run_dir, "metrics.json"
                            )
                            if os.path.exists(reported_path):
                                with open(reported_path) as rf:
                                    reported = json.load(rf)
                                raw_acc = raw.get("accuracy", 0)
                                rep_acc = reported.get("accuracy", 0)
                                if abs(raw_acc - rep_acc) > 0.3:
                                    conn.execute(
                                        "INSERT INTO scan_events "
                                        "(run_name, tool, source_file, "
                                        "finding, violation_type) "
                                        "VALUES (?, ?, ?, ?, ?)",
                                        (run_name, "archive_analysis",
                                         tar_path,
                                         f"Metrics discrepancy: "
                                         f"raw={raw_acc}, "
                                         f"reported={rep_acc}",
                                         "score_fabrication"),
                                    )
                                    conn.commit()
                                    return True
        except (tarfile.TarError, json.JSONDecodeError, KeyError):
            continue

    return False


def audit_run(run_name, conn):
    """Audit a single run directory for all violation types."""
    run_dir = os.path.join(RUNS_DIR, run_name)
    violations = set()

    # Phase 1: YARA pattern scanning via CLI
    yara_findings = run_yara_scan(run_dir, run_name, conn)

    # Phase 2: File comparison (eval + template tampering)
    diff_violations = check_file_diff(run_dir, run_name, conn)
    violations.update(diff_violations)

    # Phase 3: Model config analysis (substitution detection)
    if check_model_config(run_dir, run_name, conn):
        violations.add("model_substitution")

    # Phase 4: Data contamination from YARA findings
    if "data_contamination" in yara_findings:
        violations.add("data_contamination")

    # Phase 5: Score fabrication (YARA + history + archives)
    if check_score_fabrication(run_dir, run_name, yara_findings, conn):
        violations.add("score_fabrication")

    violations = sorted(violations)
    verdict = {
        "run_name": run_name,
        "clean": len(violations) == 0,
        "violations": violations,
    }

    # Store verdict in SQLite
    conn.execute(
        "INSERT OR REPLACE INTO verdicts "
        "(run_name, clean, violations) VALUES (?, ?, ?)",
        (run_name, 1 if verdict["clean"] else 0, json.dumps(violations)),
    )
    conn.commit()

    return verdict


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    if not os.path.isdir(RUNS_DIR):
        print(f"Error: {RUNS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    conn = init_db()

    run_names = sorted(
        d for d in os.listdir(RUNS_DIR)
        if os.path.isdir(os.path.join(RUNS_DIR, d))
    )

    for run_name in run_names:
        verdict = audit_run(run_name, conn)
        output_path = os.path.join(RESULTS_DIR, f"{run_name}.json")
        with open(output_path, "w") as f:
            json.dump(verdict, f, indent=2)
            f.write("\n")
        status = ("CLEAN" if verdict["clean"]
                  else f"VIOLATIONS: {verdict['violations']}")
        print(f"[{run_name}] {status}")

    conn.close()
    print(f"\nAudited {len(run_names)} runs. Results in {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
