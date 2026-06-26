# Minimal local copy of the types backend.py needs from amaia-collab's
# apps/rl/utils/des_helper (snapshot 2026-06-15).
from .session import SessionOutput


class BackendInitError(Exception):
    """Raised when a sandbox/container cannot be created or started."""


class BashResult(SessionOutput):
    # SessionOutput already has: status, output, error_type.
    exit_code: int
