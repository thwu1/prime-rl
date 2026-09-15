
"""Immutable Piece Table for text editing.

Each modification returns a new PieceTable, leaving the original unchanged.
This enables O(1) snapshotting by retaining references to old instances.

A piece table maintains two buffers:
  - original: the initial text content (never modified)
  - add: accumulated inserted text (append-only)

Pieces reference slices of these buffers. The logical text is the
concatenation of all pieces in order.
"""


class Piece:
    """A reference to a contiguous slice of a buffer."""
    __slots__ = ('buffer_id', 'start', 'length')

    def __init__(self, buffer_id: str, start: int, length: int):
        self.buffer_id = buffer_id
        self.start = start
        self.length = length

    def __repr__(self):
        return f"Piece({self.buffer_id!r}, {self.start}, {self.length})"


class PieceTable:
    """Immutable piece table. All mutations return new instances."""

    def __init__(self, original: str = ""):
        self._original = original
        self._add_buffer = ""
        if original:
            self._pieces = (Piece("original", 0, len(original)),)
        else:
            self._pieces = ()

    @classmethod
    def _from_parts(cls, pieces, original, add_buffer):
        pt = cls.__new__(cls)
        pt._original = original
        pt._add_buffer = add_buffer
        pt._pieces = pieces
        return pt

    def _get_buffer(self, buffer_id: str) -> str:
        if buffer_id == "original":
            return self._original
        return self._add_buffer

    def get_text(self) -> str:
        """Return the full text content."""
        parts = []
        for piece in self._pieces:
            buf = self._get_buffer(piece.buffer_id)
            parts.append(buf[piece.start:piece.start + piece.length])
        return "".join(parts)

    def length(self) -> int:
        """Return total character count."""
        return sum(p.length for p in self._pieces)

    def insert(self, offset: int, text: str) -> 'PieceTable':
        """Insert text at offset. Returns a new PieceTable."""
        if not text:
            return self

        add_start = len(self._add_buffer)
        new_add = self._add_buffer + text
        new_piece = Piece("add", add_start, len(text))

        if not self._pieces:
            return PieceTable._from_parts((new_piece,), self._original, new_add)

        cumulative = 0
        for i, piece in enumerate(self._pieces):
            if cumulative == offset:
                new_pieces = self._pieces[:i] + (new_piece,) + self._pieces[i:]
                return PieceTable._from_parts(new_pieces, self._original, new_add)
            if cumulative + piece.length >= offset:
                split_at = offset - cumulative
                left = Piece(piece.buffer_id, piece.start, split_at)
                right = Piece(piece.buffer_id, piece.start + split_at,
                              piece.length - split_at)
                parts = list(self._pieces[:i])
                if left.length > 0:
                    parts.append(left)
                parts.append(new_piece)
                if right.length > 0:
                    parts.append(right)
                parts.extend(self._pieces[i + 1:])
                return PieceTable._from_parts(tuple(parts), self._original, new_add)
            cumulative += piece.length

        new_pieces = self._pieces + (new_piece,)
        return PieceTable._from_parts(new_pieces, self._original, new_add)

    def delete(self, offset: int, length: int) -> 'PieceTable':
        """Delete 'length' characters starting at 'offset'. Returns new PieceTable."""
        if length == 0:
            return self

        del_start = offset
        del_end = offset + length
        new_pieces = []
        cumulative = 0

        for piece in self._pieces:
            piece_start = cumulative
            piece_end = cumulative + piece.length

            if piece_end <= del_start or piece_start >= del_end:
                new_pieces.append(piece)
            elif piece_start >= del_start and piece_end <= del_end:
                pass  # entirely within deletion range
            elif piece_start < del_start and piece_end > del_end:
                left_len = del_start - piece_start
                right_start = piece.start + (del_end - piece_start)
                right_len = piece_end - del_end
                if left_len > 0:
                    new_pieces.append(Piece(piece.buffer_id, piece.start, left_len))
                if right_len > 0:
                    new_pieces.append(Piece(piece.buffer_id, right_start, right_len))
            elif piece_start < del_start:
                keep_len = del_start - piece_start
                if keep_len > 0:
                    new_pieces.append(Piece(piece.buffer_id, piece.start, keep_len))
            else:
                skip = del_end - piece_start
                keep_start = piece.start + skip
                keep_len = piece.length - skip
                if keep_len > 0:
                    new_pieces.append(Piece(piece.buffer_id, keep_start, keep_len))

            cumulative += piece.length

        return PieceTable._from_parts(tuple(new_pieces), self._original, self._add_buffer)
