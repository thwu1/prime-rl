The `/app/` directory contains an incomplete implementation of TypeSim, a library for computing structural similarity between Python type annotations. The project has:

- A property specification at `/app/spec.md` defining the metric's required behavior
- A type parser at `/app/typesim/parser.py` that handles most type constructs but raises `NotImplementedError` for `Callable` types
- An empty similarity module at `/app/typesim/similarity.py`
- 40 validation cases with expected scores in `/app/test_cases.json`
- A diagnostic runner at `/app/compute_similarity.py`

Complete the implementation so that all 40 test cases produce correct similarity scores within +/-0.001 tolerance, and `str(parse_type(s))` round-trips correctly for all supported type constructs including `Callable`.