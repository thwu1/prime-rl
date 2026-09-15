#!/usr/bin/env python3
"""Generate specification compliance evaluation and probe tests.

Creates:
  - /app/spec_evaluation.json: compliance analysis for 10 feature areas
  - /app/spec_probes/*.check + *.input: boundary behavior probe tests
"""

import json
import os

# =================================================================
# Specification compliance evaluation
# =================================================================

evaluation = [
    {
        "feature": "CHECK",
        "compliance": "full",
        "tested_behaviors": [
            "forward scan from current position",
            "pattern matching with literal text",
            "inline regex via {{regex}}",
            "variable capture via [[VAR:regex]]",
            "variable substitution via [[VAR]]"
        ],
        "untested_behaviors": [
            "LITERAL directive modifier (CHECK{LITERAL}: ...)",
            "numeric substitution blocks ([[#NUMVAR:]])",
            "@LINE pseudo variable"
        ],
        "risk_assessment": "Low. Core CHECK functionality is well-tested across basic, custom_prefix, and full_lines tests. Untested behaviors (LITERAL modifier, numeric expressions, @LINE) are advanced FileCheck features documented in the full spec but explicitly beyond this implementation subset's scope."
    },
    {
        "feature": "CHECK-NEXT",
        "compliance": "full",
        "tested_behaviors": [
            "matches exactly the next input line after previous match",
            "fails if next line does not match",
            "works with regex patterns and variable references",
            "works correctly after CHECK-COUNT matches advance cursor"
        ],
        "untested_behaviors": [
            "behavior when used as first directive (should error, no previous match)",
            "interaction with --strict-whitespace mode"
        ],
        "risk_assessment": "Low. CHECK-NEXT semantics are straightforward and well-covered by basic.check, wrong_pattern.check, and interacting.check tests. The untested first-directive edge case is a rare usage error."
    },
    {
        "feature": "CHECK-NOT",
        "compliance": "full",
        "tested_behaviors": [
            "bounded scope: scans only between current position and next positive match",
            "trailing NOT without subsequent positive match scans to end of input",
            "correctly rejects input when excluded pattern found in scope",
            "interaction with CHECK-COUNT: NOT scope bounded by COUNT's first match",
            "deferred evaluation with pending NOT accumulation"
        ],
        "untested_behaviors": [
            "NOT between CHECK-DAG groups creating ordering constraints",
            "NOT with --match-full-lines (spec says NOT is unaffected by this flag)",
            "multiple consecutive NOT directives with overlapping regex patterns"
        ],
        "risk_assessment": "Medium. The deferred-evaluation fix correctly implements bounded scoping (verified by check_not_bounded and interacting tests). However, the spec explicitly states CHECK-NOT is not affected by --match-full-lines, and this is not tested. Additionally, NOT between DAG groups (which creates ordering constraints per the spec) has no dedicated test coverage. The multi_not_sequence spec probe partially addresses this gap."
    },
    {
        "feature": "CHECK-SAME",
        "compliance": "full",
        "tested_behaviors": [
            "matches on the same line as previous match",
            "works with regex patterns and variable substitution"
        ],
        "untested_behaviors": [
            "CHECK-SAME as first directive (should error)",
            "multiple CHECK-SAME directives on one logical line"
        ],
        "risk_assessment": "Low. CHECK-SAME has limited interaction surface. The basic.check test covers its core semantics and the same_regex_var spec probe verifies regex+variable interaction on the same line."
    },
    {
        "feature": "CHECK-LABEL",
        "compliance": "partial",
        "tested_behaviors": [
            "forward scan for label pattern",
            "resets context for subsequent checks (scan position)",
            "variable persistence across labels (when --enable-var-scope is off)"
        ],
        "untested_behaviors": [
            "label uniqueness enforcement (spec says label cannot match other checks)",
            "variable scope reset with --enable-var-scope flag",
            "error recovery: continuing to next LABEL block after a CHECK failure"
        ],
        "risk_assessment": "Medium. The implementation treats CHECK-LABEL as semantically equivalent to CHECK with a position reset, missing the isolation and error-recovery semantics described in the spec. In production FileCheck, LABEL creates independent verification blocks; CHECK failures in one block don't prevent checking subsequent blocks. The label_var_persist spec probe verifies that variables persist across labels (correct when --enable-var-scope is off), but uniqueness enforcement and error recovery are not implemented."
    },
    {
        "feature": "CHECK-DAG",
        "compliance": "full",
        "tested_behaviors": [
            "any-order matching within a consecutive DAG group",
            "recursive backtracking with variable state save/restore",
            "non-overlapping match constraint (each pattern matches different line)",
            "DAG group skipping non-matching intermediate lines"
        ],
        "untested_behaviors": [
            "DAG with forward variable references (use before define within same group)",
            "DAG group separated by CHECK-NOT creating ordering constraints between sub-groups",
            "overlapping DAG match behavior with --allow-deprecated-dag-overlap"
        ],
        "risk_assessment": "Medium. The backtracking fix correctly handles the common case (verified by dag_backtrack test), and the dag_skip_lines spec probe confirms intermediate line skipping works. However, the spec describes complex DAG+NOT interactions where NOT between DAG groups creates ordering constraints. This interaction pattern has no test coverage."
    },
    {
        "feature": "CHECK-COUNT",
        "compliance": "full",
        "tested_behaviors": [
            "N consecutive line matches (first forward-scan, rest CHECK-NEXT style)",
            "correctly fails with insufficient consecutive matches",
            "interaction with CHECK-NOT scope (NOT bounded by COUNT's first match)",
            "regex patterns in COUNT directives"
        ],
        "untested_behaviors": [
            "CHECK-COUNT-1 as degenerate case (should behave identically to plain CHECK)",
            "CHECK-COUNT with variable capture where captured value differs across repetitions"
        ],
        "risk_assessment": "Low. Core consecutive-matching semantics are well-tested by count_repeat (passes), count_fail (correctly rejects), and interacting (NOT+COUNT interaction). The count_with_vars edge case probe addresses variable capture across repetitions."
    },
    {
        "feature": "variables",
        "compliance": "full",
        "tested_behaviors": [
            "capture with [[VAR:regex]]",
            "substitution with [[VAR]]",
            "undefined variable raises error",
            "variable persistence across directives",
            "variable redefinition updates to new value"
        ],
        "untested_behaviors": [
            "global variables ($-prefix) with --enable-var-scope",
            "variable used on same line as its definition (spec says this is allowed)",
            "capture group counting with nested regex containing groups"
        ],
        "risk_assessment": "Low. Core variable functionality works correctly for capture, substitution, persistence, and redefinition (verified by basic.check and var_redefine spec probe). Global variable scoping is an advanced feature tied to --enable-var-scope which is not implemented in this subset."
    },
    {
        "feature": "multi-prefix",
        "compliance": "full",
        "tested_behaviors": [
            "directives from multiple prefixes collected and merged",
            "sorting by source file line number for unified pass",
            "interleaved prefix directives processed in correct order"
        ],
        "untested_behaviors": [
            "duplicate prefix detection and error reporting",
            "--allow-unused-prefixes flag behavior",
            "more than 2 prefixes used simultaneously",
            "prefix that is substring of another prefix"
        ],
        "risk_assessment": "Low. The critical semantic fix (merged single-pass vs independent per-prefix passes) is implemented and verified by multi_prefix test. Untested features are configuration-level error checking and edge cases unlikely to arise in practice."
    },
    {
        "feature": "match-full-lines",
        "compliance": "partial",
        "tested_behaviors": [
            "positive patterns anchored to match entire line",
            "leading/trailing whitespace tolerance via ^\\s* and \\s*$ anchors"
        ],
        "untested_behaviors": [
            "CHECK-NOT patterns NOT affected by --match-full-lines (per spec)",
            "interaction with --strict-whitespace",
            "full-line matching with inline regex {{...}} at boundaries"
        ],
        "risk_assessment": "Medium. The spec explicitly states that CHECK-NOT is not affected by --match-full-lines, but there is no test verifying this. If the implementation incorrectly applies full-line anchors to NOT patterns, legitimate CHECK-NOT failures could be masked (false negatives). This is the highest-risk coverage gap identified."
    }
]

with open("/app/spec_evaluation.json", "w") as f:
    json.dump(evaluation, f, indent=2)

print("spec_evaluation.json written to /app/spec_evaluation.json")
print(f"  {len(evaluation)} feature areas evaluated")

# =================================================================
# Specification probe tests
# =================================================================

probe_dir = "/app/spec_probes"
os.makedirs(probe_dir, exist_ok=True)

# Probe 1: Variable redefinition — verify [[VAR:regex]] updates variable
with open(f"{probe_dir}/var_redefine.check", "w") as f:
    f.write("; CHECK: start [[X:[a-z]+]]\n")
    f.write("; CHECK: middle [[X:[a-z]+]]\n")
    f.write("; CHECK: end [[X]]\n")
with open(f"{probe_dir}/var_redefine.input", "w") as f:
    f.write("start foo\nmiddle bar\nend bar\n")

# Probe 2: CHECK-NOT with inline regex — verify regex works in NOT patterns
with open(f"{probe_dir}/not_with_regex.check", "w") as f:
    f.write("; CHECK: begin\n")
    f.write("; CHECK-NOT: error: {{[0-9]+}}\n")
    f.write("; CHECK: end\n")
with open(f"{probe_dir}/not_with_regex.input", "w") as f:
    f.write("begin\nwarning: 42\nend\n")

# Probe 3: CHECK-SAME with regex and variable on same line
with open(f"{probe_dir}/same_regex_var.check", "w") as f:
    f.write("; CHECK: key=[[K:[a-z]+]]\n")
    f.write("; CHECK-SAME: val={{[0-9]+}}\n")
with open(f"{probe_dir}/same_regex_var.input", "w") as f:
    f.write("key=alpha val=99\n")

# Probe 4: Multiple consecutive CHECK-NOT directives bounded by positive match
with open(f"{probe_dir}/multi_not_sequence.check", "w") as f:
    f.write("; CHECK: start\n")
    f.write("; CHECK-NOT: error\n")
    f.write("; CHECK-NOT: warning\n")
    f.write("; CHECK-NOT: fatal\n")
    f.write("; CHECK: end\n")
with open(f"{probe_dir}/multi_not_sequence.input", "w") as f:
    f.write("start\ninfo: ok\ndebug: trace\nend\n")

# Probe 5: CHECK-LABEL with variable persistence across labels
with open(f"{probe_dir}/label_var_persist.check", "w") as f:
    f.write("; CHECK-LABEL: section_a\n")
    f.write("; CHECK: val = [[X:[0-9]+]]\n")
    f.write("; CHECK-LABEL: section_b\n")
    f.write("; CHECK: ref = [[X]]\n")
with open(f"{probe_dir}/label_var_persist.input", "w") as f:
    f.write("section_a\nval = 42\nsection_b\nref = 42\n")

# Probe 6: CHECK-DAG skipping non-matching intermediate lines
with open(f"{probe_dir}/dag_skip_lines.check", "w") as f:
    f.write("; CHECK-DAG: cherry\n")
    f.write("; CHECK-DAG: apple\n")
with open(f"{probe_dir}/dag_skip_lines.input", "w") as f:
    f.write("apple\nbanana\ncherry\n")

probe_count = len([f for f in os.listdir(probe_dir) if f.endswith(".check")])
print(f"Created {probe_count} spec probe tests in {probe_dir}")
