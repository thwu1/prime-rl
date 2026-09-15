A formal specification of a nonstandard IMP language variant is provided at `/app/semantics.txt` using Small-Step Operational Semantics (SOS) inference rules. The grammar is at `/app/grammar.txt`, with a corresponding Lark parser generator grammar at `/app/imp.lark`.

Build a working interpreter that faithfully executes IMP programs according to the provided SOS rules. Your interpreter must use the Lark parser generator (pre-installed) with `/app/imp.lark` for parsing. The SOS rules define nonstandard semantics: the computation each syntactic operator performs is specified solely by the mathematical operation in the rule's premise (above the line) and the syntactic operator in its conclusion (below the line). These may diverge from conventional meanings. Do not assume standard operator behavior.

The language supports variable declarations (`int`), assignments, arithmetic (binary `+`,`-`,`*`,`/`,`%` and unary `+`,`-`), boolean expressions (relational, logical, negation), `if`/`else`, `while` loops with `break`/`continue`, and `halt`. The rules use a control stack (χ) with internal `LOOP` and `LE` constructs for loop management. Integer division truncates toward zero.

**Part 1 — Execution.** Ten IMP programs are in `/app/programs/`. For each `<name>.imp`, write the final variable state to `/app/output/<name>.json` as a JSON object mapping variable names (sorted alphabetically) to integer values. Then use `jq` to construct `/app/output/summary.json` merging all results: keys are program names (sorted), values are the corresponding state objects.

**Part 2 — Semantic Debugging.** Three IMP programs in `/app/buggy/` were written assuming standard operator semantics and produce incorrect results under the nonstandard SOS rules. `/app/buggy/intent.json` describes the intended computation for each. Diagnose why each program fails under the provided SOS rules, then produce a corrected version. For each `<name>.imp`:
- Write the corrected program to `/app/output/<name>_fixed.imp`
- Run the corrected program through your interpreter and write its output to `/app/output/<name>_fixed.json`

The corrected programs must be valid IMP (parseable by `/app/imp.lark`) and must produce the intended result under the nonstandard SOS rules.

**Part 3 — Program Synthesis.** Three challenge specifications in `/app/challenges/` each describe a computation with input values and required output. For each `<name>.json`, write an IMP program from scratch that correctly implements the specified algorithm under the nonstandard SOS rules. Each challenge specifies syntactic constraints (e.g., must use a `while` loop) that the program must satisfy. For each challenge:
- Write the synthesized program to `/app/output/<name>_synth.imp`
- Run it through your interpreter and write its output to `/app/output/<name>_synth.json`

The synthesized programs must produce correct results when executed under the nonstandard semantics. You must reason about the complete operator mapping holistically to determine which syntactic operators implement each desired mathematical operation, then compose them into working algorithms with correct loop termination conditions and arithmetic.