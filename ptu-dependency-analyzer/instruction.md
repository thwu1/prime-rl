Build a command-line tool at `/app/ptu_analyzer.py` that performs dependency analysis and compilation scheduling on clang-repl-style C++ incremental compilation sessions.

LLVM's clang-repl processes C++ as a sequence of Partial Translation Units (PTUs), where each PTU incrementally extends the compilation state established by all previous ones. Your tool must parse session transcripts containing real C++ code — including templates, CRTP patterns, virtual dispatch hierarchies, operator overloading, and namespace-scoped definitions — model the accumulation of symbol definitions across PTUs, construct a cross-PTU dependency DAG, and answer structural and scheduling queries over it.

## Input

Session files at `/app/sessions/session_alpha.txt`, `/app/sessions/session_beta.txt`, and `/app/sessions/session_gamma.txt`. Each file contains PTUs delimited by `#=== PTU <N> ===#` markers.

## Invocation

```
python3 /app/ptu_analyzer.py <session_file> <command> [args]
```

## Dependency Model

PTU A directly depends on PTU B (A ≠ B) if A's source code references a user-defined name whose first definition appeared in PTU B at file or namespace scope.

A **definition** is a complete type definition (struct/class/enum with a body), a function definition (with a body), a type alias (`using X = ...`), or a variable/object declaration — all at file or namespace scope. Class and struct members (fields, member functions, nested types) belong to their enclosing type's definition and are not independently tracked as separate symbols. Template parameters are not definitions.

Built-in types (`int`, `double`, `void`, `bool`, `char`, `float`, `long`, `short`, `unsigned`, `signed`, `auto`) and C++ keywords are excluded.

A **reference** is any occurrence of a tracked name in the PTU's source code in type positions, expressions, or declarations — excluding the name immediately after `.` or `->` (member access positions).

When the same unqualified name is defined at file/namespace scope in multiple PTUs, the dependency targets the **earliest** defining PTU.

## Commands (JSON to stdout)

| Command | Output |
|---------|--------|
| `deps <n>` | `{"deps": [<sorted direct dependency PTU ids>]}` |
| `rdeps <n>` | `{"rdeps": [<sorted direct reverse dependency PTU ids>]}` |
| `undo-cascade <n>` | `{"cascade": [<sorted PTU ids transitively invalidated>]}` |
| `minimal-replay <n>` | `{"replay": [<sorted minimal PTU set including n itself>]}` |
| `dead-ptus` | `{"dead": [<sorted PTU ids with no dependents>]}` |
| `critical-path` | `{"path": [<ordered longest chain>], "length": <node count>}` |
| `compilation-tiers` | `{"tiers": [[<tier 0 ids>], [<tier 1 ids>], ...]}` |

## Query Semantics

- **undo-cascade**: Transitive forward closure through reverse dependencies. Does NOT include the undone PTU itself.
- **minimal-replay**: Transitive backward closure through dependencies, plus the target PTU.
- **dead-ptus**: PTUs with zero reverse dependencies.
- **critical-path**: Longest directed path in the DAG by node count. Ties broken by lexicographically smallest node-id sequence.
- **compilation-tiers**: Topological layering. Tier 0 contains PTUs with no dependencies. Tier k contains PTUs whose longest dependency chain from any tier-0 node has exactly k edges. PTU ids within each tier are sorted ascending.