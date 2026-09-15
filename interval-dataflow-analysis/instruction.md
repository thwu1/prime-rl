The Maven-based Java project at `/app/` must compute integer value ranges of variables at each program point in a control flow graph. The provided source under `src/main/java/dataflow/` includes a CFG parser (`CfgParser.java`), IR data structures (`Instruction.java`, `BasicBlock.java`, `CFG.java`), and a stub entry point (`Main.java`). Complete the implementation by modifying `Main.java` and adding any needed classes under `src/main/java/dataflow/`.

Build:
```
cd /app && mvn -q compile dependency:copy-dependencies -DoutputDirectory=target/lib
```

Run:
```
java -cp "target/classes:target/lib/*" dataflow.Main <cfg-file> [json-output]
```

**Input**: `.cfg` files declaring `ENTRY`, `VARS`, and `BLOCK` sections with 3-address instructions. Some blocks carry a `LOOP_HEADER` annotation. See `CfgParser.java` and `inputs/` for the full grammar.

**Text output** (stdout) — one line per (block, position, variable). Blocks appear in input-file order; variables sorted alphabetically:
```
<block_id> entry <var> <interval>
<block_id> exit <var> <interval>
```
`<interval>` is `bot` (unreachable/undefined), `[-inf,inf]`, or `[lo,hi]` with integer or `-inf`/`inf` bounds.

**JSON output** (optional second argument) — structured report written with the Gson library (dependency declared in `pom.xml`):
```json
{"analysis":{"<block>":{"entry":{"<var>":"<interval>"},"exit":{"<var>":"<interval>"}}}}
```

The engine determines, for each declared variable at each program point, the tightest provable integer range. At the entry block's entry, all variables are `bot`. Assignment of `?` yields `[-inf,inf]`. Arithmetic where any operand is `bot` yields `bot`. Division by a range containing zero yields `[-inf,inf]`.

Conditional branches (`BRANCH`) constrain variable ranges on their outgoing edges. For example, `BRANCH x < 10 B1 B2` means on the true edge `x` is at most `9`; on the false edge `x` is at least `10`. All six comparisons (`<` `<=` `>` `>=` `==` `!=`) must be handled for both variable-vs-constant and variable-vs-variable forms. If a branch makes a variable's range empty, that edge is infeasible and the successor receives `bot` for all variables via that edge.

The analysis must terminate and produce precise results on programs containing loops.

Success: `bash /tests/test.sh` exits 0.
