A skeleton evaluation engine is provided at `/app/evaluator.py`. It has the CLI interface and evaluation loop in place, but every analytical function is a stub returning empty or default values. Case data is at `/app/data/cases/`.

The environment has `universal-ctags` and `patchutils` (`lsdiff`) pre-installed.

Each case directory contains:
- `crash_report.txt` — syzbot-style kernel crash report (KASAN use-after-free/slab-out-of-bounds, null-ptr-deref, or WARNING)
- `source/` — relevant kernel C source files (pre-patch state)
- `agent_patch.diff` — AI-generated unified diff
- `developer_patch.diff` — developer ground-truth unified diff

Design and implement all analytical components in `/app/evaluator.py` so that:

    python3 /app/evaluator.py /app/data/cases /app/output/results.json

produces correct per-case results conforming to this schema:

```json
{
  "<case_id>": {
    "crash_info": {
      "type": "<string|null: one of 'use-after-free', 'null-ptr-deref', 'slab-out-of-bounds', 'warning'>",
      "access_type": "<string|null: 'Read' or 'Write' if determinable, else null>",
      "file": "<string|null: kernel source file path from crash report>",
      "function": "<string|null: function name from crash report>",
      "line": "<integer|null: line number from crash report>"
    },
    "agent_patch": {
      "modified_files": ["<sorted file paths modified by agent patch>"],
      "modified_functions": ["<sorted 'filepath:functionname' entries>"]
    },
    "developer_patch": {
      "modified_files": ["<sorted file paths modified by developer patch>"],
      "modified_functions": ["<sorted 'filepath:functionname' entries>"]
    },
    "metrics": {
      "file_iou": "<float: IoU of agent vs developer modified file sets>",
      "function_iou": "<float: IoU of agent vs developer modified function sets>",
      "localization_hit": "<bool: crash file:function in agent's modified_functions>",
      "patch_equivalent": "<bool: patches produce structurally equivalent code>"
    }
  }
}
```

All file paths in output must be clean (no `a/` or `b/` diff prefixes). Function attribution must be source-aware: determine which functions changed by mapping actual changed line numbers to function definitions in the C source, not from diff hunk header context strings (which may reference a preceding function rather than the one actually modified). Patch equivalence must detect structural equivalence including consistent bijective identifier renaming and guard clause restructuring (early-return `if(!x) return v;` vs. wrapped-block `if(x) { body } return v;` producing semantically identical patched code).