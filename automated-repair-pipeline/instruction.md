Three Python programs in `/app/programs/` each contain a bug that causes incorrect outputs for certain inputs:

- `/app/programs/middle.py` — should return the median of three integers
- `/app/programs/gcd.py` — should compute the GCD of two non-negative integers
- `/app/programs/power.py` — should compute `base ** exp` for non-negative integer `exp`

Create a Python package at `/app/pipeline/` that exposes a callable `repair_program`, importable as:

```python
from pipeline import repair_program
```

**Signature:**

```python
def repair_program(source_code: str, test_cases: List[Tuple[tuple, Any]], function_name: str) -> str
```

Given the source code of a buggy single-function Python program, a list of `(input_args_tuple, expected_output)` test-case pairs, and the target function name, return corrected source code in which the named function produces the expected output for every provided test case.

**Requirements:**

- Successfully repairs all three provided programs
- Generalizes to correctly repair unseen buggy programs — not just the three provided
- Uses only the Python standard library (no third-party packages)