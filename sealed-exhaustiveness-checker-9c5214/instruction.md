A sealed-type exhaustiveness checker project at `/app/` has defects across its build pipeline and analysis engine. The project uses a Makefile-based build that compiles Java sources, packages them into a JAR, and runs the checker via `java -jar /app/checker.jar <input_file>`.

**Project layout:**
- `/app/src/*.java` — Java sources (Types.java, ExhaustivenessChecker.java, Main.java)
- `/app/Makefile` — Build system (targets: `compile`, `jar`, `clean`)
- `/app/MANIFEST.MF` — JAR manifest
- `/app/testdata/test01.txt` through `test14.txt` — Test inputs

**Build and run:** `make -C /app jar && java -jar /app/checker.jar /app/testdata/test01.txt`

**Output format** (one line per switch block):
```
<id>:exhaustive=<bool>,null_handled=<bool>,missing=<semicolon-separated>,dominated=<semicolon-separated-indices>
```

**Exhaustiveness semantics the checker must implement:**

A switch over a **sealed type** is exhaustive when every permitted subtype is covered. If a permitted subtype is itself sealed, its subtypes must be transitively covered — matching all leaf types suffices without a pattern for intermediate sealed types.

A switch over an **enum type** is exhaustive when every declared constant is matched, regardless of whether constants have class bodies (anonymous subclasses at runtime).

A switch over a **record type** is exhaustive when, across all record deconstruction patterns for that type, each component position is independently exhaustive for that component's declared type.

**Guarded patterns** (with `when` clauses) never contribute to exhaustiveness — the guard may evaluate to false.

A `default` covers everything including null. A `null` covers only null.

**Dominance:** A type pattern for T dominates any pattern whose matched type is a subtype of T. A record pattern dominates another of the same type when each component pattern dominates its counterpart. `default` dominates everything.

**Success criteria:** `/tests/test.sh` must pass — all 14 test cases must produce expected output when the checker is built via `make -C /app jar` and run via `java -jar /app/checker.jar`.
