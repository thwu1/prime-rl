Complete the implementation of `/app/engine.py` — a system that determines whether sets of linear constraints over the rationals are satisfiable and, for unsatisfiable systems, produces verifiable certificates of infeasibility, cross-validated against the GNU GLPK solver.

## Provided Files

- `/app/models.py` — Data structures (do not modify). Study this file to understand how variables, constants, comparison types, and certificates are represented.
- `/app/engine.py` — Function stubs to implement. Read the signatures and docstrings for the required interface.
- `/usr/bin/glpsol` — GNU GLPK command-line solver binary.

## Goal

Implement every function stub in `/app/engine.py` so that all tests in `/tests/test_state.py` pass. The test suite validates constraint parsing, certificate verification (acceptance of valid proofs and rejection of invalid ones), two independent unsatisfiability oracle backends producing valid certificates across diverse problem classes, oracle dispatch, LP format export compatible with `glpsol`, and cross-validation of feasibility results against `glpsol`.