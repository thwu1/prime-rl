`/app/compact/` contains a custom binary serialization library with `encode(value) -> bytes` and `decode(data) -> value` supporting None, bool, int, float, str, bytes, list, tuple, and dict (string keys only). The codec uses zigzag encoding for signed integers, unsigned LEB128 varints for lengths and counts, and compact type tags with special-case handling for common float values.

The existing unit tests at `/app/tests/test_basic.py` pass, but the codec contains multiple latent correctness bugs that only manifest with specific input classes — edge cases in numeric encoding, unicode handling, and container serialization that the unit tests fail to exercise.

Your deliverables:

**Property-based test suite** at `/app/tests/test_pbt.py`: Design a Hypothesis-based test suite that systematically discovers all correctness defects in the codec. The suite must employ custom composite strategies for the codec's recursive type system (using `st.recursive`, `@st.composite`, or `st.deferred`) and exercise at least three distinct property categories (e.g., roundtrip identity, type/sign preservation, encoding determinism).

**Bug fixes** in `/app/compact/codec.py`: Fix every bug your property-based tests discover. The existing unit tests at `/app/tests/test_basic.py` must continue to pass after all fixes.

**Bug taxonomy** at `/app/bug_report.json`: A JSON array documenting each discovered bug. Each entry requires fields: `function` (the buggy function name), `root_cause` (precise technical description of the defect mechanism), `trigger_input` (Python repr of a minimal input that exposes the bug), and `property_type` (which category of test property catches it).