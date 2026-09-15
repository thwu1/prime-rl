A Python project at `/app/codebase/` (top-level package: `codebase`) contains 25 functions distributed across multiple subpackages that call each other through various import mechanisms.

Two test suites exercise different features of the project:
- Feature tests: all `test_*.py` files under `/app/test_suites/feature/`
- Base tests: all `test_*.py` files under `/app/test_suites/base/`

Create a Python module at `/app/isolator/` (with `__init__.py`) providing a `classify` function importable as:

```python
from isolator.analyzer import classify
```

`classify(project_dir, package_name, feature_test_dir, base_test_dir)` returns `dict[str, str]` mapping every function's dot-qualified name (relative to the package root, e.g., `core.validation.check_type`) to exactly one of four labels:

- `"feature_only"` — transitively reachable from feature test imports but not from base test imports
- `"base_only"` — transitively reachable from base test imports but not from feature test imports
- `"shared"` — transitively reachable from both test suites
- `"unused"` — not transitively reachable from either test suite

A function is transitively reachable from a test suite when any test file in that suite imports a project function that directly or indirectly calls it within the project. Only calls to functions defined within the analyzed project count.

The classifier must correctly handle all import patterns present in the codebase and must produce correct results when the test suites or project contents are modified at runtime.