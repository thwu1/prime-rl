The seL4 microkernel's formal access control model is specified in Isabelle/HOL at `/app/spec/Access.thy` (from the L4.verified project). A snapshot of kernel security state is at `/app/system_state.json`.

Produce a complete security analysis in `/app/output/` containing four artifacts:

**`authority_graph.json`** — The complete authority graph derived from the system state according to the formal specification, with all wellformedness closure conditions applied. Include answers to all queries defined in the system state file.

```json
{
  "authority_graph": {
    "<source_label>": {
      "<target_label>": ["AuthType1", "AuthType2"]
    }
  },
  "query_results": {
    "<query_id>": "<result>"
  }
}
```

Authority type lists must be sorted alphabetically. Only include source-target pairs with non-empty authority sets. Query result types: `authority_set` returns a sorted list of auth type strings; `who_has_auth` returns a sorted list of subject labels; `wellformed_check` returns a boolean; `dd_reachable` returns a boolean.

**`authority.dot`** — Graphviz DOT directed graph of the authority relations. Each security label is a node; each authority relation is a directed edge labeled with its authority types. Render to `authority.svg` using the `dot` tool.

**`invariants.smt2`** — Z3 SMT-LIB2 encoding of the computed authority graph that verifies three security properties by checking unsatisfiability of their negations:
1. The designated subject's Control authority is reflexive-only (it Controls no other label)
2. DeleteDerived authority is transitively closed
3. Call authority implies SyncSend authority for every source-target pair

**`z3_output.txt`** — Captured output from running `z3` on `invariants.smt2`.