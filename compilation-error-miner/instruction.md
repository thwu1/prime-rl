A C++ project at `/app/project/` (with `src/` and `include/` subdirectories) has multiple compilation errors across different source files. Raw GitHub Actions CI build logs from three compiler/platform configurations are at `/app/ci_logs/*.log`. A candidate fix patch is at `/app/patches/candidate_fix.patch`.

Create `/app/combench_analyzer.py` that produces `/app/output/analysis.json` when executed via `python3 /app/combench_analyzer.py`.

The analysis must contain:

- **`errors`**: Every unique compilation error across all log files, deduplicated by (file, line). Each error needs: project-relative `file`, `line`, `message`, `source_logs` (which log files reported this error), `is_cascading` (boolean: whether this error is a downstream effect of a defect in a different file), and when cascading: `root_cause_file` and `root_cause_line` identifying the actual origin of the defect. Warnings must not appear as errors.

- **`causal_dag`**: A mapping from each header-level root cause (identified as `"file:line"`) to the list of cascading error locations it produces across translation units. Only entries whose defect originates in a header file (and cascades into `.cpp` files via `#include` chains) should appear here. This requires tracing macro expansions and forward-declaration dependencies through include hierarchies to determine which reported errors share a common root cause in a header.

- **`candidate_evaluation`**: Semantic evaluation of the candidate fix patch. For each hunk: `file`, `necessary` (does it address an actual error?), and `semantically_correct` (does it fix the error properly without changing API contracts or breaking other callers?). Also include `missing_fixes`: error locations not addressed by the candidate patch. Determining semantic correctness requires understanding macro expansion scope, forward-declaration semantics, and the difference between fixing a definition vs. fixing a usage site.

- **`repair_patch`**: A self-generated unified diff that correctly fixes all compilation errors. The repair must fix at the appropriate locus—root causes in headers should be fixed in the header when it restores a missing definition, but macro-expansion errors should be fixed at usage sites rather than changing the macro's contract. The patch must be minimal and semantically correct.

- **`compilation_result`**: The tool must apply its repair patch to a copy of the project and compile every `.cpp` file with `g++` to prove zero errors. Report `success` (boolean) and `files_compiled` (list of files that were verified).