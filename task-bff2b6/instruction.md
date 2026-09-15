`/app/` contains a LibCST-based code transformation project. The objective is to automatically convert Tornado's legacy `@gen.coroutine`/`yield` coroutine syntax to Python's native `async`/`await`.

The project skeleton is partially implemented — test infrastructure, a test case collector, and a helpers module with utility functions are already provided. The core transformer module is missing.

**Your task:** implement `/app/tornado_async_transformer/transformer.py`.

This module must export `TornadoAsyncTransformer` and `TransformError`, as required by the package's `__init__.py` at `/app/tornado_async_transformer/__init__.py`.

The complete behavioral specification is defined by the test suite:

- `/app/tests/test_cases/` — 18 subdirectories, each containing a `before.py` (input code) and `after.py` (expected transformed output). These cover the full range of required transformations.
- `/app/tests/exception_cases/` — 5 Python files. Each file's module-level docstring specifies the exact error message that must be raised when the transformer encounters that unsupported pattern.
- `/app/tests/test_transform.py` — the test runner, which performs character-for-character comparison. Whitespace and formatting must be preserved exactly.
- `/app/tests/collector.py` — parameterized test case collection infrastructure.

Examine the helpers module at `/app/tornado_async_transformer/helpers.py` — it provides utilities you will likely need.

All tests must pass: `cd /app && python3 -m pytest tests/ -v`