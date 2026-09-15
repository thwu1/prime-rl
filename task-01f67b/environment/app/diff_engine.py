"""
Terminal Screen Diff Engine — implement compute_diff().

"""

from terminal import Screen


def compute_diff(prev: Screen, curr: Screen) -> bytes:
    """Compute ANSI escape sequence bytes that transform *prev* into *curr*.

    When the returned bytes are processed by a VTParser initialised with a
    clone of *prev*, the resulting screen must be identical to *curr*.

    See terminal.py for the data model and the escape sequences handled by
    VTParser.
    """
    raise NotImplementedError("Implement the screen diff algorithm")
