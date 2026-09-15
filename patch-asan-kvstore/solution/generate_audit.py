#!/usr/bin/env python3
"""Generate the peer review of the flawed audit and the corrected security audit."""

import json

# ------------------------------------------------------------------ #
#  Peer review: evaluate each entry in the prior analyst's audit      #
# ------------------------------------------------------------------ #

peer_review = {
    "reviews": [
        {
            "peer_audit_id": 1,
            "verdict": "partially_correct",
            "issues": [
                "Severity 'low' significantly understates the impact. A heap "
                "buffer overflow that corrupts malloc metadata can be leveraged "
                "for arbitrary write primitives via heap exploitation techniques "
                "(e.g., tcache poisoning, fastbin dup). This should be rated "
                "'high' at minimum."
            ],
            "corrected_severity": "high"
        },
        {
            "peer_audit_id": 2,
            "verdict": "incorrect",
            "issues": [
                "Root cause is misattributed to cmd_get. While the ASan report "
                "shows the crash in cmd_get (the read site), the actual root "
                "cause is in cmd_rename: after transferring old_e->value to "
                "new_e->value (pointer assignment), cmd_rename calls "
                "free(old_e->value), which invalidates the pointer now held by "
                "new_e. cmd_get merely reads through the dangling pointer — it "
                "is the victim, not the source of the bug."
            ],
            "corrected_function": "cmd_rename"
        },
        {
            "peer_audit_id": 3,
            "verdict": "correct",
            "issues": []
        },
        {
            "peer_audit_id": 4,
            "verdict": "incorrect",
            "issues": [
                "CWE-787 (Out-of-bounds Write) is incorrect. The vulnerability "
                "is an out-of-bounds read, not write. When end index exceeds "
                "the string length, memcpy reads past the source allocation "
                "boundary (the value's heap buffer), copying adjacent heap data "
                "into a correctly-sized output buffer. The correct "
                "classification is CWE-125 (Out-of-bounds Read). The "
                "description incorrectly states 'write beyond the allocated "
                "output buffer' when the overflow occurs on the read side."
            ],
            "corrected_cwe": "CWE-125"
        }
    ],
    "missing_vulnerabilities": [
        {
            "function": "cmd_copy",
            "cwe_id": "CWE-416",
            "description": (
                "Use-after-free when COPY is invoked with identical source and "
                "destination keys (self-copy). Since src_e and dst_e point to "
                "the same Entry, free(dst_e->value) invalidates src_e->value. "
                "The subsequent strdup(src_e->value) reads freed heap memory. "
                "No ASan report was provided because the PoC inputs do not "
                "exercise the self-copy path."
            )
        },
        {
            "function": "cmd_mget",
            "cwe_id": "CWE-121",
            "description": (
                "Stack buffer overflow in multi-get response formatting. A "
                "fixed MGET_BUF (512 byte) stack buffer receives unbounded "
                "sprintf output from multiple key-value pairs. When total "
                "formatted output exceeds 512 bytes, the sprintf calls corrupt "
                "the stack frame. No ASan report was provided because the PoC "
                "inputs use small values that fit within the buffer."
            )
        }
    ]
}

with open("/app/peer_review.json", "w") as f:
    json.dump(peer_review, f, indent=2)

print("Peer review written to /app/peer_review.json")

# ------------------------------------------------------------------ #
#  Corrected security audit with exploitability assessments           #
# ------------------------------------------------------------------ #

audit = {
    "vulnerabilities": [
        {
            "cwe_id": "CWE-122",
            "function": "parse_quoted",
            "severity": "high",
            "exploitability": "code_execution",
            "description": (
                "Off-by-one heap buffer overflow in quoted string parsing. "
                "malloc(len-2) allocates space for the unquoted content but "
                "omits the null terminator byte. When the quoted content has "
                "no escape sequences, j reaches len-2 and the terminating "
                "out[j]='\\0' writes one byte past the allocation, corrupting "
                "adjacent heap metadata. Heap metadata corruption can be "
                "leveraged for arbitrary write primitives via tcache poisoning "
                "or fastbin manipulation, enabling code execution."
            ),
            "fix_description": (
                "Changed allocation from malloc(len-2) to malloc(len-1) to "
                "include space for the null terminator."
            ),
        },
        {
            "cwe_id": "CWE-416",
            "function": "cmd_rename",
            "severity": "critical",
            "exploitability": "code_execution",
            "description": (
                "Use-after-free via pointer aliasing during key rename. "
                "new_e->value receives old_e->value (pointer transfer), "
                "then the old entry cleanup calls free(old_e->value), "
                "invalidating new_e->value. Subsequent access through the "
                "new key reads freed heap memory. The ASan report shows the "
                "crash in cmd_get (read site), but the root cause is the "
                "incorrect free in cmd_rename. The freed allocation can be "
                "reallocated with attacker-controlled content, enabling "
                "arbitrary code execution via vtable or function pointer "
                "overwrite."
            ),
            "fix_description": (
                "Removed free(old_e->value) since ownership was transferred "
                "to new_e. The pointer is simply nulled out in the old entry."
            ),
        },
        {
            "cwe_id": "CWE-121",
            "function": "cmd_keys",
            "severity": "high",
            "exploitability": "code_execution",
            "description": (
                "Stack buffer overflow in pattern normalization. The "
                "case-conversion loop copies the full user-supplied pattern "
                "into a fixed PATTERN_BUF (64 byte) stack buffer without "
                "any length check. A pattern exceeding 63 characters "
                "overwrites the return address and adjacent stack frames, "
                "enabling ROP-based code execution if stack canaries are "
                "absent."
            ),
            "fix_description": (
                "Added 'i < PATTERN_BUF - 1' guard to the normalization "
                "loop condition, truncating oversized patterns."
            ),
        },
        {
            "cwe_id": "CWE-125",
            "function": "cmd_getrange",
            "severity": "medium",
            "exploitability": "info_disclosure",
            "description": (
                "Heap buffer over-read due to unclamped end index. When the "
                "user-supplied end index exceeds the value's length, memcpy "
                "reads past the heap allocation boundary, potentially "
                "leaking adjacent heap data including other keys' values, "
                "freed memory contents, or heap metadata. This is strictly "
                "a read-side overflow — the destination buffer is correctly "
                "sized — so it cannot directly enable code execution, only "
                "information disclosure."
            ),
            "fix_description": (
                "Added 'if (end >= len) end = len - 1' to clamp the end "
                "index to the last valid position before computing the "
                "copy size."
            ),
        },
        {
            "cwe_id": "CWE-416",
            "function": "cmd_copy",
            "severity": "high",
            "exploitability": "code_execution",
            "description": (
                "Use-after-free when copying a key to itself. When source "
                "and destination keys are identical, src_e and dst_e point "
                "to the same entry. free(dst_e->value) invalidates "
                "src_e->value, and the subsequent strdup(src_e->value) "
                "reads freed memory. The freed chunk can be reclaimed by "
                "an intervening allocation with attacker-controlled data, "
                "enabling heap exploitation for code execution."
            ),
            "fix_description": (
                "Added early return when dst_e == src_e, since self-copy "
                "is a no-op that should not modify the entry."
            ),
        },
        {
            "cwe_id": "CWE-121",
            "function": "cmd_mget",
            "severity": "high",
            "exploitability": "code_execution",
            "description": (
                "Stack buffer overflow in multi-get response formatting. "
                "A fixed MGET_BUF (512 byte) stack buffer receives "
                "unbounded sprintf output from multiple key values. When "
                "total formatted output exceeds 512 bytes, the writes "
                "corrupt the stack frame, overwriting saved registers and "
                "the return address. This enables ROP-based code execution."
            ),
            "fix_description": (
                "Replaced the fixed-size stack buffer with direct printf "
                "calls for each entry, eliminating the intermediate buffer "
                "entirely."
            ),
        },
    ]
}

with open("/app/security_audit.json", "w") as f:
    json.dump(audit, f, indent=2)

print("Corrected security audit written to /app/security_audit.json")
