"""Small dependency-free helpers shared by the Sandoq provider modules."""

from __future__ import annotations


def duration_seconds(value: str | None, default: float) -> float:
    """Parse a duration, treating a bare number as seconds."""
    text = (value or "").strip().lower()
    if not text:
        return default
    for suffix, multiplier in (("ms", 0.001), ("s", 1.0), ("m", 60.0), ("h", 3600.0)):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * multiplier
    return float(text)


def exception_chain(error: BaseException) -> list[BaseException]:
    """Return an exception and its explicit/implicit causes without cycles."""
    chain: list[BaseException] = []
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        item = pending.pop(0)
        if id(item) in seen:
            continue
        seen.add(id(item))
        chain.append(item)
        if item.__cause__ is not None:
            pending.append(item.__cause__)
        if item.__context__ is not None:
            pending.append(item.__context__)
    return chain


def exception_http_status(error: BaseException) -> int | None:
    """Find an HTTP status exposed anywhere in an exception chain."""
    for item in exception_chain(error):
        for value in (
            getattr(item, "status", None),
            getattr(item, "status_code", None),
            getattr(getattr(item, "response", None), "status_code", None),
        ):
            if isinstance(value, int):
                return value
    return None
