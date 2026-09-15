# kBenchSyz Multi-Trial Verification Protocol

## Purpose

Determines whether a kernel patch resolves a crash by running the crash
reproducer multiple times against the patched kernel. A single clean run
is insufficient due to non-deterministic crash reproduction.

## Constants

| Name | Value | Meaning |
|------|-------|---------|
| RERUN_SUCCESS | 3 | Clean runs needed for resolution |
| MAX_TRYS | 5 | Maximum trial slots per bug |

## Receipt Format

Each receipt is a JSON file containing job results:

```json
{
  "jobs": [
    {
      "bug_id": "component_name__variant",
      "execution": {
        "message": "no crash reproduced",
        "crash_description": null
      }
    }
  ]
}
```

- `bug_id` follows the format `name__K` (split on `__`)
- When `message` is non-null, it contains the execution outcome
- When `message` is null, `crash_description` contains crash details

## Sequential Processing

Receipts are processed strictly in order (receipt_1.json, receipt_2.json, ...).

### First Receipt

Establishes the candidate set:
- Bugs with clean execution (`message` equals "no crash reproduced") enter
  tracking with their first trial slot filled. Added to the active re-test list.
- Bugs where a crash was reproduced (`crash_description` is not null) are
  skipped entirely and never enter tracking.
- Bugs with other message values (e.g., "compilation error") are also
  excluded from tracking.

### Subsequent Receipts

Updates the active set only:
- Only bugs currently on the re-test list are processed; all others are skipped.
- Each result fills the next available trial slot for that bug.
- After updating, a bug is removed from the re-test list if any condition is met:
  1. It has accumulated RERUN_SUCCESS clean runs → resolved
  2. All MAX_TRYS slots are filled → exhausted
  3. A crash was reproduced in this trial (`crash_description` not null) → stops re-testing

## Final Classification

After all receipts are processed, each tracked bug with >= RERUN_SUCCESS
clean runs is **resolved**; all others are **unresolved**.
