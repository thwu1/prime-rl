The `/app/` directory contains a C project that exercises a hierarchical state machine (HSM) engine. All source files compile and are complete except `/app/hsm.c`, which contains only function stubs for `hsm_ctor`, `hsm_init`, and `hsm_dispatch`.

Implement these three functions so that the engine correctly executes full UML Statechart semantics for arbitrary hierarchical state machines. The API types, return codes, reserved signals, and macros are defined in `/app/hsm.h`. A comprehensive test state machine with 6 nested states, guard conditions, and diverse transition scenarios is implemented in `/app/qhsmtst.c`. The test driver (`/app/main.c`) constructs the state machine, dispatches 18 carefully chosen signals, and prints the resulting execution traces.

State hierarchy under test:

```
hsm_top
  └── s
        ├── s1
        │     └── s11
        └── s2
              └── s21
                    └── s211
```

Build with `make` in `/app/` and verify correctness by running `./qhsmtst`. A correct implementation produces 19 lines of deterministic trace output covering initialization, cross-branch transitions, self-transitions, guard-conditioned dispatch, internal transitions, and nested initial transitions.