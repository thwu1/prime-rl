`/app/reference/` contains a reference implementation of a type similarity scoring algorithm originally developed for an academic benchmark evaluating Python type inference. The reference code at `/app/reference/type_similarity.py` computes structural similarity between Python types, but it operates on mypy's internal type representation (`mypy.types`, `mypy.nodes`) and cannot run as a standalone tool. A set of sample input/output pairs is provided at `/app/reference/calibration.json`.

Build a standalone Python package at `/app/typesim/` that reproduces the reference implementation's scoring behavior by parsing type annotation strings directly, without depending on mypy. Scores must match the reference within a tolerance of 1e-4, including for type pairs not present in the calibration data.

## Package Structure

`/app/typesim/` must contain these modules:

- `__init__.py` — exports `parse_type` and `get_type_similarity`
- `parser.py` — type annotation string parser exposing `parse_type`
- `similarity.py` — similarity scoring engine exposing `get_type_similarity`
- `cli.py` — command-line interface

## Interface Contracts

### `parser.parse_type(s: str)`

Parses a type annotation string and returns a type node object. Supported type forms: primitives (`int`, `str`, `float`, `bool`, `None`, `Any`), generic containers (`List[X]`, `Dict[K,V]`, `Tuple[X,...]`, `Set[X]`, `FrozenSet[X]`, `Deque[X]`), `Optional[X]`, `Union[X, Y, ...]`, `Callable[[A, B], R]`, and arbitrarily nested combinations.

The returned type node must expose:

- `.name` — base type name, lowercase for generic containers (`List` → `list`, `Dict` → `dict`, `Tuple` → `tuple`, `Set` → `set`, `FrozenSet` → `frozenset`). Primitives keep their name (`int`, `str`, etc.). `Callable` keeps its capitalized name. `Any` and `None` keep their names.
- `.args` — list of child type nodes. For `Callable[[A, B], R]`, flatten all parameter types and the return type into a single args list (e.g., `Callable[[int, str], bool]` yields 3 args). For `Tuple[int, ...]`, include the ellipsis as a node with `.name == "..."`.
- `.is_union` — `True` for `Union[...]` types. `Optional[X]` must be represented as a union of `X` and `None` (two args, `.is_union` is `True`).

### `similarity.get_type_similarity(a, b)`

Takes two parsed type nodes and returns a `float` in `[0.0, 1.0]`. Must be symmetric: `get_type_similarity(a, b) == get_type_similarity(b, a)`. Scores must match the reference implementation's behavior for all calibration pairs and generalize correctly to unseen type combinations.

### CLI (`/app/typesim/cli.py`)

**Single-pair mode:**
```
python3 /app/typesim/cli.py "Dict[str, List[int]]" "Dict[str, List[float]]"
```
Outputs a single float rounded to 4 decimal places on stdout.

**Batch mode:**
```
python3 /app/typesim/cli.py --batch /path/to/input.json --output /path/to/output.json
```
Input format: `[{"a": "type_str", "b": "type_str"}, ...]`
Output format: `[{"a": "...", "b": "...", "score": <float>}, ...]`