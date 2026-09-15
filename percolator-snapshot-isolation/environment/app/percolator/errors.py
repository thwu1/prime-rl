class PercolatorError(Exception):
    """Base exception for Percolator errors."""
    pass


class RequestDroppedError(PercolatorError):
    """Raised when a commit request is dropped before reaching the server.
    The commit definitely did NOT execute."""
    pass


class ResponseDroppedError(PercolatorError):
    """Raised when a commit response is dropped after the server processed it.
    The commit MAY have executed successfully."""
    pass
