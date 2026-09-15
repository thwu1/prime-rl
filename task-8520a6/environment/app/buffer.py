
"""Text buffer using piece descriptors with version support."""

from __future__ import annotations
from typing import List, Tuple


class _BufferStore:
    """Shared storage for text content."""

    def __init__(self, original: str):
        self._original = original
        self._additions = ""

    def add(self, text: str) -> Tuple[int, int]:
        """Append text to the additions buffer. Returns (start, length)."""
        start = len(self._additions)
        self._additions += text
        return start, len(text)

    def read(self, source: int, start: int, length: int) -> str:
        """Read from specified buffer. source=0: original, source=1: additions."""
        buf = self._original if source == 0 else self._additions
        return buf[start:start + length]


class _Descriptor:
    """Points to a contiguous region in a buffer."""
    __slots__ = ("source", "start", "length")

    def __init__(self, source: int, start: int, length: int):
        self.source = source
        self.start = start
        self.length = length


class PieceTable:
    """Versioned text buffer with structural sharing.

    Each edit operation returns a new instance. All instances originating
    from the same initial text share the underlying buffer storage.
    """

    def __init__(self, init, descriptors=None):
        if isinstance(init, str):
            self._store = _BufferStore(init)
            self._desc: List[_Descriptor] = []
            if init:
                self._desc.append(_Descriptor(0, 0, len(init)))
        else:
            self._store = init
            self._desc = descriptors if descriptors is not None else []

    @property
    def length(self) -> int:
        return sum(d.length for d in self._desc)

    def get_text(self) -> str:
        return "".join(
            self._store.read(d.source, d.start, d.length) for d in self._desc
        )

    def insert(self, offset: int, text: str) -> "PieceTable":
        """Insert text at offset. Returns a new PieceTable."""
        if not text:
            return PieceTable(
                self._store,
                [_Descriptor(d.source, d.start, d.length) for d in self._desc],
            )

        add_start, add_len = self._store.add(text)
        new_desc = _Descriptor(1, add_start, add_len)

        # Find insertion point and split if necessary
        pos = 0
        idx = len(self._desc)

        for i, d in enumerate(self._desc):
            if pos + d.length > offset >= pos:
                local = offset - pos
                if local == 0:
                    idx = i
                    break
                elif local == d.length:
                    idx = i + 1
                    break
                else:
                    # Split descriptor at local offset
                    left = _Descriptor(d.source, d.start, local)
                    right = _Descriptor(
                        d.source, d.start + local, d.length - local
                    )
                    self._desc[i] = left
                    self._desc.insert(i + 1, right)
                    idx = i + 1
                    break
            pos += d.length

        self._desc.insert(idx, new_desc)
        return PieceTable(self._store, self._desc)

    def delete(self, offset: int, length: int) -> "PieceTable":
        """Delete length characters starting at offset. Returns a new PieceTable."""
        if length == 0:
            return PieceTable(
                self._store,
                [_Descriptor(d.source, d.start, d.length) for d in self._desc],
            )

        new_descs: List[_Descriptor] = []
        rem_off = offset
        rem_del = length

        for d in self._desc:
            if rem_del == 0:
                new_descs.append(_Descriptor(d.source, d.start, d.length))
            elif rem_off >= d.length:
                new_descs.append(_Descriptor(d.source, d.start, d.length))
                rem_off -= d.length
            elif rem_off > 0:
                new_descs.append(_Descriptor(d.source, d.start, rem_off))
                del_here = min(rem_del, d.length - rem_off)
                rem_del -= del_here
                after = d.length - rem_off - del_here
                if after > 0:
                    new_descs.append(
                        _Descriptor(d.source, d.start + rem_off + del_here, after)
                    )
                rem_off = 0
            else:
                del_here = min(rem_del, d.length)
                rem_del -= del_here
                if del_here < d.length:
                    new_descs.append(
                        _Descriptor(
                            d.source, d.start + del_here, d.length - del_here
                        )
                    )

        return PieceTable(self._store, new_descs)
