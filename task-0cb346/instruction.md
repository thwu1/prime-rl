Six OS kernel syscall specifications at `/app/specs.py` model symbolic state transitions using the Z3 SMT solver, built on the kernel state model in `/app/kernel_model.py`. The security policy at `/app/security_policy.md` defines four invariants (S1-S4) that correct specifications must enforce.

Some specifications contain subtle vulnerabilities that violate one or more invariants. Not every invariant applies to every specification — applicability depends on which resources and operations each syscall involves.

Audit all six specifications against all applicable invariants. Formalize each applicable invariant as a Z3 satisfiability query over the specification's precondition. For violations, extract concrete counterexamples from the Z3 model. Then produce corrected specifications that satisfy all invariants while preserving the intended state-transition semantics.

Write:

- `/app/audit.json` — For each of the six specifications, report `"SOUND"` or `"VULNERABLE"` status. For vulnerable specifications, include a `violations` array with each violated invariant ID and a `counterexample` dict mapping argument names to decimal integer strings.

```json
{
  "spec_name": {
    "status": "SOUND or VULNERABLE",
    "violations": [
      {
        "invariant": "S1",
        "counterexample": {"arg_name": "decimal_int_string"}
      }
    ]
  }
}
```

- `/app/specs_fixed.py` — Corrected specifications module with all six spec functions. Fixes must be minimal (modify only the incorrect precondition clause in each buggy specification). Non-buggy specifications must remain unchanged.

## Files

- `/app/kernel_model.py` — Kernel state model: Z3 arrays, bitvectors, predicate helpers
- `/app/specs.py` — Six syscall specifications (state transition functions)
- `/app/security_policy.md` — Four security invariants (S1-S4)