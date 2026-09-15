A parameterized crossbar switch design at `/app/design/` was ported from a VCS-based project. The `slang` SystemVerilog compiler is at `/usr/local/bin/slang`. The design has multiple categories of defects:

- Some produce compilation errors with cascading diagnostics (one root cause generates multiple error messages across files)
- Others compile silently under default flags but are semantic bugs only detectable through slang's extended warning system — the code is syntactically valid but functionally incorrect
- A design specification at `/app/design/SPEC.md` documents the intended parameterization contract

Produce these deliverables:

- `/app/build.f` — A slang command file that compiles the full design with correct include paths, library search directories, and source file listings. After all fixes are applied, `slang -f /app/build.f -f /app/warning_policy.f` must exit 0 with zero errors and zero warnings.

- Fix all defects in `/app/design/` source files. This includes both compilation errors and silent semantic bugs. Use slang's warning flags (e.g. `-Weverything` and individual `-W` flags) to discover issues that default compilation misses. Cross-reference against the specification in `/app/design/SPEC.md`. Do not modify code that is intentionally correct.

- `/app/warning_policy.f` — A slang warning configuration file that enables `-Weverything` for maximum coverage, then selectively suppresses only the false-positive warnings using individual `-Wno-<name>` flags. Must NOT use `-Wnone`. Each suppression must correspond to an intentional design pattern (e.g., ports reserved for future pipelining, documentation-only parameters).

- `/app/triage_report.json` — A JSON object documenting the diagnostic analysis:
  - `"compilation_errors"`: array of objects each with `"file"` (basename), `"description"`, `"root_cause"`
  - `"silent_bugs"`: array of objects each with `"file"` (basename), `"description"`, `"how_detected"`
  - `"false_positives"`: array of objects each with `"warning_flag"` (e.g. `-Wno-unused-port`), `"reason_suppressed"`

- `/app/hierarchy_report.json` — Module hierarchy extracted from slang's `--ast-json` output, as a JSON object with a `"modules"` key containing an array. Each module entry must have `"name"` (string), `"ports"` (array of objects with `"name"` and `"direction"`), and `"parameters"` (array of objects with `"name"` and `"value"`). Must include all 5 elaborated modules: `top_xbar`, `round_robin_arb`, `xbar_switch`, `priority_enc`, `addr_decoder`.