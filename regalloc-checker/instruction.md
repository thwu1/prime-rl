A SQLite database at `/app/programs.db` contains register-allocated programs from a compiler backend. Each program represents a function after register allocation, with physical register assignments for all virtual register operands, plus spill/reload/move instructions inserted by the allocator.

Implement a verification tool at `/app/regalloc_checker.py` that determines whether each program's register allocation preserves correct dataflow semantics. The tool must handle arbitrary control flow including loops, diamond-shaped branches merging at join points, spill/reload sequences across register pressure boundaries, and SSA block parameters that establish new bindings at block entry.

Read `/app/spec.md` for the database schema, instruction semantics, correctness criteria, and required output formats.

The checker is invoked as:
```
python3 /app/regalloc_checker.py <program_name>
```

It must read program data from the SQLite database (explore the schema using `sqlite3 /app/programs.db`) and produce:
- A JSON verdict on stdout with validity status and error details
- A Graphviz DOT file at `/app/output/<program_name>.dot` visualizing the control flow graph with blocks containing errors highlighted in red (must be valid input for `dot -Tsvg`)

The database contains 10 programs with both correct and incorrect allocations covering diverse control flow patterns. The checker must correctly classify all of them.