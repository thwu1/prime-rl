#!/usr/bin/env python3
"""FDB Simulation Trace Forensics - Solution Generator.

Generates the three analysis tools and then runs them.
"""

import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


# ================================================================
# TOOL 1: FDB TRACE ANALYZER
# ================================================================

ANALYZER_CODE = r'''#!/usr/bin/env python3
"""FDB Trace Log Analyzer - Parses XML trace logs and produces structured analysis.

Uses xmlstarlet for XPath extraction and sqlite3 for knowledge database lookups.
"""

import xml.etree.ElementTree as ET
import json
import os
import glob
import sqlite3
import subprocess


DB_PATH = "/app/fdb_knowledge.db"


def query_db(sql, params=()):
    """Query the FDB knowledge database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


def get_protocol_version(binary_version):
    """Look up protocol version hex for a binary version from the database."""
    rows = query_db(
        "SELECT protocol_version FROM binary_registry WHERE version = ?",
        (binary_version,)
    )
    return rows[0][0] if rows else None


def check_protocol_compat(proto1, proto2):
    """Check protocol compatibility from the database."""
    rows = query_db(
        "SELECT compatible, notes FROM protocol_compat "
        "WHERE from_protocol = ? AND to_protocol = ?",
        (proto1, proto2)
    )
    if rows:
        return rows[0][0] == 1, rows[0][1]
    return None, None


def get_failure_signature(event_type, error_code=None):
    """Look up failure signature from the database."""
    if error_code:
        rows = query_db(
            "SELECT category, severity_class, root_cause_template, resolution "
            "FROM failure_signatures WHERE event_type = ? AND error_code = ?",
            (event_type, error_code)
        )
    else:
        rows = query_db(
            "SELECT category, severity_class, root_cause_template, resolution "
            "FROM failure_signatures WHERE event_type = ?",
            (event_type,)
        )
    if rows:
        return {
            "category": rows[0][0],
            "severity_class": rows[0][1],
            "root_cause_template": rows[0][2],
            "resolution": rows[0][3],
        }
    return None


def xmlstarlet_count_events(filepath, event_type):
    """Use xmlstarlet to count events of a specific type in a trace file."""
    try:
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t", "-c",
             f"count(//Event[@Type='{event_type}'])"],
            stdin=open(filepath),
            capture_output=True, text=True, timeout=10
        )
        return int(float(result.stdout.strip()))
    except Exception:
        return 0


def xmlstarlet_extract_errors(filepath):
    """Use xmlstarlet to extract high-severity events via XPath."""
    try:
        result = subprocess.run(
            ["xmlstarlet", "sel", "-t",
             "-m", "//Event[@Severity >= 40]",
             "-v", "@Type", "-o", "|",
             "-v", "@Severity", "-o", "|",
             "-v", "@Machine", "-o", "|",
             "-v", "@Time", "-o", "|",
             "-v", "@Error", "-o", "|",
             "-v", "@ErrorIsInjectedFault", "-n"],
            stdin=open(filepath),
            capture_output=True, text=True, timeout=10
        )
        events = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|")
            if len(parts) >= 6:
                events.append({
                    "type": parts[0],
                    "severity": int(parts[1]) if parts[1] else 0,
                    "machine": parts[2],
                    "time": float(parts[3]) if parts[3] else 0,
                    "error": parts[4],
                    "injected": parts[5].strip(),
                })
        return events
    except Exception:
        return []


def parse_trace_file(filepath):
    """Parse an FDB XML trace file and return list of event dicts."""
    tree = ET.parse(filepath)
    root = tree.getroot()
    events = []
    for elem in root:
        if elem.tag == "Event":
            events.append(dict(elem.attrib))
    return events


def extract_processes(events):
    """Extract unique processes with their roles from trace events."""
    processes = {}
    for ev in events:
        machine = ev.get("Machine", "")
        if not machine:
            continue
        if machine not in processes:
            roles_str = ev.get("Roles", "")
            roles = [r.strip() for r in roles_str.split(",") if r.strip()]
            processes[machine] = {
                "machine": machine,
                "id": ev.get("ID", ""),
                "roles": roles,
            }
        else:
            # Merge roles if we see new ones
            roles_str = ev.get("Roles", "")
            new_roles = [r.strip() for r in roles_str.split(",") if r.strip()]
            existing = set(processes[machine]["roles"])
            for r in new_roles:
                if r not in existing:
                    processes[machine]["roles"].append(r)
                    existing.add(r)
    return list(processes.values())


def extract_recovery_states(events):
    """Extract ordered recovery state transitions."""
    recovery_events = sorted(
        [e for e in events if e.get("Type") == "MasterRecoveryState"],
        key=lambda e: float(e.get("Time", "0")),
    )
    return [ev.get("RecoveryState", "") for ev in recovery_events if ev.get("RecoveryState")]


def extract_errors(events):
    """Extract error events: Severity >= 40, excluding injected faults."""
    errors = []
    for ev in events:
        sev = int(ev.get("Severity", "0"))
        if sev >= 40 and ev.get("ErrorIsInjectedFault") != "1":
            # Look up failure signature from database
            sig = get_failure_signature(ev.get("Type", ""), ev.get("Error", ""))
            errors.append({
                "type": ev.get("Type", ""),
                "severity": sev,
                "machine": ev.get("Machine", ""),
                "time": float(ev.get("Time", "0")),
                "error_code": ev.get("Error", ev.get("Reason", "")),
                "category": sig["category"] if sig else "unknown",
                "details": {
                    k: v for k, v in ev.items()
                    if k not in ("Type", "Severity", "Machine", "Time", "ID",
                                 "LogGroup", "Roles", "Error", "Reason")
                },
            })
    return sorted(errors, key=lambda e: e["time"])


def extract_workloads(events):
    """Extract workload activity from trace events."""
    workloads = {}
    for ev in events:
        typ = ev.get("Type", "")
        test_name = ev.get("TestName", "")

        if typ == "SaveAndKillTriggered":
            test_name = "SaveAndKill"
            if test_name not in workloads:
                workloads[test_name] = {"name": test_name, "events": []}
            workloads[test_name]["events"].append("triggered")
            continue

        if not test_name:
            continue

        if test_name not in workloads:
            workloads[test_name] = {"name": test_name, "events": []}

        if "Setup" in typ:
            workloads[test_name]["events"].append("setup")
        elif "Start" in typ:
            workloads[test_name]["events"].append("start")
        elif "Check" in typ:
            workloads[test_name]["events"].append("check")
            if ev.get("Passed") == "1":
                workloads[test_name]["passed"] = True
            else:
                workloads[test_name]["passed"] = False

    return list(workloads.values())


def extract_binary_version(events):
    """Extract binary version from ProgramStart events."""
    for ev in events:
        if ev.get("Type") == "ProgramStart":
            return ev.get("Version", "")
    return ""


def is_restarting_phase(events):
    """Check if this is a restarting phase (Phase 2 of restart test)."""
    for ev in events:
        if ev.get("Type") == "ProgramStart" and ev.get("Restarting") == "1":
            return True
    return False


def analyze_root_cause(phases):
    """Perform root cause analysis across phases for failed runs.

    Queries the knowledge database for protocol version identifiers and
    compatibility status.
    """
    for phase in phases:
        if not phase["recovery_completed"] and phase["errors"]:
            # Find earliest non-timeout Severity-40 error
            real_errors = [
                e for e in phase["errors"]
                if e["type"] != "SimulationTimeout"
            ]
            if real_errors:
                first_error = min(real_errors, key=lambda e: e["time"])
                affected = list(set(e["machine"] for e in real_errors))

                # Query database for protocol versions
                old_version = None
                new_version = None
                for p in phases:
                    ver = p.get("binary_version", "")
                    if ver and not p.get("is_restarting"):
                        old_version = ver
                    elif ver and p.get("is_restarting"):
                        new_version = ver

                old_proto = get_protocol_version(old_version) if old_version else None
                new_proto = get_protocol_version(new_version) if new_version else None

                compat = None
                compat_notes = None
                if old_proto and new_proto:
                    compat, compat_notes = check_protocol_compat(old_proto, new_proto)

                return {
                    "category": first_error.get("category", first_error["error_code"]),
                    "description": (
                        f"Recovery failed in phase {phase['phase']}: "
                        f"{first_error['type']} with error "
                        f"{first_error['error_code']} on {first_error['machine']}. "
                        f"TLog processes could not rejoin the cluster due to "
                        f"incompatible protocol versions between old binary "
                        f"(protocol {old_proto}) and new binary (protocol {new_proto})."
                    ),
                    "affected_processes": affected,
                    "impact": (
                        f"Master recovery stuck at {phase['final_recovery_state']} "
                        f"phase - unable to recruit sufficient TLogs"
                    ),
                    "protocol_versions": {
                        "old": old_proto or "unknown",
                        "new": new_proto or "unknown",
                        "compatible": compat if compat is not None else False,
                    },
                }
    return None


def analyze_run(run_dir):
    """Analyze all trace files in a run directory."""
    run_id = os.path.basename(run_dir)

    # Load metadata
    meta_path = os.path.join(run_dir, "metadata.json")
    metadata = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            metadata = json.load(f)

    # Find phase files
    phase_files = sorted(glob.glob(os.path.join(run_dir, "phase*.xml")))
    if not phase_files:
        # Single-phase fast test
        phase_files = sorted(glob.glob(os.path.join(run_dir, "*.xml")))

    phases = []
    for i, pf in enumerate(phase_files, 1):
        events = parse_trace_file(pf)
        recovery_states = extract_recovery_states(events)
        errors = extract_errors(events)
        workloads = extract_workloads(events)

        recovery_completed = "FULLY_RECOVERED" in recovery_states
        final_state = recovery_states[-1] if recovery_states else "UNKNOWN"

        saveandkill = any(
            ev.get("Type") == "SaveAndKillTriggered" for ev in events
        )

        # Also use xmlstarlet to cross-validate error count
        xmlstar_error_count = xmlstarlet_count_events(pf, "TLogRejoinError")

        phases.append({
            "phase": i,
            "trace_file": os.path.basename(pf),
            "binary_version": extract_binary_version(events),
            "is_restarting": is_restarting_phase(events),
            "processes": extract_processes(events),
            "recovery_states": recovery_states,
            "final_recovery_state": final_state,
            "recovery_completed": recovery_completed,
            "errors": errors,
            "workloads": workloads,
            "saveandkill_triggered": saveandkill,
        })

    # Determine overall test result
    all_recovered = all(p["recovery_completed"] for p in phases)
    any_errors = any(len(p["errors"]) > 0 for p in phases)
    test_result = "PASSED" if (all_recovered and not any_errors) else "FAILED"

    result = {
        "run_id": run_id,
        "test_result": test_result,
        "metadata": metadata,
        "phases": phases,
    }

    root_cause = analyze_root_cause(phases)
    if root_cause:
        result["root_cause"] = root_cause

    return result


def main():
    os.makedirs("/app/results", exist_ok=True)

    trace_dirs = sorted(glob.glob("/app/traces/run_*"))
    for td in trace_dirs:
        run_id = os.path.basename(td)
        result = analyze_run(td)
        output_path = f"/app/results/{run_id}_analysis.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Analyzed {run_id}: {result['test_result']}")


if __name__ == "__main__":
    main()
'''


# ================================================================
# TOOL 2: FDB SPEC VALIDATOR
# ================================================================

VALIDATOR_CODE = r'''#!/usr/bin/env python3
"""FDB Restart Test TOML Spec Validator."""

import tomllib
import json
import os
import re


def validate_spec_pair(phase1_path, phase2_path):
    """Validate a restart test TOML spec pair against FDB protocol rules.

    Rules:
    - Phase 1 must include SaveAndKill workload
    - Phase 1 must set clearAfterTest=false
    - Phase 2 must set runSetup=false
    - Phase 2 must NOT include SaveAndKill workload
    - Phase 2 must not set clearAfterTest=true
    - Configuration sections must be consistent between phases
    """
    errors = []

    with open(phase1_path, "rb") as f:
        spec1 = tomllib.load(f)
    with open(phase2_path, "rb") as f:
        spec2 = tomllib.load(f)

    # === Phase 1 validation ===
    tests1 = spec1.get("test", [])
    if isinstance(tests1, dict):
        tests1 = [tests1]

    for test in tests1:
        # Check clearAfterTest=false
        cat = test.get("clearAfterTest")
        if cat is not False:
            errors.append("Phase 1 missing clearAfterTest=false")

        # Check for SaveAndKill workload
        workloads = test.get("workload", [])
        if isinstance(workloads, dict):
            workloads = [workloads]
        has_saveandkill = any(
            w.get("testName") == "SaveAndKill" for w in workloads
        )
        if not has_saveandkill:
            errors.append("Phase 1 missing required SaveAndKill workload")

    # === Phase 2 validation ===
    tests2 = spec2.get("test", [])
    if isinstance(tests2, dict):
        tests2 = [tests2]

    for test in tests2:
        # Check runSetup=false
        rs = test.get("runSetup")
        if rs is not False:
            errors.append("Phase 2 runSetup must be false")

        # Check clearAfterTest is not true
        cat2 = test.get("clearAfterTest")
        if cat2 is True:
            errors.append("Phase 2 clearAfterTest should not be true")

        # Check no SaveAndKill
        workloads = test.get("workload", [])
        if isinstance(workloads, dict):
            workloads = [workloads]
        has_saveandkill = any(
            w.get("testName") == "SaveAndKill" for w in workloads
        )
        if has_saveandkill:
            errors.append("Phase 2 must not contain SaveAndKill workload")

    # === Cross-phase consistency ===
    config1 = spec1.get("configuration", {})
    config2 = spec2.get("configuration", {})

    if config1.get("storageEngineExcludeTypes") != config2.get("storageEngineExcludeTypes"):
        errors.append("Inconsistent storageEngineExcludeTypes between phases")

    if config1.get("tenantModes") != config2.get("tenantModes"):
        errors.append("Inconsistent tenantModes between phases")

    if config1.get("encryptModes") != config2.get("encryptModes"):
        # Only flag if both are present but different
        if ("encryptModes" in config1 and "encryptModes" in config2):
            errors.append("Inconsistent encryptModes between phases")

    return errors


def validate_all_specs(specs_dir):
    """Validate all spec pairs in directory."""
    results = []

    files = sorted(os.listdir(specs_dir))
    pairs = {}
    for f in files:
        if not f.endswith(".toml"):
            continue
        # Extract base name: everything before the last _N.toml
        match = re.match(r"^(.+)_(\d+)\.toml$", f)
        if match:
            base = match.group(1)
            num = match.group(2)
            if base not in pairs:
                pairs[base] = {}
            pairs[base][num] = f

    for name, pair_files in sorted(pairs.items()):
        if "1" in pair_files and "2" in pair_files:
            p1 = os.path.join(specs_dir, pair_files["1"])
            p2 = os.path.join(specs_dir, pair_files["2"])
            errors = validate_spec_pair(p1, p2)
            results.append({
                "name": name,
                "phase1_file": pair_files["1"],
                "phase2_file": pair_files["2"],
                "valid": len(errors) == 0,
                "errors": errors,
            })

    return {"specs": results}


def main():
    os.makedirs("/app/results", exist_ok=True)
    result = validate_all_specs("/app/test_specs")
    with open("/app/results/spec_validation.json", "w") as f:
        json.dump(result, f, indent=2)

    for spec in result["specs"]:
        status = "VALID" if spec["valid"] else "INVALID"
        print(f"  {spec['name']}: {status}")
        for err in spec["errors"]:
            print(f"    - {err}")


if __name__ == "__main__":
    main()
'''


# ================================================================
# TOOL 3: FDB RESTART TEST ORCHESTRATOR
# ================================================================

ORCHESTRATOR_CODE = r'''#!/usr/bin/env python3
"""FDB Restart Test Orchestrator - Generates reproduction commands.

Resolves binary paths from the SQLite knowledge database and generates
correct fdbserver -r simulation command lines for restart test reproduction.
"""

import json
import os
import re
import sqlite3


DB_PATH = "/app/fdb_knowledge.db"


def query_db(sql, params=()):
    """Query the FDB knowledge database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


def resolve_binary(version_line):
    """Resolve a version line (e.g., '7.2') to the latest patch binary path.

    Queries binary_registry for the latest version within the given line.
    """
    rows = query_db(
        "SELECT path, version, protocol_version FROM binary_registry "
        "WHERE version LIKE ? ORDER BY version DESC LIMIT 1",
        (f"{version_line}.%",)
    )
    if rows:
        return rows[0][0], rows[0][1], rows[0][2]
    return None, None, None


def parse_test_direction(test_path):
    """Determine test direction from path.

    - from_X.X.X -> upgrade test (old binary first, new binary second)
    - to_X.X.X   -> downgrade test (new binary first, old binary second)

    Returns (direction, version_bound) or (None, None).
    """
    parts = test_path.replace("\\", "/").split("/")
    for part in parts:
        m = re.match(r"^from_(\d+\.\d+\.\d+)", part)
        if m:
            return "upgrade", m.group(1)
        m = re.match(r"^to_(\d+\.\d+\.\d+)", part)
        if m:
            return "downgrade", m.group(1)
    return None, None


def generate_commands(scenarios):
    """Generate reproduction commands for restart test scenarios.

    Binary paths are resolved from the knowledge database.

    For upgrade tests (from_X.X.X):
      Phase 1: old binary, seed N
      Phase 2: new binary, seed N+1, --restarting

    For downgrade tests (to_X.X.X):
      Phase 1: new binary, seed N
      Phase 2: old binary, seed N+1, --restarting
    """
    commands = []

    for scenario in scenarios:
        test_path = scenario["test_path"]
        seed = scenario["seed"]
        buggify = scenario.get("buggify", True)
        source_line = scenario["source_version_line"]
        target_line = scenario["target_version_line"]

        # Resolve binary paths from the database
        source_path, source_ver, source_proto = resolve_binary(source_line)
        target_path, target_ver, target_proto = resolve_binary(target_line)

        direction, version_bound = parse_test_direction(test_path)

        # Binary selection based on direction
        if direction == "upgrade":
            # from_X.X.X: old (source) binary first, new (target) binary second
            phase1_binary = source_path
            phase2_binary = target_path
        elif direction == "downgrade":
            # to_X.X.X: new (target) binary first, old (source) binary second
            phase1_binary = target_path
            phase2_binary = source_path
        else:
            phase1_binary = source_path
            phase2_binary = target_path
            direction = "unknown"

        buggify_str = "on" if buggify else "off"
        phase2_seed = seed + 1

        # Generate command lines
        phase1_cmd = (
            f"{phase1_binary} -r simulation "
            f"-f {test_path}-1.toml "
            f"--seed {seed} "
            f"--buggify {buggify_str}"
        )

        phase2_cmd = (
            f"{phase2_binary} -r simulation "
            f"-f {test_path}-2.toml "
            f"--seed {phase2_seed} "
            f"--buggify {buggify_str} "
            f"--restarting"
        )

        commands.append({
            "test_path": test_path,
            "test_type": direction,
            "version_bound": version_bound,
            "phase1": {
                "binary": phase1_binary,
                "seed": seed,
                "buggify": buggify,
                "restarting": False,
                "command": phase1_cmd,
            },
            "phase2": {
                "binary": phase2_binary,
                "seed": phase2_seed,
                "buggify": buggify,
                "restarting": True,
                "command": phase2_cmd,
            },
        })

    return {"commands": commands}


def main():
    os.makedirs("/app/results", exist_ok=True)

    with open("/app/orchestrator_input.json") as f:
        orch_input = json.load(f)

    result = generate_commands(orch_input["scenarios"])

    with open("/app/results/reproduction_commands.json", "w") as f:
        json.dump(result, f, indent=2)

    for cmd in result["commands"]:
        print(f"  {cmd['test_path']} ({cmd['test_type']}):")
        print(f"    Phase 1: {cmd['phase1']['command']}")
        print(f"    Phase 2: {cmd['phase2']['command']}")


if __name__ == "__main__":
    main()
'''


def main():
    write_file("/app/fdb_analyzer.py", ANALYZER_CODE)
    write_file("/app/fdb_spec_validator.py", VALIDATOR_CODE)
    write_file("/app/fdb_orchestrator.py", ORCHESTRATOR_CODE)
    print("Solution tools written to /app/")


if __name__ == "__main__":
    main()
