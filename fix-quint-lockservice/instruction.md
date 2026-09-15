A Quint formal specification of a distributed lock manager with epoch-based leader election is at `/app/lock_manager.qnt`. The module models a three-node cluster with leader election via majority voting, exclusive lock management with fencing tokens, and network partition handling.

The specification typechecks but is not correct — safety invariants fail under simulation. The bugs are distributed across action definitions and invariant formulations.

Debug and fix `/app/lock_manager.qnt` so that:

- `quint typecheck /app/lock_manager.qnt` passes
- All five safety invariants (`singleLeader`, `epochMonotonicity`, `fencingTokenOrder`, `splitBrainPrevention`, `voteConsistency`) pass `quint run` simulation with `--max-steps=20 --max-samples=200`
- No invariant is trivially `true` or `false`
- Every action correctly implements its intended state transition

Write `/app/diagnosis.json` containing a JSON array of objects. Each object must have keys `definition` (the name of the buggy action or invariant), `bug` (what was wrong, >= 60 characters), and `fix` (what you changed and why it is correct, >= 60 characters).