A production renderer's dependency build system (`/app/CMakeLists.txt`) uses CMake `ExternalProject_Add` to build 13 third-party libraries from source. The build is failing. A partial build log is at `/app/build_errors.log` and the intended build specification is at `/app/build_spec.json`.

The build has **8 bugs** total. The error log captures only some of them. Several log entries suggest fixes that are incorrect or incomplete. Some bugs produce no build errors at all but violate version compatibility or configuration requirements documented in the specification. One bug causes silent degradation where the build succeeds but produces an incomplete library.

Fix all 8 bugs in `/app/CMakeLists.txt` and produce `/app/build_audit.json` containing:

- `"dependency_graph"`: adjacency list mapping each of the 13 project names to its list of direct dependencies (after all fixes are applied)
- `"topological_order"`: a valid topological build order (list of all 13 project names)
- `"critical_path"`: the longest dependency chain as a list of project names from root to terminal
- `"critical_path_length"`: integer length of the critical path
- `"max_parallelism"`: maximum number of projects buildable simultaneously with unlimited resources
- `"bugs_found"`: list of 8 objects, each with `"project"` (string), `"type"` (string), `"fix"` (string describing the change made), and `"root_cause_chain"` (string explaining the full causal chain from root cause through intermediate effects to the observed symptom)
- `"build_schedule"`: list of stages (each stage is a list of project names) forming a parallel build schedule that minimizes the number of stages under a **7 GB** peak memory constraint per stage (per-project memory costs are documented as `peak_memory_gb` in `build_spec.json`)
- `"schedule_makespan"`: number of stages in the schedule

Cross-reference `/app/build_spec.json` against `/app/CMakeLists.txt` to identify discrepancies that don't appear in the error log.