#!/usr/bin/env python3

"""
TTCN-3 SIP Conformance Test Suite Static Analyzer

Parses ETSI TTCN-3 SIP test suite source files, extracts testcase
definitions and control block execution scheduling, cross-references
to find guard/execute defects, and builds an RFC coverage map.
"""

import re
import json
from pathlib import Path
from collections import Counter, defaultdict

TTCN3_DIR = Path("/app/ttcn3")
OUTPUT = Path("/app/analysis_results.json")


def parse_testcases(filepath):
    """
    Extract unique testcase declarations and their with-extension metadata
    from a TTCN-3 source file.

    Returns (module_name, {tc_name: {module, metadata}}).
    """
    content = filepath.read_text(errors="replace")

    # Extract module name
    mod_m = re.search(r"\bmodule\s+(\w+)\s*\{", content)
    module_name = mod_m.group(1) if mod_m else filepath.stem

    # Locate every testcase declaration
    tc_regex = re.compile(r"\btestcase\s+(SIP_\w+)\s*\(")
    tc_hits = [(m.group(1), m.start()) for m in tc_regex.finditer(content)]

    # Locate every with { ... } block
    with_regex = re.compile(r"\bwith\s*\{([^}]+)\}", re.DOTALL)
    with_blocks = [(m.start(), m.group(1)) for m in with_regex.finditer(content)]

    testcases = {}
    seen = set()

    for idx, (name, pos) in enumerate(tc_hits):
        if name in seen:
            continue
        seen.add(name)

        # Boundary: next testcase declaration or end of file
        next_pos = tc_hits[idx + 1][1] if idx + 1 < len(tc_hits) else len(content)

        # Find the first with block between this tc and the next
        metadata = {}
        for wb_pos, wb_text in with_blocks:
            if pos < wb_pos < next_pos:
                for ext in re.finditer(
                    r'extension\s+"(\w+):\s*(.*?)"', wb_text, re.DOTALL
                ):
                    key = ext.group(1).strip().lower()
                    val = re.sub(r"\s+", " ", ext.group(2).strip())
                    metadata[key] = val
                break  # only the first with block

        testcases[name] = {"module": module_name, "metadata": metadata}

    return module_name, testcases


def parse_control_block(filepath):
    """
    Walk the control block of SIP_MainModule.ttcn and extract:
      - active (guard_function, testcase) pairs
      - voided testcase names (in comments)

    Handles /* */ block comments, // line comments, and multi-line
    execute() statements where the testcase name is on a following line.
    Only considers comments within the control block, not the file header.
    """
    content = filepath.read_text(errors="replace")

    cb_start = content.find("control {")
    if cb_start < 0:
        return [], []

    cb = content[cb_start:]

    # --- Phase 1: separate commented and active text ---
    voided = []
    active_chars = []
    i = 0
    in_block = False

    while i < len(cb):
        if in_block:
            end = cb.find("*/", i)
            if end < 0:
                commented = cb[i:]
                for m in re.finditer(r"execute\s*\(\s*(SIP_\w+)", commented):
                    voided.append(m.group(1))
                break
            commented = cb[i:end]
            for m in re.finditer(r"execute\s*\(\s*(SIP_\w+)", commented):
                voided.append(m.group(1))
            i = end + 2
            in_block = False
        else:
            bc = cb.find("/*", i)
            lc = cb.find("//", i)
            nl = cb.find("\n", i)

            next_bc = bc if bc >= 0 else len(cb)
            next_lc = lc if lc >= 0 else len(cb)
            next_nl = nl if nl >= 0 else len(cb)

            if next_bc <= next_lc and next_bc < next_nl and bc >= 0:
                active_chars.append(cb[i:next_bc])
                i = next_bc + 2
                in_block = True
            elif next_lc <= next_bc and next_lc < next_nl and lc >= 0:
                active_chars.append(cb[i:next_lc])
                line_end = next_nl if nl >= 0 else len(cb)
                commented = cb[next_lc + 2 : line_end]
                em = re.search(r"execute\s*\(\s*(SIP_\w+)", commented)
                if em:
                    voided.append(em.group(1))
                active_chars.append("\n")
                i = line_end + 1
            else:
                end = next_nl + 1 if nl >= 0 else len(cb)
                active_chars.append(cb[i:end])
                i = end

    active_text = "".join(active_chars)

    # --- Phase 2: extract guard/execute pairs from clean text ---
    active_pairs = []

    guards = [(m.start(), m.group(1)) for m in
              re.finditer(r"if\s*\((\w+)\(\)\)", active_text)]
    executes = [(m.start(), m.group(1)) for m in
                re.finditer(r"execute\s*\(\s*(SIP_\w+)", active_text)]

    gi = 0
    for epos, tc_name in executes:
        while gi + 1 < len(guards) and guards[gi + 1][0] < epos:
            gi += 1
        if gi < len(guards) and guards[gi][0] < epos:
            active_pairs.append((guards[gi][1], tc_name))

    return active_pairs, voided


def guard_to_expected_tc(guard):
    """
    Derive the expected testcase name from a guard function name.

    Convention: run<AB><CD>...<BEHAVIOR><NNN>
    Each pair of letters maps to an underscore-separated segment.
    BEHAVIOR is one of: TI, SM, V, I, O
    NNN is zero-padded to 3 digits.

    Example: runCCPRMPRQV001 -> SIP_CC_PR_MP_RQ_V_001
    """
    if not guard.startswith("run"):
        return None

    body = guard[3:]

    num_m = re.search(r"(\d+)$", body)
    if not num_m:
        return None
    number = num_m.group(1).zfill(3)
    prefix = body[: num_m.start()]

    for beh in ("TI", "SM", "V", "I", "O"):
        if prefix.endswith(beh):
            behavior = beh
            group_abbrev = prefix[: -len(beh)]
            break
    else:
        return None

    if len(group_abbrev) % 2 != 0 or len(group_abbrev) == 0:
        return None

    segments = [group_abbrev[i : i + 2] for i in range(0, len(group_abbrev), 2)]
    return "SIP_" + "_".join(segments) + "_" + behavior + "_" + number


def find_defects(pairs):
    """
    Cross-reference guard/execute pairs to find:
      - guard_mismatches: expected tc differs from actual
      - duplicate_guards: same guard used for multiple execute() calls
    """
    guard_counter = Counter(g for g, _ in pairs)
    dupes = []
    for guard, count in sorted(guard_counter.items()):
        if count > 1:
            tcs = [t for g, t in pairs if g == guard]
            dupes.append({"guard_function": guard, "testcases": tcs})

    mismatches = []
    for guard, testcase in pairs:
        expected = guard_to_expected_tc(guard)
        if expected is None or expected == testcase:
            continue

        def parse_tc(name):
            parts = name.replace("SIP_", "").rsplit("_", 2)
            if len(parts) == 3:
                return parts[0], parts[1], parts[2]
            return None, None, None

        exp_group, exp_beh, exp_num = parse_tc(expected)
        act_group, act_beh, act_num = parse_tc(testcase)

        if exp_group != act_group:
            dtype = "cross_group_mismatch"
        elif exp_beh != act_beh:
            dtype = "behavior_type_mismatch"
        else:
            dtype = "number_mismatch"

        mismatches.append(
            {
                "guard_function": guard,
                "executed_testcase": testcase,
                "expected_testcase": expected,
                "defect_type": dtype,
            }
        )

    return mismatches, dupes


def extract_rfc_coverage(all_testcases):
    """
    Build a mapping from RFC 3261 section numbers to testcase names,
    extracted from 'Reference' metadata in with-extension blocks.
    """
    coverage = defaultdict(set)

    for name, tc in all_testcases.items():
        ref = tc.get("metadata", {}).get("reference", "")
        if not ref:
            continue

        clean = re.sub(r"\[\d+\]", "", ref)

        for sec in re.findall(r"\b(\d+(?:\.\d+)+)\b", clean):
            coverage[sec].add(name)

    return {k: sorted(v) for k, v in sorted(coverage.items())}


def main():
    all_testcases = {}
    module_counts = {}

    for ttcn_file in sorted(TTCN3_DIR.glob("*.ttcn")):
        if "MainModule" in ttcn_file.name:
            continue
        module_name, testcases = parse_testcases(ttcn_file)
        all_testcases.update(testcases)
        module_counts[module_name] = len(testcases)

    main_module = TTCN3_DIR / "SIP_MainModule.ttcn"
    active_pairs, voided_raw = parse_control_block(main_module)

    voided = sorted(set(voided_raw))

    mismatches, dupes = find_defects(active_pairs)

    rfc_coverage = extract_rfc_coverage(all_testcases)

    results = {
        "testcase_definitions": {
            **module_counts,
            "total": sum(module_counts.values()),
        },
        "control_block": {
            "active_executions": len(active_pairs),
            "voided_testcases": voided,
        },
        "defects": {
            "guard_mismatches": mismatches,
            "duplicate_guards": dupes,
            "total_defect_count": len(mismatches) + len(dupes),
        },
        "rfc_coverage": rfc_coverage,
    }

    OUTPUT.write_text(json.dumps(results, indent=2))

    print(f"Analysis complete. Results written to {OUTPUT}")
    print(f"  Testcase definitions: {results['testcase_definitions']}")
    print(f"  Active executions:    {results['control_block']['active_executions']}")
    print(f"  Voided testcases:     {len(voided)}")
    print(f"  Guard mismatches:     {len(mismatches)}")
    print(f"  Duplicate guards:     {len(dupes)}")
    print(f"  RFC sections covered: {len(rfc_coverage)}")


if __name__ == "__main__":
    main()
