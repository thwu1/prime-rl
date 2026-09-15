
"""UAX#29 Extended Grapheme Cluster segmentation with streaming GraphemeCursor.

Complete implementation of grapheme_clusters() and GraphemeCursor,
faithfully translated from the Rust unicode-segmentation crate.
"""

from segmenter.tables import grapheme_category, is_incb_linker, is_incb_extend

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class GraphemeIncomplete(Exception):
    pass

class PreContext(GraphemeIncomplete):
    def __init__(self, offset):
        self.offset = offset
        super().__init__(f"Need pre-context ending at offset {offset}")

class NextChunk(GraphemeIncomplete):
    pass

class PrevChunk(GraphemeIncomplete):
    pass

class InvalidOffset(GraphemeIncomplete):
    pass

# ---------------------------------------------------------------------------
# Pair classification
# ---------------------------------------------------------------------------

NOT_BREAK = 0
BREAK = 1
EXTENDED = 2
INCB_CONSONANT = 3
REGIONAL = 4
EMOJI = 5


def check_pair(cat_before, cat_after):
    if cat_before == "CR" and cat_after == "LF":
        return NOT_BREAK
    if cat_before in ("Control", "CR", "LF"):
        return BREAK
    if cat_after in ("Control", "CR", "LF"):
        return BREAK
    if cat_before == "L" and cat_after in ("L", "V", "LV", "LVT"):
        return NOT_BREAK
    if cat_before in ("LV", "V") and cat_after in ("V", "T"):
        return NOT_BREAK
    if cat_before in ("LVT", "T") and cat_after == "T":
        return NOT_BREAK
    if cat_after in ("Extend", "ZWJ"):
        return NOT_BREAK
    if cat_after == "SpacingMark":
        return EXTENDED
    if cat_before == "Prepend":
        return EXTENDED
    if cat_after == "InCB_Consonant":
        return INCB_CONSONANT
    if cat_before == "ZWJ" and cat_after == "Extended_Pictographic":
        return EMOJI
    if cat_before == "Regional_Indicator" and cat_after == "Regional_Indicator":
        return REGIONAL
    return BREAK


# ---------------------------------------------------------------------------
# Whole-string segmentation
# ---------------------------------------------------------------------------

def grapheme_clusters(text, extended=True):
    if not text:
        return []

    cps = [ord(c) for c in text]
    cats = [grapheme_category(cp) for cp in cps]
    n = len(cps)
    boundaries = [0]

    for i in range(1, n):
        pair = check_pair(cats[i - 1], cats[i])
        is_break = False

        if pair == NOT_BREAK:
            is_break = False
        elif pair == BREAK:
            is_break = True
        elif pair == EXTENDED:
            is_break = not extended
        elif pair == INCB_CONSONANT:
            if extended:
                linker_count = 0
                is_break = True
                for j in range(i - 1, -1, -1):
                    cp = cps[j]
                    if is_incb_linker(cp):
                        linker_count += 1
                    elif is_incb_extend(cp):
                        continue
                    else:
                        if linker_count > 0 and cats[j] == "InCB_Consonant":
                            is_break = False
                        break
            else:
                is_break = True
        elif pair == REGIONAL:
            ris_count = 0
            for j in range(i - 1, -1, -1):
                if cats[j] == "Regional_Indicator":
                    ris_count += 1
                else:
                    break
            is_break = ris_count % 2 == 0
        elif pair == EMOJI:
            is_break = True
            for j in range(i - 2, -1, -1):
                if cats[j] == "Extend":
                    continue
                if cats[j] == "Extended_Pictographic":
                    is_break = False
                break

        if is_break:
            boundaries.append(i)

    boundaries.append(n)
    return [text[boundaries[j] : boundaries[j + 1]] for j in range(len(boundaries) - 1)]


# ---------------------------------------------------------------------------
# Chunked / streaming cursor
# ---------------------------------------------------------------------------

class GraphemeCursor:
    def __init__(self, offset, length, is_extended=True):
        self.offset = offset
        self.length = length
        self.is_extended = is_extended
        self.state = "break" if (offset == 0 or offset == length) else "unknown"
        self.cat_before = None
        self.cat_after = None
        self.pre_context_offset = None
        self.incb_linker_count = None
        self.ris_count = None
        self.resuming = False
        self._emoji_seen_zwj = False

    def cur_cursor(self):
        return self.offset

    def set_cursor(self, offset):
        if offset != self.offset:
            self.offset = offset
            self.state = "break" if (offset == 0 or offset == self.length) else "unknown"
            self.cat_before = None
            self.cat_after = None
            self.incb_linker_count = None
            self.ris_count = None

    def _decide(self, is_break):
        self.state = "break" if is_break else "not_break"

    # -- context-dependent backward scanners --

    def _handle_incb(self, chunk, chunk_start):
        if not self.is_extended:
            self._decide(True)
            return

        incb_linker_count = self.incb_linker_count if self.incb_linker_count is not None else 0

        for ch in reversed(chunk):
            cp = ord(ch)
            if is_incb_linker(cp):
                incb_linker_count += 1
                self.incb_linker_count = incb_linker_count
            elif is_incb_extend(cp):
                pass
            else:
                result = not (self.incb_linker_count is not None
                              and self.incb_linker_count > 0
                              and grapheme_category(cp) == "InCB_Consonant")
                self._decide(result)
                return

        if chunk_start == 0:
            self._decide(True)
        else:
            self.pre_context_offset = chunk_start
            self.state = "incb"

    def _handle_regional(self, chunk, chunk_start):
        ris_count = self.ris_count if self.ris_count is not None else 0
        for ch in reversed(chunk):
            if grapheme_category(ord(ch)) != "Regional_Indicator":
                self.ris_count = ris_count
                self._decide(ris_count % 2 == 0)
                return
            ris_count += 1
        self.ris_count = ris_count
        if chunk_start == 0:
            self._decide(ris_count % 2 == 0)
        else:
            self.pre_context_offset = chunk_start
            self.state = "regional"

    def _handle_emoji(self, chunk, chunk_start, seen_zwj):
        it = iter(reversed(chunk))
        if not seen_zwj:
            ch = next(it, None)
            if ch is None:
                # Empty chunk, need more context or decide
                if chunk_start == 0:
                    self._decide(True)
                else:
                    self.pre_context_offset = chunk_start
                    self.state = "emoji"
                    self._emoji_seen_zwj = False
                return
            if grapheme_category(ord(ch)) != "ZWJ":
                self._decide(True)
                return
            seen_zwj = True
        for ch in it:
            cat = grapheme_category(ord(ch))
            if cat == "Extend":
                continue
            if cat == "Extended_Pictographic":
                self._decide(False)
                return
            self._decide(True)
            return
        if chunk_start == 0:
            self._decide(True)
        else:
            self.pre_context_offset = chunk_start
            self.state = "emoji"
            self._emoji_seen_zwj = seen_zwj

    # -- public API --

    def provide_context(self, chunk, chunk_start):
        assert self.pre_context_offset is not None
        assert chunk_start + len(chunk) == self.pre_context_offset
        self.pre_context_offset = None

        if self.is_extended and chunk_start + len(chunk) == self.offset:
            if chunk:
                ch = chunk[-1]
                if grapheme_category(ord(ch)) == "Prepend":
                    self._decide(False)  # GB9b
                    return

        if self.state == "incb":
            self._handle_incb(chunk, chunk_start)
        elif self.state == "regional":
            self._handle_regional(chunk, chunk_start)
        elif self.state == "emoji":
            self._handle_emoji(chunk, chunk_start, self._emoji_seen_zwj)
        else:
            if self.cat_before is None and self.offset == chunk_start + len(chunk):
                if chunk:
                    self.cat_before = grapheme_category(ord(chunk[-1]))

    def _boundary_result(self):
        if self.state == "break":
            return True
        if self.state == "not_break":
            return False
        if self.pre_context_offset is not None:
            raise PreContext(self.pre_context_offset)
        raise RuntimeError("inconsistent state")

    def is_boundary(self, chunk, chunk_start):
        if self.state == "break":
            return True
        if self.state == "not_break":
            return False

        chunk_end = chunk_start + len(chunk)
        if (self.offset < chunk_start or self.offset >= chunk_end) and \
           (self.offset > chunk_end or self.cat_after is None):
            raise InvalidOffset()

        if self.pre_context_offset is not None:
            raise PreContext(self.pre_context_offset)

        offset_in_chunk = self.offset - chunk_start

        if self.cat_after is None:
            self.cat_after = grapheme_category(ord(chunk[offset_in_chunk]))

        if self.offset == chunk_start:
            # At chunk boundary: we don't have text before the cursor in
            # this chunk.  If cat_before is known (from forward iteration),
            # resolve simple pair results immediately.  For context-dependent
            # results, use forward-tracked counts when available (to avoid
            # double-counting with backward scans) or request pre-context.
            if self.cat_before is not None:
                pair = check_pair(self.cat_before, self.cat_after)
                if pair == NOT_BREAK:
                    self._decide(False)
                    return False
                elif pair == BREAK:
                    self._decide(True)
                    return True
                elif pair == EXTENDED:
                    result = not self.is_extended
                    self._decide(result)
                    return result
                elif pair == REGIONAL:
                    if self.ris_count is not None:
                        result = self.ris_count % 2 == 0
                        self._decide(result)
                        return result
                    # Need backward scan — reset count to avoid doubling
                    self.state = "regional"
                    self.ris_count = None
                elif pair == INCB_CONSONANT:
                    self.state = "incb"
                    self.incb_linker_count = None
                elif pair == EMOJI:
                    self.state = "emoji"
                    self._emoji_seen_zwj = False
                self.pre_context_offset = chunk_start
                raise PreContext(chunk_start)
            else:
                # cat_before unknown — set state based on cat_after and
                # request pre-context.
                ca = self.cat_after
                if ca == "InCB_Consonant":
                    self.state = "incb"
                    self.incb_linker_count = None
                elif ca == "Regional_Indicator":
                    self.state = "regional"
                    self.ris_count = None
                elif ca == "Extended_Pictographic":
                    self.state = "emoji"
                    self._emoji_seen_zwj = False
                self.pre_context_offset = chunk_start
                raise PreContext(chunk_start)

        if self.cat_before is None:
            self.cat_before = grapheme_category(ord(chunk[offset_in_chunk - 1]))

        pair = check_pair(self.cat_before, self.cat_after)

        if pair == NOT_BREAK:
            self._decide(False)
            return False
        elif pair == BREAK:
            self._decide(True)
            return True
        elif pair == EXTENDED:
            result = not self.is_extended
            self._decide(result)
            return result
        elif pair == INCB_CONSONANT:
            self._handle_incb(chunk[:offset_in_chunk], chunk_start)
            return self._boundary_result()
        elif pair == REGIONAL:
            if self.ris_count is not None:
                result = self.ris_count % 2 == 0
                self._decide(result)
                return result
            self._handle_regional(chunk[:offset_in_chunk], chunk_start)
            return self._boundary_result()
        elif pair == EMOJI:
            self._handle_emoji(chunk[:offset_in_chunk], chunk_start, False)
            return self._boundary_result()

    def next_boundary(self, chunk, chunk_start):
        """Find the next boundary after the current offset.

        Faithfully follows the Rust unicode-segmentation crate's loop structure:
        the character is processed INSIDE the loop for both resuming and
        non-resuming cases, ensuring end-of-string is handled correctly.
        """
        if self.offset == self.length:
            return None

        idx = self.offset - chunk_start
        if idx < 0 or idx > len(chunk):
            raise InvalidOffset()
        if idx >= len(chunk):
            raise NextChunk()

        # Create a character iterator starting at the cursor position
        pos = idx  # position in chunk

        while True:
            if pos >= len(chunk):
                raise NextChunk()

            ch = chunk[pos]
            cp = ord(ch)

            if self.resuming:
                if self.cat_after is None:
                    self.cat_after = grapheme_category(cp)
            else:
                self.offset += 1
                self.state = "unknown"
                self.cat_before = self.cat_after
                self.cat_after = None
                if self.cat_before is None:
                    self.cat_before = grapheme_category(cp)

                # Track InCB linker count
                if is_incb_linker(cp):
                    if self.incb_linker_count is not None:
                        self.incb_linker_count += 1
                    else:
                        self.incb_linker_count = 1
                elif not is_incb_extend(cp):
                    self.incb_linker_count = 0

                # Track RI count
                if self.cat_before == "Regional_Indicator":
                    if self.ris_count is not None:
                        self.ris_count += 1
                    # else stays None (unknown)
                else:
                    self.ris_count = 0

                pos += 1
                if pos < len(chunk):
                    self.cat_after = grapheme_category(ord(chunk[pos]))
                elif self.offset == self.length:
                    self._decide(True)
                else:
                    self.resuming = True
                    raise NextChunk()

            self.resuming = True
            if self.is_boundary(chunk, chunk_start):
                self.resuming = False
                return self.offset
            self.resuming = False

    def prev_boundary(self, chunk, chunk_start):
        """Find the previous boundary before the current offset.

        Faithfully follows the Rust unicode-segmentation crate's logic.
        """
        if self.offset == 0:
            return None
        if self.offset == chunk_start:
            raise PrevChunk()

        offset_in_chunk = self.offset - chunk_start
        # Create reverse character iterator over chunk[:offset_in_chunk]
        prefix = chunk[:offset_in_chunk]
        rev_chars = list(reversed(prefix))
        it = iter(rev_chars)
        ch = next(it)

        while True:
            if self.offset == chunk_start:
                self.resuming = True
                raise PrevChunk()

            if self.resuming:
                self.cat_before = grapheme_category(ord(ch))
            else:
                cp = ord(ch)
                self.offset -= 1
                self.cat_after = self.cat_before
                self.cat_before = None
                self.state = "unknown"

                # Track InCB backward
                if self.incb_linker_count is not None:
                    if self.incb_linker_count > 0 and is_incb_linker(cp):
                        self.incb_linker_count -= 1
                    elif is_incb_extend(cp):
                        pass  # keep count
                    else:
                        self.incb_linker_count = None

                # Track RI backward
                if self.ris_count is not None:
                    if self.ris_count > 0:
                        self.ris_count -= 1
                    else:
                        self.ris_count = None

                nxt = next(it, None)
                if nxt is not None:
                    ch = nxt
                    self.cat_before = grapheme_category(ord(ch))
                elif self.offset == 0:
                    self._decide(True)
                else:
                    self.resuming = True
                    self.cat_after = grapheme_category(cp)
                    raise PrevChunk()

            self.resuming = True
            if self.is_boundary(chunk, chunk_start):
                self.resuming = False
                return self.offset
            self.resuming = False
