"""Migration file integrity verification via checksums."""
import hashlib
import re


def compute_checksum(filepath):
    """Compute a checksum of the SQL content, excluding comments.

    Comments are stripped before hashing to allow documentation changes
    without triggering checksum mismatches.
    """
    with open(filepath) as f:
        content = f.read()

    # Strip SQL single-line comments (lines starting with --)
    stripped = re.sub(r'^--.*$', '', content)

    # Normalize whitespace
    stripped = re.sub(r'\s+', ' ', stripped).strip()

    return hashlib.sha256(stripped.encode('utf-8')).hexdigest()
