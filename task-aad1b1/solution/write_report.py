#!/usr/bin/env python3
"""Generate regression_report.json from git bisect results."""
import json
import sys

identity_sha = sys.argv[1] if len(sys.argv) > 1 else "unknown"
diff_sha = sys.argv[2] if len(sys.argv) > 2 else "unknown"

report = [
    {
        "issue_id": "001",
        "commit": identity_sha,
        "description": "Non-canonical structure: delete does not compact singleton sub-nodes or collision nodes back to inline entries"
    },
    {
        "issue_id": "002",
        "commit": identity_sha,
        "description": "Excessive memory: no-op inserts create new nodes instead of preserving object identity; delete does not compact sub-tree singletons"
    },
    {
        "issue_id": "003",
        "commit": diff_sha,
        "description": "Diff failures: missing identity shortcut for shared subtrees, collision diff only checks key presence not values, entry-vs-subnode incorrectly reports all keys as changed"
    }
]

with open('/app/regression_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"Wrote regression_report.json with {len(report)} entries")
