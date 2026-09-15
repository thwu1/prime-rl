A dataset of kernel-style memory safety bugs is available at `/app/data/`:

- `/app/data/reports/bug_NNN.txt` — KASAN crash reports from the kernel address sanitizer
- `/app/data/sources/*.c` — C source files that reproduce each bug when compiled and executed
- `/app/data/patches/bug_NNN_patch_X.json` — Candidate function-level patches. Each JSON contains `source_file`, `target_function`, and `replacement` (the complete replacement function definition including signature and body)

Create `/app/rgym_eval.py`. When executed, it must analyze each bug's crash report, apply every candidate patch to its corresponding source, verify each patch for memory safety using both address sanitizer instrumentation and Valgrind memory checking, and write results to `/app/output/report.json`.

## Expected output

`/app/output/report.json` must conform to this structure:

```json
{
  "bugs": {
    "<bug_id>": {
      "report": {
        "bug_type": "<KASAN bug classification>",
        "access_type": "<Read or Write>",
        "access_size": "<int: violating access size in bytes>",
        "faulting_function": "<canonical function name, no compiler suffixes>",
        "source_location": "<file:line>",
        "call_stack": ["<canonical function names from the crash trace>"],
        "slab_cache": "<allocator cache name>",
        "object_size": "<int: allocated object size in bytes>"
      },
      "patches": {
        "<patch_id>": {
          "applied": "<bool>",
          "compiled": "<bool>",
          "result": "<pass|trigger|build_fail>",
          "valgrind_clean": "<true|false|null>"
        }
      }
    }
  },
  "summary": {
    "total_patches": "<int>",
    "pass_count": "<int>",
    "trigger_count": "<int>",
    "build_fail_count": "<int>",
    "pass_rate": "<float>"
  }
}
```

Field semantics:

- `result`: `"pass"` if the patched binary executes free of memory safety violations; `"trigger"` if violations persist at runtime; `"build_fail"` if the patched source fails to compile
- `valgrind_clean`: `true` if the patched binary runs without Valgrind memory errors, `false` if errors are detected, `null` for uncompilable patches
- `pass_rate`: ratio of passing patches to total patches