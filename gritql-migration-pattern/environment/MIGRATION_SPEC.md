# Migration Specification: restlib → httpclient

## Import Transformations

### Module Import
- `import restlib` → `import httpclient`

### From-Import: Classes
- `from restlib import Session` → `from httpclient import Client`
- All usage sites must be updated: `Session()` → `Client()`

### From-Import: Exceptions
- `from restlib.exceptions import <names>` → `from httpclient.errors import <mapped_names>`
  **Note:** the target submodule changes from `exceptions` to `errors`
- All bare-name usage sites must be updated to the mapped names

## API Transformations

### HTTP Method Calls (Qualified Access)
All HTTP method calls are restructured to use a unified `fetch()` function
with the HTTP method as a new first string argument:
- `restlib.get(url, ...)` → `httpclient.fetch("GET", url, ...)`
- `restlib.post(url, ...)` → `httpclient.fetch("POST", url, ...)`
- `restlib.put(url, ...)` → `httpclient.fetch("PUT", url, ...)`
- `restlib.delete(url, ...)` → `httpclient.fetch("DELETE", url, ...)`
- `restlib.patch(url, ...)` → `httpclient.fetch("PATCH", url, ...)`

The HTTP method string is inserted as a **new first positional argument**.
All existing arguments shift one position right. All other keyword arguments
are preserved unchanged.

Additionally: the `data` keyword argument must be renamed to `content` in
all HTTP method calls.

### Session / Client Constructor
- `restlib.Session(...)` → `httpclient.Client(...)`
- The `timeout_ms` keyword argument must be converted:
  `timeout_ms=N` → `timeout=<N/1000>` where N is an integer literal.
  The value is divided by 1000 and expressed as a float literal.
  Example: `timeout_ms=5000` → `timeout=5.0`
  Example: `timeout_ms=10000` → `timeout=10.0`
- All other keyword arguments are preserved unchanged.

### Exception Hierarchy (Qualified Access)
Qualified exception access via `restlib.exceptions.<name>` is remapped:

| restlib                             | httpclient                     |
|-------------------------------------|--------------------------------|
| `restlib.exceptions.RequestError`   | `httpclient.TransportError`    |
| `restlib.exceptions.ConnectionError`| `httpclient.ConnectError`      |
| `restlib.exceptions.Timeout`        | `httpclient.TimeoutError`      |
| `restlib.exceptions.HTTPError`      | `httpclient.HTTPStatusError`   |

### Exception Hierarchy (From-Import)
When exceptions are imported via `from restlib.exceptions import ...`,
the import source changes to `httpclient.errors` and each name is mapped:

| from restlib.exceptions import | from httpclient.errors import |
|-------------------------------|-------------------------------|
| `RequestError`                | `TransportError`              |
| `ConnectionError`             | `ConnectError`                |
| `Timeout`                     | `TimeoutError`                |
| `HTTPError`                   | `HTTPStatusError`             |

All bare-name usages of the imported exceptions must be updated to match.

### Retry Decorator
The retry decorator is renamed and its arguments are transformed:
- `@restlib.retry(max_retries=N, delay=D)` → `@httpclient.with_retry(attempts=<N+1>, backoff=<float(D)>)`
- `max_retries=N` → `attempts=<N+1>`: the integer value is incremented by 1
  (because `max_retries` counts retry attempts while `attempts` counts total attempts)
- `delay=D` → `backoff=<float(D)>`: the integer value is converted to a float literal
- Example: `@restlib.retry(max_retries=3, delay=2)` → `@httpclient.with_retry(attempts=4, backoff=2.0)`

## Constraints

- All existing formatting (whitespace, indentation, line breaks) must be preserved
- Comments must be preserved unchanged (even if they mention "restlib")
- String literals must be preserved unchanged (even if they contain "restlib")
- Code not related to the `restlib` library must remain unchanged
- Keyword arguments not explicitly mentioned in the transformation rules must be preserved unchanged
- The transformer must handle files with mixed import styles (e.g., both `import restlib` and `from restlib.exceptions import ...` in the same file)
