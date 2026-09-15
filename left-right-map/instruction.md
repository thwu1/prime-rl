A left-right concurrent multi-value map is implemented at `/app/left_right_map.py`. The implementation has correctness defects — its test suite at `/app/tests/test_left_right.py` is currently failing.

The specification at `/app/spec.md` describes the API for a sharded concurrent map (`/app/sharded_map.py`) that wraps multiple base map instances, along with the required benchmark output artifacts and analysis report format. Workload definitions are at `/app/workloads.json`.

**Goal**: Fix the base map implementation so its test suite passes, implement the sharded concurrent map conforming to the spec, and produce all benchmark and analysis artifacts at `/app/output/`.