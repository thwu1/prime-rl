"""
Virtual Screen Reader - WAI-ARIA compliant accessibility tree builder and navigator.

Implement this class to pass all tests. The module must:
- Parse HTML and build an accessibility tree per WAI-ARIA 1.2 and HTML-AAM 1.0
- Compute accessible names (aria-label, aria-labelledby, text content)
- Support linear navigation (next/previous) producing correct spoken phrases
- Handle: aria-hidden, hidden attr, inert (with modal dialog escape), aria-owns
  reparenting, presentational roles (role="presentation"/role="none"),
  aria-roledescription, heading levels, childrenPresentational roles
- Support navigation commands for headings and landmarks
"""


class VirtualScreenReader:
    """A virtual screen reader that traverses an accessibility tree built from HTML."""

    def start(self, html: str) -> None:
        """
        Initialize the screen reader with HTML content (body innerHTML).
        Parses the HTML, builds the accessibility tree, flattens it for
        linear navigation, and positions the cursor at the first node
        (the document root). The initial node's spoken phrase is logged.
        """
        raise NotImplementedError

    def next(self) -> str:
        """
        Move the cursor to the next node in the flattened tree.
        Wraps around to the beginning when reaching the end.
        Returns the spoken phrase of the new current node.
        """
        raise NotImplementedError

    def previous(self) -> str:
        """
        Move the cursor to the previous node in the flattened tree.
        Wraps around to the end when reaching the beginning.
        Returns the spoken phrase of the new current node.
        """
        raise NotImplementedError

    def last_spoken_phrase(self) -> str:
        """Return the most recent spoken phrase, or empty string if none."""
        raise NotImplementedError

    def spoken_phrase_log(self) -> list:
        """Return a copy of the complete log of all spoken phrases."""
        raise NotImplementedError

    def clear_spoken_phrase_log(self) -> None:
        """Clear the spoken phrase log."""
        raise NotImplementedError

    def perform(self, command: str):
        """
        Execute a navigation command. Supported commands:
        - moveToNextHeading / moveToPreviousHeading
        - moveToNextHeadingLevelN / moveToPreviousHeadingLevelN (N=1..6)
        - moveToNextLandmark / moveToPreviousLandmark

        Returns the spoken phrase if a matching element was found,
        or None if no match exists.
        """
        raise NotImplementedError
