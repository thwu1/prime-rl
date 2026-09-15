#!/usr/bin/env python3
"""
dbt Pipeline Failure Forensics — Solution

Parses SQL model files, queries the SQLite run history, compares against
the stale manifest, and produces a comprehensive forensics report.

"""
import json
import os
import re
import sqlite3
from collections import deque


def extract_refs(sql_content):
    """Extract ref() model names from SQL, ignoring all comment syntaxes."""
    # Strip Jinja block comments {# ... #} (may span multiple lines)
    clean = re.sub(r'\{#.*?#\}', '', sql_content, flags=re.DOTALL)
    # Strip SQL block comments /* ... */ (may span multiple lines)
    clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
    # Strip SQL single-line comments (-- ...)
    clean = re.sub(r'--.*?$', '', clean, flags=re.MULTILINE)
    # Match {{ ref('name') }} or {{ ref("name") }} with flexible whitespace
    refs = re.findall(
        r"\{\{\s*ref\(\s*['\"](\w+)['\"]\s*\)\s*\}\}", clean
    )
    return sorted(set(refs))


def scan_source_models(models_dir):
    """Walk model directory, return {model_name: [ref_deps]}."""
    models = {}
    for root, _dirs, files in os.walk(models_dir):
        for fname in files:
            if fname.endswith(".sql"):
                name = fname[:-4]
                with open(os.path.join(root, fname)) as f:
                    sql = f.read()
                models[name] = extract_refs(sql)
    return models


def analyze_drift(source_models, manifest):
    """Compare source SQL models against stale manifest."""
    manifest_model_names = {
        node["name"]
        for node in manifest["nodes"].values()
        if node["resource_type"] == "model"
    }
    source_names = set(source_models.keys())

    added = sorted(source_names - manifest_model_names)
    removed = sorted(manifest_model_names - source_names)

    dependency_changes = {}
    for name in sorted(source_names & manifest_model_names):
        source_refs = set(source_models[name])
        uid = f"model.analytics.{name}"
        if uid not in manifest["nodes"]:
            continue
        manifest_deps = manifest["nodes"][uid]["depends_on"]["nodes"]
        manifest_ref_names = set()
        for dep_uid in manifest_deps:
            dep_node = manifest["nodes"].get(dep_uid)
            if dep_node:
                manifest_ref_names.add(dep_node["name"])
        added_deps = sorted(source_refs - manifest_ref_names)
        if added_deps:
            dependency_changes[name] = added_deps

    return {"added": added, "removed": removed,
            "dependency_changes": dependency_changes}


def load_run_results(db_path):
    """Query SQLite for per-run status maps."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    runs = [r[0] for r in c.execute(
        "SELECT run_id FROM runs ORDER BY run_id").fetchall()]
    results = {}
    for run_id in runs:
        rows = c.execute(
            "SELECT unique_id, status FROM node_results WHERE run_id=?",
            (run_id,),
        ).fetchall()
        results[run_id] = {uid: st for uid, st in rows}
    conn.close()
    return results


def find_root_causes(manifest, status_map):
    """Identify root cause nodes in a single run."""
    failed = {"error", "skipped"}
    root_causes = []
    for uid, node in manifest["nodes"].items():
        if status_map.get(uid, "pass") not in failed:
            continue
        upstream = node["depends_on"]["nodes"]
        upstream_ok = all(
            status_map.get(dep, "pass") not in failed for dep in upstream
        )
        if upstream_ok:
            root_causes.append(uid)
    return sorted(root_causes)


def temporal_analysis(manifest, run_results):
    """Classify root causes as persistent, transient, or masked."""
    runs = sorted(run_results.keys())
    rc_by_run = {
        run_id: find_root_causes(manifest, run_results[run_id])
        for run_id in runs
    }

    all_rcs = set()
    for rcs in rc_by_run.values():
        all_rcs.update(rcs)

    persistent = sorted(
        uid for uid in all_rcs
        if all(
            run_results[r].get(uid, "pass") in ("error", "skipped")
            for r in runs
        )
    )

    transient = sorted(
        uid for uid in all_rcs
        if any(run_results[r].get(uid, "pass") == "pass" for r in runs)
    )

    masked = {}
    for uid in persistent:
        masked_runs = sorted(
            r for r in runs
            if run_results[r].get(uid, "pass") in ("error", "skipped")
            and uid not in rc_by_run[r]
        )
        if masked_runs:
            masked[uid] = masked_runs

    return rc_by_run, persistent, transient, masked


def parse_selectors_yaml(path):
    """Parse the simple selectors.yml without PyYAML."""
    selectors = []
    with open(path) as f:
        lines = f.readlines()

    current = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = {"name": stripped.split(":", 1)[1].strip()}
            selectors.append(current)
        elif current is not None and stripped.startswith("method:"):
            current.setdefault("definition", {})["method"] = (
                stripped.split(":", 1)[1].strip().strip('"\'')
            )
        elif current is not None and stripped.startswith("value:"):
            current.setdefault("definition", {})["value"] = (
                stripped.split(":", 1)[1].strip().strip('"\'')
            )
    return selectors


def validate_selectors(selectors_path, source_model_names):
    """Find selectors referencing non-existent source models."""
    selectors = parse_selectors_yaml(selectors_path)

    stale = []
    for sel in selectors:
        defn = sel.get("definition", {})
        if defn.get("method") != "fqn":
            continue
        value = defn.get("value", "")
        if value == "*":
            continue
        model_name = value.strip("+@")
        if model_name and model_name not in source_model_names:
            stale.append(sel["name"])
    return sorted(stale)


def find_blocking_dep(persistent, source_models, manifest):
    """Identify the missing dependency causing persistent failure."""
    for uid in persistent:
        name = manifest["nodes"][uid]["name"]
        source_refs = set(source_models.get(name, []))
        manifest_deps = manifest["nodes"][uid]["depends_on"]["nodes"]
        manifest_ref_names = set()
        for dep_uid in manifest_deps:
            dep_node = manifest["nodes"].get(dep_uid)
            if dep_node:
                manifest_ref_names.add(dep_node["name"])
        missing = sorted(source_refs - manifest_ref_names)
        if missing:
            return missing[0]
    return None


def compute_cascade_impact(root_causes, manifest):
    """For each root cause, count distinct model nodes transitively downstream."""
    child_map = manifest.get("child_map", {})
    impact = {}
    for rc_uid in root_causes:
        visited = set()
        queue = deque(child_map.get(rc_uid, []))
        for c in queue:
            visited.add(c)
        while queue:
            node_id = queue.popleft()
            for child_id in child_map.get(node_id, []):
                if child_id not in visited:
                    visited.add(child_id)
                    queue.append(child_id)
        model_count = sum(
            1 for v in visited
            if manifest["nodes"].get(v, {}).get("resource_type") == "model"
        )
        impact[rc_uid] = model_count
    return impact


def compute_fix_priority(rc_by_run, cascade_impact):
    """Rank root causes by (runs_as_rc * cascade_impact) desc, alpha tiebreak."""
    all_rcs = set()
    for rcs in rc_by_run.values():
        all_rcs.update(rcs)

    scored = []
    for uid in all_rcs:
        runs_as_rc = sum(1 for rcs in rc_by_run.values() if uid in rcs)
        score = runs_as_rc * cascade_impact.get(uid, 0)
        scored.append((uid, score))

    scored.sort(key=lambda x: (-x[1], x[0]))
    return [uid for uid, _ in scored]


def main():
    # Load manifest
    with open("/data/manifest.json") as f:
        manifest = json.load(f)

    # Scan SQL source files
    source_models = scan_source_models("/data/models")

    # Drift analysis
    drift = analyze_drift(source_models, manifest)

    # Load run history from SQLite
    run_results = load_run_results("/data/pipeline_runs.db")

    # Temporal root-cause analysis
    rc_by_run, persistent, transient, masked = temporal_analysis(
        manifest, run_results
    )

    # Selector validation
    stale_selectors = validate_selectors(
        "/data/selectors.yml", set(source_models.keys())
    )

    # Blocking dependency identification
    blocking = find_blocking_dep(persistent, source_models, manifest)

    # Cascade impact analysis
    all_rcs = set()
    for rcs in rc_by_run.values():
        all_rcs.update(rcs)
    cascade_impact = compute_cascade_impact(all_rcs, manifest)

    # Fix priority ranking
    fix_priority = compute_fix_priority(rc_by_run, cascade_impact)

    # Build and write report
    report = {
        "drift": drift,
        "root_causes_by_run": rc_by_run,
        "persistent_root_cause": persistent,
        "transient_root_causes": transient,
        "masked_in_runs": masked,
        "stale_selectors": stale_selectors,
        "blocking_dependency": blocking,
        "cascade_impact": cascade_impact,
        "fix_priority": fix_priority,
    }

    with open("/app/forensics.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Forensics report written to /app/forensics.json")


if __name__ == "__main__":
    main()
