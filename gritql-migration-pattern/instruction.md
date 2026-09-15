A Python module at `/app/transformer.py` contains a stub `transform(source: str) -> str` function. Implement this function to convert Python source code that uses the `restlib` HTTP library into equivalent code using `httpclient`.

The complete migration specification is at `/app/MIGRATION_SPEC.md`. The transformation covers:

- Module and from-import rewriting with submodule fan-out (`restlib.exceptions` maps to `httpclient.errors`, not `httpclient`)
- HTTP method call restructuring: `restlib.get(url, ...)` becomes `httpclient.fetch("GET", url, ...)` — a new string literal must be inserted as the first positional argument while preserving all existing arguments
- Keyword argument renaming (`data` → `content`) within HTTP method calls
- Constructor kwarg arithmetic: `timeout_ms=5000` → `timeout=5.0` — the integer literal must be divided by 1000 and emitted as a float literal
- Exception hierarchy remapping for both qualified access (`restlib.exceptions.Timeout` → `httpclient.TimeoutError`) and bare-name patterns from `from` imports
- Decorator argument transformation with computation: `@restlib.retry(max_retries=3, delay=2)` → `@httpclient.with_retry(attempts=4, backoff=2.0)` — retries-to-attempts requires incrementing, delay-to-backoff requires int-to-float conversion
- Coordinated bare-name updates when symbols are imported via `from` imports
- Format-preserving output: comments, string literals, and non-restlib code must remain exactly unchanged

These transformation rules interact — applying each rule in isolation will produce incorrect results in cases where multiple rules affect the same syntactic construct simultaneously.