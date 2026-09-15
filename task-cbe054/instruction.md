An OSPF conformance testing project at `/app/` contains a neighbor FSM model (`fsm_model.json`) that has diverged from the RFC 2328 Section 10.3 specification (`rfc_ospf_neighbor_fsm.txt`), a sparse existing test suite (`existing_tests.json`), FRRouting configs defining a three-router multi-area topology (`frr_configs/`), and JSON schemas for all outputs (`schemas/`).

The FSM model has specification errors, test coverage is inadequate, and the project lacks topology documentation and a visual state diagram.

All outputs go in `/app/output/`, implemented via `/app/run_pipeline.py`:

- `fsm.json` — corrected FSM with every transition as a discrete from/event/to entry, no wildcards (validates against `schemas/fsm_schema.json`)
- `topology.json` — OSPF topology extracted from the FRRouting configs: router IDs, interfaces, network types, areas, links (validates against `schemas/topology_schema.json`)
- `fsm_diagram.svg` — Graphviz-rendered state diagram of the corrected FSM
- `coverage_before.json` — existing test coverage against the corrected FSM (validates against `schemas/coverage_schema.json`)
- `test_suite.json` — new topology-aware test cases achieving at least 80% total transition coverage (validates against `schemas/test_case_schema.json`)
- `coverage_after.json` — combined coverage of existing and new tests (validates against `schemas/coverage_schema.json`)

```
```