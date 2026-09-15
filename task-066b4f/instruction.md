A project skeleton at `/app/` defines a [LibCST](https://github.com/Instagram/LibCST)-based code transformation tool that converts Tornado's legacy `@gen.coroutine`/`yield` async pattern to Python 3.5+ native `async`/`await`. The test infrastructure and all test cases are provided, but the transformer implementation is empty.

Implement `TornadoAsyncTransformer` in `/app/tornado_async_transformer/transformer.py` and any needed helpers in `/app/tornado_async_transformer/helpers.py` so that all tests pass.

The project contains:

- `/app/tornado_async_transformer/` — the package to implement (skeleton `__init__.py` already exports `TornadoAsyncTransformer` and `TransformError`)
- `/app/tests/test_cases/` — 15 directories each with `before.py`/`after.py` transformation pairs defining expected behavior
- `/app/tests/exception_cases/` — 4 Python files where transformation should raise `TransformError` (each file's module docstring is the expected error substring)
- `/app/tests/collector.py` — discovers and loads test cases from the filesystem
- `/app/tests/test_transformer.py` — parameterized pytest runner

The transformer must correctly handle: multiple Tornado import styles (`import tornado`, `from tornado import gen`, `from tornado.gen import coroutine`), nested coroutines vs. nested plain generators, `@gen_test` test decorators (which should be preserved unlike `@gen.coroutine`), `yield [list]` → `asyncio.gather` conversion with automatic `import asyncio`, `gen.sleep` → `asyncio.sleep`, various `gen.Return` forms, and must reject unsupported patterns (`gen.Task`, dict yields) with `TransformError`.

Validate with `cd /app && python -m pytest tests/ -v`.