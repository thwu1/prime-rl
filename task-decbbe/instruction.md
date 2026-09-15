A legacy marketplace engine at `/app/legacy_system.py` handles inventory aging, cart pricing with discounts, state persistence, and receipt formatting in a single monolithic class. Its behavioral specification is at `/app/specification.md`.

The implementation has multiple conformance defects whose effects cascade across subsystems — fixing a discount accumulation issue, for instance, may cause the total to breach a cap that itself is incorrectly enforced, so both defects must be resolved in concert. The monolithic structure makes these interactions difficult to trace.

Your objectives:

1. Make the system fully conform to `/app/specification.md` — every item category, discount type (including the discount cap rule), state persistence contract, and extensibility requirement described there must work correctly.
2. Decompose the monolith into at least three Python modules in `/app/` (not counting `models.py`, `__init__.py`, or `run_scenario.py`). `/app/legacy_system.py` must remain as a facade preserving all public method signatures and importing from the internal modules.
3. No function or method in any `/app/*.py` module may exceed cyclomatic complexity 5, as measured by `radon cc -s`.
4. No circular import dependencies between modules.
5. `/app/models.py` must not be modified.

Use `python3 /app/run_scenario.py` to observe current behavior and compare it against the specification.