
"""Verification tests for the restlib-to-httpclient code migration transformer.

Each test calls ``transform(input_code)`` and compares the result against
the expected output (whitespace-normalized).
"""

import sys
import textwrap

sys.path.insert(0, "/app")

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Strip trailing whitespace per line and leading/trailing blank lines."""
    lines = text.strip().split("\n")
    lines = [line.rstrip() for line in lines]
    return "\n".join(lines)


def apply_transform(input_code: str) -> str:
    """Apply the transformer to *input_code* and return the result."""
    from transformer import transform
    return transform(input_code)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_basic_import_and_get():
    """Module import + GET call with method arg insertion."""
    inp = textwrap.dedent("""\
        import restlib

        response = restlib.get("https://api.example.com/data")
        print(response.status_code)
    """)
    expected = textwrap.dedent("""\
        import httpclient

        response = httpclient.fetch("GET", "https://api.example.com/data")
        print(response.status_code)
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_post_with_data_to_content():
    """POST call: insert method arg + rename data kwarg to content."""
    inp = textwrap.dedent("""\
        import restlib

        response = restlib.post("https://api.example.com/submit", data={"key": "value"}, headers={"Content-Type": "application/json"})
        print(response.status_code)
    """)
    expected = textwrap.dedent("""\
        import httpclient

        response = httpclient.fetch("POST", "https://api.example.com/submit", content={"key": "value"}, headers={"Content-Type": "application/json"})
        print(response.status_code)
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_session_timeout_ms_conversion():
    """Session constructor: rename + timeout_ms integer arithmetic."""
    inp = textwrap.dedent("""\
        import restlib

        session = restlib.Session(base_url="https://api.example.com", timeout_ms=5000)
        session.close()
    """)
    expected = textwrap.dedent("""\
        import httpclient

        session = httpclient.Client(base_url="https://api.example.com", timeout=5.0)
        session.close()
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_qualified_exception_handling():
    """restlib.exceptions.* -> httpclient.* exception hierarchy."""
    inp = textwrap.dedent("""\
        import restlib

        try:
            response = restlib.get("https://api.example.com/data")
        except restlib.exceptions.Timeout:
            print("Timed out")
        except restlib.exceptions.ConnectionError:
            print("Connection failed")
        except restlib.exceptions.HTTPError as e:
            print(f"HTTP error: {e}")
        except restlib.exceptions.RequestError as e:
            print(f"Request failed: {e}")
    """)
    expected = textwrap.dedent("""\
        import httpclient

        try:
            response = httpclient.fetch("GET", "https://api.example.com/data")
        except httpclient.TimeoutError:
            print("Timed out")
        except httpclient.ConnectError:
            print("Connection failed")
        except httpclient.HTTPStatusError as e:
            print(f"HTTP error: {e}")
        except httpclient.TransportError as e:
            print(f"Request failed: {e}")
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_from_import_session():
    """from restlib import Session -> from httpclient import Client + usage rename."""
    inp = textwrap.dedent("""\
        from restlib import Session

        s = Session()
        s.headers.update({"Authorization": "Bearer token"})
        r = s.get("https://api.example.com/data")
        s.close()
    """)
    expected = textwrap.dedent("""\
        from httpclient import Client

        s = Client()
        s.headers.update({"Authorization": "Bearer token"})
        r = s.get("https://api.example.com/data")
        s.close()
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_from_import_exceptions_submodule_fanout():
    """from restlib.exceptions -> from httpclient.errors (submodule fan-out) + bare names."""
    inp = textwrap.dedent("""\
        from restlib.exceptions import RequestError, Timeout

        try:
            result = get_data()
        except Timeout:
            print("Timed out")
        except RequestError as e:
            print(f"Error: {e}")
    """)
    expected = textwrap.dedent("""\
        from httpclient.errors import TransportError, TimeoutError

        try:
            result = get_data()
        except TimeoutError:
            print("Timed out")
        except TransportError as e:
            print(f"Error: {e}")
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_retry_decorator_transformation():
    """Decorator: max_retries+1 -> attempts, delay -> float backoff."""
    inp = textwrap.dedent("""\
        import restlib

        @restlib.retry(max_retries=3, delay=2)
        def fetch_data(url):
            return restlib.get(url)
    """)
    expected = textwrap.dedent("""\
        import httpclient

        @httpclient.with_retry(attempts=4, backoff=2.0)
        def fetch_data(url):
            return httpclient.fetch("GET", url)
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_multiple_http_methods():
    """All common HTTP methods with method arg insertion + data->content."""
    inp = textwrap.dedent("""\
        import restlib

        r1 = restlib.get("https://api.example.com/users")
        r2 = restlib.post("https://api.example.com/users", data={"name": "Alice"})
        r3 = restlib.put("https://api.example.com/users/1", data={"name": "Bob"})
        r4 = restlib.delete("https://api.example.com/users/1")
        r5 = restlib.patch("https://api.example.com/users/1", data={"active": False})
    """)
    expected = textwrap.dedent("""\
        import httpclient

        r1 = httpclient.fetch("GET", "https://api.example.com/users")
        r2 = httpclient.fetch("POST", "https://api.example.com/users", content={"name": "Alice"})
        r3 = httpclient.fetch("PUT", "https://api.example.com/users/1", content={"name": "Bob"})
        r4 = httpclient.fetch("DELETE", "https://api.example.com/users/1")
        r5 = httpclient.fetch("PATCH", "https://api.example.com/users/1", content={"active": False})
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_string_and_comment_preservation():
    """Identifiers inside strings and comments must NOT be transformed."""
    inp = textwrap.dedent("""\
        import restlib

        # restlib library is great for HTTP
        url = "https://restlib.example.com/api"
        data = restlib.get(url)  # using restlib.get here
        msg = 'restlib.Session is useful'
    """)
    expected = textwrap.dedent("""\
        import httpclient

        # restlib library is great for HTTP
        url = "https://restlib.example.com/api"
        data = httpclient.fetch("GET", url)  # using restlib.get here
        msg = 'restlib.Session is useful'
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_mixed_import_styles():
    """Both module import and from-import exceptions in the same file."""
    inp = textwrap.dedent("""\
        import restlib
        from restlib.exceptions import ConnectionError

        try:
            r = restlib.get("https://api.example.com")
        except ConnectionError:
            print("Connect failed")
        except restlib.exceptions.RequestError:
            print("Request failed")
    """)
    expected = textwrap.dedent("""\
        import httpclient
        from httpclient.errors import ConnectError

        try:
            r = httpclient.fetch("GET", "https://api.example.com")
        except ConnectError:
            print("Connect failed")
        except httpclient.TransportError:
            print("Request failed")
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )


def test_combined_complex():
    """All transformation types in a single file: decorator, session, methods, exceptions."""
    inp = textwrap.dedent("""\
        import restlib

        @restlib.retry(max_retries=2, delay=1)
        def sync_users():
            session = restlib.Session(timeout_ms=10000)
            try:
                users = restlib.get("https://api.example.com/users")
                for user in users.json():
                    restlib.post(f"https://backup.example.com/users", data=user)
            except restlib.exceptions.Timeout:
                print("Operation timed out")
            except restlib.exceptions.HTTPError as e:
                print(f"HTTP error: {e}")
            finally:
                session.close()
    """)
    expected = textwrap.dedent("""\
        import httpclient

        @httpclient.with_retry(attempts=3, backoff=1.0)
        def sync_users():
            session = httpclient.Client(timeout=10.0)
            try:
                users = httpclient.fetch("GET", "https://api.example.com/users")
                for user in users.json():
                    httpclient.fetch("POST", f"https://backup.example.com/users", content=user)
            except httpclient.TimeoutError:
                print("Operation timed out")
            except httpclient.HTTPStatusError as e:
                print(f"HTTP error: {e}")
            finally:
                session.close()
    """)
    result = apply_transform(inp)
    assert normalize(result) == normalize(expected), (
        f"Mismatch.\n--- expected ---\n{expected}\n--- got ---\n{result}"
    )
