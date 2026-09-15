#!/usr/bin/env python3
"""Generate the audit report as /app/audit.json."""
import json

audit = [
    {
        "test_case": "comment_prefix",
        "root_cause": "implementation_bug",
        "description": "Parser only recognized directives after ';' prefix (anchored with ^;). Fixed to use re.search with re.escape(prefix), finding directives anywhere in a line after //, #, or any text."
    },
    {
        "test_case": "check_not_bounded",
        "root_cause": "implementation_bug",
        "description": "CHECK-NOT eagerly scanned from current position to end of file. Fixed by deferring NOT evaluation: accumulate pending NOTs, verify in [cur, match_pos) when the next positive directive matches."
    },
    {
        "test_case": "dag_backtrack",
        "root_cause": "implementation_bug",
        "description": "CHECK-DAG used greedy first-fit assignment. When variable X was captured as 'y' from the first matching line, 'store y' could not be found. Fixed with recursive backtracking that saves/restores self.variables on each branch."
    },
    {
        "test_case": "multi_prefix",
        "root_cause": "implementation_bug",
        "description": "Multiple prefixes were run as independent full passes over input. CHECK-NEXT after an ALT directive failed because the CHECK pass skipped the ALT line. Fixed by collecting all prefix directives, sorting by source line number, and running a single unified pass."
    },
    {
        "test_case": "count_repeat",
        "root_cause": "implementation_bug",
        "description": "CHECK-COUNT-N was treated as a plain CHECK, matching only once. After the single match, CHECK-NEXT expected end_of_items but found the second 'item: processed'. Fixed to match first forward then N-1 consecutive lines."
    },
    {
        "test_case": "interacting",
        "root_cause": "implementation_bug",
        "description": "Required both CHECK-NOT scope fix (bug 2) and CHECK-COUNT-N fix (bug 5). With either fix alone, the test still fails: bug 2 alone causes NOT to scan past COUNT matches, bug 5 alone causes COUNT to consume only 1 line making CHECK-NEXT fail."
    },
    {
        "test_case": "wrong_pattern",
        "root_cause": "wrong_pattern",
        "description": "CHECK-NEXT expected test_gamma immediately after test_beta, but input has test_delta between them. This is not a tool bug. Fixed by adding CHECK-NEXT: test_delta: pass between test_beta and test_gamma."
    },
    {
        "test_case": "count_fail",
        "root_cause": "implementation_bug",
        "description": "CHECK-COUNT-3 incorrectly passed with only 1 match because COUNT-N was treated as plain CHECK. After implementing proper consecutive matching, it correctly fails when only 2 of 3 required consecutive matches exist."
    }
]

with open("/app/audit.json", "w") as f:
    json.dump(audit, f, indent=2)

print("audit.json written to /app/audit.json")
