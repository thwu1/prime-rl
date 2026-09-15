An Answer Set Programming project for a combinatorial graph optimization problem is set up at `/app/`. The project contains problem documentation, test instances with an expected-results manifest, a validation checker, and a legacy ASP encoding for a related but different problem.

Explore the project structure to understand:
- The specific optimization problem being solved
- The input predicate format used by the instances
- The output predicates and solution structure expected by the checker
- How the legacy encoding differs from what is needed
- The optimality targets for each instance

Write a correct ASP-Core-2 encoding at `/app/encoding.lp` that works with the `clingo` solver and proves optimality on all provided test instances. The `clingo` Python package is not pre-installed; install it via pip when needed.