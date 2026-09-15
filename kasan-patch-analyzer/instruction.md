A kernel crash triage workstation at `/app/` contains:
- KASAN sanitizer crash reports in `/app/crash_reports/`
- VM verification run data in `/app/verification_data/runs.json`
- Candidate kernel patches in `/app/patches/`
- Kernel source excerpts for patched subsystems in `/app/kernel_src/`

Build a Python package at `/app/kasan_analyzer/` (with `__init__.py`) that correctly analyzes all provided data. The package must expose four modules:

**`parser`**: `parse_kasan_report(text: str) -> KASANReport` — `KASANReport` fields: `bug_type`, `access_type`, `access_size`, `faulting_function`, `source_file`, `source_line`, `crash_addr`, `task_name`, `pid`, `call_stack` (list of `StackFrame`), `alloc_stack`, `free_stack`, `object_cache`, `object_size`. `StackFrame` fields: `function`, `offset`, `source_file`, `source_line`, `is_inline`.

**`localizer`**: `localize_bug(report) -> list[tuple[str, str, int, float]]` — Ranked root-cause candidates. The top result should identify the actual defect location.

**`verifier`**: `classify_verification(runs) -> VerificationOutcome` — Enum with values `PASS="pass"`, `TRIGGER="trigger"`, `RACEY="racey"`, `BOOT_FAIL="boot_fail"`. Run dicts have keys: `vm_id`, `type`, `outcome`, `duration_sec`.

**`patch_analyzer`**: `analyze_patch(patch_text, report, candidates) -> PatchAnalysis` — `PatchAnalysis` fields: `target_files`, `target_functions`, `patch_strategy`, `targets_buggy_file`, `strategy_matches_bug`, `classification` (one of `"plausible"`, `"helpful"`, `"wrong"`), `applies_cleanly`.

Study the provided data to determine parsing logic, classification thresholds, filtering criteria, and analysis rules.