"""
Virtual Screen Reader — W3C Compliant

Implement this module so that the VirtualScreenReader class correctly
simulates screen reader navigation over HTML content following:
  - WAI-ARIA 1.2 (roles, states, properties)
  - HTML-AAM 1.0 (implicit role mappings for HTML elements)
  - ACCNAME 1.2 (accessible name and description computation)

See /data/fixtures/ for example HTML documents.
"""



class VirtualScreenReader:
    """
    Simulates screen reader navigation over parsed HTML content.

    Spoken phrase format (comma-separated, empty parts omitted):
      role, name, value, description, level N

    Container elements with accessible children produce enter and exit
    phrases: "role[, name]" and "end of role[, name]".
    """

    def start(self, html: str) -> str:
        """
        Parse HTML, build accessibility tree, position cursor at first
        node. Returns spoken phrase of first node. Adds to log.
        """
        raise NotImplementedError

    def next(self) -> str:
        """
        Move cursor to next node (wraps at end).
        Returns spoken phrase. Adds to log.
        """
        raise NotImplementedError

    def previous(self) -> str:
        """
        Move cursor to previous node (wraps at start).
        Returns spoken phrase. Adds to log.
        """
        raise NotImplementedError

    def move_to_next(self, role: str) -> str:
        """
        Jump forward to next non-exit node matching the given ARIA role.
        Wraps around. Returns spoken phrase or '' if not found.
        Does not change position or log if not found.
        """
        raise NotImplementedError

    def move_to_previous(self, role: str) -> str:
        """
        Jump backward to previous non-exit node matching the given role.
        Wraps around. Returns spoken phrase or '' if not found.
        Does not change position or log if not found.
        """
        raise NotImplementedError

    def move_to_next_landmark(self) -> str:
        """
        Jump forward to next landmark role.
        Wraps. Returns spoken phrase or ''.
        Does not change position or log if not found.
        """
        raise NotImplementedError

    def move_to_flowto(self) -> str:
        """
        Follow the current element's aria-flowto attribute to jump to
        the referenced node in the accessibility tree. Takes the first
        target if multiple IDs are specified. Returns spoken phrase or
        '' if no aria-flowto or target not found.
        Does not change position or log if not found.
        """
        raise NotImplementedError

    def current(self) -> str:
        """
        Returns spoken phrase of current node without moving or logging.
        """
        raise NotImplementedError

    def spoken_phrase_log(self) -> list:
        """
        Returns list of all spoken phrases produced by navigation calls.
        """
        raise NotImplementedError
