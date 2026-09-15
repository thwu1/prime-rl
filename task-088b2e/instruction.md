A TTCN-3 conformance testing pipeline at `/app/` validates telecom protocol implementations (SIP registration per TS 102 027-3, Diameter Rx per TS 101 580) against ETSI test specifications. The pipeline is not operational.

Two components need repair:

1. `/app/matcher.py` — the template matching engine has semantic bugs causing oracle test failures
2. `/app/engine.py` — the test execution engine does not exist

Run `make all` from `/app/` to see the current pipeline status. The Makefile runs four stages: structure validation, oracle testing, conformance execution, and report verification. Each stage uses a different CLI tool from the pipeline.

Fix all issues so that `make all` completes with zero failures, producing valid conformance reports at `/app/report_profile_a.json` and `/app/report_profile_b.json`.

Consult `/app/spec.md`, `/app/reference.md`, and `/app/ttcn3_reference.md` for the TTCN-3 semantics governing both components. Oracle test suites at `/app/oracle/` exercise the matching engine and verdict resolution system. The conformance test suites at `/app/suites/` define protocol-level test scenarios in JSON-IR format.

Do not modify `/app/Makefile`, `/app/conformance_runner.py`, `/app/run_conformance.py`, `/app/ttcn3_validate.py`, or any files under `/app/oracle/`, `/app/suites/`, or `/app/pics/`.