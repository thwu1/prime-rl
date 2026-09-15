
"""UAX#29 Extended Grapheme Cluster segmentation with streaming GraphemeCursor.

This module provides the rule-encoding function check_pair() and exception classes.
You must implement grapheme_clusters() and the GraphemeCursor class.
"""

from segmenter.tables import grapheme_category, is_incb_linker, is_incb_extend

# ---------------------------------------------------------------------------
# Exception hierarchy for chunk-based processing
# ---------------------------------------------------------------------------

class GraphemeIncomplete(Exception):
    """Raised when chunk data is insufficient to decide a boundary."""
    pass

class PreContext(GraphemeIncomplete):
    """More backward context needed, ending at the given offset."""
    def __init__(self, offset):
        self.offset = offset
        super().__init__(f"Need pre-context ending at offset {offset}")

class NextChunk(GraphemeIncomplete):
    """The next chunk of text is needed to continue forward iteration."""
    pass

class PrevChunk(GraphemeIncomplete):
    """The previous chunk of text is needed to continue backward iteration."""
    pass

class InvalidOffset(GraphemeIncomplete):
    """Cursor offset is outside the provided chunk."""
    pass

# ---------------------------------------------------------------------------
# Pair classification constants (results of check_pair)
# ---------------------------------------------------------------------------

NOT_BREAK = 0
BREAK = 1
EXTENDED = 2        # break unless in extended mode
INCB_CONSONANT = 3  # context-dependent (GB9c)
REGIONAL = 4        # context-dependent (GB12/GB13)
EMOJI = 5           # context-dependent (GB11)


def check_pair(cat_before, cat_after):
    """Classify the boundary between two adjacent grapheme categories.

    Encodes UAX#29 rules GB3 through GB999.  Returns one of the constants
    NOT_BREAK, BREAK, EXTENDED, INCB_CONSONANT, REGIONAL, or EMOJI.

    Results INCB_CONSONANT, REGIONAL, and EMOJI require additional
    context beyond the adjacent pair to resolve — consult the UAX#29
    specification for the full rules.
    """
    if cat_before == "CR" and cat_after == "LF":
        return NOT_BREAK        # GB3
    if cat_before in ("Control", "CR", "LF"):
        return BREAK            # GB4
    if cat_after in ("Control", "CR", "LF"):
        return BREAK            # GB5
    if cat_before == "L" and cat_after in ("L", "V", "LV", "LVT"):
        return NOT_BREAK        # GB6
    if cat_before in ("LV", "V") and cat_after in ("V", "T"):
        return NOT_BREAK        # GB7
    if cat_before in ("LVT", "T") and cat_after == "T":
        return NOT_BREAK        # GB8
    if cat_after in ("Extend", "ZWJ"):
        return NOT_BREAK        # GB9
    if cat_after == "SpacingMark":
        return EXTENDED         # GB9a
    if cat_before == "Prepend":
        return EXTENDED         # GB9b
    if cat_after == "InCB_Consonant":
        return INCB_CONSONANT   # GB9c
    if cat_before == "ZWJ" and cat_after == "Extended_Pictographic":
        return EMOJI            # GB11
    if cat_before == "Regional_Indicator" and cat_after == "Regional_Indicator":
        return REGIONAL         # GB12 / GB13
    return BREAK                # GB999


# ---------------------------------------------------------------------------
# Whole-string segmentation
# ---------------------------------------------------------------------------

def grapheme_clusters(text, extended=True):
    """Segment *text* into extended grapheme clusters per UAX#29.

    Args:
        text: Unicode string to segment.
        extended: Use extended grapheme clusters (default True).

    Returns:
        List of grapheme-cluster strings whose concatenation equals *text*.
    """
    raise NotImplementedError("Implement grapheme_clusters")


# ---------------------------------------------------------------------------
# Chunked / streaming cursor
# ---------------------------------------------------------------------------

class GraphemeCursor:
    """Cursor-based grapheme cluster boundary detection for chunked text.

    Supports text that arrives in arbitrary chunks (e.g. from a rope data
    structure).  The cursor maintains its position and accumulated state,
    requesting additional context via exceptions when the current chunk is
    insufficient.

    All offsets are **character (codepoint) indices**, not byte offsets.

    Typical usage for forward iteration::

        cursor = GraphemeCursor(0, total_length)
        chunks = [...]  # ordered, non-overlapping pieces of the full string
        chunk_idx = 0
        while True:
            try:
                b = cursor.next_boundary(chunks[chunk_idx], starts[chunk_idx])
                if b is None:
                    break
                boundaries.append(b)
            except NextChunk:
                chunk_idx += 1
            except PreContext as e:
                # find the chunk that ends at e.offset and provide it
                cursor.provide_context(pre_chunk, pre_start)
    """

    def __init__(self, offset, length, is_extended=True):
        """Create a cursor at *offset* in a string of *length* codepoints."""
        raise NotImplementedError

    def cur_cursor(self):
        """Return the current cursor offset."""
        raise NotImplementedError

    def set_cursor(self, offset):
        """Move the cursor to *offset*, resetting boundary state."""
        raise NotImplementedError

    def provide_context(self, chunk, chunk_start):
        """Supply pre-context to resolve a pending ``PreContext``.

        ``chunk_start + len(chunk)`` must equal the offset from the
        ``PreContext`` exception.  This may itself trigger a new
        ``PreContext`` if even more backward context is required (e.g.
        for long runs of Regional Indicator symbols).
        """
        raise NotImplementedError

    def is_boundary(self, chunk, chunk_start):
        """Test whether the current offset is a grapheme cluster boundary.

        Returns ``True`` or ``False``.
        Raises ``PreContext`` if backward context is needed.
        Raises ``InvalidOffset`` if the offset is outside the chunk.
        """
        raise NotImplementedError

    def next_boundary(self, chunk, chunk_start):
        """Find the next boundary after the current offset.

        Returns the boundary offset, or ``None`` at end-of-string.
        Raises ``NextChunk`` when the chunk is exhausted.
        Raises ``PreContext`` when backward context is needed (call
        ``provide_context`` and retry).
        """
        raise NotImplementedError

    def prev_boundary(self, chunk, chunk_start):
        """Find the previous boundary before the current offset.

        Returns the boundary offset, or ``None`` at start-of-string.
        Raises ``PrevChunk`` when the chunk is exhausted going backward.
        Raises ``PreContext`` when backward context is needed.
        """
        raise NotImplementedError
