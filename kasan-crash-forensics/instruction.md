KASAN crash artifacts from Syzbot kernel fuzzing are at `/app/crash_data/`. The dataset contains raw sanitizer crash reports (`report_NNN.txt`), candidate kernel patches (`patch_NNN.diff`), and multi-VM patch verification result logs (`vm_results_NNN.json`). Each VM result file corresponds to the same-numbered patch; each entry has a `vm_id` and an `outcome` (one of: `no_crash`, `crash_same`, `crash_different`, `boot_fail`, `timeout`).

Produce two outputs:

**`/app/triage.db`** — SQLite database with three tables:

`crashes` — `id` INTEGER PRIMARY KEY, `report_file` TEXT, `bug_type` TEXT, `access_type` TEXT, `access_size` INTEGER, `faulting_function` TEXT, `faulting_file` TEXT, `faulting_line` INTEGER, `pid` INTEGER, `comm` TEXT, `slab_cache` TEXT, `object_size` INTEGER, `buggy_addr` TEXT, `object_addr` TEXT, `shadow_object_start` TEXT, `shadow_object_size` INTEGER, `shadow_is_freed` INTEGER, `shadow_oob_distance` INTEGER

`patch_verdicts` — `id` INTEGER PRIMARY KEY, `patch_file` TEXT, `verdict` TEXT (Pass/Trigger/Racey/BootFail), `confidence` REAL (0.0–1.0)

`correlations` — `crash_id` INTEGER, `patch_id` INTEGER, `touches_faulting_function` INTEGER (0/1), `file_overlap` TEXT (JSON array), `plausibility_score` REAL (0.0–1.0) — one row per crash-patch pair

**`/app/triage_report.json`** — JSON array of entries: `crash_id`, `report_file`, `bug_type`, `faulting_function`, `shadow_analysis` (object with `object_start`, `object_size`, `is_freed`, `oob_distance` — or null when absent), `recommended_patches` (sorted descending by `plausibility_score`; each: `patch_file`, `verdict`, `confidence`, `plausibility_score`).

Address columns and JSON address fields store hex strings. NULL columns indicate data absent from the report (e.g., SLAB metadata and shadow analysis are absent for null-pointer-dereference crashes). Patch verdicts derive from multi-VM outcomes using kernel APR verification semantics. Correlations reflect code-level overlap between each patch's modified source locations and crash call stacks.