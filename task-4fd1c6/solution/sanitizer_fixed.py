"""
Hardened sanitizer for shell command template inputs.

Uses strict allowlist combined with control character filtering
to prevent all forms of shell command injection.
"""
import re

# Strict allowlist: letters, digits, dot, underscore, at-sign,
# colon, slash, hyphen. Anchored with ^ and $ to require the
# ENTIRE string to match (unlike re.match without $).
_SAFE_PATTERN = re.compile(r'^[a-zA-Z0-9._@:/-]+$')


def sanitize(value):
    """Sanitize a value for safe use in shell command templates.

    Args:
        value: The string to sanitize.

    Returns:
        The original value if it passes all checks.

    Raises:
        ValueError: If the value is empty, not a string, or contains
                    disallowed characters.
    """
    if not value:
        raise ValueError("Empty value not allowed")
    if not isinstance(value, str):
        raise ValueError("Value must be a string")

    # Block all control characters (0x00-0x1f and DEL 0x7f).
    # This catches newlines, carriage returns, tabs, null bytes,
    # and all other control characters that can act as shell
    # metacharacters or disrupt command parsing.
    for ch in value:
        code = ord(ch)
        if code < 0x20 or code == 0x7f:
            raise ValueError(
                f"Control character U+{code:04X} not allowed"
            )

    # Allowlist check with proper anchoring. re.match with a $
    # anchor (or equivalently re.fullmatch) ensures the ENTIRE
    # string consists of safe characters, not just a prefix.
    if not _SAFE_PATTERN.match(value):
        raise ValueError("Value contains disallowed characters")

    return value
