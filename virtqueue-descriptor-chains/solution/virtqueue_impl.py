
"""VIRTIO 1.2 Split Virtqueue Simulator — reference implementation."""

import struct

VIRTQ_DESC_F_NEXT = 0x1
VIRTQ_DESC_F_WRITE = 0x2
VIRTQ_DESC_F_INDIRECT = 0x4
VIRTQ_AVAIL_F_NO_INTERRUPT = 0x1

DESCRIPTOR_SIZE = 16


class CircularChainError(Exception):
    """Raised when a descriptor chain contains a cycle."""
    pass


class InvalidDescriptorError(Exception):
    """Raised on out-of-bounds indices or structural violations."""
    pass


class VirtqueueDescriptor:
    """A single 16-byte virtqueue descriptor."""
    __slots__ = ('addr', 'length', 'flags', 'next_idx')

    def __init__(self, addr, length, flags, next_idx):
        self.addr = addr
        self.length = length
        self.flags = flags
        self.next_idx = next_idx

    @classmethod
    def from_bytes(cls, data, offset=0):
        addr, length, flags, next_idx = struct.unpack_from('<QIHH', data, offset)
        return cls(addr, length, flags, next_idx)


class DescriptorChain:
    """Result of walking a descriptor chain from a head index."""
    __slots__ = (
        'head_index', 'readable_descriptors', 'writable_descriptors',
        'total_readable_bytes', 'total_writable_bytes', 'has_indirect',
    )

    def __init__(self, head_index):
        self.head_index = head_index
        self.readable_descriptors = []
        self.writable_descriptors = []
        self.total_readable_bytes = 0
        self.total_writable_bytes = 0
        self.has_indirect = False

    def _add(self, desc):
        if desc.flags & VIRTQ_DESC_F_WRITE:
            self.writable_descriptors.append(desc)
            self.total_writable_bytes += desc.length
        else:
            self.readable_descriptors.append(desc)
            self.total_readable_bytes += desc.length


class SplitVirtqueue:
    """VIRTIO 1.2 split virtqueue processor.

    Parameters
    ----------
    queue_size : int
        Number of entries in the descriptor table / rings.
    desc_table : bytes
        Raw descriptor table (queue_size * 16 bytes).
    avail_ring : bytes
        Raw available ring.
    used_ring : bytes
        Raw used ring (will be copied into a mutable bytearray).
    memory : bytes, optional
        Backing memory for indirect descriptor resolution.
    event_idx : bool
        If True, use VIRTIO_F_EVENT_IDX notification suppression.
    """

    def __init__(self, queue_size, desc_table, avail_ring, used_ring,
                 memory=None, event_idx=False):
        self.queue_size = queue_size
        self._desc_table = desc_table
        self._avail_ring = avail_ring
        self._used_ring = bytearray(used_ring)
        self._memory = memory
        self._event_idx = event_idx

        # Parse avail ring header
        self._avail_flags, self._avail_idx = struct.unpack_from(
            '<HH', self._avail_ring, 0)

        # Internal counters
        self._last_avail_idx = 0
        self._used_idx = 0

    # ------------------------------------------------------------------
    # Descriptor access
    # ------------------------------------------------------------------

    def get_descriptor(self, index):
        """Return the VirtqueueDescriptor at *index*."""
        if index < 0 or index >= self.queue_size:
            raise InvalidDescriptorError(
                f"Descriptor index {index} out of bounds "
                f"(queue_size={self.queue_size})")
        return VirtqueueDescriptor.from_bytes(
            self._desc_table, index * DESCRIPTOR_SIZE)

    # ------------------------------------------------------------------
    # Chain walking
    # ------------------------------------------------------------------

    def _walk_indirect(self, desc):
        """Resolve an indirect descriptor table and return its descriptors."""
        if desc.length % DESCRIPTOR_SIZE != 0:
            raise InvalidDescriptorError(
                f"Indirect table length {desc.length} is not a multiple of "
                f"{DESCRIPTOR_SIZE}")
        if self._memory is None:
            raise InvalidDescriptorError(
                "No memory provided for indirect descriptor resolution")

        table_start = desc.addr
        table_end = table_start + desc.length
        if table_end > len(self._memory):
            raise InvalidDescriptorError(
                f"Indirect table [{table_start}:{table_end}) exceeds memory "
                f"size {len(self._memory)}")

        num_entries = desc.length // DESCRIPTOR_SIZE

        # Pre-parse all entries
        entries = []
        for i in range(num_entries):
            d = VirtqueueDescriptor.from_bytes(
                self._memory, table_start + i * DESCRIPTOR_SIZE)
            if d.flags & VIRTQ_DESC_F_INDIRECT:
                raise InvalidDescriptorError(
                    "Nested indirect descriptors are not allowed")
            entries.append(d)

        # Walk the chain inside the indirect table
        result = []
        visited = set()
        idx = 0
        while True:
            if idx in visited:
                raise CircularChainError(
                    f"Circular chain in indirect table at index {idx}")
            if idx < 0 or idx >= num_entries:
                raise InvalidDescriptorError(
                    f"Indirect index {idx} out of bounds "
                    f"(table has {num_entries} entries)")
            visited.add(idx)
            d = entries[idx]
            result.append(d)
            if d.flags & VIRTQ_DESC_F_NEXT:
                idx = d.next_idx
            else:
                break
        return result

    def walk_chain(self, head_index):
        """Walk the descriptor chain starting at *head_index*."""
        if head_index < 0 or head_index >= self.queue_size:
            raise InvalidDescriptorError(
                f"Head index {head_index} out of bounds "
                f"(queue_size={self.queue_size})")

        chain = DescriptorChain(head_index)
        visited = set()
        idx = head_index

        while True:
            if idx in visited:
                raise CircularChainError(
                    f"Circular descriptor chain at index {idx}")
            if idx < 0 or idx >= self.queue_size:
                raise InvalidDescriptorError(
                    f"Descriptor index {idx} out of bounds "
                    f"(queue_size={self.queue_size})")
            visited.add(idx)

            desc = self.get_descriptor(idx)

            if desc.flags & VIRTQ_DESC_F_INDIRECT:
                chain.has_indirect = True
                for d in self._walk_indirect(desc):
                    chain._add(d)
                break  # indirect terminates the main chain
            else:
                chain._add(desc)
                if desc.flags & VIRTQ_DESC_F_NEXT:
                    idx = desc.next_idx
                else:
                    break

        return chain

    # ------------------------------------------------------------------
    # Available ring
    # ------------------------------------------------------------------

    def get_pending_chains(self):
        """Return unprocessed chains from the available ring."""
        chains = []
        while self._last_avail_idx != self._avail_idx:
            ring_pos = self._last_avail_idx % self.queue_size
            offset = 4 + ring_pos * 2  # skip flags(2) + idx(2)
            head = struct.unpack_from('<H', self._avail_ring, offset)[0]
            chains.append(self.walk_chain(head))
            self._last_avail_idx = (self._last_avail_idx + 1) & 0xFFFF
        return chains

    # ------------------------------------------------------------------
    # Used ring
    # ------------------------------------------------------------------

    def mark_used(self, head_index, written_bytes):
        """Record a processed chain in the used ring."""
        ring_pos = self._used_idx % self.queue_size
        entry_offset = 4 + ring_pos * 8  # skip flags(2) + idx(2)
        struct.pack_into('<II', self._used_ring, entry_offset,
                         head_index, written_bytes)
        self._used_idx = (self._used_idx + 1) & 0xFFFF
        struct.pack_into('<H', self._used_ring, 2, self._used_idx)

    def get_used_entries(self):
        """Return all (id, len) pairs from the used ring."""
        used_idx = struct.unpack_from('<H', self._used_ring, 2)[0]
        entries = []
        for i in range(used_idx):
            ring_pos = i % self.queue_size
            offset = 4 + ring_pos * 8
            id_val, len_val = struct.unpack_from('<II', self._used_ring, offset)
            entries.append((id_val, len_val))
        return entries

    # ------------------------------------------------------------------
    # Notification suppression
    # ------------------------------------------------------------------

    @staticmethod
    def _vring_need_event(event_idx, new_idx, old_idx):
        """VIRTIO vring_need_event check with uint16 wrapping."""
        return ((new_idx - event_idx - 1) & 0xFFFF) < \
               ((new_idx - old_idx) & 0xFFFF)

    def should_notify(self, old_used_idx):
        """Determine whether the device should send an interrupt.

        Parameters
        ----------
        old_used_idx : int
            The used ring idx *before* the latest mark_used() calls.
        """
        if not self._event_idx:
            avail_flags = struct.unpack_from('<H', self._avail_ring, 0)[0]
            return not (avail_flags & VIRTQ_AVAIL_F_NO_INTERRUPT)

        used_event_offset = 4 + self.queue_size * 2
        used_event = struct.unpack_from(
            '<H', self._avail_ring, used_event_offset)[0]
        return self._vring_need_event(used_event, self._used_idx, old_used_idx)
