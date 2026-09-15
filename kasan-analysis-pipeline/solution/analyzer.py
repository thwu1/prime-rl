#!/usr/bin/env python3

"""
Reference solution: Kernel APR Benchmark Evaluation Pipeline.

Reads data from SQLite database, parses KASAN crash reports,
classifies multi-VM verdicts, computes APR evaluation metrics,
and decodes KASAN shadow memory state.
"""

import json
import os
import re
import sqlite3

DB_PATH = "/app/benchmark.db"


# ============================================================
# KASAN Report Parser
# ============================================================

def parse_stack_frame(line):
    """Parse a single call stack frame line."""
    line = line.strip()
    if not line or line.startswith("<") or line.startswith("</"):
        return None

    # Inline frame: function source:line [inline]
    m = re.match(r'^(\S+)\s+([\w/.\-]+):(\d+)\s+\[inline\]$', line)
    if m:
        return {
            "function": m.group(1),
            "file": m.group(2),
            "line": int(m.group(3)),
            "is_inline": True,
        }

    # Non-inline frame: function+0xoffset/0xsize source:line
    m = re.match(r'^(\S+)\+0x[0-9a-f]+/0x[0-9a-f]+\s+([\w/.\-]+):(\d+)$', line)
    if m:
        return {
            "function": m.group(1),
            "file": m.group(2),
            "line": int(m.group(3)),
            "is_inline": False,
        }

    return None


def parse_stack_section(lines, start_idx):
    """Parse contiguous stack frames starting at start_idx."""
    frames = []
    idx = start_idx
    while idx < len(lines):
        line = lines[idx].strip()
        if not line or line.startswith("====="):
            break
        if re.match(r'^(Allocated|Freed|The buggy|Memory state|BUG:)', line):
            break
        if line in ("<IRQ>", "</IRQ>", "<TASK>", "</TASK>"):
            idx += 1
            continue
        frame = parse_stack_frame(line)
        if frame:
            frames.append(frame)
            idx += 1
            continue
        break
    return frames, idx


def decode_shadow_byte(text):
    """Extract the KASAN shadow byte at the faulting address.

    In KASAN memory state dumps, the '>' marks the row containing the
    faulting address, and '^' on the next line points to the shadow byte.
    Each shadow byte covers 8 bytes of real memory.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(">"):
            if i + 1 < len(lines):
                arrow_line = lines[i + 1]
                arrow_pos = arrow_line.find("^")
                if arrow_pos >= 0:
                    colon_pos = line.index(":")
                    data_start = colon_pos + 2
                    data_part = line[data_start:]
                    bytes_str = data_part.split()
                    byte_idx = (arrow_pos - data_start) // 3
                    if 0 <= byte_idx < len(bytes_str):
                        return bytes_str[byte_idx]
    return None


def parse_kasan_report(text, shadow_legend):
    """Parse a KASAN crash report into structured data."""
    result = {
        "bug_type": None,
        "access_type": None,
        "access_size": None,
        "faulting_function": None,
        "faulting_source_file": None,
        "faulting_source_line": None,
        "buggy_addr": None,
        "task_name": None,
        "pid": None,
        "cpu": None,
        "tainted": None,
        "crash_stack": [],
        "alloc_stack": None,
        "free_stack": None,
        "slab_cache": None,
        "slab_object_size": None,
        "alloc_size": None,
        "global_variable": None,
        "shadow_byte_value": None,
        "shadow_byte_meaning": None,
    }

    lines = text.split("\n")

    for i, line in enumerate(lines):
        # BUG line
        m = re.match(
            r'BUG: KASAN: (\S+) in (\S+)\+0x[0-9a-f]+/0x[0-9a-f]+\s+'
            r'([\w/.\-]+):(\d+)',
            line,
        )
        if m:
            result["bug_type"] = m.group(1)
            result["faulting_function"] = m.group(2)
            result["faulting_source_file"] = m.group(3)
            result["faulting_source_line"] = int(m.group(4))
            continue

        # Access line
        m = re.match(
            r'(Read|Write) of size (\d+) at addr ([0-9a-f]+) by task (.+)/(\d+)',
            line,
        )
        if m:
            result["access_type"] = m.group(1)
            result["access_size"] = int(m.group(2))
            result["buggy_addr"] = m.group(3)
            result["task_name"] = m.group(4)
            result["pid"] = int(m.group(5))
            continue

        # CPU / taint line
        m = re.match(r'CPU: (\d+) UID: \d+ PID: (\d+) Comm: (\S+)', line)
        if m:
            result["cpu"] = int(m.group(1))
            result["tainted"] = "Not tainted" not in line
            continue

        # Call Trace
        if line.strip() == "Call Trace:":
            frames, _ = parse_stack_section(lines, i + 1)
            result["crash_stack"] = frames
            continue

        # Allocated by task
        m = re.match(r'Allocated by task (\d+):', line)
        if m:
            frames, _ = parse_stack_section(lines, i + 1)
            result["alloc_stack"] = frames
            continue

        # Freed by task
        m = re.match(r'Freed by task (\d+):', line)
        if m:
            frames, _ = parse_stack_section(lines, i + 1)
            result["free_stack"] = frames
            continue

        # Slab cache info
        m = re.match(
            r'\s*which belongs to the cache (\S+) of size (\d+)', line
        )
        if m:
            result["slab_cache"] = m.group(1)
            result["slab_object_size"] = int(m.group(2))
            continue

        # Allocation size
        m = re.search(r'(?:allocated|freed) (\d+)-byte region', line)
        if m:
            result["alloc_size"] = int(m.group(1))
            continue

        # Global variable
        m = re.match(
            r'\s*(\w+)\+0x[0-9a-f]+/0x[0-9a-f]+\s+at\s+addr\s+[0-9a-f]+',
            line,
        )
        if m and result["bug_type"] == "global-out-of-bounds":
            result["global_variable"] = m.group(1)
            continue

    # Shadow memory analysis
    shadow_byte = decode_shadow_byte(text)
    if shadow_byte:
        result["shadow_byte_value"] = shadow_byte
        result["shadow_byte_meaning"] = shadow_legend.get(shadow_byte)

    return result


# ============================================================
# Multi-VM Verdict Classifier
# ============================================================

def classify_vm_verdict(outcomes):
    """Classify multi-VM verification outcome.

    Standard kernel patch verification semantics:
    - boot_fail takes priority (catastrophic failure)
    - All pass → pass
    - All trigger → trigger
    - Mix of pass and trigger → racey (non-deterministic bug)
    """
    counts = {"pass": 0, "trigger": 0, "boot_fail": 0, "other": 0}
    for o in outcomes:
        if o in counts:
            counts[o] += 1
        else:
            counts["other"] += 1

    if counts["boot_fail"] > 0:
        verdict = "boot_fail"
    elif counts["trigger"] > 0 and counts["pass"] > 0:
        verdict = "racey"
    elif counts["trigger"] > 0:
        verdict = "trigger"
    elif counts["pass"] > 0:
        verdict = "pass"
    else:
        verdict = "other"

    return {
        "verdict": verdict,
        "vm_count": sum(counts.values()),
        "pass_count": counts["pass"],
        "trigger_count": counts["trigger"],
        "boot_fail_count": counts["boot_fail"],
    }


# ============================================================
# Main Pipeline
# ============================================================

def main():
    os.makedirs("/app/output", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load shadow byte legend from database
    shadow_legend = {}
    c.execute("SELECT byte_value, description FROM shadow_byte_legend")
    for row in c.fetchall():
        shadow_legend[row[0]] = row[1]

    # --- 1. Crash Analysis ---
    crash_analysis = {}
    c.execute("SELECT report_id, raw_text FROM crash_reports ORDER BY report_id")
    for report_id, raw_text in c.fetchall():
        crash_analysis[report_id] = parse_kasan_report(raw_text, shadow_legend)

    # --- 2. Patch Verdicts ---
    patch_verdicts = {}
    c.execute("SELECT DISTINCT case_id FROM vm_test_runs ORDER BY case_id")
    cases = [row[0] for row in c.fetchall()]
    for case_id in cases:
        c.execute(
            "SELECT outcome FROM vm_test_runs "
            "WHERE case_id = ? ORDER BY vm_index",
            (case_id,),
        )
        outcomes = [row[0] for row in c.fetchall()]
        patch_verdicts[case_id] = classify_vm_verdict(outcomes)

    # --- 3. Experiment Metrics ---
    c.execute("SELECT COUNT(*) FROM experiment_bugs")
    total_bugs = c.fetchone()[0]

    c.execute(
        "SELECT config_name, cost_per_bug FROM experiment_configs "
        "ORDER BY config_name"
    )
    configs = [(row[0], row[1]) for row in c.fetchall()]

    config_solved = {}
    per_config = {}

    for config_name, cost in configs:
        c.execute(
            "SELECT bug_id, verdict, build_status FROM experiment_results "
            "WHERE config_name = ?",
            (config_name,),
        )
        solved = set()
        comp_fails = 0
        bad_patches = 0
        for bug_id, verdict, build_status in c.fetchall():
            if verdict == "pass":
                solved.add(bug_id)
            if build_status == "compilation_fail":
                comp_fails += 1
            elif build_status == "bad_patch":
                bad_patches += 1

        config_solved[config_name] = solved
        per_config[config_name] = {
            "pass_rate": len(solved) / total_bugs,
            "pass_count": len(solved),
            "total_bugs": total_bugs,
            "unique_solves": [],
            "unique_solve_count": 0,
            "avg_cost_per_bug": cost,
            "compilation_fail_count": comp_fails,
            "bad_patch_count": bad_patches,
        }

    # Unique solves: bugs solved by exactly one config
    all_config_names = [cn for cn, _ in configs]
    for config_name in all_config_names:
        others_solved = set()
        for other_name in all_config_names:
            if other_name != config_name:
                others_solved |= config_solved[other_name]
        unique = sorted(config_solved[config_name] - others_solved)
        per_config[config_name]["unique_solves"] = unique
        per_config[config_name]["unique_solve_count"] = len(unique)

    # Combined (union) metrics
    all_solved = set()
    for solved_set in config_solved.values():
        all_solved |= solved_set

    experiment_metrics = {
        "per_config": per_config,
        "combined_pass_rate": len(all_solved) / total_bugs,
        "combined_pass_count": len(all_solved),
        "combined_solved_bugs": sorted(all_solved),
        "total_bugs": total_bugs,
    }

    # --- Write output ---
    output = {
        "crash_analysis": crash_analysis,
        "patch_verdicts": patch_verdicts,
        "experiment_metrics": experiment_metrics,
    }

    with open("/app/output/evaluation.json", "w") as f:
        json.dump(output, f, indent=2)

    conn.close()
    print("Evaluation complete. Output written to /app/output/evaluation.json")


if __name__ == "__main__":
    main()
