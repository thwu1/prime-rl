
"""Code migration transformer: restlib -> httpclient.

Implement the transform() function to convert Python source code that uses
the ``restlib`` HTTP library to use ``httpclient`` instead.

The transformer must handle all cases described in /app/MIGRATION_SPEC.md.
The transformation must preserve formatting, comments, and string literals
exactly -- only Python identifiers that are part of ``restlib`` API usage
should be changed.
"""

# Exception name mapping: restlib exception -> httpclient exception
EXCEPTION_MAP = {
    "RequestError": "TransportError",
    "ConnectionError": "ConnectError",
    "Timeout": "TimeoutError",
    "HTTPError": "HTTPStatusError",
}

# HTTP methods that map to httpclient.fetch()
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


def transform(source: str) -> str:
    """Transform Python source code from restlib to httpclient.

    Args:
        source: Python source code string using the restlib library.

    Returns:
        Transformed source code using httpclient instead of restlib.
        Must preserve formatting, comments, and non-restlib code exactly.
    """
    # TODO: Implement the full transformation.
    return source
