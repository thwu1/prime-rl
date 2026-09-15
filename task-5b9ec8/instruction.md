A multi-package SysML v2 textual model of a remote sensing satellite resides at `/app/model/` (6 `.sysml` files). The model uses SysML v2 textual notation across multiple packages with cross-package imports.

Perform a comprehensive conformance and traceability analysis of this model and produce four artifacts under `/app/results/`.

## `/app/results/conformance.json`

A JSON object with these keys:

- `type_hierarchy` — map each `part def` to its ordered specialization ancestor chain (immediate parent first, root last). Types with no parent map to `[]`.
- `instruments` — sorted list of `part def` names that transitively specialize `Instrument`.
- `verification_verdicts` — sorted-by-case-name list of `{"case": <name>, "requirement_id": <short-name>, "verdict": "pass"|"fail"}`. Each verification case usage must be evaluated against its bound subject per the semantics of the verified requirement's type and constraint expressions.
- `orphan_requirements` — sorted list of requirement short-name IDs (`<'REQ-...'>`  values) with no `satisfy` relationship in the model.
- `unverified_requirements` — sorted list of requirement short-name IDs not referenced by any verification case.
- `mass_analysis` — `{"subsystem_masses": {<name>: <float>}, "total_mass": <float>, "violations": [{"subsystem": <name>, "computed_mass": <float>, "budget": <float>, "overrun": <float>}]}`. Violations sorted by subsystem name.
- `power_analysis` — `{"total_generation": <float>, "total_consumption": <float>, "margin": <float>, "margin_percent": <float>, "subsystem_power": {<name>: <float>}, "power_violations": [...]}`. `margin_percent` rounded to 2 decimals. Violations sorted by subsystem name.
- `requirement_coverage` — `{"total": <int>, "satisfied": <int>, "coverage_percent": <float>}` (percent rounded to 2 decimals).
- `verification_coverage` — `{"total": <int>, "verified": <int>, "coverage_percent": <float>}` (percent rounded to 2 decimals).
- `unallocated_actions` — sorted list of action definition type names for leaf actions in the mission decomposition with no `allocate` relationship.
- `action_allocation` — `{"total": <int>, "allocated": <int>}`.

Only requirement usages bearing a short-name ID via `<'...'>` syntax count toward totals.

## `/app/results/traceability.dot` and `/app/results/traceability.svg`

Directed graph of the model's traceability relationships rendered as SVG. Requirements use `note` shape (labeled by short-name ID), parts/subsystems use `box3d`, verification cases use `diamond`. Edge colors: `satisfy` = blue, `verify` = green, `allocate` = orange.

## `/app/results/nonconformance.json`

Filtered summary of conformance issues: `failed_verifications`, `mass_violations`, `power_violations`, `orphan_requirements`, and `unallocated_actions`.