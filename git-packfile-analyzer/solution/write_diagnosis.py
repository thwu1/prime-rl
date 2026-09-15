#!/usr/bin/env python3
"""Write the diagnosis report documenting all discovered corruptions."""

import json

diagnosis = {
    "issues": [
        {
            "category": "head_corruption",
            "description": (
                "HEAD pointed to refs/heads/main which does not exist; "
                "the correct default branch is refs/heads/master. Fixed by "
                "writing 'ref: refs/heads/master' to .git/HEAD."
            )
        },
        {
            "category": "shallow_marker",
            "description": (
                "A spurious .git/shallow file was present containing a "
                "commit SHA, causing git to treat the repository as a "
                "shallow clone and hide part of the commit history. "
                "Removed the file to restore full history access."
            )
        },
        {
            "category": "pack_version",
            "description": (
                "The packfile header contained version 3 which is not "
                "supported by git (only version 2 is valid). Fixed by "
                "writing the correct version number 2 into bytes 4-7 of "
                "the pack header."
            )
        },
        {
            "category": "pack_checksum",
            "description": (
                "The packfile's trailing 20-byte SHA-1 checksum was zeroed "
                "out, preventing git from verifying pack integrity or "
                "generating a pack index. Fixed by computing SHA-1 over "
                "all pack data except the last 20 bytes and writing the "
                "correct checksum."
            )
        },
        {
            "category": "pack_index_missing",
            "description": (
                "The pack index (.idx) file was deleted from "
                ".git/objects/pack/, preventing git from looking up "
                "objects by SHA. Regenerated using git index-pack after "
                "repairing the packfile."
            )
        },
        {
            "category": "branch_ref_corruption",
            "description": (
                "The feature/string-utils branch ref in packed-refs "
                "pointed to a non-existent commit SHA (the last hex digit "
                "was altered). Fixed by examining the merge commit's "
                "second parent to determine the correct SHA for the "
                "feature branch head."
            )
        }
    ]
}

with open('/app/diagnosis.json', 'w') as f:
    json.dump(diagnosis, f, indent=2)

print(f"Diagnosis written to /app/diagnosis.json ({len(diagnosis['issues'])} issues)")
