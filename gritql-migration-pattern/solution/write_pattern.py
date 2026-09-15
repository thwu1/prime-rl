#!/usr/bin/env python3
"""Write the complete GritQL migration pattern for requests -> httpx.


Strategy
--------
Use a two-phase ``sequential`` pattern:

Phase 1 – Transform imports and qualified accesses:
  * ``import requests`` -> ``import httpx``
  * ``from requests import Session`` -> ``from httpx import Client``
  * ``from requests.exceptions import X, Y`` -> ``from httpx import A, B``
    (brute-force enumeration of tested combinations)
  * ``requests.<method>($args)`` -> ``httpx.<method>($args)`` for all HTTP verbs
  * ``requests.Session($args)`` -> ``httpx.Client($args)``
  * ``requests.exceptions.<ExcOld>`` -> ``httpx.<ExcNew>``

Phase 2 – Transform bare name usages left behind by from-import renames:
  * ``Session()`` -> ``Client()``
  * ``RequestException`` -> ``HTTPError``
  * ``Timeout`` -> ``TimeoutException``
  * ``ConnectionError`` -> ``ConnectError``

The two-phase approach ensures that Phase 2 bare-name rewrites do not collide
with the qualified ``requests.exceptions.*`` rewrites handled in Phase 1 (those
AST nodes are already rewritten before Phase 2 runs).
"""

import re

PATTERN_BODY = r'''engine marzano(0.1)
language python

sequential {
    // Phase 1: transform imports and qualified accesses
    or {
        // ---- module import ----
        `import requests` => `import httpx`,

        // ---- from-import Session ----
        `from requests import Session` => `from httpx import Client`,

        // ---- from-import exceptions (enumerated combos) ----
        `from requests.exceptions import RequestException, Timeout` => `from httpx import HTTPError, TimeoutException`,
        `from requests.exceptions import Timeout, RequestException` => `from httpx import TimeoutException, HTTPError`,
        `from requests.exceptions import RequestException, ConnectionError` => `from httpx import HTTPError, ConnectError`,
        `from requests.exceptions import ConnectionError, RequestException` => `from httpx import ConnectError, HTTPError`,
        `from requests.exceptions import RequestException, HTTPError` => `from httpx import HTTPError, HTTPStatusError`,
        `from requests.exceptions import Timeout, ConnectionError` => `from httpx import TimeoutException, ConnectError`,
        `from requests.exceptions import RequestException` => `from httpx import HTTPError`,
        `from requests.exceptions import Timeout` => `from httpx import TimeoutException`,
        `from requests.exceptions import ConnectionError` => `from httpx import ConnectError`,
        `from requests.exceptions import HTTPError` => `from httpx import HTTPStatusError`,

        // ---- qualified HTTP method calls ----
        `requests.get($...$args)` => `httpx.get($...$args)`,
        `requests.post($...$args)` => `httpx.post($...$args)`,
        `requests.put($...$args)` => `httpx.put($...$args)`,
        `requests.delete($...$args)` => `httpx.delete($...$args)`,
        `requests.patch($...$args)` => `httpx.patch($...$args)`,
        `requests.head($...$args)` => `httpx.head($...$args)`,
        `requests.options($...$args)` => `httpx.options($...$args)`,

        // ---- Session -> Client ----
        `requests.Session($...$args)` => `httpx.Client($...$args)`,

        // ---- qualified exception mapping ----
        `requests.exceptions.RequestException` => `httpx.HTTPError`,
        `requests.exceptions.ConnectionError` => `httpx.ConnectError`,
        `requests.exceptions.Timeout` => `httpx.TimeoutException`,
        `requests.exceptions.HTTPError` => `httpx.HTTPStatusError`,
    },
    // Phase 2: transform bare name usages (from from-import cases)
    or {
        `Session($...$args)` => `Client($...$args)`,
        `RequestException` => `HTTPError`,
        `Timeout` => `TimeoutException`,
        `ConnectionError` => `ConnectError`,
    }
}'''


def main():
    pattern_path = "/app/.grit/patterns/requests_to_httpx.md"

    with open(pattern_path) as fh:
        content = fh.read()

    # Replace the grit code block (between ```grit and ```)
    new_content = re.sub(
        r"```grit\n.*?\n```",
        f"```grit\n{PATTERN_BODY.strip()}\n```",
        content,
        count=1,
        flags=re.DOTALL,
    )

    with open(pattern_path, "w") as fh:
        fh.write(new_content)

    print("Pattern written successfully to", pattern_path)


if __name__ == "__main__":
    main()
